"""Tests del proveedor OpenAI con cliente falso (sin red).

Ejecutar: python tests/test_openai_provider.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx2  # noqa: E402
import openai  # noqa: E402

from src.config import ModelConfig  # noqa: E402
from src.pipeline import TriagePipeline  # noqa: E402
from src.prompts import load_prompt  # noqa: E402
from src.providers.base import ProviderError, ProviderFatalError, ProviderUnavailable  # noqa: E402
from src.providers.factory import build_provider  # noqa: E402
from src.providers.openai_provider import OpenAIProvider, _client_from_env  # noqa: E402
from src.schemas import Category  # noqa: E402

MODEL = ModelConfig(
    id="gpt-4.1-mini",
    temperature=0.0,
    max_tokens=700,
    input_per_1m_usd=0.40,
    output_per_1m_usd=1.60,
)

VALID_JSON = (
    '{"answer": "Revisamos el cargo duplicado.", "confidence": 0.9, '
    '"category": "billing", "actions": ["Verificar pagos duplicados"]}'
)


def _completion(text: str | None, prompt_tokens: int = 120, completion_tokens: int = 40) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _api_error(cls: type, status: int) -> Exception:
    request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx2.Response(status, request=request)
    return cls("simulado", response=response, body=None)


class FakeCompletions:
    def __init__(self, outcomes: list) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes: list) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))


def _complete(client: FakeClient, **overrides):
    params = dict(model="gpt-4.1-mini", temperature=0.0, max_tokens=700, timeout_s=30)
    params.update(overrides)
    return OpenAIProvider(client=client).complete("sys", "usr", **params)


def _expect(exc_type: type, client: FakeClient) -> None:
    try:
        _complete(client)
    except exc_type:
        return
    raise AssertionError(f"se esperaba {exc_type.__name__}")


def test_success_maps_text_and_usage() -> None:
    client = FakeClient([_completion(VALID_JSON, 120, 40)])
    response = _complete(client)
    assert response.text == VALID_JSON
    assert response.prompt_tokens == 120
    assert response.completion_tokens == 40
    assert response.token_source == "api"


def test_request_shape() -> None:
    client = FakeClient([_completion(VALID_JSON)])
    _complete(client, timeout_s=12)
    call = client.chat.completions.calls[0]
    assert call["model"] == "gpt-4.1-mini"
    assert call["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert call["max_completion_tokens"] == 700
    assert call["response_format"] == {"type": "json_object"}
    assert call["temperature"] == 0.0
    assert call["timeout"] == 12
    assert "reasoning_effort" not in call


def test_optional_params_omitted_when_none() -> None:
    client = FakeClient([_completion(VALID_JSON)])
    _complete(client, temperature=None)
    assert "temperature" not in client.chat.completions.calls[0]


def test_effort_sent_as_reasoning_effort() -> None:
    client = FakeClient([_completion(VALID_JSON)])
    _complete(client, temperature=None, effort="low")
    assert client.chat.completions.calls[0]["reasoning_effort"] == "low"


def test_empty_content_becomes_empty_text() -> None:
    client = FakeClient([_completion(None)])
    assert _complete(client).text == ""


def test_rate_limit_is_retryable() -> None:
    _expect(ProviderError, FakeClient([_api_error(openai.RateLimitError, 429)]))


def test_server_error_is_retryable() -> None:
    _expect(ProviderError, FakeClient([_api_error(openai.InternalServerError, 500)]))


def test_auth_error_is_fatal() -> None:
    _expect(ProviderFatalError, FakeClient([_api_error(openai.AuthenticationError, 401)]))


def test_bad_request_is_fatal() -> None:
    _expect(ProviderFatalError, FakeClient([_api_error(openai.BadRequestError, 400)]))


def test_pipeline_retries_on_invalid_json_then_succeeds() -> None:
    client = FakeClient([_completion('{"answer": "x"}', 100, 10), _completion(VALID_JSON, 110, 20)])
    pipeline = TriagePipeline(
        provider=OpenAIProvider(client=client),
        model=MODEL,
        prompt=load_prompt("v1"),
        max_retries=2,
        timeout_s=30,
    )
    result = pipeline.run("me cobraron dos veces la suscripción")
    assert result.success is True
    assert result.attempts == 2
    assert result.response.category is Category.BILLING
    assert result.prompt_tokens == 210
    assert result.completion_tokens == 30
    assert "no cumplió el contrato" in client.chat.completions.calls[1]["messages"][1]["content"]


def _with_key(value: str | None):
    previous = os.environ.pop("OPENAI_API_KEY", None)
    if value is not None:
        os.environ["OPENAI_API_KEY"] = value
    return previous


def _restore(previous: str | None) -> None:
    os.environ.pop("OPENAI_API_KEY", None)
    if previous is not None:
        os.environ["OPENAI_API_KEY"] = previous


def test_missing_key_is_unavailable() -> None:
    previous = _with_key(None)
    try:
        _client_from_env()
    except ProviderUnavailable as exc:
        assert "OPENAI_API_KEY" in str(exc)
        return
    finally:
        _restore(previous)
    raise AssertionError("sin clave debió ser ProviderUnavailable")


def test_client_disables_sdk_retries() -> None:
    previous = _with_key("sk-test-no-real")
    try:
        assert _client_from_env().max_retries == 0
    finally:
        _restore(previous)


def test_factory_builds_openai_when_key_present() -> None:
    previous = _with_key("sk-test-no-real")
    try:
        assert build_provider("openai").name == "openai"
    finally:
        _restore(previous)


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        else:
            print(f"ok   {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} tests pasaron")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

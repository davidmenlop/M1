"""Tests del proveedor Anthropic con cliente falso (sin red).

Ejecutar: python tests/test_anthropic_provider.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402
import httpx2  # noqa: E402

from src.config import ModelConfig  # noqa: E402
from src.pipeline import TriagePipeline  # noqa: E402
from src.prompts import load_prompt  # noqa: E402
from src.providers.anthropic_provider import AnthropicProvider, _client_from_env  # noqa: E402
from src.providers.base import ProviderError, ProviderFatalError, ProviderUnavailable  # noqa: E402
from src.providers.factory import build_provider  # noqa: E402
from src.schemas import Category  # noqa: E402

MODEL = ModelConfig(
    id="claude-haiku-4-5",
    temperature=None,
    max_tokens=700,
    input_per_1m_usd=1.00,
    output_per_1m_usd=5.00,
)

VALID_JSON = (
    '{"answer": "Revisamos el cargo duplicado.", "confidence": 0.9, '
    '"category": "billing", "actions": ["Verificar pagos duplicados"]}'
)


def _message(text: str, input_tokens: int = 120, output_tokens: int = 40) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _api_error(cls: type, status: int) -> Exception:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request)
    return cls("simulado", response=response, body=None)


class FakeMessages:
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
        self.messages = FakeMessages(outcomes)


def _pipeline(client: FakeClient, max_retries: int = 2) -> TriagePipeline:
    return TriagePipeline(
        provider=AnthropicProvider(client=client),
        model=MODEL,
        prompt=load_prompt("v1"),
        max_retries=max_retries,
        timeout_s=30,
    )


def test_success_maps_text_and_usage() -> None:
    client = FakeClient([_message(VALID_JSON, 120, 40)])
    response = AnthropicProvider(client=client).complete(
        "sys", "usr", model="claude-haiku-4-5", temperature=None, max_tokens=700, timeout_s=30
    )
    assert response.text == VALID_JSON
    assert response.prompt_tokens == 120
    assert response.completion_tokens == 40
    assert response.token_source == "api"


def test_request_carries_model_and_timeout() -> None:
    client = FakeClient([_message(VALID_JSON)])
    AnthropicProvider(client=client).complete(
        "sys", "usr", model="claude-haiku-4-5", temperature=None, max_tokens=700, timeout_s=12
    )
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "usr"}]
    assert call["max_tokens"] == 700
    assert call["timeout"] == 12


def test_sampling_params_never_sent() -> None:
    client = FakeClient([_message(VALID_JSON)])
    AnthropicProvider(client=client).complete(
        "sys", "usr", model="claude-haiku-4-5", temperature=None, max_tokens=700, timeout_s=12
    )
    call = client.messages.calls[0]
    assert "temperature" not in call
    assert "extra_body" not in call
    assert "output_config" not in call


def test_configured_temperature_fails_before_calling_api() -> None:
    client = FakeClient([_message(VALID_JSON)])
    try:
        AnthropicProvider(client=client).complete(
            "sys", "usr", model="claude-haiku-4-5", temperature=0.0, max_tokens=700, timeout_s=12
        )
    except ProviderFatalError as exc:
        assert "temperature" in str(exc)
        assert client.messages.calls == [], "no debió llamar a la API"
        return
    raise AssertionError("temperature configurada debió ser ProviderFatalError")


def test_effort_sent_as_output_config() -> None:
    client = FakeClient([_message(VALID_JSON)])
    AnthropicProvider(client=client).complete(
        "sys", "usr", model="claude-haiku-5-5", temperature=None, max_tokens=2000,
        timeout_s=12, effort="low",
    )
    assert client.messages.calls[0]["output_config"] == {"effort": "low"}


def test_thinking_blocks_are_ignored_in_text() -> None:
    message = _message(VALID_JSON)
    message.content.insert(0, SimpleNamespace(type="thinking", thinking=""))
    client = FakeClient([message])
    response = AnthropicProvider(client=client).complete(
        "s", "u", model="claude-haiku-5-5", temperature=None, max_tokens=2000, timeout_s=5
    )
    assert response.text == VALID_JSON


def test_rate_limit_is_retryable() -> None:
    client = FakeClient([_api_error(anthropic.RateLimitError, 429)])
    try:
        AnthropicProvider(client=client).complete(
            "s", "u", model="m", temperature=None, max_tokens=10, timeout_s=5
        )
    except ProviderError:
        return
    raise AssertionError("429 debió ser ProviderError (reintentable)")


def test_server_error_is_retryable() -> None:
    client = FakeClient([_api_error(anthropic.InternalServerError, 500)])
    try:
        AnthropicProvider(client=client).complete(
            "s", "u", model="m", temperature=None, max_tokens=10, timeout_s=5
        )
    except ProviderError:
        return
    raise AssertionError("500 debió ser ProviderError")


def test_auth_error_is_fatal() -> None:
    client = FakeClient([_api_error(anthropic.AuthenticationError, 401)])
    try:
        AnthropicProvider(client=client).complete(
            "s", "u", model="m", temperature=None, max_tokens=10, timeout_s=5
        )
    except ProviderFatalError:
        return
    raise AssertionError("401 debió ser ProviderFatalError (no reintentable)")


def test_pipeline_retries_on_rate_limit_then_succeeds() -> None:
    client = FakeClient([_api_error(anthropic.RateLimitError, 429), _message(VALID_JSON, 100, 30)])
    result = _pipeline(client).run("me cobraron dos veces la suscripción")
    assert result.success is True
    assert result.attempts == 2
    assert result.response.category is Category.BILLING
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 30
    assert result.token_source == "api"


def test_pipeline_sums_usage_across_retries() -> None:
    client = FakeClient([_message("no es json", 100, 10), _message(VALID_JSON, 110, 20)])
    result = _pipeline(client).run("me cobraron dos veces la suscripción")
    assert result.attempts == 2
    assert result.prompt_tokens == 210
    assert result.completion_tokens == 30


def test_pipeline_fatal_error_propagates() -> None:
    client = FakeClient([_api_error(anthropic.AuthenticationError, 401)])
    try:
        _pipeline(client).run("hola")
    except ProviderFatalError:
        return
    raise AssertionError("un error fatal no debe convertirse en fallback")


def test_missing_key_is_unavailable() -> None:
    previous = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        _client_from_env()
    except ProviderUnavailable as exc:
        assert "ANTHROPIC_API_KEY" in str(exc)
        return
    finally:
        if previous is not None:
            os.environ["ANTHROPIC_API_KEY"] = previous
    raise AssertionError("sin clave debió ser ProviderUnavailable")


def test_client_disables_sdk_retries() -> None:
    previous = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-no-real"
    try:
        client = _client_from_env()
        assert client.max_retries == 0
    finally:
        if previous is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = previous


def test_factory_builds_anthropic_when_key_present() -> None:
    previous = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-no-real"
    try:
        assert build_provider("anthropic").name == "anthropic"
    finally:
        if previous is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = previous


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

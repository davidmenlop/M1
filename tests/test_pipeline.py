"""Tests de la Fase 2: parseo, pipeline con mock, reintento, fallback, costo y métricas.

Ejecutar: python tests/test_pipeline.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ConfigError, ModelConfig, available_models, load_model_config  # noqa: E402
from src.observability.metrics import append_metric, build_record  # noqa: E402
from src.observability.pricing import compute_cost  # noqa: E402
from src.pipeline import ParseError, TriagePipeline, extract_json  # noqa: E402
from src.prompts import load_prompt  # noqa: E402
from src.providers.base import ProviderUnavailable  # noqa: E402
from src.providers.factory import build_provider  # noqa: E402
from src.providers.mock_provider import MockProvider, classify  # noqa: E402
from src.schemas import Category, TriageResponse  # noqa: E402

MODEL = ModelConfig(
    id="mock-1",
    temperature=0.0,
    max_tokens=700,
    input_per_1m_usd=0.0,
    output_per_1m_usd=0.0,
)

EXAMPLES = [
    ("Hola, me cobraron dos veces la suscripción de este mes, necesito que me reintegren uno de los cargos.", "billing"),
    ("no me llega la factura de agosto, la necesito para mi contador urgente", "billing"),
    ("El dashboard de reportes me tira error 500 desde ayer, no puedo generar el cierre de caja.", "technical"),
    ("Se me cayó la integración con Mercado Pago, los pagos no se están sincronizando desde esta mañana.", "technical"),
    ("Quiero agregar un usuario nuevo a mi cuenta con permisos de solo lectura, ¿cómo lo hago?", "account"),
    ("Necesito cambiar el email de administrador de la cuenta, el actual ya no existe en mi empresa.", "account"),
    ("¿Tienen algún descuento para clientes que llevan más de 2 años con Nubbix?", "other"),
    ("hola buenas, quería saber si tienen planes para empresas más grandes, somos 80 empleados", "other"),
]


def _pipeline(provider: MockProvider | None = None, max_retries: int = 2) -> TriagePipeline:
    return TriagePipeline(
        provider=provider or MockProvider(),
        model=MODEL,
        prompt=load_prompt("v1"),
        max_retries=max_retries,
        timeout_s=30,
    )


def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_fence() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_finds_object_in_prose() -> None:
    assert extract_json('Aquí va: {"a": 1} espero que sirva') == {"a": 1}


def test_extract_json_rejects_non_json() -> None:
    try:
        extract_json("no es json")
    except ParseError:
        return
    raise AssertionError("texto sin JSON debió fallar")


def test_mock_classifies_example_tickets() -> None:
    for text, expected in EXAMPLES:
        category, _ = classify(text)
        assert category == expected, f"{expected} esperado, {category} obtenido para: {text[:40]}"


def test_pipeline_succeeds_on_first_attempt() -> None:
    result = _pipeline().run(EXAMPLES[0][0])
    assert result.success is True
    assert result.attempts == 1
    assert result.response.category is Category.BILLING
    assert result.token_source == "estimated"
    assert result.cost_usd == 0.0


def test_retry_recovers_after_malformed_output() -> None:
    result = _pipeline(MockProvider(malformed_attempts=1)).run(EXAMPLES[2][0])
    assert result.success is True
    assert result.attempts == 2
    assert result.response.category is Category.TECHNICAL


def test_fallback_after_all_attempts_fail() -> None:
    result = _pipeline(MockProvider(malformed_attempts=10), max_retries=2).run(EXAMPLES[0][0])
    assert result.success is False
    assert result.attempts == 3
    assert result.response.category is Category.OTHER
    assert result.response.confidence == 0.0
    assert result.response.actions == ["Escalar la consulta a un agente humano"]
    assert result.error is not None


def test_cost_is_reproducible() -> None:
    cost = compute_cost(1_000_000, 500_000, 0.40, 1.60)
    assert abs(cost - 1.20) < 1e-9


def test_metrics_append_jsonl() -> None:
    required = {
        "ts", "request_id", "provider", "model", "prompt_version", "query_sha256",
        "attempts", "retries", "success", "category", "confidence", "prompt_tokens",
        "completion_tokens", "total_tokens", "token_source", "latency_s", "cost_usd", "error",
    }
    query = EXAMPLES[4][0]
    result = _pipeline().run(query)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sub" / "metrics.jsonl"
        append_metric(path, build_record(result, query))
        append_metric(path, build_record(result, query))
        lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert required <= set(record)
    assert record["total_tokens"] == record["prompt_tokens"] + record["completion_tokens"]
    assert len(record["query_sha256"]) == 64


def test_prompt_render_injects_contract_and_query() -> None:
    prompt = load_prompt("v1")
    system, user = prompt.render("hola")
    assert "{contract}" not in system
    assert "{query}" not in user
    assert "<consulta>" in user and "hola" in user
    assert '"category"' in system


def test_unknown_provider_is_unavailable() -> None:
    try:
        build_provider("desconocido")
    except ProviderUnavailable as exc:
        assert "openai" in str(exc) and "anthropic" in str(exc)
        return
    raise AssertionError("un proveedor desconocido debió no estar disponible")


def test_model_key_selects_alternative_model() -> None:
    config = load_model_config("anthropic", "haiku-5-5")
    assert config.id == "claude-haiku-5-5"
    assert config.temperature is None
    assert config.effort == "low"
    assert "haiku-5-5" in available_models("anthropic")


def test_default_model_has_no_effort() -> None:
    assert load_model_config("anthropic").effort is None
    assert load_model_config("openai").temperature == 0.0


def test_unknown_model_key_is_config_error() -> None:
    try:
        load_model_config("anthropic", "no-existe")
    except ConfigError as exc:
        assert "default" in str(exc) and "haiku-5-5" in str(exc)
        return
    raise AssertionError("una clave de modelo inexistente debió ser ConfigError")


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

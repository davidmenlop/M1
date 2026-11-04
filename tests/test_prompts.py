"""Tests de los prompts versionados (sin red).

Ejecutar: python tests/test_prompts.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ModelConfig  # noqa: E402
from src.pipeline import TriagePipeline  # noqa: E402
from src.prompts import PromptError, list_versions, load_prompt  # noqa: E402
from src.providers.base import LLMProvider, LLMResponse  # noqa: E402
from src.providers.mock_provider import MockProvider  # noqa: E402
from src.schemas import Category, TriageResponse  # noqa: E402

MODEL = ModelConfig(id="fake", temperature=None, max_tokens=700, input_per_1m_usd=0, output_per_1m_usd=0)
PLACEHOLDERS = ("{contract}", "{examples}", "{query}")

CONTRACT_OK = {
    "answer": "Revisamos el cargo.",
    "confidence": 0.9,
    "category": "billing",
    "actions": ["Verificar pagos"],
}


class ScriptedProvider(LLMProvider):
    """Devuelve textos fijos en orden y guarda lo que recibió."""

    name = "scripted"

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.users: list[str] = []
        self.systems: list[str] = []

    def complete(self, system, user, *, model, temperature, max_tokens, timeout_s, effort=None):
        self.systems.append(system)
        self.users.append(user)
        return LLMResponse(text=self._texts.pop(0), prompt_tokens=10, completion_tokens=5, token_source="api")


def _pipeline(version: str, provider: LLMProvider) -> TriagePipeline:
    return TriagePipeline(provider=provider, model=MODEL, prompt=load_prompt(version), max_retries=2, timeout_s=5)


def _write(tmp: Path, name: str, body: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")  # JSON es YAML válido
    return path


def _base(version: str = "v9", **extra) -> dict:
    return {
        "version": version,
        "technique": "test",
        "system": "Contrato: {contract}",
        "user_template": "<consulta>{query}</consulta>",
        **extra,
    }


def _expect_prompt_error(body: dict, fragment: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _write(Path(tmp), "v9_test.yaml", body)
        try:
            load_prompt("v9", Path(tmp))
        except PromptError as exc:
            assert fragment in str(exc), str(exc)
            return
    raise AssertionError(f"se esperaba PromptError con '{fragment}'")


# --- Carga y render de las versiones reales -------------------------------------------


def test_four_versions_available() -> None:
    assert list_versions() == ["v1", "v2", "v3", "v4"]


def test_every_version_loads_and_renders_without_placeholders() -> None:
    for version in list_versions():
        system, user = load_prompt(version).render("me cobraron dos veces")
        for placeholder in PLACEHOLDERS:
            assert placeholder not in system + user, (version, placeholder)
        assert "<consulta>\nme cobraron dos veces\n</consulta>" in user, version
        assert "JSON" in system, f"{version}: JSON mode de OpenAI exige la palabra JSON"


def test_v1_render_is_unchanged() -> None:
    system, _ = load_prompt("v1").render("hola")
    assert TriageResponse.json_contract() in system


def test_v2_to_v4_have_one_example_per_category() -> None:
    for version in ("v2", "v3", "v4"):
        categories = {ex.output["category"] for ex in load_prompt(version).examples}
        assert categories == {c.value for c in Category}, version


def test_examples_are_rendered_in_system() -> None:
    prompt = load_prompt("v2")
    system, _ = prompt.render("x")
    for example in prompt.examples:
        assert example.query in system


def test_v3_contract_puts_reasoning_first_and_required() -> None:
    schema = json.loads(load_prompt("v3").contract())
    assert list(schema["properties"])[0] == "reasoning"
    assert schema["required"][0] == "reasoning"
    assert set(TriageResponse.model_fields) <= set(schema["properties"])


def test_v4_only_changes_rules_over_v3() -> None:
    # v4 aísla el efecto de las reglas de negocio: mismos ejemplos, campos internos y seguridad.
    v3, v4 = load_prompt("v3"), load_prompt("v4")
    assert v4.examples == v3.examples
    assert v4.internal_fields == v3.internal_fields
    assert v4.user_template == v3.user_template
    security = v3.system.split("## Seguridad")[1].split("## Categorías")[0]
    assert security in v4.system
    for rule in ("baja de la suscripción", "email que recibe las facturas", "datos incorrectos"):
        assert rule in v4.system and rule not in v3.system, rule


def test_v2_contract_has_no_internal_fields() -> None:
    schema = json.loads(load_prompt("v2").contract())
    assert "reasoning" not in schema["properties"]


def test_unknown_version_lists_available() -> None:
    try:
        load_prompt("v7")
    except PromptError as exc:
        assert "v1, v2, v3, v4" in str(exc)
        return
    raise AssertionError("una versión inexistente debió ser PromptError")


# --- Validación del YAML --------------------------------------------------------------


def test_invalid_example_is_rejected() -> None:
    bad = {**CONTRACT_OK, "category": "facturacion"}
    body = _base(system="{contract} {examples}", examples=[{"query": "q", "output": bad}])
    _expect_prompt_error(body, "no cumple el contrato")


def test_examples_without_slot_are_rejected() -> None:
    body = _base(examples=[{"query": "q", "output": CONTRACT_OK}])
    _expect_prompt_error(body, "{examples}")


def test_slot_without_examples_is_rejected() -> None:
    _expect_prompt_error(_base(system="{contract} {examples}"), "no hay 'examples'")


def test_internal_field_cannot_shadow_contract() -> None:
    _expect_prompt_error(_base(internal_fields={"category": "x"}), "redefinir")


def test_example_must_include_internal_fields() -> None:
    body = _base(
        system="{contract} {examples}",
        internal_fields={"reasoning": "por qué"},
        examples=[{"query": "q", "output": CONTRACT_OK}],
    )
    _expect_prompt_error(body, "campos internos")


# --- Integración con el pipeline -------------------------------------------------------


def test_v3_reasoning_is_stripped_before_validation() -> None:
    payload = {"reasoning": "Cobro duplicado: billing.", **CONTRACT_OK}
    provider = ScriptedProvider([json.dumps(payload)])
    result = _pipeline("v3", provider).run("me cobraron dos veces")
    assert result.success is True and result.attempts == 1
    assert "reasoning" not in result.response.to_dict()
    assert "reasoning" not in result.response.to_json()


def test_v2_rejects_reasoning_as_extra_field() -> None:
    payload = {"reasoning": "no pedido", **CONTRACT_OK}
    provider = ScriptedProvider([json.dumps(payload), json.dumps(CONTRACT_OK)])
    result = _pipeline("v2", provider).run("me cobraron dos veces")
    assert result.success is True
    assert result.attempts == 2, "un campo fuera del contrato debe disparar reintento"
    assert "reasoning" in provider.users[1]


def test_mock_runs_end_to_end_with_every_version() -> None:
    for version in list_versions():
        result = _pipeline(version, MockProvider()).run("Me cobraron dos veces la suscripción")
        assert result.success is True, version
        assert result.response.category is Category.BILLING, version
        assert result.prompt_version == version


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

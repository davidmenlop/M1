"""Smoke tests del contrato. Ejecutar: python tests/test_schemas.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from src.schemas import Category, TriageResponse


def _valid_payload() -> dict:
    return {
        "answer": "Revisamos el doble cobro y te confirmamos el reintegro en 48 h.",
        "confidence": 0.86,
        "category": "billing",
        "actions": ["Verificar pagos duplicados", "Solicitar reintegro"],
    }


def test_valid_payload() -> None:
    result = TriageResponse.model_validate(_valid_payload())
    assert result.category is Category.BILLING
    assert result.confidence == 0.86
    assert 1 <= len(result.actions) <= 3


def test_category_is_normalized() -> None:
    result = TriageResponse.model_validate({**_valid_payload(), "category": "  BILLING "})
    assert result.category is Category.BILLING


def test_actions_are_cleaned_and_deduplicated() -> None:
    result = TriageResponse.model_validate(
        {
            **_valid_payload(),
            "actions": ["  Verificar  pagos ", "verificar pagos", "", "   ", "Reintegrar"],
        }
    )
    assert result.actions == ["Verificar pagos", "Reintegrar"]


def test_actions_are_capped_at_three() -> None:
    result = TriageResponse.model_validate(
        {**_valid_payload(), "actions": ["a1", "a2", "a3", "a4"]}
    )
    assert result.actions == ["a1", "a2", "a3"]


def test_rejects_out_of_range_confidence() -> None:
    for bad in (-0.1, 1.1):
        try:
            TriageResponse.model_validate({**_valid_payload(), "confidence": bad})
        except ValidationError:
            continue
        raise AssertionError(f"confidence={bad} debio fallar")


def test_rejects_unknown_category() -> None:
    try:
        TriageResponse.model_validate({**_valid_payload(), "category": "ventas"})
    except ValidationError:
        return
    raise AssertionError("una categoria desconocida debio fallar")


def test_rejects_extra_fields() -> None:
    try:
        TriageResponse.model_validate({**_valid_payload(), "reasoning": "..."})
    except ValidationError:
        return
    raise AssertionError("un campo extra debio fallar")


def test_rejects_blank_answer() -> None:
    try:
        TriageResponse.model_validate({**_valid_payload(), "answer": "   "})
    except ValidationError:
        return
    raise AssertionError("un answer vacio debio fallar")


def test_rejects_empty_actions() -> None:
    try:
        TriageResponse.model_validate({**_valid_payload(), "actions": ["", "  "]})
    except ValidationError:
        return
    raise AssertionError("actions vacias debieron fallar")


def test_json_is_ascii_safe_and_matches_contract() -> None:
    result = TriageResponse.model_validate({**_valid_payload(), "answer": "Facturacion y nandu"})
    payload = result.to_json()
    assert payload.isascii()
    assert set(json.loads(payload)) == {"answer", "confidence", "category", "actions"}
    assert result.to_dict()["category"] == "billing"


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

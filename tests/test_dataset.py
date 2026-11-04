"""Tests del dataset de evaluación y de la herramienta de revisión (sin red).

Ejecutar: python tests/test_dataset.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import (  # noqa: E402
    EXPECTED_SPLIT,
    MIN_PER_CATEGORY,
    leakage,
    load_dataset,
    save_dataset,
    summary,
    validate,
)
from evals.review_labels import Quit, apply_decision  # noqa: E402

CASES = load_dataset()


def _errors(cases, prompts_dir=None) -> list[str]:
    return validate(cases, prompts_dir).errors


def _with(index: int, **changes) -> list[dict]:
    cases = copy.deepcopy(CASES)
    cases[index].update(changes)
    return cases


# --- El dataset real -----------------------------------------------------------------


def test_real_dataset_is_structurally_valid() -> None:
    report = validate(CASES)
    assert report.ok, report.errors


def test_real_dataset_size_split_and_balance() -> None:
    info = summary(CASES)
    assert info["total"] == sum(EXPECTED_SPLIT.values())
    for category, row in info["by_category"].items():
        assert sum(row.values()) >= MIN_PER_CATEGORY, category
        assert row["holdout"] >= 1, category


def test_real_dataset_has_no_leakage() -> None:
    assert leakage(CASES) == []


def test_every_difficulty_and_edge_case_present() -> None:
    assert {c["difficulty"] for c in CASES} == {"easy", "medium", "hard"}
    edges = [c for c in CASES if c["id"].startswith("edge-")]
    assert len(edges) == 8
    tags = {t for c in edges for t in c["tags"]}
    for tag in ("ambiguo", "fuera_de_alcance", "portugues", "largo", "amenaza_legal", "inyeccion", "sin_informacion"):
        assert tag in tags, tag


# --- Validación ----------------------------------------------------------------------


def test_invalid_category_is_error() -> None:
    assert any("expected_category" in e for e in _errors(_with(0, expected_category="facturacion")))


def test_validated_requires_reviewer() -> None:
    assert any("validated_by" in e for e in _errors(_with(0, label_status="validated", validated_by=None)))


def test_disputed_requires_note() -> None:
    assert any("disputa" in e for e in _errors(_with(0, label_status="disputed", validated_by="x", review_note=None)))


def test_accented_keywords_are_error() -> None:
    cases = _with(0, expected_actions=[{"intent": "x", "keywords": ["facturación"]}])
    assert any("tildes" in e for e in _errors(cases))


def test_empty_input_is_error() -> None:
    assert any("vacío" in e for e in _errors(_with(0, input="   ")))


def test_unknown_field_is_error() -> None:
    assert any("desconocidos" in e for e in _errors(_with(0, extra_field=1)))


def test_near_duplicates_are_error() -> None:
    cases = _with(1, input=CASES[0]["input"] + " gracias")
    assert any("casi duplicados" in e for e in _errors(cases))


def test_wrong_split_size_is_error() -> None:
    holdout = next(i for i, c in enumerate(CASES) if c["split"] == "holdout")
    assert any("split holdout" in e for e in _errors(_with(holdout, split="dev")))


def test_leakage_detects_copied_example() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prompt = {
            "version": "v1",
            "technique": "t",
            "system": "{contract} {examples}",
            "user_template": "{query}",
            "examples": [{
                "query": CASES[0]["input"].upper(),
                "output": {"answer": "a", "confidence": 0.5, "category": "billing", "actions": ["x"]},
            }],
        }
        (Path(tmp) / "v1_test.yaml").write_text(json.dumps(prompt), encoding="utf-8")
        problems = leakage(CASES, Path(tmp))
    assert problems and CASES[0]["id"] in problems[0] and "idéntico" in problems[0]


def test_drafts_are_warning_not_error() -> None:
    report = validate(CASES)
    drafts = sum(1 for c in CASES if c["label_status"] == "draft")
    if drafts:
        assert any("sin validar" in w for w in report.warnings)


# --- Revisión ------------------------------------------------------------------------


def test_accept_validates_without_changing_label() -> None:
    case = CASES[0]
    updated = apply_decision(case, "", "Ana")
    assert updated["label_status"] == "validated"
    assert updated["validated_by"] == "Ana"
    assert updated["expected_category"] == case["expected_category"]
    assert case["label_status"] == CASES[0]["label_status"], "no debe mutar el original"


def test_change_category_keeps_proposal_and_leaves_reminder() -> None:
    case = next(c for c in CASES if c["expected_category"] == "billing")
    updated = apply_decision(case, "a", "Ana", "es un permiso")
    assert updated["expected_category"] == "account"
    assert updated["proposed_category"] == "billing"
    assert "es un permiso" in updated["review_note"]
    assert "revisar expected_actions" in updated["review_note"]


def test_same_category_key_is_plain_accept() -> None:
    case = next(c for c in CASES if c["expected_category"] == "billing")
    updated = apply_decision(case, "b", "Ana")
    assert updated["review_note"] is None


def test_dispute_requires_note() -> None:
    try:
        apply_decision(CASES[0], "d", "Ana", "")
    except ValueError:
        pass
    else:
        raise AssertionError("una disputa sin nota debió fallar")
    updated = apply_decision(CASES[0], "d", "Ana", "podría ser technical")
    assert updated["label_status"] == "disputed"


def test_skip_and_quit() -> None:
    assert apply_decision(CASES[0], "s", "Ana") is None
    try:
        apply_decision(CASES[0], "q", "Ana")
    except Quit:
        return
    raise AssertionError("q debió lanzar Quit")


def test_reviewed_dataset_stays_valid_and_reports_agreement() -> None:
    # Parte de un dataset sin cambios de revisión, sea cual sea el estado real del archivo.
    cases = [{**c, "expected_category": c["proposed_category"]} for c in copy.deepcopy(CASES)]
    cases = [apply_decision(c, "", "Ana") for c in cases]
    billing = next(i for i, c in enumerate(cases) if c["proposed_category"] == "billing")
    cases[billing] = apply_decision(cases[billing], "o", "Ana")
    report = validate(cases)
    assert report.ok and not report.warnings, (report.errors, report.warnings)
    info = summary(cases)
    assert info["changed_by_reviewer"] == [cases[billing]["id"]]
    assert info["agreement"] == round(1 - 1 / len(cases), 3)


def test_save_and_load_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dataset.jsonl"
        save_dataset(CASES, path)
        assert load_dataset(path) == CASES
        assert list(Path(tmp).iterdir()) == [path], "no deben quedar temporales"


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

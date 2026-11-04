"""Tests de las métricas y del runner de evals (sin red).

Ejecutar: python tests/test_eval_metrics.py
"""

from __future__ import annotations

import contextlib
import io
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import DatasetError, load_dataset  # noqa: E402
from evals.metrics import (  # noqa: E402
    action_score,
    aggregate,
    check_thresholds,
    compute,
    keyword_coverage,
    percentile,
)
from evals.runner import main as runner_main  # noqa: E402
from evals.runner import select_cases  # noqa: E402

INTENT_COBRO = {"intent": "verificar cobro", "keywords": ["cobro", "debito"]}
INTENT_REINTEGRO = {"intent": "reintegrar", "keywords": ["reintegr"]}


def _r(cid, expected, predicted, confidence=0.9, success=True, attempts=1, cost=0.001, latency=1.0,
       actions=None, answer="", keywords=None, difficulty="easy"):
    return {
        "id": cid, "expected": expected, "predicted": predicted, "confidence": confidence,
        "success": success, "attempts": attempts, "cost_usd": cost, "latency_s": latency,
        "actions": actions or [], "expected_actions": [INTENT_COBRO], "answer": answer,
        "answer_keywords": keywords or [], "difficulty": difficulty,
        "prompt_tokens": 100, "completion_tokens": 20,
    }


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, abs_tol=1e-9)


# Escenario de referencia, calculado a mano:
#   billing:   2 casos, ambos bien
#   technical: 2 casos, 1 bien y 1 predicho billing
#   account:   1 caso, bien
#   other:     1 caso, predicho account
RESULTS = [
    _r("b1", "billing", "billing"),
    _r("b2", "billing", "billing"),
    _r("t1", "technical", "technical"),
    _r("t2", "technical", "billing", confidence=0.6, attempts=2),
    _r("a1", "account", "account"),
    _r("o1", "other", "account", confidence=0.5, success=False, attempts=3),
]


def test_accuracy_and_confusion() -> None:
    m = compute(RESULTS)
    assert _close(m["accuracy"], 4 / 6)
    assert m["confusion_matrix"]["technical"]["billing"] == 1
    assert m["confusion_matrix"]["other"]["account"] == 1
    assert {x["id"] for x in m["misclassified"]} == {"t2", "o1"}


def test_per_class_and_macro_f1() -> None:
    m = compute(RESULTS)
    pc = m["per_class"]
    # billing: tp=2 fp=1 fn=0 -> p=2/3 r=1 f1=0.8
    assert _close(pc["billing"]["precision"], 2 / 3) and _close(pc["billing"]["f1"], 0.8)
    # technical: tp=1 fp=0 fn=1 -> p=1 r=0.5 f1=2/3
    assert _close(pc["technical"]["f1"], 2 / 3)
    # account: tp=1 fp=1 fn=0 -> p=0.5 r=1 f1=2/3
    assert _close(pc["account"]["f1"], 2 / 3)
    # other: tp=0 -> f1=0
    assert pc["other"]["f1"] == 0.0
    assert _close(m["macro_f1"], (0.8 + 2 / 3 + 2 / 3 + 0) / 4)
    assert m["min_class_recall"] == 0.0


def test_reliability_metrics() -> None:
    m = compute(RESULTS)
    assert _close(m["schema_valid_rate"], 5 / 6)
    assert _close(m["retry_rate"], 2 / 6)
    assert _close(m["first_try_valid_rate"], 4 / 6)
    assert m["errors"] == ["o1"]


def test_brier_and_confidence_split() -> None:
    m = compute(RESULTS)
    expected = (4 * (0.9 - 1) ** 2 + (0.6 - 0) ** 2 + (0.5 - 0) ** 2) / 6
    assert _close(m["brier"], expected)
    assert _close(m["mean_confidence_correct"], 0.9)
    assert _close(m["mean_confidence_wrong"], 0.55)


def test_action_score_normalizes_accents_and_case() -> None:
    assert action_score([INTENT_COBRO], ["Revisar el DÉBITO duplicado"]) == 1.0
    assert action_score([INTENT_COBRO, INTENT_REINTEGRO], ["Revisar el cobro"]) == 0.5
    assert action_score([INTENT_COBRO], ["Escalar a ingeniería"]) == 0.0


def test_keyword_coverage() -> None:
    assert keyword_coverage([], "x") is None
    assert keyword_coverage(["factura", "cobro"], "Revisamos tu Factura") == 0.5


def test_coverage_ignores_cases_without_keywords() -> None:
    results = [_r("x", "billing", "billing", answer="cobro", keywords=["cobro"]), _r("y", "billing", "billing")]
    assert compute(results)["answer_keyword_coverage"] == 1.0


def test_percentile_interpolates() -> None:
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert _close(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95), 9.55)
    assert percentile([], 0.5) == 0.0


def test_cost_and_latency() -> None:
    m = compute(RESULTS)
    assert _close(m["total_cost_usd"], 0.006)
    assert _close(m["mean_cost_usd"], 0.001)
    assert m["latency_p95_s"] == 1.0


def test_aggregate_mean_and_std() -> None:
    a = compute(RESULTS)
    b = compute([_r("b1", "billing", "billing")] * 6)
    summary = aggregate([a, b])
    assert summary["runs"] == 2
    assert _close(summary["accuracy"]["mean"], (4 / 6 + 1) / 2)
    assert summary["accuracy"]["std"] > 0
    single = aggregate([a])
    assert _close(single["accuracy"], 4 / 6)


def test_thresholds() -> None:
    checks = check_thresholds(aggregate([compute(RESULTS)]))
    assert checks["schema_valid_rate"]["passed"] is False
    assert checks["mean_cost_usd"]["passed"] is True
    perfect = check_thresholds(aggregate([compute([_r("b", "billing", "billing")])]))
    assert all(c["passed"] for c in perfect.values())


def test_select_cases_excludes_unvalidated() -> None:
    cases = load_dataset()
    cases[0] = {**cases[0], "label_status": "draft"}
    selected, skipped = select_cases(cases, cases[0]["split"], None)
    assert cases[0]["id"] in skipped
    assert all(c["label_status"] == "validated" for c in selected)


def test_select_cases_by_ids_and_unknown_id() -> None:
    cases = load_dataset()
    selected, _ = select_cases(cases, "all", ["acc-04", "tec-01"])
    assert sorted(c["id"] for c in selected) == ["acc-04", "tec-01"]
    try:
        select_cases(cases, "dev", ["no-existe"])
    except DatasetError:
        return
    raise AssertionError("un id inexistente debió ser DatasetError")


def test_runner_end_to_end_with_mock() -> None:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = runner_main(["--provider", "mock", "--no-save", "--ids", "bil-01", "tec-01", "oth-02"])
    assert code == 0, err.getvalue()
    report = out.getvalue()
    assert "3 casos × 1 corrida" in report
    assert "Matriz de confusión" in report and "Umbrales de aceptación" in report


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

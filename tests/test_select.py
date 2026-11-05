"""Tests del criterio de selección (ADR-022), sin red.

Ejecutar: python tests/test_select.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.select import Candidate, load_candidates, select  # noqa: E402


def _c(prompt, f1, action=0.9, cost=0.001, p95=2.0, schema=1.0, retry=0.0, provider="openai"):
    return Candidate(path=Path(f"{prompt}.json"), provider=provider, model_key="default", model_id="m",
                     prompt=prompt, runs=1, macro_f1=f1, action=action, cost=cost, p95=p95,
                     schema=schema, retry=retry)


def test_best_macro_f1_wins_when_gap_is_large() -> None:
    result = select([_c("a", 0.90), _c("b", 0.95)])
    assert result["winner"].prompt == "b"
    assert "del mejor" in result["stage"][_c("a", 0).key]


def test_gates_discard_before_ranking() -> None:
    result = select([_c("a", 1.0, schema=0.97), _c("b", 1.0, retry=0.2), _c("c", 0.80)])
    assert result["winner"].prompt == "c"
    assert result["stage"][_c("a", 0).key].startswith("descartado: schema")
    assert result["stage"][_c("b", 0).key].startswith("descartado: retry")


def test_retry_rate_at_limit_passes() -> None:
    assert select([_c("a", 0.9, retry=0.10)])["winner"].prompt == "a"


def test_f1_tie_is_broken_by_action_score() -> None:
    result = select([_c("a", 0.95, action=0.80), _c("b", 0.93, action=0.90)])
    assert result["winner"].prompt == "b"
    assert "action" in result["stage"][_c("a", 0).key]


def test_second_tie_is_broken_by_cost_then_latency() -> None:
    result = select([_c("a", 0.95, action=0.90, cost=0.002), _c("b", 0.94, action=0.89, cost=0.001)])
    assert result["winner"].prompt == "b"
    same_cost = select([_c("a", 0.95, cost=0.001, p95=3.0), _c("b", 0.95, cost=0.001, p95=2.0)])
    assert same_cost["winner"].prompt == "b"


def test_difference_of_exactly_tie_threshold_is_not_a_tie() -> None:
    result = select([_c("a", 0.93, action=1.0), _c("b", 0.96, action=0.5)])
    assert result["winner"].prompt == "b"


def test_no_eligible_candidate() -> None:
    assert select([_c("a", 1.0, schema=0.5)])["winner"] is None


def test_real_results_exclude_baseline_and_single_anthropic_runs() -> None:
    results = sorted((Path(__file__).resolve().parents[1] / "evals" / "results").glob("*.json"))
    candidates, excluded = load_candidates(results)
    assert all(c.provider != "mock" for c in candidates)
    assert all(c.runs >= 3 for c in candidates if c.provider == "anthropic")
    assert any("línea base" in line for line in excluded)


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

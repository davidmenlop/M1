"""Aplica el criterio de selección declarado antes de medir (ADR-022) a los resultados guardados.

Uso:
    python evals/select.py evals/results/*.json

Solo cuentan como evidencia las corridas del split dev que:
- se hicieron con el árbol limpio (ADR-026);
- usan el dataset y el prompt actuales (mismo sha256);
- en Anthropic, promedian al menos 3 corridas (ADR-022);
- tienen los guardrails en el estado pedido (--guardrails; por defecto off, como la Fase 7).
El mock es la línea base: se muestra en la comparativa, pero no compite.
Si hay varias corridas de la misma combinación, se usa la más reciente.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import DATASET_PATH  # noqa: E402
from evals.metrics import value  # noqa: E402
from src.prompts import PROMPTS_DIR  # noqa: E402

TIE = 0.03                 # diferencia que se considera ruido con 32 casos (ADR-022)
MAX_RETRY_RATE = 0.10
MIN_REPEATS = {"anthropic": 3}
OVERFIT_DROP = 0.10        # caída de macro-F1 en holdout que se reporta como sobreajuste


@dataclass
class Candidate:
    path: Path
    provider: str
    model_key: str
    model_id: str
    prompt: str
    runs: int
    macro_f1: float
    action: float
    cost: float
    p95: float
    schema: float
    retry: float

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.provider, self.model_id, self.prompt)

    @property
    def label(self) -> str:
        return f"{self.provider} / {self.model_id} · {self.prompt}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_candidates(paths: list[Path], split: str = "dev", guardrails: str = "off") -> tuple[list[Candidate], list[str]]:
    """Lee los resultados válidos como evidencia; devuelve también por qué se excluyó cada uno."""
    dataset_sha = _sha256(DATASET_PATH)
    latest: dict[tuple[str, str, str], tuple[str, Candidate]] = {}
    excluded = []
    for path in sorted(paths):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta, summary = data["meta"], data["summary"]
        if meta["split"] != split:
            continue
        prompt_file = PROMPTS_DIR / meta["prompt_file"]
        reason = None
        if meta["provider"] == "mock":
            reason = "línea base, no es candidato"
        elif meta["git"]["dirty"]:
            reason = "árbol sucio"
        elif meta["dataset_sha256"] != dataset_sha:
            reason = "dataset distinto del actual"
        elif not prompt_file.exists() or meta["prompt_sha256"] != _sha256(prompt_file):
            reason = "prompt distinto del actual"
        elif ("on" if meta.get("guardrails", {}).get("enabled") else "off") != guardrails:
            reason = f"guardrails distintos de '{guardrails}'"
        elif summary["runs"] < MIN_REPEATS.get(meta["provider"], 1):
            reason = f"{summary['runs']} corrida(s); se exigen {MIN_REPEATS[meta['provider']]}"
        if reason:
            excluded.append(f"{path.name}: {reason}")
            continue
        candidate = Candidate(
            path=path, provider=meta["provider"], model_key=meta["model_key"], model_id=meta["model_id"],
            prompt=meta["prompt_version"], runs=summary["runs"],
            macro_f1=value(summary["macro_f1"]), action=value(summary["action_score"]),
            cost=value(summary["mean_cost_usd"]), p95=value(summary["latency_p95_s"]),
            schema=value(summary["schema_valid_rate"]), retry=value(summary["retry_rate"]),
        )
        previous = latest.get(candidate.key)
        if previous and previous[0] > meta["created_at"]:
            excluded.append(f"{path.name}: hay una corrida más reciente")
            continue
        if previous:
            excluded.append(f"{previous[1].path.name}: hay una corrida más reciente")
        latest[candidate.key] = (meta["created_at"], candidate)
    return [c for _, c in latest.values()], excluded


def _gap(best: float, observed: float) -> float:
    # Redondeo: sin él, 0.96 - 0.93 da 0.0299… y una diferencia de 0.03 contaría como empate.
    return round(best - observed, 9)


def select(candidates: list[Candidate]) -> dict[str, Any]:
    """Devuelve el ganador y la etapa en la que quedó cada candidato (ADR-022)."""
    stage: dict[tuple, str] = {}
    eligible = []
    for c in candidates:
        if c.schema < 1.0:
            stage[c.key] = f"descartado: schema {c.schema:.0%}"
        elif c.retry > MAX_RETRY_RATE:
            stage[c.key] = f"descartado: retry {c.retry:.0%}"
        else:
            eligible.append(c)
    if not eligible:
        return {"winner": None, "stage": stage, "ranking": []}

    best_f1 = max(c.macro_f1 for c in eligible)
    tied_f1 = [c for c in eligible if _gap(best_f1, c.macro_f1) < TIE]
    for c in eligible:
        if c not in tied_f1:
            stage[c.key] = f"macro-F1 a {best_f1 - c.macro_f1:.3f} del mejor"

    best_action = max(c.action for c in tied_f1)
    tied_action = [c for c in tied_f1 if _gap(best_action, c.action) < TIE]
    for c in tied_f1:
        if c not in tied_action:
            stage[c.key] = f"empate en F1; action a {best_action - c.action:.3f} del mejor"

    tied_action.sort(key=lambda c: (c.cost, c.p95))
    winner = tied_action[0]
    for c in tied_action[1:]:
        stage[c.key] = f"empate en F1 y action; más caro ({c.cost / winner.cost:.1f}×)"
    stage[winner.key] = "GANADOR"

    ranking = sorted(candidates, key=lambda c: (c.key not in {x.key for x in eligible}, -c.macro_f1, -c.action, c.cost))
    return {"winner": winner, "stage": stage, "ranking": ranking, "best_f1": best_f1}


def print_selection(result: dict[str, Any], excluded: list[str]) -> None:
    print("| # | combinación | corridas | macro-F1 | action | USD/req | p95 s | resultado |")
    print("|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(result["ranking"], 1):
        print(f"| {i} | {c.label} | {c.runs} | {c.macro_f1:.3f} | {c.action:.3f} | {c.cost:.5f} "
              f"| {c.p95:.2f} | {result['stage'][c.key]} |")
    if excluded:
        print("\nNo cuentan como evidencia:")
        for line in excluded:
            print(f"  - {line}")
    winner = result["winner"]
    print(f"\nGanador (ADR-022): {winner.label if winner else 'ninguno'}")
    if winner:
        print(f"  holdout: python evals/runner.py --provider {winner.provider} "
              f"--model {winner.model_key} --prompt {winner.prompt} --split holdout"
              + (" --repeat 3" if winner.provider in MIN_REPEATS else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--guardrails", choices=("off", "on"), default="off",
                        help="comparar solo corridas con guardrails en este estado (por defecto: off)")
    args = parser.parse_args(argv)
    candidates, excluded = load_candidates(args.results, guardrails=args.guardrails)
    if not candidates:
        print("no hay resultados válidos como evidencia", file=sys.stderr)
        return 1
    print_selection(select(candidates), excluded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

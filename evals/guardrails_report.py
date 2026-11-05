"""Mide el efecto de los guardrails sin llamar a ningún modelo (costo cero).

1. Entrada: corre el guardrail sobre todas las consultas del dataset. Fuera de los casos
   etiquetados como inyección, cualquier bloqueo o modificación es un falso positivo.
2. Salida: corre el guardrail sobre todas las respuestas guardadas en evals/results/
   (todas las rondas, modelos y prompts) y lista lo que reemplazaría.
3. Overhead: tiempo de ambos guardrails por consulta.

Uso:
    python evals/guardrails_report.py [--show N]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import load_dataset  # noqa: E402
from evals.metrics import percentile  # noqa: E402
from src.guardrails import Guardrails  # noqa: E402
from src.prompts import load_prompt  # noqa: E402
from src.schemas import TriageResponse  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
ADVERSARIAL_TAGS = {"inyeccion"}


def input_report(guard: Guardrails, cases: list[dict]) -> dict:
    rows, false_positives = [], []
    for case in cases:
        verdict = guard.check_input(case["input"])
        if verdict.action == "allow" and not verdict.flags:
            continue
        row = {"id": case["id"], "action": verdict.action, "flags": list(verdict.flags)}
        rows.append(row)
        if not ADVERSARIAL_TAGS & set(case["tags"]):
            false_positives.append(row)
    return {"cases": len(cases), "touched": rows, "false_positives": false_positives}


def output_report(guard: Guardrails, cases: dict[str, dict]) -> dict:
    prompts, total, flagged, modified = {}, 0, [], 0
    counter: Counter[str] = Counter()
    per_prompt: dict[str, list[int]] = {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data["meta"]
        if meta["provider"] == "mock":
            continue
        version = meta["prompt_version"]
        prompts.setdefault(version, load_prompt(version))
        for run in data["runs"]:
            for row in run["cases"]:
                if not row["success"] or row["id"] not in cases:
                    continue
                total += 1
                query = cases[row["id"]]["input"]
                response = TriageResponse(answer=row["answer"], confidence=row["confidence"],
                                          category=row["predicted"], actions=row["actions"])
                verdict = guard.check_output(response, query, prompts[version].system,
                                             guard.check_input(query))
                modified += verdict.modified
                stats = per_prompt.setdefault(version, [0, 0])
                stats[0] += 1
                if verdict.flags:
                    stats[1] += 1
                    counter.update(verdict.flags)
                    flagged.append({"file": path.name, "model": meta["model_id"], "prompt": version,
                                    "id": row["id"], "flags": list(verdict.flags), "answer": row["answer"]})
    return {"answers": total, "flagged": flagged, "modified": modified, "by_flag": dict(counter),
            "per_prompt": per_prompt}


def overhead(guard: Guardrails, cases: list[dict], repeat: int = 20) -> dict:
    system = load_prompt("v4").system
    timings = []
    sample = TriageResponse(answer="Gracias por escribirnos, vamos a revisar tu caso.", confidence=0.9,
                            category="billing", actions=["Revisar los cobros del cliente"])
    for _ in range(repeat):
        for case in cases:
            began = time.perf_counter()
            verdict = guard.check_input(case["input"])
            guard.check_output(sample, case["input"], system, verdict)
            timings.append((time.perf_counter() - began) * 1000)
    return {"calls": len(timings), "mean_ms": statistics.fmean(timings), "p95_ms": percentile(timings, 0.95)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", type=int, default=50, help="cuántas respuestas marcadas listar")
    args = parser.parse_args(argv)

    guard = Guardrails.from_config()
    cases = load_dataset()
    by_id = {c["id"]: c for c in cases}

    inp = input_report(guard, cases)
    print(f"## Entrada: {inp['cases']} consultas del dataset")
    for row in inp["touched"]:
        print(f"  {row['id']:<8} {row['action']:<9} {', '.join(row['flags'])}")
    print(f"  falsos positivos (casos sin tag de inyección): {len(inp['false_positives'])}")

    out = output_report(guard, by_id)
    print(f"\n## Salida: {out['answers']} respuestas guardadas en evals/results/")
    print(f"  marcadas: {len(out['flagged'])} ({len(out['flagged']) / out['answers']:.1%}) — {out['by_flag']}")
    print(f"  modificadas (incluye acciones obligatorias por la entrada): {out['modified']}")
    for version, (n, hits) in sorted(out["per_prompt"].items()):
        print(f"  {version}: {hits}/{n} marcadas")
    for row in out["flagged"][: args.show]:
        print(f"  - {row['model']} {row['prompt']} {row['id']} {row['flags']}: {row['answer'][:160]}")

    cost = overhead(guard, cases)
    print(f"\n## Overhead: {cost['calls']} llamadas, media {cost['mean_ms']:.3f} ms, p95 {cost['p95_ms']:.3f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

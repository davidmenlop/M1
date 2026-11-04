"""Valida evals/dataset.jsonl: estructura, balance, duplicados y leakage contra los prompts.

Uso:
    python evals/validate_dataset.py            # errores -> exit 1; casos sin validar -> aviso
    python evals/validate_dataset.py --strict   # además exige que todo esté validado
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import CATEGORIES, DATASET_PATH, SPLITS, DatasetError, load_dataset, summary, validate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=DATASET_PATH)
    parser.add_argument("--strict", action="store_true", help="falla si quedan casos sin validar o en disputa")
    args = parser.parse_args(argv)

    try:
        cases = load_dataset(args.path)
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = validate(cases)
    info = summary(cases)

    print(f"Dataset: {args.path} — {info['total']} casos\n")
    print(f"{'categoría':<12}" + "".join(f"{s:>9}" for s in SPLITS) + f"{'total':>9}")
    for category in CATEGORIES:
        row = info["by_category"][category]
        print(f"{category:<12}" + "".join(f"{row[s]:>9}" for s in SPLITS) + f"{sum(row.values()):>9}")
    print(f"\ndificultad: {info['by_difficulty']}")
    print(f"estado:     {info['by_status']}")
    if info["agreement"] is not None:
        print(
            f"revisados:  {info['reviewed']}; acuerdo con el borrador: {info['agreement']:.0%}"
            + (f" (cambiados: {', '.join(info['changed_by_reviewer'])})" if info["changed_by_reviewer"] else "")
        )

    for warning in report.warnings:
        print(f"aviso: {warning}")
    for error in report.errors:
        print(f"ERROR: {error}")

    if not report.ok:
        print(f"\n{len(report.errors)} errores")
        return 1
    if args.strict and report.warnings:
        print("\n--strict: hay casos sin validar o en disputa")
        return 1
    print("\nestructura OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

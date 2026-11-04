"""Revisión humana de etiquetas del dataset, caso por caso.

Uso (en tu terminal, es interactivo):
    python evals/review_labels.py              # revisa los casos en borrador
    python evals/review_labels.py --all        # vuelve a revisar todos
    python evals/review_labels.py --id acc-04  # un caso puntual
    python evals/review_labels.py --by "Nombre Apellido"

Teclas por caso:
    Enter      aceptar la categoría propuesta
    b t a o    cambiar a billing / technical / account / other
    d          marcar en disputa (pide una nota)
    s          saltar (queda como estaba)
    q          salir

Cada decisión se guarda al instante: se puede cortar y retomar en cualquier momento.
Criterios: evals/guia-de-etiquetado.md
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import DATASET_PATH, load_dataset, save_dataset, summary  # noqa: E402

KEYS = {"b": "billing", "t": "technical", "a": "account", "o": "other"}
WIDTH = 88


class Quit(Exception):
    pass


def apply_decision(case: dict[str, Any], key: str, reviewer: str, note: str | None = None) -> dict[str, Any] | None:
    """Devuelve el caso actualizado, o None si la decisión es saltar. No modifica el original."""
    key = key.strip().lower()
    if key == "q":
        raise Quit
    if key == "s":
        return None
    updated = dict(case)
    note = (note or "").strip() or None
    if key == "":
        updated.update(label_status="validated", validated_by=reviewer, review_note=note)
        return updated
    if key in KEYS:
        new = KEYS[key]
        if new != case["expected_category"]:
            reminder = f"categoría cambiada de {case['expected_category']} a {new}: revisar expected_actions"
            note = f"{note} | {reminder}" if note else reminder
        updated.update(expected_category=new, label_status="validated", validated_by=reviewer, review_note=note)
        return updated
    if key == "d":
        if not note:
            raise ValueError("una disputa necesita una nota")
        updated.update(label_status="disputed", validated_by=reviewer, review_note=note)
        return updated
    raise ValueError(f"tecla desconocida '{key}'")


def _git_user() -> str:
    try:
        name = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        name = ""
    return name or "revisor"


def _show(case: dict[str, Any], position: int, total: int) -> None:
    print("\n" + "=" * WIDTH)
    print(f"[{position}/{total}]  {case['id']}  ·  split {case['split']}  ·  dificultad {case['difficulty']}"
          + (f"  ·  tags: {', '.join(case['tags'])}" if case["tags"] else ""))
    print("-" * WIDTH)
    for line in textwrap.wrap(case["input"], WIDTH - 2):
        print(f"  {line}")
    print("-" * WIDTH)
    status = case["label_status"]
    print(f"Categoría propuesta:  {case['expected_category'].upper()}   (estado: {status})")
    for line in textwrap.wrap(f"Por qué: {case['rationale']}", WIDTH):
        print(line)
    print("Acciones esperadas:   " + " · ".join(a["intent"] for a in case["expected_actions"]))
    if case.get("review_note"):
        print(f"Nota previa:          {case['review_note']}")


def _ask(case: dict[str, Any], reviewer: str) -> dict[str, Any] | None:
    while True:
        key = input("\n[Enter] aceptar · b/t/a/o cambiar · d disputa · s saltar · q salir > ")
        lowered = key.strip().lower()
        note = None
        try:
            if lowered == "d":
                note = input("Motivo de la disputa > ")
            elif lowered in KEYS and KEYS[lowered] != case["expected_category"]:
                note = input("Motivo del cambio (opcional) > ")
            return apply_decision(case, key, reviewer, note)
        except ValueError as exc:
            print(f"  {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Revisión humana de etiquetas")
    parser.add_argument("--path", type=Path, default=DATASET_PATH)
    parser.add_argument("--all", action="store_true", help="revisar también los ya validados")
    parser.add_argument("--id", dest="case_id", help="revisar un único caso")
    parser.add_argument("--by", help="nombre del revisor (por defecto: git config user.name)")
    args = parser.parse_args(argv)

    if not sys.stdin.isatty():
        print("error: la revisión es interactiva; corré el comando en una terminal", file=sys.stderr)
        return 2

    reviewer = args.by or _git_user()
    cases = load_dataset(args.path)
    if args.case_id:
        queue = [i for i, c in enumerate(cases) if c["id"] == args.case_id]
        if not queue:
            print(f"error: no existe el caso {args.case_id}", file=sys.stderr)
            return 2
    else:
        queue = [i for i, c in enumerate(cases) if args.all or c["label_status"] != "validated"]
    if not queue:
        print("No hay casos pendientes. Usá --all para revisar todo de nuevo.")
        return 0

    print(f"Revisor: {reviewer}. {len(queue)} casos para revisar. Criterios: evals/guia-de-etiquetado.md")
    done = 0
    try:
        for position, index in enumerate(queue, start=1):
            _show(cases[index], position, len(queue))
            updated = _ask(cases[index], reviewer)
            if updated is not None:
                cases[index] = updated
                save_dataset(cases, args.path)
                done += 1
                print(f"  guardado: {updated['id']} -> {updated['expected_category']} ({updated['label_status']})")
    except (Quit, KeyboardInterrupt, EOFError):
        print("\nRevisión interrumpida; lo decidido ya está guardado.")

    info = summary(cases)
    print(f"\n{done} decisiones guardadas. Estado: {info['by_status']}")
    if info["agreement"] is not None:
        print(f"Acuerdo con el borrador: {info['agreement']:.0%} de {info['reviewed']} revisados")
    print("Siguiente paso: python evals/validate_dataset.py --strict")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

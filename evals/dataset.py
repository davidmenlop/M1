"""Dataset de evaluación: carga, validación, leakage y resumen.

Formato: evals/dataset.jsonl, un caso por línea. Ver evals/guia-de-etiquetado.md.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import REPO_ROOT
from src.prompts import list_versions, load_prompt
from src.schemas import Category

DATASET_PATH = REPO_ROOT / "evals" / "dataset.jsonl"

CATEGORIES = tuple(c.value for c in Category)
SPLITS = ("dev", "holdout")
DIFFICULTIES = ("easy", "medium", "hard")
STATUSES = ("draft", "validated", "disputed")
ID_PATTERN = re.compile(r"^(bil|tec|acc|oth|edge)-\d{2}$")

EXPECTED_SPLIT = {"dev": 32, "holdout": 8}
MIN_PER_CATEGORY = 8
LEAKAGE_THRESHOLD = 0.5      # Jaccard de tokens contra ejemplos few-shot
DUPLICATE_THRESHOLD = 0.8    # Jaccard entre dos casos del dataset

FIELDS: dict[str, type | tuple[type, ...]] = {
    "id": str,
    "split": str,
    "input": str,
    "expected_category": str,
    "proposed_category": str,
    "difficulty": str,
    "tags": list,
    "rationale": str,
    "expected_actions": list,
    "answer_keywords": list,
    "label_status": str,
    "validated_by": (str, type(None)),
    "review_note": (str, type(None)),
}


class DatasetError(ValueError):
    pass


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", normalize(text)))


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def load_dataset(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        raise DatasetError(f"no existe {path}")
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{path.name}:{number}: JSON inválido: {exc}") from exc
        if not isinstance(case, dict):
            raise DatasetError(f"{path.name}:{number}: cada línea debe ser un objeto")
        cases.append(case)
    return cases


def save_dataset(cases: list[dict[str, Any]], path: Path = DATASET_PATH) -> None:
    """Escritura atómica: un corte a mitad de la revisión no deja el archivo a medias."""
    text = "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".dataset-", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _check_case(case: dict[str, Any], report: Report) -> None:
    cid = case.get("id", "<sin id>")
    for name, kind in FIELDS.items():
        if name not in case:
            report.errors.append(f"{cid}: falta el campo '{name}'")
        elif not isinstance(case[name], kind):
            report.errors.append(f"{cid}: '{name}' tiene un tipo inválido")
    extra = sorted(set(case) - set(FIELDS))
    if extra:
        report.errors.append(f"{cid}: campos desconocidos {extra}")
    if report.errors and any(e.startswith(f"{cid}:") for e in report.errors):
        return

    if not ID_PATTERN.match(cid):
        report.errors.append(f"{cid}: el id debe seguir el patrón bil|tec|acc|oth|edge-NN")
    if not case["input"].strip():
        report.errors.append(f"{cid}: 'input' vacío (la CLI rechaza consultas vacías)")
    for name, allowed in (
        ("split", SPLITS),
        ("expected_category", CATEGORIES),
        ("proposed_category", CATEGORIES),
        ("difficulty", DIFFICULTIES),
        ("label_status", STATUSES),
    ):
        if case[name] not in allowed:
            report.errors.append(f"{cid}: {name}='{case[name]}' no está en {list(allowed)}")
    if case["label_status"] == "validated" and not case["validated_by"]:
        report.errors.append(f"{cid}: validado sin 'validated_by'")
    if case["label_status"] == "disputed" and not case["review_note"]:
        report.errors.append(f"{cid}: en disputa sin 'review_note' que explique por qué")

    if not case["expected_actions"]:
        report.errors.append(f"{cid}: 'expected_actions' no puede estar vacío")
    for index, action in enumerate(case["expected_actions"], start=1):
        if (
            not isinstance(action, dict)
            or not isinstance(action.get("intent"), str)
            or not isinstance(action.get("keywords"), list)
            or not action["keywords"]
            or not all(isinstance(k, str) and k.strip() for k in action["keywords"])
        ):
            report.errors.append(f"{cid}: la acción {index} necesita 'intent' y 'keywords' no vacías")
            continue
        # Las keywords se comparan normalizadas: tienen que estar escritas sin tildes.
        accented = [k for k in action["keywords"] if normalize(k) != k]
        if accented:
            report.errors.append(f"{cid}: keywords con mayúsculas o tildes {accented}")
    if not all(isinstance(k, str) and normalize(k) == k for k in case["answer_keywords"]):
        report.errors.append(f"{cid}: 'answer_keywords' debe ir en minúsculas y sin tildes")


def validate(cases: list[dict[str, Any]], prompts_dir: Path | None = None) -> Report:
    report = Report()
    for case in cases:
        _check_case(case, report)
    if not report.ok:
        return report

    ids = Counter(case["id"] for case in cases)
    report.errors += [f"id duplicado: {cid}" for cid, n in ids.items() if n > 1]

    splits = Counter(case["split"] for case in cases)
    for split, expected in EXPECTED_SPLIT.items():
        if splits[split] != expected:
            report.errors.append(f"split {split}: {splits[split]} casos, se esperan {expected}")

    per_category = Counter(case["expected_category"] for case in cases)
    for category in CATEGORIES:
        if per_category[category] < MIN_PER_CATEGORY:
            report.errors.append(f"categoría {category}: {per_category[category]} casos, mínimo {MIN_PER_CATEGORY}")
        holdout = sum(1 for c in cases if c["split"] == "holdout" and c["expected_category"] == category)
        if holdout == 0:
            report.errors.append(f"categoría {category}: sin casos en holdout")

    for i, a in enumerate(cases):
        for b in cases[i + 1 :]:
            similarity = jaccard(a["input"], b["input"])
            if similarity >= DUPLICATE_THRESHOLD:
                report.errors.append(f"casi duplicados {a['id']} y {b['id']} (jaccard {similarity:.2f})")

    report.errors += leakage(cases, prompts_dir)

    pending = [c["id"] for c in cases if c["label_status"] == "draft"]
    disputed = [c["id"] for c in cases if c["label_status"] == "disputed"]
    if pending:
        report.warnings.append(f"{len(pending)} casos sin validar por un humano")
    if disputed:
        report.warnings.append(f"{len(disputed)} casos en disputa: {', '.join(disputed)}")
    return report


def leakage(cases: list[dict[str, Any]], prompts_dir: Path | None = None) -> list[str]:
    """Casos del dataset demasiado parecidos a un ejemplo few-shot de algún prompt."""
    kwargs = {} if prompts_dir is None else {"prompts_dir": prompts_dir}
    problems = []
    for version in list_versions(**kwargs):
        for number, example in enumerate(load_prompt(version, **kwargs).examples, start=1):
            for case in cases:
                if normalize(case["input"]).strip() == normalize(example.query).strip():
                    problems.append(f"leakage: {case['id']} es idéntico al ejemplo {number} de {version}")
                    continue
                similarity = jaccard(case["input"], example.query)
                if similarity >= LEAKAGE_THRESHOLD:
                    problems.append(
                        f"leakage: {case['id']} se parece al ejemplo {number} de {version} (jaccard {similarity:.2f})"
                    )
    return problems


def summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    table = {
        category: {split: 0 for split in SPLITS} for category in CATEGORIES
    }
    for case in cases:
        table[case["expected_category"]][case["split"]] += 1
    reviewed = [c for c in cases if c["label_status"] in ("validated", "disputed")]
    changed = [c["id"] for c in reviewed if c["expected_category"] != c["proposed_category"]]
    return {
        "total": len(cases),
        "by_category": table,
        "by_status": dict(Counter(c["label_status"] for c in cases)),
        "by_difficulty": dict(Counter(c["difficulty"] for c in cases)),
        "reviewed": len(reviewed),
        "changed_by_reviewer": changed,
        "agreement": None if not reviewed else round(1 - len(changed) / len(reviewed), 3),
    }

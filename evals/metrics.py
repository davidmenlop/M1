"""Métricas de evaluación: funciones puras sobre los resultados por caso.

Cada resultado de caso es un dict con, al menos:
    expected, predicted, confidence, success, attempts, actions, answer,
    expected_actions, answer_keywords, difficulty, cost_usd, latency_s,
    prompt_tokens, completion_tokens
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from evals.dataset import CATEGORIES, normalize

# Umbrales de aceptación declarados en la guía de desarrollo (README, Fase 6).
THRESHOLDS = {
    "schema_valid_rate": 1.0,       # >=
    "accuracy": 0.85,               # >=
    "min_class_recall": 0.75,       # >=
    "mean_cost_usd": 0.01,          # <
}


def intent_matched(intent: dict[str, Any], actions: list[str]) -> bool:
    texts = [normalize(action) for action in actions]
    return any(keyword in text for keyword in intent["keywords"] for text in texts)


def action_score(expected_actions: list[dict[str, Any]], actions: list[str]) -> float:
    if not expected_actions:
        return 1.0
    hits = sum(intent_matched(intent, actions) for intent in expected_actions)
    return hits / len(expected_actions)


def keyword_coverage(keywords: list[str], answer: str) -> float | None:
    if not keywords:
        return None
    text = normalize(answer)
    return sum(keyword in text for keyword in keywords) / len(keywords)


def confusion_matrix(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """matrix[esperado][predicho] = cantidad."""
    matrix = {e: {p: 0 for p in CATEGORIES} for e in CATEGORIES}
    for r in results:
        matrix[r["expected"]][r["predicted"]] += 1
    return matrix


def per_class(matrix: dict[str, dict[str, int]]) -> dict[str, dict[str, float | int]]:
    report = {}
    for c in CATEGORIES:
        tp = matrix[c][c]
        fn = sum(matrix[c].values()) - tp
        fp = sum(matrix[e][c] for e in CATEGORIES) - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        report[c] = {"support": tp + fn, "precision": precision, "recall": recall, "f1": f1}
    return report


def percentile(values: list[float], q: float) -> float:
    """Percentil con interpolación lineal (igual que numpy por defecto)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def compute(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    if n == 0:
        raise ValueError("no hay resultados para calcular métricas")
    correct = [r["predicted"] == r["expected"] for r in results]
    matrix = confusion_matrix(results)
    classes = per_class(matrix)
    present = [c for c in CATEGORIES if classes[c]["support"] > 0]

    confidences_ok = [r["confidence"] for r, ok in zip(results, correct) if ok]
    confidences_ko = [r["confidence"] for r, ok in zip(results, correct) if not ok]
    coverages = [v for r in results if (v := keyword_coverage(r["answer_keywords"], r["answer"])) is not None]
    by_difficulty = {}
    for level in sorted({r["difficulty"] for r in results}):
        subset = [ok for r, ok in zip(results, correct) if r["difficulty"] == level]
        by_difficulty[level] = {"n": len(subset), "accuracy": sum(subset) / len(subset)}

    costs = [r["cost_usd"] for r in results]
    latencies = [r["latency_s"] for r in results]
    return {
        "n": n,
        "schema_valid_rate": sum(r["success"] for r in results) / n,
        "first_try_valid_rate": sum(r["success"] and r["attempts"] == 1 for r in results) / n,
        "retry_rate": sum(r["attempts"] > 1 for r in results) / n,
        "accuracy": sum(correct) / n,
        "macro_f1": sum(classes[c]["f1"] for c in present) / len(present),
        "min_class_recall": min(classes[c]["recall"] for c in present),
        "per_class": classes,
        "confusion_matrix": matrix,
        "accuracy_by_difficulty": by_difficulty,
        "action_score": statistics.fmean(action_score(r["expected_actions"], r["actions"]) for r in results),
        "answer_keyword_coverage": statistics.fmean(coverages) if coverages else None,
        "brier": statistics.fmean((r["confidence"] - ok) ** 2 for r, ok in zip(results, correct)),
        "mean_confidence_correct": statistics.fmean(confidences_ok) if confidences_ok else None,
        "mean_confidence_wrong": statistics.fmean(confidences_ko) if confidences_ko else None,
        "prompt_tokens": sum(r["prompt_tokens"] for r in results),
        "completion_tokens": sum(r["completion_tokens"] for r in results),
        "total_cost_usd": round(sum(costs), 8),
        "mean_cost_usd": round(sum(costs) / n, 8),
        "latency_p50_s": round(percentile(latencies, 0.50), 4),
        "latency_p95_s": round(percentile(latencies, 0.95), 4),
        "errors": [r["id"] for r in results if not r["success"]],
        "misclassified": [
            {"id": r["id"], "expected": r["expected"], "predicted": r["predicted"]}
            for r, ok in zip(results, correct) if not ok
        ],
    }


SCALARS = (
    "schema_valid_rate", "first_try_valid_rate", "retry_rate", "accuracy", "macro_f1",
    "min_class_recall", "action_score", "answer_keyword_coverage", "brier",
    "mean_confidence_correct", "mean_confidence_wrong", "total_cost_usd", "mean_cost_usd",
    "latency_p50_s", "latency_p95_s",
)


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Promedio y desvío de las métricas escalares entre corridas repetidas (ADR-022)."""
    summary: dict[str, Any] = {"runs": len(runs), "n": runs[0]["n"]}
    for key in SCALARS:
        values = [run[key] for run in runs if run[key] is not None]
        if not values:
            summary[key] = None
        elif len(values) == 1:
            summary[key] = values[0]
        else:
            summary[key] = {"mean": statistics.fmean(values), "std": statistics.stdev(values)}
    return summary


def value(metric: Any) -> float | None:
    """Valor escalar de una métrica simple o agregada."""
    if isinstance(metric, dict):
        return metric["mean"]
    return metric


def check_thresholds(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    checks = {}
    for key, limit in THRESHOLDS.items():
        observed = value(summary[key])
        passed = observed < limit if key == "mean_cost_usd" else observed >= limit
        checks[key] = {"limit": limit, "observed": observed, "passed": passed}
    return checks

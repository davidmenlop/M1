"""Registro append-only de métricas por request (una línea JSON por request)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.pipeline import TriageResult


def build_record(result: TriageResult, query: str) -> dict[str, Any]:
    prompt_tokens = result.prompt_tokens
    completion_tokens = result.completion_tokens
    return {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "request_id": result.request_id,
        "provider": result.provider,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "query_chars": len(query),
        "attempts": result.attempts,
        "retries": result.attempts - 1,
        "success": result.success,
        "category": str(result.response.category),
        "confidence": result.response.confidence,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "token_source": result.token_source,
        "latency_s": round(result.latency_s, 4),
        "cost_usd": result.cost_usd,
        "error": result.error,
    }


def append_metric(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")

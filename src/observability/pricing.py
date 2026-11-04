"""Costo estimado en USD a partir de tokens y precios por 1M de tokens."""

from __future__ import annotations

TOKENS_PER_UNIT = 1_000_000


def compute_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_per_1m_usd: float,
    output_per_1m_usd: float,
) -> float:
    cost = (prompt_tokens * input_per_1m_usd + completion_tokens * output_per_1m_usd) / TOKENS_PER_UNIT
    return round(cost, 8)

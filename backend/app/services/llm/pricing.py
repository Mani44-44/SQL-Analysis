"""Per-model token pricing (USD per 1M tokens) used for cost tracking.

Source: Anthropic public pricing as of 2026-10. Unknown models cost 0 and log a warning upstream.
"""

from __future__ import annotations

from app.services.llm.base import Usage

# model -> (input $/MTok, output $/MTok)
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


def cost_usd(usage: Usage) -> float:
    price_in, price_out = PRICES.get(usage.model, (0.0, 0.0))
    total = (
        usage.tokens_in * price_in
        + usage.cache_read_tokens * price_in * CACHE_READ_MULTIPLIER
        + usage.cache_write_tokens * price_in * CACHE_WRITE_MULTIPLIER
        + usage.tokens_out * price_out
    )
    return round(total / 1_000_000, 6)

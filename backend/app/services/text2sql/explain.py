"""Plain-language explanation of a result (fast tier), with a deterministic fallback."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.prompts import load_prompt
from app.services.llm import LLMError, LLMProvider, Tier, Usage
from app.services.text2sql.models import Explanation, PipelineResult

logger = logging.getLogger(__name__)

MAX_ROWS_IN_PROMPT = 20


def summarise_result(result: PipelineResult) -> dict[str, Any]:
    """Compact, bounded view of the result: never more than MAX_ROWS_IN_PROMPT rows."""
    stats: dict[str, dict[str, float]] = {}
    for i, col in enumerate(result.columns):
        nums = [
            r[i]
            for r in result.rows
            if isinstance(r[i], int | float) and not isinstance(r[i], bool)
        ]
        if nums and len(nums) == len([r for r in result.rows if r[i] is not None]):
            stats[col] = {"min": min(nums), "max": max(nums), "sum": round(sum(nums), 2)}
    return {
        "columns": result.columns,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "rows": result.rows[:MAX_ROWS_IN_PROMPT],
        "rows_shown": min(result.row_count, MAX_ROWS_IN_PROMPT),
        "column_stats_over_returned_rows": stats,
        "assumptions": result.assumptions,
    }


def fallback_explanation(result: PipelineResult) -> str:
    if not result.rows:
        return "The query ran successfully but returned no rows."
    if result.row_count == 1 and len(result.columns) <= 3:
        parts = [
            f"{c.replace('_', ' ')}: {v}"
            for c, v in zip(result.columns, result.rows[0], strict=False)
        ]
        return "Result — " + "; ".join(parts) + "."
    more = " (truncated)" if result.truncated else ""
    return (
        f"The query returned {result.row_count:,} rows{more} across {len(result.columns)} columns."
    )


def explain(provider: LLMProvider, result: PipelineResult) -> tuple[str, Usage | None]:
    prompt = load_prompt("explain")
    payload = json.dumps(summarise_result(result), default=str, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    question = (result.resolved_question or result.question).replace("</", "<\\/")
    try:
        llm = provider.complete_json(
            task="explain",
            output_model=Explanation,
            system=prompt.text,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"<question>\n{question}\n</question>\n\n<result>\n{payload}\n</result>"
                    ),
                }
            ],
            tier=Tier.FAST,
        )
    except LLMError as e:
        logger.info("explain_fallback", extra={"error": str(e)})
        return fallback_explanation(result), None
    text = llm.output.answer.strip()
    return (text or fallback_explanation(result)), llm.usage

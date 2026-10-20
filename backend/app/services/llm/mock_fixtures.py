"""Default handlers for the mock provider used when no API key is configured.

Questions matching the demo workspace's suggested questions get their reference SQL; anything
else gets an explicit "mock mode" unanswerable response, so a keyless dev server fails clearly
instead of with a confusing validation error.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.llm.mock import MockCall, MockProvider

MOCK_MODE_MESSAGE = (
    "AskData is running in mock mode (no ANTHROPIC_API_KEY configured), so it can only answer "
    "the suggested demo questions. Set ANTHROPIC_API_KEY to ask anything."
)

_QUESTION = re.compile(r"<question>\s*(.*?)\s*</question>", re.DOTALL)


def extract_question(text: str) -> str:
    m = _QUESTION.search(text)
    return m.group(1) if m else text


def _generate(call: MockCall) -> dict[str, Any]:
    from app.demo.questions import DEMO_QUESTIONS, normalise

    question = extract_question(call.last_user)
    wanted = normalise(question)
    for q in DEMO_QUESTIONS:
        if normalise(q.question) == wanted:
            return {
                "kind": "sql",
                "standalone_question": q.question,
                "sql": q.sql,
                "reasoning": "Reference query for this demo question (mock mode).",
                "assumptions": list(q.assumptions),
                "tables_used": [],
                "confidence": 0.9,
                "clarifying_question": "",
                "missing_data": "",
            }
    return {
        "kind": "unanswerable",
        "standalone_question": question,
        "sql": "",
        "reasoning": "",
        "assumptions": [],
        "tables_used": [],
        "confidence": 0.0,
        "clarifying_question": "",
        "missing_data": MOCK_MODE_MESSAGE,
    }


def build_default_mock() -> MockProvider:
    provider = MockProvider()
    provider.register("generate_sql", _generate)
    provider.register("correct_sql", _generate)
    # No "explain" handler: the pipeline falls back to its deterministic, data-driven summary.
    return provider

"""Deterministic mock "model" for wiring checks of the benchmark harness.

It answers from the gold labels, with scripted, deterministic imperfections so every metric
path is exercised and the expected numbers are known exactly:

- every 5th SQL case first returns SQL with a hallucinated column; the correction returns gold
  (exercises the self-correction loop and recovery rate);
- every 7th SQL case returns a wrong-but-valid query (counts rows instead) and keeps it
  (exercises execution mismatches and error categories);
- every 3rd non-SQL case returns kind "sql" instead of clarify/unanswerable.

These numbers measure the harness, never a model. They must not be reported as accuracy.
"""

from __future__ import annotations

from typing import Any

from app.eval.dataset import EvalCase
from app.services.llm.mock import MockCall, MockProvider
from app.services.llm.mock_fixtures import extract_question


def _gen(kind: str, sql: str = "", question: str = "") -> dict[str, Any]:
    return {
        "kind": kind,
        "standalone_question": question,
        "sql": sql,
        "reasoning": "oracle",
        "assumptions": [],
        "tables_used": [],
        "confidence": 0.9,
        "clarifying_question": "Which period?" if kind == "clarify" else "",
        "missing_data": "Not in the data." if kind == "unanswerable" else "",
    }


def plan(cases: list[EvalCase]) -> dict[str, str]:
    """case_id -> behaviour ('gold' | 'correctable' | 'wrong' | 'wrong_kind')."""
    out: dict[str, str] = {}
    sql_i = other_i = 0
    for c in cases:
        if c.expected_kind == "sql":
            sql_i += 1
            if sql_i % 7 == 0:
                out[c.id] = "wrong"
            elif sql_i % 5 == 0:
                out[c.id] = "correctable"
            else:
                out[c.id] = "gold"
        else:
            other_i += 1
            out[c.id] = "wrong_kind" if other_i % 3 == 0 else "gold"
    return out


def build_oracle(cases: list[EvalCase]) -> MockProvider:
    by_question = {c.question: c for c in cases}
    behaviour = plan(cases)
    provider = MockProvider()

    def generate(call: MockCall) -> dict[str, Any]:
        q = extract_question(call.last_user)
        case = by_question.get(q)
        if case is None:
            return _gen("unanswerable", question=q)
        b = behaviour[case.id]
        if case.expected_kind != "sql":
            return (
                _gen("sql", "SELECT 1 AS x", q)
                if b == "wrong_kind"
                else _gen(case.expected_kind, question=q)
            )
        assert case.gold_sql is not None
        if b == "correctable" and "<previous_attempt>" not in call.last_user:
            return _gen("sql", "SELECT not_a_column FROM transactions", q)
        if b == "wrong":
            return _gen("sql", "SELECT count(*) AS n FROM transactions WHERE amount > 0", q)
        return _gen("sql", case.gold_sql, q)

    provider.register("generate_sql", generate)
    provider.register("correct_sql", generate)
    provider.register("explain", lambda call: {"answer": "oracle"})
    return provider

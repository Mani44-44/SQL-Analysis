from __future__ import annotations

from typing import Any

import pytest

from app.services.charts.picker import ChartSpec, chart_dict, pick_chart, validate_chart_spec
from app.services.text2sql.explain import MAX_ROWS_IN_PROMPT, fallback_explanation, summarise_result
from app.services.text2sql.models import PipelineResult

MONTHS = [f"2025-{m:02d}-01" for m in range(1, 13)]


@pytest.mark.parametrize(
    ("columns", "types", "rows", "question", "expected"),
    [
        (["n"], ["BIGINT"], [[5]], "", "kpi"),
        (["a", "b"], ["DOUBLE", "DOUBLE"], [[1.0, 2.0]], "", "kpi"),
        (["month", "spend"], ["DATE", "DOUBLE"], [[m, 1.0] for m in MONTHS], "", "line"),
        (["month", "spend"], ["TIMESTAMP", "DOUBLE"], [[m, 1.0] for m in MONTHS], "", "line"),
        (["year", "spend"], ["BIGINT", "DOUBLE"], [[2024, 1.0], [2025, 2.0]], "", "line"),
        (["merchant", "spend"], ["VARCHAR", "DOUBLE"], [["a", 1.0], ["b", 2.0]], "", "bar"),
        (
            ["merchant", "spend"],
            ["VARCHAR", "DOUBLE"],
            [["a", 1.0], ["b", 2.0]],
            "spend split by merchant",
            "pie",
        ),
        (
            ["merchant", "delta"],
            ["VARCHAR", "DOUBLE"],
            [["a", -1.0], ["b", 2.0]],
            "breakdown",
            "bar",
        ),
        (["c", "v"], ["VARCHAR", "BIGINT"], [[str(i), i] for i in range(40)], "", "table"),
        (["x", "y"], ["DOUBLE", "DOUBLE"], [[1.0, 2.0], [2.0, 3.0], [3.0, 5.0]], "", "scatter"),
        (["name", "city"], ["VARCHAR", "VARCHAR"], [["a", "b"]], "", "table"),
        (["n"], ["BIGINT"], [], "", "table"),
        (
            ["cat", "mode", "n"],
            ["VARCHAR", "VARCHAR", "BIGINT"],
            [["a", "UPI", 1], ["a", "Card", 2], ["b", "UPI", 3]],
            "",
            "bar",
        ),
    ],
)
def test_pick_chart(
    columns: list[str], types: list[str], rows: list[list[Any]], question: str, expected: str
) -> None:
    spec = pick_chart(columns, types, rows, question=question)
    assert spec.type == expected
    validate_chart_spec(spec, columns)


def test_line_with_series() -> None:
    rows = [[m, t, 1.0] for m in MONTHS[:3] for t in ("Debit", "Credit")]
    spec = pick_chart(["month", "type", "amount"], ["DATE", "VARCHAR", "DOUBLE"], rows)
    assert spec.type == "line" and spec.series == "type" and spec.x == "month"


def test_spec_validation() -> None:
    with pytest.raises(ValueError):
        validate_chart_spec(ChartSpec(type="bar", x="nope", y=["v"]), ["v"])
    with pytest.raises(ValueError):
        ChartSpec(type="line", x="a")


def test_chart_dict_has_labels() -> None:
    d = chart_dict(
        ["month", "total_spend"], ["DATE", "DOUBLE"], [[MONTHS[0], 1.0], [MONTHS[1], 2.0]]
    )
    assert d["labels"] == {"month": "Month", "total_spend": "Total spend"}


def test_explanation_summary_is_bounded() -> None:
    r = PipelineResult(
        question="q", status="ok", columns=["a", "b"], rows=[[i, "x"] for i in range(500)]
    )
    s = summarise_result(r)
    assert len(s["rows"]) == MAX_ROWS_IN_PROMPT
    assert s["column_stats_over_returned_rows"]["a"]["max"] == 499
    assert "b" not in s["column_stats_over_returned_rows"]


def test_fallback_explanations() -> None:
    assert "no rows" in fallback_explanation(PipelineResult(question="q", status="ok"))
    one = PipelineResult(question="q", status="ok", columns=["total"], rows=[[42]])
    assert "total: 42" in fallback_explanation(one)
    many = PipelineResult(question="q", status="ok", columns=["a"], rows=[[1]] * 3, truncated=True)
    assert "3 rows (truncated)" in fallback_explanation(many)

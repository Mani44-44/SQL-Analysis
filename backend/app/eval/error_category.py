"""Heuristic error categories for failed benchmark cases (spec section 9.2).

Applied in order; the first rule that fires wins:
kind_mismatch, hallucinated_column, validation_error, execution_error, wrong_table, wrong_join,
wrong_aggregation, date_handling, wrong_filter, wrong_columns, other.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_DATE_FUNCS = {
    "TimestampTrunc", "DateTrunc", "Year", "Month", "Day", "Quarter", "Extract", "TimeToStr",
    "DayOfWeek", "DayOfWeekIso", "DateDiff", "DateAdd", "DateSub", "Dayname", "Monthname", "Week",
}  # fmt: skip
_AGG_FUNCS = {"Sum", "Avg", "Count", "Min", "Max", "Median", "CountIf", "ArgMax", "ArgMin"}
_VALIDATION_CODES = {
    "parse_error", "multiple_statements", "not_select", "forbidden_statement", "table_function",
    "system_table", "forbidden_function", "recursive_cte", "cross_join", "too_long",
    "too_complex", "empty", "parameter", "unknown_table",
}  # fmt: skip


def _parse(sql: str) -> exp.Expr | None:
    try:
        return sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return None


def _tables(tree: exp.Expr) -> set[str]:
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table)} - ctes


def _funcs(tree: exp.Expr, names: set[str]) -> set[str]:
    return {type(f).__name__ for f in tree.find_all(exp.Func) if type(f).__name__ in names}


def _join_shape(tree: exp.Expr) -> list[tuple[str, bool]]:
    """(side/kind, has condition) per join; comma joins have no condition."""
    return sorted(
        ((j.side or j.kind or "INNER").upper(), bool(j.args.get("on") or j.args.get("using")))
        for j in tree.find_all(exp.Join)
    )


def _filter_columns(tree: exp.Expr) -> set[str]:
    cols: set[str] = set()
    for clause in list(tree.find_all(exp.Where)) + list(tree.find_all(exp.Having)):
        cols |= {c.name.lower() for c in clause.find_all(exp.Column)}
    return cols


def _filter_literals(tree: exp.Expr) -> set[str]:
    lits: set[str] = set()
    for clause in tree.find_all(exp.Where):
        lits |= {str(lit.this) for lit in clause.find_all(exp.Literal)}
    return lits


def categorize(
    *,
    expected_kind: str,
    predicted_kind: str | None,
    gold_sql: str | None,
    predicted_sql: str | None,
    error_code: str | None,
) -> str:
    if predicted_kind != expected_kind:
        return "kind_mismatch"
    if error_code == "unknown_column":
        return "hallucinated_column"
    if error_code in _VALIDATION_CODES:
        return "validation_error"
    if error_code:
        return "execution_error"
    if not gold_sql or not predicted_sql:
        return "other"
    g, p = _parse(gold_sql), _parse(predicted_sql)
    if g is None or p is None:
        return "other"
    if _tables(g) != _tables(p):
        return "wrong_table"
    if _join_shape(g) != _join_shape(p):
        return "wrong_join"
    if _funcs(g, _AGG_FUNCS) != _funcs(p, _AGG_FUNCS):
        return "wrong_aggregation"
    if _funcs(g, _DATE_FUNCS) != _funcs(p, _DATE_FUNCS):
        return "date_handling"
    if _filter_columns(g) != _filter_columns(p) or _filter_literals(g) != _filter_literals(p):
        return "wrong_filter"
    if len(g.selects if isinstance(g, exp.Query) else []) != len(
        p.selects if isinstance(p, exp.Query) else []
    ):
        return "wrong_columns"
    return "other"

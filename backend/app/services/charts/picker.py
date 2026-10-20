"""Rule-based chart selection from the shape and types of a query result.

The returned spec is validated (every referenced column must exist) before it reaches the UI.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ChartType = Literal["kpi", "line", "bar", "pie", "scatter", "table"]

_NUMERIC = re.compile(
    r"^(TINYINT|SMALLINT|INTEGER|INT|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT|UHUGEINT"
    r"|FLOAT|REAL|DOUBLE|DECIMAL.*|NUMERIC.*)$",
    re.IGNORECASE,
)
_TEMPORAL = re.compile(r"^(DATE|TIMESTAMP.*|TIME.*)$", re.IGNORECASE)
_TIME_NAMES = re.compile(r"(^|_)(year|month|week|day|date|quarter|hour|period)(_|$)", re.IGNORECASE)
_PIE_HINT = re.compile(
    r"\b(share|split|breakdown|proportion|percentage|distribution|portion|mix)\b", re.IGNORECASE
)

MAX_BAR_CATEGORIES = 30
MAX_SERIES = 8
MAX_PIE_SLICES = 6
MAX_MEASURES = 4


class ChartSpec(BaseModel):
    type: ChartType
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    series: str | None = None
    title: str = ""
    x_kind: Literal["temporal", "categorical", "quantitative"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> ChartSpec:
        if self.type in ("line", "bar", "pie", "scatter") and (not self.x or not self.y):
            raise ValueError(f"{self.type} chart needs x and y")
        if self.type == "kpi" and not self.y:
            raise ValueError("kpi needs at least one value column")
        return self


def validate_chart_spec(spec: ChartSpec, columns: list[str]) -> ChartSpec:
    cols = set(columns)
    referenced = [c for c in [spec.x, spec.series, *spec.y] if c]
    missing = [c for c in referenced if c not in cols]
    if missing:
        raise ValueError(f"chart references unknown columns: {missing}")
    return spec


def _kind(col: str, sql_type: str, values: list[Any]) -> str:
    if _TEMPORAL.match(sql_type):
        return "temporal"
    if _NUMERIC.match(sql_type):
        is_int = bool(re.match(r"^(TINY|SMALL|BIG|HUGE|U)?INT", sql_type, re.IGNORECASE))
        if is_int and _TIME_NAMES.search(col):
            return "temporal_num"  # e.g. year = 2025: a dimension, not a measure
        return "numeric"
    return "categorical"


def _humanise(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def pick_chart(
    columns: list[str],
    column_types: list[str],
    rows: list[list[Any]],
    *,
    question: str = "",
) -> ChartSpec:
    if not rows or not columns:
        return ChartSpec(type="table")
    by_col = {c: [r[i] for r in rows] for i, c in enumerate(columns)}
    kinds = {c: _kind(c, t, by_col[c]) for c, t in zip(columns, column_types, strict=False)}
    measures = [c for c in columns if kinds[c] == "numeric"]
    temporal = [c for c in columns if kinds[c] in ("temporal", "temporal_num")]
    categorical = [c for c in columns if kinds[c] == "categorical"]
    title = question.strip().rstrip("?")[:120]

    def distinct(c: str) -> int:
        return len({str(v) for v in by_col[c]})

    # Single row of numbers -> KPI card(s)
    if len(rows) == 1 and measures and not categorical and not temporal:
        return ChartSpec(type="kpi", y=measures[:MAX_MEASURES], title=title)
    if not measures:
        return ChartSpec(type="table", title=title)

    ys = measures[:MAX_MEASURES]
    if temporal:
        x = temporal[0]
        if len(categorical) == 1 and len(ys) == 1 and distinct(categorical[0]) <= MAX_SERIES:
            return ChartSpec(
                type="line", x=x, y=ys, series=categorical[0], title=title, x_kind="temporal"
            )
        if not categorical and len(rows) >= 2:
            return ChartSpec(type="line", x=x, y=ys, title=title, x_kind="temporal")
    if len(categorical) == 1 and not temporal:
        x = categorical[0]
        n = distinct(x)
        if (
            len(ys) == 1
            and n <= MAX_PIE_SLICES
            and _PIE_HINT.search(question)
            and all(isinstance(v, int | float) and v >= 0 for v in by_col[ys[0]] if v is not None)
        ):
            return ChartSpec(type="pie", x=x, y=ys, title=title, x_kind="categorical")
        if n <= MAX_BAR_CATEGORIES:
            return ChartSpec(type="bar", x=x, y=ys, title=title, x_kind="categorical")
    if len(categorical) == 2 and len(ys) == 1 and not temporal:
        a, b = categorical
        if distinct(a) <= MAX_BAR_CATEGORIES and distinct(b) <= MAX_SERIES:
            return ChartSpec(type="bar", x=a, y=ys, series=b, title=title, x_kind="categorical")
    if not categorical and not temporal and len(measures) >= 2 and len(rows) >= 3:
        return ChartSpec(
            type="scatter", x=measures[0], y=[measures[1]], title=title, x_kind="quantitative"
        )
    return ChartSpec(type="table", title=title)


def chart_dict(
    columns: list[str], column_types: list[str], rows: list[list[Any]], question: str = ""
) -> dict[str, Any]:
    spec = validate_chart_spec(pick_chart(columns, column_types, rows, question=question), columns)
    out = spec.model_dump()
    out["labels"] = {c: _humanise(c) for c in [spec.x, spec.series, *spec.y] if c}
    return out

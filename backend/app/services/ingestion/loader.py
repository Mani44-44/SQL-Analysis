"""Write cleaned, typed tables into a workspace DuckDB file and profile them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from app.services.ingestion.infer import DUCKDB_TYPES, LogicalType

TOP_VALUES_MAX_DISTINCT = 50
TOP_VALUES_TYPES = {"text", "boolean"}


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass
class TypedColumn:
    name: str
    original_name: str
    logical_type: LogicalType
    values: list[str | None]
    coerced_nulls: int = 0


@dataclass
class ColumnProfile:
    name: str
    logical_type: LogicalType
    null_pct: float
    distinct_count: int
    min_value: str | None
    max_value: str | None
    top_values: list[dict[str, Any]] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)


@dataclass
class TableProfile:
    name: str
    row_count: int
    columns: list[ColumnProfile]


def load_table(con: duckdb.DuckDBPyConnection, table: str, columns: list[TypedColumn]) -> None:
    frame = pd.DataFrame({c.name: pd.Series(c.values, dtype="object") for c in columns})
    con.register("_askdata_frame", frame)
    try:
        select = ", ".join(
            f"CAST({q} AS {DUCKDB_TYPES[c.logical_type]}) AS {q}"
            for c in columns
            for q in [quote_ident(c.name)]
        )
        con.execute(
            f"CREATE OR REPLACE TABLE {quote_ident(table)} AS SELECT {select} FROM _askdata_frame"
        )
    finally:
        con.unregister("_askdata_frame")


def drop_table(con: duckdb.DuckDBPyConnection, table: str) -> None:
    con.execute(f"DROP TABLE IF EXISTS {quote_ident(table)}")


def profile_table(
    con: duckdb.DuckDBPyConnection, table: str, columns: list[tuple[str, LogicalType]]
) -> TableProfile:
    t = quote_ident(table)
    row = con.execute(f"SELECT count(*) FROM {t}").fetchone()
    row_count = int(row[0]) if row else 0
    profiles: list[ColumnProfile] = []
    for name, ltype in columns:
        c = quote_ident(name)
        stats = con.execute(
            f"SELECT count(*) - count({c}), count(DISTINCT {c}), "
            f"CAST(min({c}) AS VARCHAR), CAST(max({c}) AS VARCHAR) FROM {t}"
        ).fetchone()
        assert stats is not None
        nulls, distinct, mn, mx = int(stats[0]), int(stats[1]), stats[2], stats[3]
        top: list[dict[str, Any]] = []
        if ltype in TOP_VALUES_TYPES and 0 < distinct <= TOP_VALUES_MAX_DISTINCT:
            top = [
                {"value": str(v).lower() if isinstance(v, bool) else str(v), "count": int(n)}
                for v, n in con.execute(
                    f"SELECT {c}, count(*) AS n FROM {t} WHERE {c} IS NOT NULL "
                    f"GROUP BY 1 ORDER BY n DESC, 1 LIMIT 5"
                ).fetchall()
            ]
        samples = [
            str(r[0])
            for r in con.execute(
                f"SELECT DISTINCT CAST({c} AS VARCHAR) AS v FROM {t} WHERE {c} IS NOT NULL "
                f"ORDER BY hash(v) LIMIT 3"
            ).fetchall()
        ]
        if ltype in ("text",) and mn is not None and len(mn) > 80:
            mn, mx = mn[:80], (mx or "")[:80]
        profiles.append(
            ColumnProfile(
                name=name,
                logical_type=ltype,
                null_pct=round(100.0 * nulls / row_count, 2) if row_count else 0.0,
                distinct_count=distinct,
                min_value=mn,
                max_value=mx,
                top_values=top,
                sample_values=[s[:120] for s in samples],
            )
        )
    return TableProfile(table, row_count, profiles)

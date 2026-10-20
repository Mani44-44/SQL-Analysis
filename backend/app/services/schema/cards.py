"""Schema cards: the workspace schema as structured objects and as compact prompt text."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import DataSource, GlossaryTerm, TableMeta
from app.services.ingestion.infer import DUCKDB_TYPES


class ColumnCard(BaseModel):
    id: str
    name: str
    type: str  # logical type
    sql_type: str
    description: str | None = None
    original_name: str | None = None
    null_pct: float = 0.0
    distinct_count: int = 0
    min_value: str | None = None
    max_value: str | None = None
    top_values: list[dict[str, Any]] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)
    type_overridden: bool = False


class TableCard(BaseModel):
    id: str
    source_id: str
    name: str
    row_count: int
    description: str | None = None
    columns: list[ColumnCard]


class JoinHint(BaseModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str


class GlossaryCard(BaseModel):
    id: str
    term: str
    definition: str


class WorkspaceSchema(BaseModel):
    tables: list[TableCard]
    join_hints: list[JoinHint] = Field(default_factory=list)
    glossary: list[GlossaryCard] = Field(default_factory=list)

    @property
    def table_names(self) -> set[str]:
        return {t.name for t in self.tables}

    def table(self, name: str) -> TableCard | None:
        return next((t for t in self.tables if t.name == name), None)

    @property
    def column_count(self) -> int:
        return sum(len(t.columns) for t in self.tables)

    def fingerprint(self) -> str:
        """Stable hash of everything that affects SQL generation."""
        payload = {
            "tables": [
                [t.name, t.description, [[c.name, c.type, c.description] for c in t.columns]]
                for t in sorted(self.tables, key=lambda t: t.name)
            ],
            "glossary": sorted([g.term, g.definition] for g in self.glossary),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def infer_join_hints(tables: list[TableCard]) -> list[JoinHint]:
    """Columns ending in _id that appear in more than one table are likely join keys."""
    hints: list[JoinHint] = []
    by_col: dict[str, list[str]] = {}
    for t in tables:
        for c in t.columns:
            if c.name == "id" or c.name.endswith("_id"):
                by_col.setdefault(c.name, []).append(t.name)
    for col, owners in sorted(by_col.items()):
        if len(owners) < 2:
            continue
        # Prefer the table where the key is unique (dimension) as the right side.
        dims = []
        for name in owners:
            t = next(t for t in tables if t.name == name)
            card = next(c for c in t.columns if c.name == col)
            if t.row_count and card.distinct_count == t.row_count:
                dims.append(name)
        for left in owners:
            for right in dims:
                if left != right:
                    hints.append(
                        JoinHint(
                            left_table=left, left_column=col, right_table=right, right_column=col
                        )
                    )
    return hints


def load_workspace_schema(db: Session, workspace_id: str) -> WorkspaceSchema:
    tables = db.scalars(
        select(TableMeta)
        .join(DataSource)
        .where(TableMeta.workspace_id == workspace_id, DataSource.status == "ready")
        .options(selectinload(TableMeta.columns))
        .order_by(TableMeta.name)
    ).all()
    cards = [
        TableCard(
            id=t.id,
            source_id=t.source_id,
            name=t.name,
            row_count=t.row_count,
            description=t.description,
            columns=[
                ColumnCard(
                    id=c.id,
                    name=c.name,
                    type=c.type,
                    sql_type=DUCKDB_TYPES.get(c.type, "VARCHAR"),  # type: ignore[call-overload]
                    description=c.description,
                    original_name=c.original_name,
                    null_pct=c.null_pct,
                    distinct_count=c.distinct_count,
                    min_value=c.min_value,
                    max_value=c.max_value,
                    top_values=list(c.top_values or []),
                    sample_values=list(c.sample_values or []),
                    type_overridden=c.type_override is not None,
                )
                for c in t.columns
            ],
        )
        for t in tables
    ]
    glossary = [
        GlossaryCard(id=g.id, term=g.term, definition=g.definition)
        for g in db.scalars(
            select(GlossaryTerm)
            .where(GlossaryTerm.workspace_id == workspace_id)
            .order_by(GlossaryTerm.term)
        )
    ]
    return WorkspaceSchema(tables=cards, join_hints=infer_join_hints(cards), glossary=glossary)


def _clip(v: str, n: int = 40) -> str:
    v = v.replace("\n", " ")
    return v if len(v) <= n else v[: n - 1] + "…"


def render_schema(
    schema: WorkspaceSchema,
    *,
    include_samples: bool = True,
    tables: list[str] | None = None,
) -> str:
    """Render tables as compact annotated DDL for prompts."""
    wanted = set(tables) if tables is not None else None
    parts: list[str] = []
    for t in schema.tables:
        if wanted is not None and t.name not in wanted:
            continue
        header = f"TABLE {t.name}  -- {t.row_count:,} rows"
        if t.description:
            header += f"; {_clip(t.description, 160)}"
        lines = [header]
        for c in t.columns:
            notes: list[str] = []
            if c.description:
                notes.append(_clip(c.description, 120))
            if c.null_pct:
                notes.append(f"{c.null_pct:g}% null")
            if include_samples:
                if c.top_values:
                    notes.append(
                        "values: " + ", ".join(repr(_clip(str(v["value"]))) for v in c.top_values)
                    )
                elif c.min_value is not None and c.type in (
                    "integer",
                    "float",
                    "currency",
                    "percent",
                    "date",
                    "timestamp",
                ):
                    notes.append(f"range {c.min_value} .. {c.max_value}")
                elif c.sample_values:
                    notes.append("e.g. " + ", ".join(repr(_clip(v)) for v in c.sample_values))
            line = f"  {c.name} {c.sql_type}"
            if notes:
                line += "  -- " + "; ".join(notes)
            lines.append(line)
        parts.append("\n".join(lines))
    hints = [
        h for h in schema.join_hints
        if wanted is None or (h.left_table in wanted and h.right_table in wanted)
    ]  # fmt: skip
    if hints:
        parts.append(
            "JOIN KEYS\n"
            + "\n".join(
                f"  {h.left_table}.{h.left_column} = {h.right_table}.{h.right_column}"
                for h in hints
            )
        )
    return "\n\n".join(parts)


def render_glossary(terms: list[GlossaryCard]) -> str:
    return "\n".join(f"- {g.term}: {g.definition}" for g in terms)

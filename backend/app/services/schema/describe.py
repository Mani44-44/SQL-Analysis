"""LLM-drafted table/column descriptions (fast tier). Only fills descriptions that are empty."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import TableMeta
from app.prompts import load_prompt
from app.services.llm import LLMError, LLMProvider, Tier

logger = logging.getLogger(__name__)


class ColumnDescription(BaseModel):
    name: str
    description: str


class TableDescription(BaseModel):
    table_description: str = ""
    columns: list[ColumnDescription] = Field(default_factory=list)


def _profile_payload(table: TableMeta) -> str:
    return json.dumps(
        {
            "table": table.name,
            "row_count": table.row_count,
            "columns": [
                {
                    "name": c.name,
                    "original_header": c.original_name,
                    "type": c.type,
                    "null_pct": c.null_pct,
                    "distinct": c.distinct_count,
                    "min": c.min_value,
                    "max": c.max_value,
                    "top_values": [v["value"] for v in (c.top_values or [])],
                    "samples": c.sample_values,
                }
                for c in table.columns
            ],
        },
        ensure_ascii=False,
    )


def draft_descriptions(db: Session, table: TableMeta, provider: LLMProvider) -> bool:
    """Ask the fast model for descriptions; returns True if anything was filled in."""
    prompt = load_prompt("describe_table")
    try:
        result = provider.complete_json(
            task="describe_table",
            output_model=TableDescription,
            system=prompt.text,
            messages=[
                {
                    "role": "user",
                    "content": f"<table_profile>\n{_profile_payload(table)}\n</table_profile>",
                }
            ],
            tier=Tier.FAST,
        )
    except LLMError as e:
        logger.warning("describe_failed", extra={"table": table.name, "error": str(e)})
        return False

    out = result.output
    changed = False
    if out.table_description and not table.description:
        table.description = out.table_description.strip()[:500]
        changed = True
    by_name = {c.name: c.description.strip()[:300] for c in out.columns if c.description.strip()}
    for col in table.columns:
        if not col.description and col.name in by_name:
            col.description = by_name[col.name]
            changed = True
    if changed:
        db.commit()
    return changed

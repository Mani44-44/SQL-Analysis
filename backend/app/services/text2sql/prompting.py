"""Prompt assembly for SQL generation and correction.

The system prompt holds the stable parts (instructions + schema + glossary) so it is cacheable;
the user message holds the volatile parts (history, question, previous attempt). Calls are
single-turn: earlier turns are summarised inside a delimited <history> block, never replayed as
assistant messages.
"""

from __future__ import annotations

from app.prompts import load_prompt
from app.services.schema.cards import GlossaryCard, WorkspaceSchema, render_glossary, render_schema
from app.services.text2sql.models import Attempt, HistoryTurn

_MAX_DATA_CHARS = 60_000


def _escape(text: str) -> str:
    """Neutralise closing tags so data cannot break out of its delimited block."""
    return text.replace("</", "<\\/")


def build_system_prompt(
    schema: WorkspaceSchema,
    *,
    tables: list[str] | None,
    glossary: list[GlossaryCard],
    include_samples: bool,
    examples: list[tuple[str, str]] | None = None,
) -> tuple[str, str]:
    prompt = load_prompt("generate_sql")
    schema_text = render_schema(schema, include_samples=include_samples, tables=tables)
    block = f"<schema>\n{_escape(schema_text)[:_MAX_DATA_CHARS]}\n</schema>"
    if glossary:
        block += f"\n\n<glossary>\n{_escape(render_glossary(glossary))}\n</glossary>"
    if examples:
        shots = "\n\n".join(f"Q: {_escape(q)}\nSQL: {_escape(s)}" for q, s in examples)
        block += f"\n\n<examples>\nWorked examples on this schema:\n\n{shots}\n</examples>"
    return prompt.render(schema_block=block), prompt.tag


def build_user_message(
    question: str,
    history: list[HistoryTurn],
    previous: Attempt | None = None,
    *,
    note: str | None = None,
) -> str:
    parts: list[str] = []
    if history:
        lines = []
        for i, h in enumerate(history, 1):
            lines.append(f"[{i}] Q: {_escape(h.question)}")
            if h.sql:
                lines.append(f"    SQL: {_escape(h.sql)}")
            elif h.kind != "sql":
                lines.append(f"    ({h.kind})")
        parts.append("<history>\n" + "\n".join(lines) + "\n</history>")
    parts.append(f"<question>\n{_escape(question)}\n</question>")
    if previous is not None:
        parts.append(
            "<previous_attempt>\n"
            f"<sql>\n{_escape(previous.sql)}\n</sql>\n"
            f"<error>\n{_escape(previous.error or '')}\n</error>\n"
            "</previous_attempt>\n"
            + (
                note
                or "The previous SQL failed. Return a corrected query (or a different kind if "
                "the question cannot be answered)."
            )
        )
    return "\n\n".join(parts)

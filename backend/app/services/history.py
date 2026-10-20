"""Conversation / query-run persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, QueryRun
from app.services.text2sql.models import HistoryTurn, PipelineResult


class ConversationNotFoundError(Exception):
    pass


def get_or_create_conversation(
    db: Session,
    workspace_id: str,
    conversation_id: str | None,
    *,
    title: str,
    user_id: str | None = None,
) -> Conversation:
    if conversation_id:
        conv = db.get(Conversation, conversation_id)
        # A conversation belongs to one workspace and, if it was started signed in, one user.
        if (
            conv is None
            or conv.workspace_id != workspace_id
            or (conv.user_id is not None and conv.user_id != user_id)
        ):
            raise ConversationNotFoundError(conversation_id)
        return conv
    conv = Conversation(workspace_id=workspace_id, user_id=user_id, title=title[:300])
    db.add(conv)
    db.flush()
    return conv


def history_for(db: Session, conversation_id: str, limit: int = 4) -> list[HistoryTurn]:
    runs = db.scalars(
        select(QueryRun)
        .where(QueryRun.conversation_id == conversation_id)
        .order_by(QueryRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        HistoryTurn(
            question=r.resolved_question or r.question or "",
            sql=r.final_sql,
            kind=r.kind,
        )
        for r in reversed(runs)
        if r.question or r.final_sql
    ]


def save_pipeline_run(
    db: Session,
    *,
    workspace_id: str,
    conversation: Conversation,
    result: PipelineResult,
    user_id: str | None = None,
) -> QueryRun:
    error_category = result.error_code
    run = QueryRun(
        workspace_id=workspace_id,
        conversation_id=conversation.id,
        user_id=user_id,
        source="ask",
        question=result.question,
        resolved_question=result.resolved_question,
        kind=result.kind,
        generated_sql=result.generated_sql,
        final_sql=result.sql or (result.attempts[-1].sql if result.attempts else None),
        status=result.status,
        error=result.error,
        error_category=error_category,
        attempts=len(result.attempts),
        rows_returned=result.row_count,
        truncated=result.truncated,
        duration_ms=result.duration_ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=0.0 if result.cached else result.cost_usd,
        model=result.model,
        prompt_version=result.prompt_version,
        chart_spec=result.chart,
        explanation=result.explanation,
        assumptions=result.assumptions,
        confidence=result.confidence,
        trace=[t.as_dict() for t in result.trace]
        + [
            {
                "stage": "attempt",
                "n": a.number,
                "sql": a.sql,
                "error_code": a.error_code,
                "error": a.error,
            }
            for a in result.attempts
        ],
    )
    db.add(run)
    db.flush()
    db.add(Message(conversation_id=conversation.id, role="user", content=result.question))
    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_text(result),
            query_run_id=run.id,
        )
    )
    db.commit()
    return run


def assistant_text(result: PipelineResult) -> str:
    if result.status == "clarify":
        return result.clarifying_question or ""
    if result.status == "unanswerable":
        return result.missing_data or "This question can't be answered from the data."
    if result.status == "error":
        return result.error or "Something went wrong."
    return result.explanation or f"Returned {result.row_count} row(s)."


def save_manual_run(
    db: Session,
    *,
    workspace_id: str,
    conversation: Conversation | None,
    sql: str,
    status: str,
    rows: int = 0,
    truncated: bool = False,
    duration_ms: int = 0,
    error: str | None = None,
    error_category: str | None = None,
    chart: dict[str, object] | None = None,
    user_id: str | None = None,
) -> QueryRun:
    run = QueryRun(
        workspace_id=workspace_id,
        conversation_id=conversation.id if conversation else None,
        user_id=user_id,
        source="manual",
        kind="sql",
        generated_sql=None,
        final_sql=sql,
        status=status,
        error=error,
        error_category=error_category,
        attempts=1,
        rows_returned=rows,
        truncated=truncated,
        duration_ms=duration_ms,
        chart_spec=chart,
    )
    db.add(run)
    db.commit()
    return run

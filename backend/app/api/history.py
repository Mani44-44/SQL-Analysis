"""Conversations, query runs, saved queries, feedback and CSV export."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_workspace
from app.core.config import get_settings
from app.db.models import Conversation, Feedback, QueryRun, SavedQuery, Workspace
from app.db.session import get_db
from app.services.execution.executor import ExecutionError
from app.services.execution.service import run_query
from app.services.schema.cards import load_workspace_schema
from app.services.sqlguard import SqlGuardError, validate_sql

router = APIRouter(tags=["history"])


# ---------------------------------------------------------------- conversations


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    last_activity: datetime | None
    turns: int


class RunSummary(BaseModel):
    id: str
    question: str | None
    resolved_question: str | None
    status: str
    kind: str
    source: str
    sql: str | None
    explanation: str | None
    assumptions: list[Any]
    chart: dict[str, Any] | None
    confidence: float | None
    row_count: int
    attempts: int
    duration_ms: int
    cost_usd: float
    error: str | None
    created_at: datetime
    rating: int | None = None


class ConversationDetail(BaseModel):
    id: str
    workspace_id: str
    title: str
    created_at: datetime
    runs: list[RunSummary]


def _run_summary(r: QueryRun, rating: int | None = None) -> RunSummary:
    return RunSummary(
        id=r.id,
        question=r.question,
        resolved_question=r.resolved_question,
        status=r.status,
        kind=r.kind,
        source=r.source,
        sql=r.final_sql,
        explanation=r.explanation,
        assumptions=list(r.assumptions or []),
        chart=r.chart_spec,
        confidence=r.confidence,
        row_count=r.rows_returned,
        attempts=r.attempts,
        duration_ms=r.duration_ms,
        cost_usd=r.cost_usd,
        error=r.error,
        created_at=r.created_at,
        rating=rating,
    )


@router.get("/workspaces/{workspace_id}/conversations", response_model=list[ConversationSummary])
def list_conversations(
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[ConversationSummary]:
    stats = (
        select(
            QueryRun.conversation_id,
            func.count(QueryRun.id).label("n"),
            func.max(QueryRun.created_at).label("last"),
        )
        .group_by(QueryRun.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(Conversation, stats.c.n, stats.c.last)
        .outerjoin(stats, stats.c.conversation_id == Conversation.id)
        .where(Conversation.workspace_id == ws.id)
        .order_by(func.coalesce(stats.c.last, Conversation.created_at).desc())
        .limit(limit)
    ).all()
    return [
        ConversationSummary(
            id=c.id, title=c.title, created_at=c.created_at, last_activity=last, turns=n or 0
        )
        for c, n, last in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)) -> ConversationDetail:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    runs = db.scalars(
        select(QueryRun).where(QueryRun.conversation_id == conv.id).order_by(QueryRun.created_at)
    ).all()
    ratings = _latest_ratings(db, [r.id for r in runs])
    return ConversationDetail(
        id=conv.id,
        workspace_id=conv.workspace_id,
        title=conv.title,
        created_at=conv.created_at,
        runs=[_run_summary(r, ratings.get(r.id)) for r in runs],
    )


def _latest_ratings(db: Session, run_ids: list[str]) -> dict[str, int]:
    if not run_ids:
        return {}
    out: dict[str, int] = {}
    for fb in db.scalars(
        select(Feedback).where(Feedback.query_run_id.in_(run_ids)).order_by(Feedback.created_at)
    ):
        out[fb.query_run_id] = fb.rating
    return out


def _get_run(db: Session, run_id: str) -> QueryRun:
    run = db.get(QueryRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="query run not found")
    return run


class RunDetail(RunSummary):
    workspace_id: str
    generated_sql: str | None
    trace: list[Any]
    model: str | None
    prompt_version: str | None
    tokens_in: int
    tokens_out: int


@router.get("/query-runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunDetail:
    r = _get_run(db, run_id)
    base = _run_summary(r, _latest_ratings(db, [r.id]).get(r.id))
    return RunDetail(
        **base.model_dump(),
        workspace_id=r.workspace_id,
        generated_sql=r.generated_sql,
        trace=list(r.trace or []),
        model=r.model,
        prompt_version=r.prompt_version,
        tokens_in=r.tokens_in,
        tokens_out=r.tokens_out,
    )


# ---------------------------------------------------------------- feedback


class FeedbackIn(BaseModel):
    rating: Literal[1, -1]
    corrected_sql: str | None = Field(default=None, max_length=20_000)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: str
    query_run_id: str
    rating: int
    corrected_sql: str | None
    comment: str | None


@router.post("/query-runs/{run_id}/feedback", response_model=FeedbackOut, status_code=201)
def add_feedback(run_id: str, body: FeedbackIn, db: Session = Depends(get_db)) -> FeedbackOut:
    run = _get_run(db, run_id)
    corrected = (body.corrected_sql or "").strip() or None
    if corrected:
        schema = load_workspace_schema(db, run.workspace_id)
        try:
            corrected = validate_sql(corrected, schema.allowed()).sql
        except SqlGuardError as e:
            raise HTTPException(
                status_code=422, detail=f"corrected SQL is invalid: {e.message}"
            ) from e
    fb = Feedback(
        query_run_id=run.id,
        rating=body.rating,
        corrected_sql=corrected,
        comment=(body.comment or "").strip() or None,
    )
    db.add(fb)
    db.commit()
    return FeedbackOut(
        id=fb.id,
        query_run_id=run.id,
        rating=fb.rating,
        corrected_sql=fb.corrected_sql,
        comment=fb.comment,
    )


# ---------------------------------------------------------------- saved queries


class SavedQueryIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    sql: str = Field(min_length=1, max_length=20_000)


class SavedQueryOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    sql: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/workspaces/{workspace_id}/saved-queries", response_model=list[SavedQueryOut])
def list_saved(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[SavedQuery]:
    return list(
        db.scalars(
            select(SavedQuery)
            .where(SavedQuery.workspace_id == ws.id)
            .order_by(SavedQuery.created_at.desc())
        )
    )


@router.post(
    "/workspaces/{workspace_id}/saved-queries", response_model=SavedQueryOut, status_code=201
)
def create_saved(
    body: SavedQueryIn, ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> SavedQuery:
    if ws.is_demo:
        raise HTTPException(status_code=403, detail="the demo workspace is read-only")
    schema = load_workspace_schema(db, ws.id)
    try:
        sql = validate_sql(body.sql, schema.allowed()).sql
    except SqlGuardError as e:
        raise HTTPException(status_code=422, detail=e.message) from e
    sq = SavedQuery(workspace_id=ws.id, title=body.title.strip(), sql=sql)
    db.add(sq)
    db.commit()
    return sq


@router.delete("/saved-queries/{saved_id}", status_code=204)
def delete_saved(saved_id: str, db: Session = Depends(get_db)) -> None:
    sq = db.get(SavedQuery, saved_id)
    if sq is None:
        raise HTTPException(status_code=404, detail="saved query not found")
    db.delete(sq)
    db.commit()


# ---------------------------------------------------------------- export


def _csv_stream(columns: list[str], rows: list[list[Any]]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    yield buf.getvalue()
    for row in rows:
        buf.seek(0)
        buf.truncate(0)
        writer.writerow(["" if v is None else v for v in row])
        yield buf.getvalue()


@router.get("/query-runs/{run_id}/export")
def export_run(
    run_id: str,
    format: Literal["csv"] = "csv",
    db: Session = Depends(get_db),
) -> StreamingResponse:
    run = _get_run(db, run_id)
    if run.status != "ok" or not run.final_sql:
        raise HTTPException(status_code=409, detail="only successful queries can be exported")
    schema = load_workspace_schema(db, run.workspace_id)
    try:
        res = run_query(
            run.workspace_id, run.final_sql, schema.allowed(), row_cap=get_settings().export_row_cap
        )
    except (SqlGuardError, ExecutionError) as e:
        raise HTTPException(status_code=409, detail=f"export failed: {e.message}") from e
    filename = f"askdata-{run.id[:8]}.csv"
    return StreamingResponse(
        _csv_stream(res.columns, res.rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

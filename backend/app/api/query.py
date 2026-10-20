"""Natural-language ask (JSON or SSE stream) and manual SQL run."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import Caller, enforce_limits, get_workspace
from app.core.config import get_settings
from app.core.limits import cost_tracker
from app.db.models import Workspace
from app.db.session import get_db, get_sessionmaker
from app.services.charts.picker import chart_dict
from app.services.execution.executor import ExecutionError
from app.services.execution.service import run_query
from app.services.history import (
    ConversationNotFoundError,
    get_or_create_conversation,
    history_for,
    save_manual_run,
    save_pipeline_run,
)
from app.services.llm import get_provider
from app.services.schema.cards import load_workspace_schema
from app.services.sqlguard import SqlGuardError
from app.services.text2sql.cache import AnswerCache
from app.services.text2sql.models import PipelineResult
from app.services.text2sql.pipeline import Text2SQLPipeline

router = APIRouter(tags=["query"])

_cache: AnswerCache | None = None


def get_answer_cache() -> AnswerCache:
    global _cache
    if _cache is None:
        _cache = AnswerCache(ttl_s=get_settings().answer_cache_ttl_s)
    return _cache


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


class AttemptOut(BaseModel):
    number: int
    sql: str
    error: str | None = None
    error_code: str | None = None


class AskOut(BaseModel):
    query_run_id: str
    conversation_id: str | None
    status: str
    kind: str
    question: str
    resolved_question: str
    sql: str | None
    columns: list[str]
    column_types: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    assumptions: list[str]
    reasoning: str = ""
    confidence: float | None
    tables_used: list[str]
    clarifying_question: str | None
    missing_data: str | None
    explanation: str | None
    chart: dict[str, Any] | None
    warnings: list[str]
    attempts: list[AttemptOut]
    error: str | None
    error_code: str | None
    duration_ms: int
    cost_usd: float
    cached: bool = False


def _to_out(result: PipelineResult, run_id: str, conversation_id: str | None) -> AskOut:
    return AskOut(
        query_run_id=run_id,
        conversation_id=conversation_id,
        status=result.status,
        kind=result.kind,
        question=result.question,
        resolved_question=result.resolved_question,
        sql=result.sql or (result.attempts[-1].sql if result.attempts else None),
        columns=result.columns,
        column_types=result.column_types,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        assumptions=result.assumptions,
        reasoning=result.reasoning,
        confidence=result.confidence,
        tables_used=result.tables_used,
        clarifying_question=result.clarifying_question,
        missing_data=result.missing_data,
        explanation=result.explanation,
        chart=result.chart,
        warnings=result.warnings,
        attempts=[
            AttemptOut(number=a.number, sql=a.sql, error=a.error, error_code=a.error_code)
            for a in result.attempts
        ],
        error=result.error,
        error_code=result.error_code,
        duration_ms=result.duration_ms,
        cost_usd=round(result.cost_usd, 6),
        cached=result.cached,
    )


def _run_ask(
    workspace_id: str,
    body: AskIn,
    caller: Caller,
    on_event: Any = None,
) -> AskOut:
    """Runs in a worker thread with its own DB session."""
    db = get_sessionmaker()()
    try:
        schema = load_workspace_schema(db, workspace_id)
        try:
            conv = get_or_create_conversation(
                db, workspace_id, body.conversation_id, title=body.question, user_id=caller.user_id
            )
        except ConversationNotFoundError as e:
            raise HTTPException(status_code=404, detail="conversation not found") from e
        history = history_for(db, conv.id, get_settings().followup_history_turns)
        pipeline = Text2SQLPipeline(get_provider(), cache=get_answer_cache())
        result = pipeline.run(
            workspace_id=workspace_id,
            question=body.question.strip(),
            schema=schema,
            history=history,
            on_event=on_event,
        )
        if not result.cached:
            cost_tracker().add(caller.key, result.cost_usd)
        run = save_pipeline_run(
            db, workspace_id=workspace_id, conversation=conv, result=result, user_id=caller.user_id
        )
        return _to_out(result, run.id, conv.id)
    finally:
        db.close()


@router.post("/workspaces/{workspace_id}/ask", response_model=AskOut)
async def ask(
    body: AskIn,
    request: Request,
    ws: Workspace = Depends(get_workspace),
    caller: Caller = Depends(enforce_limits),
) -> Any:
    if "text/event-stream" not in request.headers.get("accept", ""):
        return await run_in_threadpool(_run_ask, ws.id, body, caller)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    def on_event(name: str, payload: dict[str, Any]) -> None:
        if name != "done":
            loop.call_soon_threadsafe(queue.put_nowait, (name, payload))

    async def worker() -> None:
        try:
            out = await run_in_threadpool(_run_ask, ws.id, body, caller, on_event)
            await queue.put(("result", out.model_dump(mode="json")))
        except HTTPException as e:
            await queue.put(("error", {"detail": e.detail, "status": e.status_code}))
        except Exception:
            await queue.put(("error", {"detail": "internal error", "status": 500}))
        finally:
            await queue.put(None)

    async def stream() -> AsyncIterator[dict[str, str]]:
        task = asyncio.create_task(worker())
        try:
            while (item := await queue.get()) is not None:
                name, payload = item
                yield {"event": name, "data": json.dumps(payload, default=str)}
            yield {"event": "done", "data": "{}"}
        finally:
            await task

    return EventSourceResponse(stream())


class RunSqlIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    conversation_id: str | None = None


class RunSqlOut(BaseModel):
    query_run_id: str
    status: str
    sql: str | None
    columns: list[str] = []
    column_types: list[str] = []
    rows: list[list[Any]] = []
    row_count: int = 0
    truncated: bool = False
    chart: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    duration_ms: int = 0


def _run_sql(workspace_id: str, body: RunSqlIn, caller: Caller) -> RunSqlOut:
    db: Session = get_sessionmaker()()
    try:
        schema = load_workspace_schema(db, workspace_id)
        conv = None
        if body.conversation_id:
            try:
                conv = get_or_create_conversation(
                    db, workspace_id, body.conversation_id, title="", user_id=caller.user_id
                )
            except ConversationNotFoundError as e:
                raise HTTPException(status_code=404, detail="conversation not found") from e
        start = time.perf_counter()
        try:
            res = run_query(workspace_id, body.sql, schema.allowed())
        except (SqlGuardError, ExecutionError) as e:
            run = save_manual_run(
                db,
                workspace_id=workspace_id,
                conversation=conv,
                sql=body.sql,
                status="error",
                error=e.message,
                error_category=e.code,
                user_id=caller.user_id,
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
            return RunSqlOut(
                query_run_id=run.id,
                status="error",
                sql=body.sql,
                error=e.message,
                error_code=e.code,
            )
        chart = _chart_for(res.columns, res.column_types, res.rows)
        run = save_manual_run(
            db,
            workspace_id=workspace_id,
            conversation=conv,
            sql=res.sql,
            status="ok",
            rows=res.row_count,
            truncated=res.truncated,
            duration_ms=res.duration_ms,
            chart=chart,
            user_id=caller.user_id,
        )
        return RunSqlOut(
            query_run_id=run.id,
            status="ok",
            sql=res.sql,
            columns=res.columns,
            column_types=res.column_types,
            rows=res.rows,
            row_count=res.row_count,
            truncated=res.truncated,
            chart=chart,
            duration_ms=res.duration_ms,
        )
    finally:
        db.close()


def _chart_for(
    columns: list[str], types: list[str], rows: list[list[Any]]
) -> dict[str, Any] | None:
    try:
        return chart_dict(columns, types, rows)
    except ValueError:
        return None


@router.post("/workspaces/{workspace_id}/sql/run", response_model=RunSqlOut)
async def run_sql(
    body: RunSqlIn,
    ws: Workspace = Depends(get_workspace),
    caller: Caller = Depends(enforce_limits),
) -> RunSqlOut:
    return await run_in_threadpool(_run_sql, ws.id, body, caller)


@router.get("/workspaces/{workspace_id}/suggestions", response_model=list[str])
def suggestions(ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)) -> list[str]:
    """Suggested starter questions: curated for the demo, schema-derived otherwise."""
    if ws.is_demo:
        from app.demo.questions import DEMO_QUESTIONS

        return [q.question for q in DEMO_QUESTIONS]
    schema = load_workspace_schema(db, ws.id)
    out: list[str] = []
    for t in schema.tables[:3]:
        name = t.name.replace("_", " ")
        out.append(f"How many rows are in {name}?")
        dates = [c for c in t.columns if c.type in ("date", "timestamp")]
        nums = [c for c in t.columns if c.type in ("integer", "float", "currency")]
        cats = [c for c in t.columns if c.type == "text" and 1 < c.distinct_count <= 30]
        if dates and nums:
            out.append(f"Show total {nums[0].name.replace('_', ' ')} by month from {name}")
        if cats and nums:
            out.append(
                f"What is the total {nums[0].name.replace('_', ' ')} by "
                f"{cats[0].name.replace('_', ' ')} in {name}?"
            )
    return out[:6]

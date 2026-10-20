"""Benchmark runs (read-only; runs are started from the CLI) and operational metrics."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import EvalRun, Feedback, QueryRun
from app.db.session import get_db
from app.eval.metrics import percentile
from app.eval.report import compare_summaries

router = APIRouter(tags=["eval"])


class EvalRunSummary(BaseModel):
    id: str
    dataset: str
    git_sha: str | None
    model: str
    prompt_version: str
    config: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
    summary: dict[str, Any]


class EvalResultOut(BaseModel):
    case_id: str
    repeat: int
    predicted_kind: str | None
    predicted_sql: str | None
    exec_match: bool
    superset_match: bool
    kind_match: bool
    first_attempt_match: bool
    error_type: str | None
    attempts: int
    latency_ms: int
    cost_usd: float


class EvalRunDetail(EvalRunSummary):
    results: list[EvalResultOut]


def _summary(r: EvalRun) -> EvalRunSummary:
    return EvalRunSummary(
        id=r.id,
        dataset=r.dataset,
        git_sha=r.git_sha,
        model=r.model,
        prompt_version=r.prompt_version,
        config=dict(r.config or {}),
        started_at=r.started_at,
        finished_at=r.finished_at,
        summary=dict(r.summary or {}),
    )


@router.get("/eval/runs", response_model=list[EvalRunSummary])
def list_runs(
    db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=500)
) -> list[EvalRunSummary]:
    runs = db.scalars(select(EvalRun).order_by(EvalRun.started_at.desc()).limit(limit))
    return [_summary(r) for r in runs]


def _get(db: Session, run_id: str) -> EvalRun:
    run = db.scalars(
        select(EvalRun).where(EvalRun.id == run_id).options(selectinload(EvalRun.results))
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    return run


@router.get("/eval/runs/{run_id}", response_model=EvalRunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)) -> EvalRunDetail:
    run = _get(db, run_id)
    return EvalRunDetail(
        **_summary(run).model_dump(),
        results=[
            EvalResultOut(
                case_id=x.case_id,
                repeat=x.repeat,
                predicted_kind=x.predicted_kind,
                predicted_sql=x.predicted_sql,
                exec_match=x.exec_match,
                superset_match=x.superset_match,
                kind_match=x.kind_match,
                first_attempt_match=x.first_attempt_match,
                error_type=x.error_type,
                attempts=x.attempts,
                latency_ms=x.latency_ms,
                cost_usd=x.cost_usd,
            )
            for x in sorted(run.results, key=lambda x: (x.case_id, x.repeat))
        ],
    )


@router.get("/eval/compare")
def compare(a: str, b: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    ra, rb = _get(db, a), _get(db, b)
    amap = {
        x.case_id: x.exec_match or (x.kind_match and x.predicted_kind != "sql")
        for x in ra.results
        if x.repeat == 0
    }
    bmap = {
        x.case_id: x.exec_match or (x.kind_match and x.predicted_kind != "sql")
        for x in rb.results
        if x.repeat == 0
    }
    common = sorted(set(amap) & set(bmap))
    return {
        "a": _summary(ra).model_dump(mode="json"),
        "b": _summary(rb).model_dump(mode="json"),
        "metrics": compare_summaries(dict(ra.summary or {}), dict(rb.summary or {})),
        "fixed": [c for c in common if not amap[c] and bmap[c]],
        "broken": [c for c in common if amap[c] and not bmap[c]],
    }


@router.get("/metrics")
def metrics(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Operational metrics over natural-language asks in the last `days` days."""
    since = datetime.now(UTC) - timedelta(days=days)
    q = select(QueryRun).where(QueryRun.created_at >= since, QueryRun.source == "ask")
    if workspace_id:
        q = q.where(QueryRun.workspace_id == workspace_id)
    runs = list(db.scalars(q))
    run_ids = [r.id for r in runs]
    feedback = (
        list(db.scalars(select(Feedback).where(Feedback.query_run_id.in_(run_ids))))
        if run_ids
        else []
    )
    per_day: Counter[str] = Counter()
    for r in runs:
        created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)
        per_day[created.date().isoformat()] += 1
    n = len(runs)
    latencies = [float(r.duration_ms) for r in runs]
    ok = sum(1 for r in runs if r.status == "ok")
    corrected = sum(1 for r in runs if r.attempts > 1)
    failures = Counter(r.error_category or "unknown" for r in runs if r.status == "error")
    down = sum(1 for f in feedback if f.rating < 0)
    return {
        "days": days,
        "total_queries": n,
        "queries_per_day": dict(sorted(per_day.items())),
        "success_rate": round(ok / n, 4) if n else 0.0,
        "status_breakdown": dict(Counter(r.status for r in runs)),
        "latency_ms_p50": round(percentile(latencies, 0.5)),
        "latency_ms_p95": round(percentile(latencies, 0.95)),
        "cost_usd_total": round(sum(r.cost_usd for r in runs), 4),
        "cost_usd_per_query": round(sum(r.cost_usd for r in runs) / n, 6) if n else 0.0,
        "correction_loop_rate": round(corrected / n, 4) if n else 0.0,
        "feedback_count": len(feedback),
        "thumbs_down_rate": round(down / len(feedback), 4) if feedback else 0.0,
        "failure_categories": dict(failures.most_common()),
    }

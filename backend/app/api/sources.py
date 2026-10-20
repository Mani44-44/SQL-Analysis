"""Data-source upload and management."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ensure_access, get_current_user, get_workspace, get_writable_workspace
from app.core.config import get_settings
from app.db.models import DataSource, TableMeta, User, Workspace
from app.db.session import get_db
from app.services.ingestion.readers import UnsupportedFileError, detect_type
from app.services.ingestion.service import (
    delete_source_data,
    run_ingestion_job,
    source_file_path,
)

router = APIRouter(tags=["sources"])

CHUNK = 1024 * 1024


class SourceOut(BaseModel):
    id: str
    workspace_id: str
    type: str
    filename: str
    status: str
    error: str | None
    created_at: datetime
    tables: list[str] = []


def _out(db: Session, s: DataSource) -> SourceOut:
    names = list(db.scalars(select(TableMeta.name).where(TableMeta.source_id == s.id)))
    return SourceOut(
        id=s.id,
        workspace_id=s.workspace_id,
        type=s.type,
        filename=s.filename,
        status=s.status,
        error=s.error,
        created_at=s.created_at,
        tables=sorted(names),
    )


def _safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip()
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch in "._- ")[:200].strip()
    return cleaned or "upload"


@router.post("/workspaces/{workspace_id}/sources/upload", response_model=SourceOut, status_code=202)
async def upload_source(
    file: UploadFile,
    background: BackgroundTasks,
    ws: Workspace = Depends(get_writable_workspace),
    db: Session = Depends(get_db),
) -> SourceOut:
    settings = get_settings()
    filename = _safe_filename(file.filename or "upload")
    try:
        file_type = detect_type(filename)
    except UnsupportedFileError as e:
        raise HTTPException(status_code=415, detail=str(e)) from e

    source = DataSource(workspace_id=ws.id, type=file_type, filename=filename, status="pending")
    db.add(source)
    db.flush()
    dest = source_file_path(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=413, detail=f"file exceeds {settings.max_upload_mb} MB"
                    )
                out.write(chunk)
    except HTTPException:
        db.rollback()
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        db.rollback()
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="file is empty")
    db.commit()
    background.add_task(run_ingestion_job, source.id)
    return _out(db, source)


@router.get("/workspaces/{workspace_id}/sources", response_model=list[SourceOut])
def list_sources(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[SourceOut]:
    rows = db.scalars(
        select(DataSource).where(DataSource.workspace_id == ws.id).order_by(DataSource.created_at)
    )
    return [_out(db, s) for s in rows]


def _get_source(source_id: str, db: Session) -> DataSource:
    s = db.get(DataSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="source not found")
    return s


@router.get("/sources/{source_id}", response_model=SourceOut)
def read_source(
    source_id: str, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)
) -> SourceOut:
    s = _get_source(source_id, db)
    ensure_access(db, s.workspace_id, user)
    return _out(db, s)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)
) -> None:
    s = _get_source(source_id, db)
    ensure_access(db, s.workspace_id, user, write=True)
    delete_source_data(db, s)
    db.delete(s)
    db.commit()

"""Shared API dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Workspace
from app.db.session import get_db


def get_workspace(workspace_id: str, db: Session = Depends(get_db)) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return ws


def get_writable_workspace(ws: Workspace = Depends(get_workspace)) -> Workspace:
    if ws.is_demo:
        raise HTTPException(status_code=403, detail="the demo workspace is read-only")
    return ws

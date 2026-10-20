"""Workspace CRUD."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_workspace, get_writable_workspace
from app.db.models import Workspace
from app.db.session import get_db
from app.services.ingestion.service import delete_workspace_data

router = APIRouter(tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    is_demo: bool
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(db: Session = Depends(get_db)) -> list[Workspace]:
    return list(db.scalars(select(Workspace).order_by(Workspace.created_at)))


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceIn, db: Session = Depends(get_db)) -> Workspace:
    ws = Workspace(name=body.name.strip())
    db.add(ws)
    db.commit()
    return ws


@router.get("/workspaces/demo", response_model=WorkspaceOut)
def get_demo_workspace(db: Session = Depends(get_db)) -> Workspace:
    ws = db.scalars(select(Workspace).where(Workspace.is_demo.is_(True))).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="demo workspace has not been seeded")
    return ws


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def read_workspace(ws: Workspace = Depends(get_workspace)) -> Workspace:
    return ws


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(
    ws: Workspace = Depends(get_writable_workspace), db: Session = Depends(get_db)
) -> None:
    ws_id = ws.id
    db.delete(ws)
    db.commit()
    delete_workspace_data(ws_id)

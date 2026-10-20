"""Workspace CRUD."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_owned_workspace,
    get_workspace,
    member_role,
    require_user,
)
from app.db.models import User, Workspace, WorkspaceMember
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
    role: str | None = None


def _out(ws: Workspace, role: str | None) -> WorkspaceOut:
    return WorkspaceOut(
        id=ws.id, name=ws.name, is_demo=ws.is_demo, created_at=ws.created_at, role=role
    )


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(
    db: Session = Depends(get_db), user: User | None = Depends(get_current_user)
) -> list[WorkspaceOut]:
    """The caller's workspaces (with role) plus the public demo."""
    q = select(Workspace, WorkspaceMember.role).outerjoin(
        WorkspaceMember,
        (WorkspaceMember.workspace_id == Workspace.id)
        & (WorkspaceMember.user_id == (user.id if user else "")),
    )
    q = q.where(or_(Workspace.is_demo.is_(True), WorkspaceMember.user_id.is_not(None)))
    rows = db.execute(q.order_by(Workspace.is_demo.desc(), Workspace.created_at)).all()
    return [_out(ws, role) for ws, role in rows]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    body: WorkspaceIn, db: Session = Depends(get_db), user: User = Depends(require_user)
) -> WorkspaceOut:
    ws = Workspace(name=body.name.strip(), owner_id=user.id)
    ws.members.append(WorkspaceMember(user_id=user.id, role="owner"))
    db.add(ws)
    db.commit()
    return _out(ws, "owner")


@router.get("/workspaces/demo", response_model=WorkspaceOut)
def get_demo_workspace(db: Session = Depends(get_db)) -> WorkspaceOut:
    ws = db.scalars(select(Workspace).where(Workspace.is_demo.is_(True))).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="demo workspace has not been seeded")
    return _out(ws, None)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def read_workspace(
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> WorkspaceOut:
    return _out(ws, member_role(db, ws.id, user))


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(
    ws: Workspace = Depends(get_owned_workspace), db: Session = Depends(get_db)
) -> None:
    ws_id = ws.id
    db.delete(ws)
    db.commit()
    delete_workspace_data(ws_id)

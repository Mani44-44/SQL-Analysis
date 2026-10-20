"""Schema explorer, description edits, type overrides and glossary."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ensure_access, get_current_user, get_workspace, get_writable_workspace
from app.db.models import ColumnMeta, GlossaryTerm, TableMeta, User, Workspace
from app.db.session import get_db
from app.services.ingestion.infer import LogicalType
from app.services.ingestion.service import ingest_source
from app.services.schema.cards import (
    GlossaryCard,
    WorkspaceSchema,
    load_workspace_schema,
)

router = APIRouter(tags=["schema"])


@router.get("/workspaces/{workspace_id}/schema", response_model=WorkspaceSchema)
def get_schema(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> WorkspaceSchema:
    return load_workspace_schema(db, ws.id)


def _ensure_writable(db: Session, workspace_id: str, user: User | None) -> None:
    ensure_access(db, workspace_id, user, write=True)


class ColumnPatch(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    type_override: LogicalType | None = None
    clear_type_override: bool = False


@router.patch("/columns/{column_id}", response_model=WorkspaceSchema)
def patch_column(
    column_id: str,
    body: ColumnPatch,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> WorkspaceSchema:
    col = db.get(ColumnMeta, column_id)
    if col is None:
        raise HTTPException(status_code=404, detail="column not found")
    table = col.table
    _ensure_writable(db, table.workspace_id, user)
    if body.description is not None:
        col.description = body.description.strip() or None
    reload = False
    if body.clear_type_override and col.type_override is not None:
        col.type_override = None
        reload = True
    elif body.type_override is not None and body.type_override != col.type:
        col.type_override = body.type_override
        reload = True
    db.commit()
    if reload:
        result = ingest_source(db, table.source_id, describe=False)
        if result.status != "ready":
            raise HTTPException(status_code=422, detail=f"reload failed: {result.error}")
    return load_workspace_schema(db, table.workspace_id)


class TablePatch(BaseModel):
    description: str | None = Field(default=None, max_length=2000)


@router.patch("/tables/{table_id}", response_model=WorkspaceSchema)
def patch_table(
    table_id: str,
    body: TablePatch,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> WorkspaceSchema:
    t = db.get(TableMeta, table_id)
    if t is None:
        raise HTTPException(status_code=404, detail="table not found")
    _ensure_writable(db, t.workspace_id, user)
    if body.description is not None:
        t.description = body.description.strip() or None
    db.commit()
    return load_workspace_schema(db, t.workspace_id)


class GlossaryIn(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=2000)


@router.get("/workspaces/{workspace_id}/glossary", response_model=list[GlossaryCard])
def list_glossary(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[GlossaryCard]:
    rows = db.scalars(
        select(GlossaryTerm).where(GlossaryTerm.workspace_id == ws.id).order_by(GlossaryTerm.term)
    )
    return [GlossaryCard(id=g.id, term=g.term, definition=g.definition) for g in rows]


@router.post("/workspaces/{workspace_id}/glossary", response_model=GlossaryCard, status_code=201)
def add_glossary(
    body: GlossaryIn,
    ws: Workspace = Depends(get_writable_workspace),
    db: Session = Depends(get_db),
) -> GlossaryCard:
    g = GlossaryTerm(workspace_id=ws.id, term=body.term.strip(), definition=body.definition.strip())
    db.add(g)
    db.commit()
    return GlossaryCard(id=g.id, term=g.term, definition=g.definition)


@router.delete("/glossary/{term_id}", status_code=204)
def delete_glossary(
    term_id: str, db: Session = Depends(get_db), user: User | None = Depends(get_current_user)
) -> None:
    g = db.get(GlossaryTerm, term_id)
    if g is None:
        raise HTTPException(status_code=404, detail="term not found")
    _ensure_writable(db, g.workspace_id, user)
    db.delete(g)
    db.commit()

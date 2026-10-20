"""Readers (sandboxed executor) and the writer (ingestion) open the same DuckDB file with
different configurations; DuckDB rejects that while an instance is alive, so the per-workspace
RW lock must serialise them (D-011)."""

from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from app.db.models import ColumnMeta, DataSource, Workspace
from app.db.session import get_sessionmaker
from app.services.execution.service import run_query
from app.services.ingestion.service import ingest_source, source_file_path
from app.services.schema.cards import load_workspace_schema

CSV = "code,label\n" + "".join(f"{i},label{i}\n" for i in range(2000))


def _setup(db: Session) -> tuple[str, str]:
    ws = Workspace(name="c")
    db.add(ws)
    db.commit()
    src = DataSource(workspace_id=ws.id, type="csv", filename="codes.csv")
    db.add(src)
    db.commit()
    p = source_file_path(src)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(CSV)
    assert ingest_source(db, src.id, describe=False).status == "ready"
    return ws.id, src.id


def test_query_reingest_query(db: Session) -> None:
    ws, src = _setup(db)
    schema = load_workspace_schema(db, ws).allowed()
    assert run_query(ws, "SELECT sum(code) FROM codes", schema).rows[0][0] == sum(range(2000))
    col = db.query(ColumnMeta).filter_by(name="code").one()
    col.type_override = "text"
    db.commit()
    assert ingest_source(db, src, describe=False).status == "ready"
    schema = load_workspace_schema(db, ws).allowed()
    r = run_query(ws, "SELECT typeof(code) FROM codes LIMIT 1", schema)
    assert r.rows[0][0] == "VARCHAR"


def test_concurrent_reads_during_reingest(db: Session) -> None:
    ws, src = _setup(db)
    schema = load_workspace_schema(db, ws).allowed()
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                r = run_query(ws, "SELECT count(*) FROM codes", schema)
                assert r.rows[0][0] == 2000
            except BaseException as e:
                errors.append(e)
                return

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        session = get_sessionmaker()()
        try:
            for _ in range(3):
                assert ingest_source(session, src, describe=False).status == "ready"
        finally:
            session.close()
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=30)
    assert not errors, errors

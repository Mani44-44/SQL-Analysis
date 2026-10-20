from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.db.models import ColumnMeta, DataSource, TableMeta, Workspace
from app.services.ingestion.service import ingest_source, source_file_path
from app.services.llm import MockProvider
from app.services.schema.cards import load_workspace_schema, render_schema
from app.services.storage import workspace_db_path


def _make_source(
    db: Session, ws: Workspace, filename: str, content: bytes, type_: str
) -> DataSource:
    src = DataSource(workspace_id=ws.id, type=type_, filename=filename)
    db.add(src)
    db.commit()
    p = source_file_path(src)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return src


def _ws(db: Session) -> Workspace:
    ws = Workspace(name="t")
    db.add(ws)
    db.commit()
    return ws


def test_demo_ingestion_types(db: Session, demo_ws: str) -> None:
    schema = load_workspace_schema(db, demo_ws)
    assert schema.table_names == {"accounts", "budgets", "categories", "merchants", "transactions"}
    tx = schema.table("transactions")
    assert tx is not None
    types = {c.name: c.type for c in tx.columns}
    assert types["txn_date"] == "date"
    assert types["amount"] == "currency"
    assert types["txn_id"] == "text"
    budgets = schema.table("budgets")
    assert budgets is not None
    assert {c.name: c.type for c in budgets.columns}["month"] == "date"
    accounts = schema.table("accounts")
    assert accounts is not None
    assert {c.name: c.type for c in accounts.columns}["active"] == "boolean"
    # repeated header + blank rows removed
    con = duckdb.connect(str(workspace_db_path(demo_ws)), read_only=True)
    try:
        n = con.execute("SELECT count(*) FROM transactions WHERE txn_id = 'Txn ID'").fetchone()
        assert n == (0,)
        bad = con.execute("SELECT count(*) FROM transactions WHERE amount IS NULL").fetchone()
        assert bad == (0,)
    finally:
        con.close()
    hints = {(h.left_table, h.right_table) for h in schema.join_hints}
    assert ("transactions", "merchants") in hints
    assert ("transactions", "accounts") in hints
    text = render_schema(schema)
    assert "TABLE transactions" in text and "JOIN KEYS" in text


def test_type_override_reloads_and_keeps_descriptions(db: Session) -> None:
    ws = _ws(db)
    src = _make_source(db, ws, "codes.csv", b"code,label\n1,a\n2,b\n", "csv")
    assert ingest_source(db, src.id).status == "ready"
    col = db.query(ColumnMeta).filter_by(name="code").one()
    assert col.type == "integer"
    col.description = "item code"
    col.type_override = "text"
    db.commit()
    ingest_source(db, src.id, describe=False)
    db.expire_all()
    col = db.query(ColumnMeta).filter_by(name="code").one()
    assert col.type == "text"
    assert col.description == "item code"
    assert col.type_override == "text"


def test_bad_file_marks_failed(db: Session) -> None:
    ws = _ws(db)
    src = _make_source(db, ws, "bad.sqlite", b"not a database at all" * 10, "sqlite")
    result = ingest_source(db, src.id)
    assert result.status == "failed"
    assert result.error


def test_sqlite_import(db: Session, tmp_path: Path) -> None:
    p = tmp_path / "x.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE people (name TEXT, age INTEGER)")
    con.executemany("INSERT INTO people VALUES (?, ?)", [("a", 30), ("b", None)])
    con.commit()
    con.close()
    ws = _ws(db)
    src = _make_source(db, ws, "x.sqlite", p.read_bytes(), "sqlite")
    assert ingest_source(db, src.id).status == "ready"
    t = db.query(TableMeta).filter_by(name="people").one()
    assert t.row_count == 2
    assert {c.name: c.type for c in t.columns} == {"name": "text", "age": "integer"}


def test_xlsx_multi_sheet_and_name_collision(db: Session, tmp_path: Path) -> None:
    wb = Workbook()
    ws1 = wb.active
    assert ws1 is not None
    ws1.title = "A"
    ws1.append(["x"])
    ws1.append([1])
    ws2 = wb.create_sheet("B")
    ws2.append(["y"])
    ws2.append(["hello"])
    p = tmp_path / "book.xlsx"
    wb.save(p)
    ws = _ws(db)
    src1 = _make_source(db, ws, "book.xlsx", p.read_bytes(), "xlsx")
    assert ingest_source(db, src1.id).status == "ready"
    src2 = _make_source(db, ws, "book.xlsx", p.read_bytes(), "xlsx")
    assert ingest_source(db, src2.id).status == "ready"
    names = {t.name for t in db.query(TableMeta).all()}
    assert names == {"book_a", "book_b", "book_a_2", "book_b_2"}


def test_llm_descriptions_fill_only_empty(db: Session, mock_llm: MockProvider) -> None:
    mock_llm.register(
        "describe_table",
        lambda call: {
            "table_description": "A table of codes.",
            "columns": [
                {"name": "code", "description": "Numeric code."},
                {"name": "zzz", "description": "x"},
            ],
        },
    )
    ws = _ws(db)
    src = _make_source(db, ws, "codes.csv", b"code,label\n1,a\n", "csv")
    ingest_source(db, src.id)
    t = db.query(TableMeta).one()
    assert t.description == "A table of codes."
    descs = {c.name: c.description for c in t.columns}
    assert descs == {"code": "Numeric code.", "label": None}
    assert "<table_profile>" in mock_llm.calls[0].last_user

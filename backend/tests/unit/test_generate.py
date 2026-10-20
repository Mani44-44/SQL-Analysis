from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import load_workbook

from app.demo.generate import generate, indian_grouping


def test_indian_grouping() -> None:
    assert indian_grouping(120000) == "1,20,000.00"
    assert indian_grouping(12345678.9) == "1,23,45,678.90"
    assert indian_grouping(999) == "999.00"


def _xlsx_rows(path: Path) -> list[list[object]]:
    ws = load_workbook(path).active
    assert ws is not None
    return [list(r) for r in ws.iter_rows(values_only=True)]


def test_generator_is_deterministic(tmp_path: Path) -> None:
    a = generate(tmp_path / "a")
    b = generate(tmp_path / "b")
    for name in ("transactions", "accounts", "merchants", "categories"):
        assert a[name].read_bytes() == b[name].read_bytes(), name
    assert _xlsx_rows(a["budgets"]) == _xlsx_rows(b["budgets"])


def test_generator_injects_mess(tmp_path: Path) -> None:
    files = generate(tmp_path)
    with files["transactions"].open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == " Txn ID"
    body = rows[1:]
    assert any(all(c == "" for c in r) for r in body), "blank rows"
    assert any(r[0] == "Txn ID" for r in body), "repeated header"
    amounts = [r[5] for r in body if len(r) > 5]
    assert any(a.startswith("₹") for a in amounts)
    assert any(a.startswith("Rs.") for a in amounts)
    dates = [r[1] for r in body if len(r) > 1 and r[1]]
    assert any("/" in d for d in dates)
    assert any(d[:4].isdigit() for d in dates)

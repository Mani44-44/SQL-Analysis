"""Read uploaded files into raw string tables (cleaning and typing happen later)."""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

SUPPORTED_EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".xlsx": "xlsx",
    ".sqlite": "sqlite",
    ".db": "sqlite",
    ".sqlite3": "sqlite",
}


class UnsupportedFileError(ValueError):
    pass


@dataclass
class RawTable:
    name: str
    header: list[str]
    rows: list[list[str | None]]


def detect_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"unsupported file type '{ext}'; upload CSV, XLSX or SQLite")
    return SUPPORTED_EXTENSIONS[ext]


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnsupportedFileError("could not decode file text")  # pragma: no cover


def read_csv(path: Path, max_rows: int) -> list[RawTable]:
    text = _decode(path.read_bytes())
    sample = text[:20000]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header: list[str] | None = None
    rows: list[list[str | None]] = []
    for record in reader:
        if header is None:
            if not any(c.strip() for c in record):
                continue  # leading blank lines
            header = list(record)
            continue
        if len(rows) >= max_rows:
            raise UnsupportedFileError(f"file exceeds the {max_rows:,} row limit")
        rows.append(list(record))
    if header is None:
        raise UnsupportedFileError("file is empty")
    return [RawTable(path.stem, header, rows)]


def _cell(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat()  # type: ignore[no-any-return]
    return str(v)


def read_xlsx(path: Path, max_rows: int) -> list[RawTable]:
    wb = load_workbook(path, read_only=True, data_only=True)
    tables: list[RawTable] = []
    try:
        sheets = [ws for ws in wb.worksheets if ws.max_row and ws.max_row > 0]
        for ws in sheets:
            it = ws.iter_rows(values_only=True)
            header: list[str] | None = None
            rows: list[list[str | None]] = []
            for record in it:
                values = [_cell(v) for v in record]
                if header is None:
                    if not any(v and v.strip() for v in values):
                        continue
                    header = [v or "" for v in values]
                    continue
                if len(rows) >= max_rows:
                    raise UnsupportedFileError(f"sheet exceeds the {max_rows:,} row limit")
                rows.append(values)
            if header is None:
                continue
            name = path.stem if len(sheets) == 1 else f"{path.stem}_{ws.title}"
            tables.append(RawTable(name, header, rows))
    finally:
        wb.close()
    if not tables:
        raise UnsupportedFileError("workbook has no data")
    return tables


def read_sqlite(path: Path, max_rows: int) -> list[RawTable]:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only = ON")
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        tables: list[RawTable] = []
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            cur = con.execute(f"SELECT * FROM {quoted} LIMIT ?", (max_rows + 1,))  # noqa: S608
            header = [d[0] for d in cur.description]
            rows = [[_cell(v) for v in r] for r in cur.fetchall()]
            if len(rows) > max_rows:
                raise UnsupportedFileError(f"table {name} exceeds the {max_rows:,} row limit")
            tables.append(RawTable(name, header, rows))
    except sqlite3.DatabaseError as e:
        raise UnsupportedFileError(f"not a valid SQLite database: {e}") from e
    finally:
        con.close()
    if not tables:
        raise UnsupportedFileError("SQLite database has no tables")
    return tables


def read_file(path: Path, file_type: str, max_rows: int) -> list[RawTable]:
    if file_type == "csv":
        return read_csv(path, max_rows)
    if file_type == "xlsx":
        return read_xlsx(path, max_rows)
    if file_type == "sqlite":
        return read_sqlite(path, max_rows)
    raise UnsupportedFileError(f"unsupported type {file_type}")

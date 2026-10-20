"""Structural cleaning: headers, null placeholders, blank and repeated-header rows."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.services.ingestion.readers import RawTable

NULL_TOKENS = {"", "na", "n/a", "null", "none", "nil", "-", "--", "nan", "#n/a"}

# DuckDB reserved keywords that cannot be used unquoted as column names.
RESERVED = {
    "all", "analyse", "analyze", "and", "any", "array", "as", "asc", "asymmetric", "both",
    "case", "cast", "check", "collate", "column", "constraint", "create", "default",
    "deferrable", "desc", "describe", "distinct", "do", "else", "end", "except", "false",
    "fetch", "for", "foreign", "from", "grant", "group", "having", "in", "initially",
    "intersect", "into", "lateral", "leading", "limit", "offset", "on", "only", "or",
    "order", "pivot", "placing", "primary", "qualify", "references", "returning", "select",
    "show", "some", "summarize", "symmetric", "table", "then", "to", "trailing", "true",
    "union", "unique", "unpivot", "using", "variadic", "when", "where", "window", "with",
}  # fmt: skip


def to_identifier(raw: str, fallback: str = "col") -> str:
    """Normalise an arbitrary header / file name into a safe snake_case SQL identifier."""
    s = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s.strip())
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    s = re.sub(r"_+", "_", s)
    if not s:
        s = fallback
    if s[0].isdigit():
        s = f"{fallback}_{s}"
    if s in RESERVED:
        s = f"{s}_"
    return s[:63]


def dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen[n] = 1
            out.append(n)
            continue
        i = seen[n] + 1
        while f"{n}_{i}" in seen:
            i += 1
        seen[n] = i
        seen[f"{n}_{i}"] = 1
        out.append(f"{n}_{i}")
    return out


def normalise_cell(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    return None if s.lower() in NULL_TOKENS else s


@dataclass
class CleanTable:
    name: str
    columns: list[str]
    original_columns: list[str]
    rows: list[list[str | None]]
    dropped_blank: int = 0
    dropped_header_repeats: int = 0


def clean_table(raw: RawTable) -> CleanTable:
    original = [h.strip() for h in raw.header]
    # Trim trailing fully-empty header columns (common in spreadsheets).
    width = len(original)
    while width > 0 and not original[width - 1]:
        if any(len(r) >= width and normalise_cell(r[width - 1]) for r in raw.rows):
            break
        width -= 1
    original = original[:width]
    columns = dedupe([to_identifier(h, f"column_{i + 1}") for i, h in enumerate(original)])
    header_key = [h.lower() for h in original]

    rows: list[list[str | None]] = []
    blank = repeats = 0
    for r in raw.rows:
        cells = [normalise_cell(c) for c in (list(r) + [None] * width)[:width]]
        if all(c is None for c in cells):
            blank += 1
            continue
        if [(c or "").lower() for c in cells] == header_key:
            repeats += 1
            continue
        rows.append(cells)

    return CleanTable(
        name=to_identifier(raw.name, "table"),
        columns=columns,
        original_columns=original,
        rows=rows,
        dropped_blank=blank,
        dropped_header_repeats=repeats,
    )

"""Column type inference and value conversion.

Logical types and their DuckDB storage types:

    boolean -> BOOLEAN      integer -> BIGINT       float -> DOUBLE
    currency -> DOUBLE      percent -> DOUBLE (stored as the number shown, e.g. 12.5)
    date -> DATE            timestamp -> TIMESTAMP  text -> VARCHAR

Numeric and boolean types require every non-null value to parse. Date/timestamp types require
at least `threshold` (default 95%) to parse; the rest become NULL and are counted as coerced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

LogicalType = Literal[
    "boolean", "integer", "float", "currency", "percent", "date", "timestamp", "text"
]
LOGICAL_TYPES: tuple[LogicalType, ...] = (
    "boolean", "integer", "float", "currency", "percent", "date", "timestamp", "text",
)  # fmt: skip

DUCKDB_TYPES: dict[LogicalType, str] = {
    "boolean": "BOOLEAN",
    "integer": "BIGINT",
    "float": "DOUBLE",
    "currency": "DOUBLE",
    "percent": "DOUBLE",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "text": "VARCHAR",
}

TRUE_TOKENS = {"true", "t", "yes", "y"}
FALSE_TOKENS = {"false", "f", "no", "n"}
_BOOL_STRICT = {"true", "false", "yes", "no", "y", "n", "t", "f", "1", "0"}

_CURRENCY_PREFIX = re.compile(r"^(?:₹|rs\.?|inr|\$|usd|€|eur|£|gbp)\s*", re.IGNORECASE)
_CURRENCY_SUFFIX = re.compile(r"\s*(?:₹|inr|usd|eur|gbp)$", re.IGNORECASE)
_DRCR = re.compile(r"\s*(dr|cr)\.?$", re.IGNORECASE)
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_GROUPED = re.compile(r"^[+-]?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?$")
_INT = re.compile(r"^[+-]?\d+$")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}  # fmt: skip


@dataclass
class ParsedNumber:
    value: float
    is_currency: bool
    is_percent: bool
    is_int: bool


def parse_number(raw: str) -> ParsedNumber | None:
    s = raw.strip()
    if not s:
        return None
    sign = 1.0
    is_currency = False
    is_percent = False
    if s.startswith("(") and s.endswith(")"):
        sign, s = -1.0, s[1:-1].strip()
    m = _DRCR.search(s)
    if m:
        if m.group(1).lower() == "dr":
            sign = -sign
        s = s[: m.start()].strip()
        is_currency = True
    if s.startswith("-") and len(s) > 1 and not s[1].isdigit():
        sign, s = -sign, s[1:].strip()
    stripped = _CURRENCY_PREFIX.sub("", s)
    stripped = _CURRENCY_SUFFIX.sub("", stripped)
    if stripped != s:
        is_currency = True
    s = stripped.strip()
    if s.endswith("%"):
        is_percent, s = True, s[:-1].strip()
    if "," in s:
        if not _GROUPED.match(s):
            return None
        s = s.replace(",", "")
    if not _NUMBER.match(s):
        return None
    try:
        value = float(s) * sign
    except ValueError:  # pragma: no cover - guarded by regex
        return None
    return ParsedNumber(value, is_currency, is_percent, bool(_INT.match(s)))


# ----------------------------------------------------------------------------- dates


_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_ISO_SLASH = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$")
_D_MON_Y = re.compile(r"^(\d{1,2})[\s-]([A-Za-z]{3,9})[\s,-]+(\d{2}|\d{4})$")
_MON_D_Y = re.compile(r"^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})$")
_MON_Y = re.compile(r"^([A-Za-z]{3,9})[\s-](\d{2}|\d{4})$")
_Y_M = re.compile(r"^(\d{4})-(\d{1,2})$")
_TS = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{2})"
    r"(?::(\d{2})(?:\.(\d{1,6}))?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
_DMY_TS = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$")


def _year(y: str) -> int:
    v = int(y)
    return v + (2000 if v < 70 else 1900) if len(y) == 2 else v


def _month(name: str) -> int | None:
    return _MONTHS.get(name[:3].lower())


def slash_order(values: list[str]) -> Literal["dmy", "mdy"]:
    """Decide day-first vs month-first for a column of a/b/yyyy values. Defaults to day-first."""
    first_gt12 = second_gt12 = False
    for v in values:
        m = _DMY.match(v) or _DMY_TS.match(v)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            first_gt12 |= a > 12
            second_gt12 |= b > 12
    if second_gt12 and not first_gt12:
        return "mdy"
    return "dmy"


def parse_date(raw: str, order: Literal["dmy", "mdy"] = "dmy") -> date | None:
    s = raw.strip()
    try:
        if m := _ISO_DATE.match(s) or _ISO_SLASH.match(s):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := _DMY.match(s):
            a, b = int(m.group(1)), int(m.group(2))
            d, mo = (a, b) if order == "dmy" else (b, a)
            return date(_year(m.group(3)), mo, d)
        if m := _D_MON_Y.match(s):
            mo_ = _month(m.group(2))
            return date(_year(m.group(3)), mo_, int(m.group(1))) if mo_ else None
        if m := _MON_D_Y.match(s):
            mo_ = _month(m.group(1))
            return date(int(m.group(3)), mo_, int(m.group(2))) if mo_ else None
        if m := _MON_Y.match(s):
            mo_ = _month(m.group(1))
            return date(_year(m.group(2)), mo_, 1) if mo_ else None
        if m := _Y_M.match(s):
            return date(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None
    return None


def parse_timestamp(raw: str, order: Literal["dmy", "mdy"] = "dmy") -> datetime | None:
    s = raw.strip()
    try:
        if m := _TS.match(s):
            frac = (m.group(7) or "0").ljust(6, "0")
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), int(m.group(6) or 0), int(frac),
            )  # fmt: skip
        if m := _DMY_TS.match(s):
            a, b = int(m.group(1)), int(m.group(2))
            d, mo = (a, b) if order == "dmy" else (b, a)
            return datetime(
                int(m.group(3)), mo, d, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)
            )
    except ValueError:
        return None
    d_only = parse_date(s, order)
    return datetime(d_only.year, d_only.month, d_only.day) if d_only else None


# ----------------------------------------------------------------------------- inference


@dataclass
class InferredColumn:
    logical_type: LogicalType
    values: list[str | None]  # canonical strings castable by DuckDB to the storage type
    coerced_nulls: int = 0


def _fmt_float(v: float) -> str:
    return repr(v)


def convert(
    values: list[str | None], logical_type: LogicalType, threshold: float = 0.95
) -> InferredColumn | None:
    """Convert values to canonical strings for `logical_type`.

    Returns None if the column does not satisfy the type (used during inference). For forced
    types (user override) call with threshold=0.0 so unparseable values become NULL.
    """
    non_null = [v for v in values if v is not None]
    n = len(non_null)
    out: list[str | None] = []
    failures = 0

    if logical_type == "text":
        return InferredColumn("text", list(values))

    if logical_type == "boolean":
        for v in values:
            if v is None:
                out.append(None)
                continue
            low = v.lower()
            if low in TRUE_TOKENS or low == "1":
                out.append("true")
            elif low in FALSE_TOKENS or low == "0":
                out.append("false")
            else:
                failures += 1
                out.append(None)
    elif logical_type in ("integer", "float", "currency", "percent"):
        for v in values:
            if v is None:
                out.append(None)
                continue
            p = parse_number(v)
            if p is None or (logical_type == "integer" and not p.is_int):
                failures += 1
                out.append(None)
            elif logical_type == "integer":
                out.append(str(int(p.value)))
            else:
                out.append(_fmt_float(p.value))
    elif logical_type in ("date", "timestamp"):
        order = slash_order(non_null)
        for v in values:
            if v is None:
                out.append(None)
                continue
            if logical_type == "date":
                d = parse_date(v, order)
                if d is None:
                    ts = parse_timestamp(v, order)
                    d = ts.date() if ts and ts.time() == datetime.min.time() else None
                out.append(d.isoformat() if d else None)
            else:
                ts = parse_timestamp(v, order)
                out.append(ts.isoformat(sep=" ") if ts else None)
            if out[-1] is None:
                failures += 1

    if n and failures:
        exact = logical_type not in ("date", "timestamp")
        if threshold > 0 and (exact or (n - failures) / n < threshold):
            return None
    return InferredColumn(logical_type, out, coerced_nulls=failures)


def infer_column(values: list[str | None], threshold: float = 0.95) -> InferredColumn:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return InferredColumn("text", list(values))

    lowered = {v.lower() for v in non_null}
    if lowered <= _BOOL_STRICT and not lowered <= {"0", "1"}:
        r = convert(values, "boolean", threshold)
        if r:
            return r

    parsed = [parse_number(v) for v in non_null]
    if all(p is not None for p in parsed):
        nums = [p for p in parsed if p is not None]
        # Codes with leading zeros (e.g. "007", PIN codes) stay text.
        if any(len(v) > 1 and v.startswith("0") and v[1].isdigit() for v in non_null):
            return InferredColumn("text", list(values))
        if any(p.is_percent for p in nums):
            r = convert(values, "percent", threshold)
        elif any(p.is_currency for p in nums):
            r = convert(values, "currency", threshold)
        elif all(p.is_int for p in nums):
            r = convert(values, "integer", threshold)
        else:
            r = convert(values, "float", threshold)
        if r:
            return r

    has_time = any(_TS.match(v) or _DMY_TS.match(v) for v in non_null)
    if has_time:
        r = convert(values, "timestamp", threshold)
        if r:
            all_midnight = all(v is None or v.endswith("00:00:00") for v in r.values)
            if all_midnight:
                d = convert(values, "date", threshold)
                if d:
                    return d
            return r
    r = convert(values, "date", threshold)
    if r:
        return r
    return InferredColumn("text", list(values))

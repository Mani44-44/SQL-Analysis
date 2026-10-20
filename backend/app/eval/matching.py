"""Execution-match semantics (spec section 9.2).

- Column order and names are ignored: predicted columns are mapped onto gold columns.
- Rows are compared as a multiset unless the gold SQL has a top-level ORDER BY.
- Numbers are canonicalised (money-style rounding to 2 dp for |x| >= 1, 4 significant digits
  below 1), so 1234.5678 == 1234.57 and 0.123456 == 0.1235. Ints equal floats of equal value.
- NULL equals NULL. Booleans compare as booleans (never equal to 0/1).
- Temporal strings are canonicalised: '2025-01-01T00:00:00' == '2025-01-01', and month labels
  'YYYY-MM' == 'YYYY-MM-01'.
- strict match: same number of columns. superset match: prediction may have extra columns.
  Both require the same number of rows.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp

_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00:00(?:\.0+)?$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
MAX_PERMUTATIONS = 5000


def canon(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int | float):
        f = float(value)
        if f != f:  # NaN
            return None
        if abs(f) >= 1:
            return round(f, 2)
        return float(f"{f:.4g}")
    if isinstance(value, str):
        s = value.strip()
        if m := _MIDNIGHT.match(s):
            return m.group(1)
        if m := _MONTH.match(s):
            return f"{m.group(1)}-{m.group(2)}-01"
        return s
    if isinstance(value, list | tuple):
        return tuple(canon(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((str(k), canon(v)) for k, v in value.items()))
    return str(value)


def _sort_key(v: Any) -> tuple[int, str]:
    return (0, "") if v is None else (1, repr(v))


def gold_is_ordered(gold_sql: str) -> bool:
    """True if the top-level query has ORDER BY (row order then matters)."""
    try:
        tree = sqlglot.parse_one(gold_sql, read="duckdb")
    except sqlglot.errors.ParseError:
        return False
    return isinstance(tree, exp.Query) and tree.args.get("order") is not None


@dataclass
class MatchResult:
    strict: bool
    superset: bool


def _rows_equal(gold: list[tuple[Any, ...]], pred: list[tuple[Any, ...]], ordered: bool) -> bool:
    if ordered:
        return gold == pred
    return Counter(gold) == Counter(pred)


def match_results(
    gold_columns: Sequence[str],
    gold_rows: Sequence[Sequence[Any]],
    pred_columns: Sequence[str],
    pred_rows: Sequence[Sequence[Any]],
    *,
    ordered: bool = False,
) -> MatchResult:
    n_gold, n_pred = len(gold_columns), len(pred_columns)
    if len(gold_rows) != len(pred_rows) or n_pred < n_gold or n_gold == 0:
        return MatchResult(False, False)
    g = [tuple(canon(v) for v in r) for r in gold_rows]
    p = [tuple(canon(v) for v in r) for r in pred_rows]

    # Candidate predicted columns for each gold column: equal value multisets.
    def col(rows: list[tuple[Any, ...]], i: int) -> list[Any]:
        return sorted((r[i] for r in rows), key=_sort_key)

    gold_cols = [col(g, i) for i in range(n_gold)]
    pred_cols = [col(p, j) for j in range(n_pred)]
    candidates = [[j for j in range(n_pred) if pred_cols[j] == gold_cols[i]] for i in range(n_gold)]
    if any(not c for c in candidates):
        return MatchResult(False, False)

    tried = 0
    for assignment in itertools.product(*candidates):
        if len(set(assignment)) != n_gold:
            continue
        tried += 1
        if tried > MAX_PERMUTATIONS:
            break
        projected = [tuple(r[j] for j in assignment) for r in p]
        if _rows_equal(g, projected, ordered):
            strict = n_pred == n_gold
            return MatchResult(strict=strict, superset=True)
    return MatchResult(False, False)

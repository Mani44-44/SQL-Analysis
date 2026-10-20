from __future__ import annotations

import pytest

from app.eval.matching import canon, gold_is_ordered, match_results


def m(gc, gr, pc, pr, ordered=False):  # type: ignore[no-untyped-def]
    return match_results(gc, gr, pc, pr, ordered=ordered)


def test_identical() -> None:
    r = m(["a"], [[1], [2]], ["x"], [[1], [2]])
    assert r.strict and r.superset


def test_column_order_and_names_ignored() -> None:
    r = m(["name", "n"], [["a", 1], ["b", 2]], ["cnt", "label"], [[2, "b"], [1, "a"]])
    assert r.strict


def test_row_pairing_is_respected() -> None:
    # Same column multisets, different pairing -> not a match.
    r = m(["k", "v"], [["a", 1], ["b", 2]], ["k", "v"], [["a", 2], ["b", 1]])
    assert not r.strict and not r.superset


def test_order_only_matters_when_requested() -> None:
    assert m(["a"], [[1], [2]], ["a"], [[2], [1]]).strict
    assert not m(["a"], [[1], [2]], ["a"], [[2], [1]], ordered=True).strict


def test_float_tolerance_and_int_float() -> None:
    assert m(["a"], [[1234.5678]], ["a"], [[1234.57]]).strict
    assert m(["a"], [[0.123456]], ["a"], [[0.1235]]).strict
    assert m(["a"], [[5]], ["a"], [[5.0]]).strict
    assert not m(["a"], [[100.0]], ["a"], [[101.0]]).strict


def test_nulls_and_bools() -> None:
    assert m(["a"], [[None]], ["a"], [[None]]).strict
    assert not m(["a"], [[None]], ["a"], [[0]]).strict
    assert not m(["a"], [[True]], ["a"], [[1]]).strict


def test_temporal_canonicalisation() -> None:
    assert m(["m"], [["2025-01-01T00:00:00"]], ["m"], [["2025-01-01"]]).strict
    assert m(["m"], [["2025-01-01"]], ["m"], [["2025-01"]]).strict
    assert not m(["m"], [["2025-01-01T10:00:00"]], ["m"], [["2025-01-01"]]).strict


def test_superset_columns() -> None:
    r = m(["merchant"], [["a"], ["b"]], ["merchant", "spend"], [["a", 1], ["b", 2]])
    assert r.superset and not r.strict
    assert not m(["a", "b"], [[1, 2]], ["a"], [[1]]).superset  # fewer columns never match


def test_row_count_must_match() -> None:
    assert not m(["a"], [[1]], ["a"], [[1], [1]]).superset


def test_duplicate_rows_multiset() -> None:
    assert not m(["a"], [[1], [1], [2]], ["a"], [[1], [2], [2]]).strict


def test_empty_results() -> None:
    assert m(["a"], [], ["b"], []).strict


@pytest.mark.parametrize(
    ("sql", "ordered"),
    [
        ("SELECT a FROM t ORDER BY a", True),
        ("SELECT a FROM t", False),
        ("SELECT * FROM (SELECT a FROM t ORDER BY a) x", False),
        ("WITH c AS (SELECT 1) SELECT * FROM c ORDER BY 1", True),
        ("not sql at all (", False),
    ],
)
def test_gold_is_ordered(sql: str, ordered: bool) -> None:
    assert gold_is_ordered(sql) is ordered


def test_canon() -> None:
    assert canon(True) == ("bool", True)
    assert canon(float("nan")) is None
    assert canon([1, "2025-01"]) == (1.0, "2025-01-01")

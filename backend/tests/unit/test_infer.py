from __future__ import annotations

from datetime import date, datetime

import pytest

from app.services.ingestion.infer import (
    convert,
    infer_column,
    parse_date,
    parse_number,
    parse_timestamp,
    slash_order,
)


@pytest.mark.parametrize(
    ("raw", "value", "currency"),
    [
        ("₹1,20,000.50", 120000.5, True),
        ("Rs. 1234.5", 1234.5, True),
        ("Rs 99", 99.0, True),
        ("INR 1,234.50", 1234.5, True),
        ("$1,000", 1000.0, True),
        ("1,234.50", 1234.5, False),
        ("500 Dr", -500.0, True),
        ("500 Cr", 500.0, True),
        ("(250.00)", -250.0, False),
        ("-₹75", -75.0, True),
        ("1e3", 1000.0, False),
        ("42", 42.0, False),
    ],
)
def test_parse_number(raw: str, value: float, currency: bool) -> None:
    p = parse_number(raw)
    assert p is not None
    assert p.value == pytest.approx(value)
    assert p.is_currency is currency


@pytest.mark.parametrize("raw", ["abc", "1,2,3", "12.5.1", "", "₹", "T000123", "1 2"])
def test_parse_number_rejects(raw: str) -> None:
    assert parse_number(raw) is None


def test_parse_percent() -> None:
    p = parse_number("12.5%")
    assert p is not None and p.is_percent and p.value == 12.5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-03-04", date(2025, 3, 4)),
        ("2025/03/04", date(2025, 3, 4)),
        ("04/03/2025", date(2025, 3, 4)),
        ("4-Mar-25", date(2025, 3, 4)),
        ("04 March 2025", date(2025, 3, 4)),
        ("March 4, 2025", date(2025, 3, 4)),
        ("Jan-2025", date(2025, 1, 1)),
        ("2025-01", date(2025, 1, 1)),
    ],
)
def test_parse_date(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


def test_parse_date_invalid() -> None:
    assert parse_date("31/02/2025") is None
    assert parse_date("hello") is None


def test_slash_order_detection() -> None:
    assert slash_order(["13/01/2025", "01/02/2025"]) == "dmy"
    assert slash_order(["01/13/2025", "02/01/2025"]) == "mdy"
    assert slash_order(["01/02/2025"]) == "dmy"  # ambiguous -> Indian default
    assert parse_date("01/13/2025", "mdy") == date(2025, 1, 13)


def test_parse_timestamp() -> None:
    assert parse_timestamp("2025-03-04T10:15:30") == datetime(2025, 3, 4, 10, 15, 30)
    assert parse_timestamp("04/03/2025 18:05") == datetime(2025, 3, 4, 18, 5)


def test_infer_types() -> None:
    assert infer_column(["1", "2", None, "3"]).logical_type == "integer"
    assert infer_column(["1.5", "2"]).logical_type == "float"
    assert infer_column(["₹1,000", "Rs. 20", "30.00"]).logical_type == "currency"
    assert infer_column(["10%", "5.5%"]).logical_type == "percent"
    assert infer_column(["Yes", "N", "yes", "no"]).logical_type == "boolean"
    assert infer_column(["0", "1", "1"]).logical_type == "integer"
    assert infer_column(["007", "008"]).logical_type == "text"
    assert infer_column(["2025-01-01", "02/01/2025", "3-Jan-25"]).logical_type == "date"
    assert infer_column(["2025-01-01 10:00:00", "2025-01-02 11:30:00"]).logical_type == "timestamp"
    assert infer_column(["2025-01-01 00:00:00", "2025-01-02 00:00:00"]).logical_type == "date"
    assert infer_column(["a", "b"]).logical_type == "text"
    assert infer_column([None, None]).logical_type == "text"


def test_infer_number_with_one_bad_value_stays_text() -> None:
    assert infer_column(["1", "2", "three"]).logical_type == "text"


def test_date_threshold() -> None:
    good = [f"2025-01-{d:02d}" for d in range(1, 21)]
    r = infer_column([*good, "garbage"], threshold=0.95)
    assert r.logical_type == "date"
    assert r.coerced_nulls == 1
    assert r.values[-1] is None
    assert infer_column([*good[:5], "x", "y"], threshold=0.95).logical_type == "text"


def test_infer_canonical_values() -> None:
    r = infer_column(["₹1,20,000.50", "Rs. 5"])
    assert r.values == ["120000.5", "5.0"]
    d = infer_column(["13/01/2025", "4-Mar-25"])
    assert d.values == ["2025-01-13", "2025-03-04"]


def test_forced_convert_nulls_failures() -> None:
    r = convert(["1", "x", None], "integer", threshold=0.0)
    assert r is not None
    assert r.values == ["1", None, None]
    assert r.coerced_nulls == 1

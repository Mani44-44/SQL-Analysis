from __future__ import annotations

import pytest

from app.services.ingestion.clean import clean_table, dedupe, normalise_cell, to_identifier
from app.services.ingestion.readers import RawTable


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Txn ID", "txn_id"),
        ("TXN DATE", "txn_date"),
        ("Budget (₹)", "budget"),
        ("accountId", "account_id"),
        ("2024 Sales", "col_2024_sales"),
        ("", "col"),
        ("order", "order_"),
        ("Café Name", "cafe_name"),
        ("a--b__c", "a_b_c"),
    ],
)
def test_to_identifier(raw: str, expected: str) -> None:
    assert to_identifier(raw) == expected


def test_dedupe() -> None:
    assert dedupe(["a", "a", "b", "a", "a_2"]) == ["a", "a_2", "b", "a_3", "a_2_2"]


@pytest.mark.parametrize("v", ["", "  ", "N/A", "na", "NULL", "-", "None", "#N/A"])
def test_null_tokens(v: str) -> None:
    assert normalise_cell(v) is None


def test_normalise_strips() -> None:
    assert normalise_cell("  Success ") == "Success"


def test_clean_table_drops_blank_and_repeated_header_rows() -> None:
    raw = RawTable(
        "My File",
        [" Name ", "Amount", ""],
        [
            ["a", "1", ""],
            ["", "", ""],
            ["Name", "Amount", ""],
            ["b", "2"],  # short row is padded
            ["  ", " N/A "],
        ],
    )
    t = clean_table(raw)
    assert t.name == "my_file"
    assert t.columns == ["name", "amount"]  # trailing empty header column trimmed
    assert t.original_columns == ["Name", "Amount"]
    assert t.rows == [["a", "1"], ["b", "2"]]
    assert t.dropped_blank == 2
    assert t.dropped_header_repeats == 1


def test_clean_table_keeps_unnamed_column_with_data() -> None:
    t = clean_table(RawTable("t", ["a", ""], [["1", "x"]]))
    assert t.columns == ["a", "column_2"]

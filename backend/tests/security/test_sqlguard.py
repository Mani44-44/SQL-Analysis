"""Table-driven safety suite for the SQL validator (spec section 9.4).

Every attack category has explicit cases; each must be rejected with the expected error code.
Legitimate analytics queries must pass, so the guard is not trivially "reject everything".
"""

from __future__ import annotations

import pytest

from app.services.sqlguard import AllowedSchema, SqlGuardError, apply_row_cap, validate_sql
from tests.security.conftest import STATIC_SCHEMA

# --------------------------------------------------------------------------------------- allowed

ALLOWED = [
    "SELECT * FROM transactions",
    "select count(*) from transactions where status = 'Success'",
    "FROM transactions SELECT txn_id LIMIT 5",
    "SELECT strftime(txn_date, '%Y-%m') AS month, sum(amount) AS spend FROM transactions "
    "WHERE type = 'Debit' GROUP BY 1 ORDER BY 1",
    "SELECT date_trunc('month', t.txn_date) AS m, c.category_name, sum(t.amount) "
    "FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
    "JOIN categories c ON c.category_id = m.category_id GROUP BY ALL",
    "WITH monthly AS (SELECT date_trunc('month', txn_date) AS m, sum(amount) AS s "
    "FROM transactions GROUP BY 1) SELECT m, s, s - lag(s) OVER (ORDER BY m) AS delta FROM monthly",
    "SELECT merchant_id, amount FROM transactions QUALIFY row_number() OVER "
    "(PARTITION BY merchant_id ORDER BY amount DESC) = 1",
    "SELECT * EXCLUDE (notes) FROM transactions",
    "SELECT account_id, count(*) FILTER (WHERE status = 'Failed') AS failed FROM transactions "
    "GROUP BY account_id HAVING failed > 0",
    "SELECT a.account_name FROM accounts a WHERE EXISTS "
    "(SELECT 1 FROM transactions t WHERE t.account_id = a.account_id)",
    "SELECT category_id FROM categories UNION SELECT category_id FROM budgets",
    "SELECT * FROM transactions, accounts WHERE transactions.account_id = accounts.account_id",
    "SELECT * FROM main.transactions",
    "SELECT txn_date - INTERVAL 7 DAY, extract(year FROM txn_date), coalesce(notes, '-') "
    "FROM transactions",
    "SELECT median(amount), quantile_cont(amount, 0.9), stddev(amount) FROM transactions",
    "SELECT CASE WHEN amount > 1000 THEN 'big' ELSE 'small' END AS size, count(*) "
    "FROM transactions GROUP BY 1",
    "SELECT * FROM (SELECT account_id, sum(amount) AS total FROM transactions GROUP BY 1) x "
    "WHERE x.total > 100",
    "SELECT list_transform([1, 2, 3], x -> x * 2) AS doubled",
    "SELECT 1",
    "SELECT budget, month FROM budgets WHERE month >= DATE '2025-06-01'",
    "SELECT lower(description) LIKE '%swiggy%' AS is_swiggy FROM transactions",
    "SELECT date_diff('day', min(txn_date), max(txn_date)) FROM transactions",
    "SELECT * FROM transactions ORDER BY amount DESC LIMIT 10 OFFSET 5",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed_queries_pass(sql: str) -> None:
    v = validate_sql(sql, STATIC_SCHEMA)
    assert v.sql


# --------------------------------------------------------------------------------------- blocked

BLOCKED: list[tuple[str, str, str]] = [
    # category, sql, expected code
    # destructive / DDL / DML
    ("destructive", "DROP TABLE transactions", "not_select"),
    ("destructive", "DELETE FROM transactions", "not_select"),
    ("destructive", "UPDATE transactions SET amount = 0", "not_select"),
    ("destructive", "INSERT INTO transactions SELECT * FROM transactions", "not_select"),
    ("destructive", "CREATE TABLE x AS SELECT * FROM transactions", "not_select"),
    ("destructive", "ALTER TABLE transactions ADD COLUMN x INT", "not_select"),
    ("destructive", "TRUNCATE transactions", "not_select"),
    ("destructive", "CREATE MACRO m(x) AS x", "not_select"),
    ("destructive", "SELECT * INTO newtable FROM transactions", "forbidden_statement"),
    # multi-statement injection
    ("multi", "SELECT 1; DROP TABLE transactions", "multiple_statements"),
    ("multi", "SELECT 1;SELECT 2", "multiple_statements"),
    (
        "multi",
        "SELECT * FROM transactions WHERE txn_id = 'x'; DELETE FROM accounts; --'",
        "multiple_statements",
    ),
    # settings / extensions / attach
    ("settings", "SET threads = 64", "not_select"),
    ("settings", "RESET memory_limit", "not_select"),
    ("settings", "PRAGMA database_list", "not_select"),
    ("settings", "SELECT current_setting('memory_limit')", "forbidden_function"),
    ("extensions", "INSTALL httpfs", "not_select"),
    ("extensions", "LOAD httpfs", "not_select"),
    ("attach", "ATTACH 'other.duckdb' AS other", "not_select"),
    ("attach", "DETACH other", "not_select"),
    ("attach", "USE other", "not_select"),
    ("export", "COPY transactions TO 'out.csv'", "not_select"),
    ("export", "EXPORT DATABASE 'dump'", "parse_error"),
    ("call", "CALL pragma_version()", "not_select"),
    # file / table functions
    ("files", "SELECT * FROM read_csv('/etc/passwd')", "table_function"),
    ("files", "SELECT * FROM read_csv_auto('C:/Windows/win.ini')", "table_function"),
    ("files", "SELECT * FROM read_parquet('s3://bucket/x.parquet')", "table_function"),
    ("files", "SELECT * FROM read_json('x.json')", "table_function"),
    ("files", "SELECT * FROM glob('*')", "table_function"),
    ("files", "SELECT * FROM 'data/workspaces/other.duckdb'", "unknown_table"),
    ("files", "SELECT read_text('/etc/passwd')", "forbidden_function"),
    ("files", "SELECT * FROM sniff_csv('x.csv')", "table_function"),
    ("files", "SELECT * FROM query('SELECT 1')", "table_function"),
    ("files", "SELECT getenv('ANTHROPIC_API_KEY')", "forbidden_function"),
    ("files", "SELECT (SELECT content FROM read_text('x'))", "table_function"),
    # system catalogs / cross-workspace
    ("system", "SELECT * FROM information_schema.tables", "system_table"),
    ("system", "SELECT * FROM duckdb_settings()", "table_function"),
    ("system", "SELECT * FROM duckdb_tables()", "table_function"),
    ("system", "SELECT * FROM pg_catalog.pg_tables", "system_table"),
    ("system", "SELECT * FROM sqlite_master", "unknown_table"),
    ("system", "SELECT * FROM other_ws.main.transactions", "system_table"),
    ("system", "SELECT * FROM temp.main.x", "system_table"),
    ("system", "SELECT version()", "forbidden_function"),
    ("cross_workspace", "SELECT * FROM salaries", "unknown_table"),
    (
        "cross_workspace",
        "SELECT * FROM transactions t JOIN secret_table s ON true",
        "unknown_table",
    ),
    # CTE scoping: a CTE named like a system view must not leak outside its scope
    (
        "cte_scope",
        "SELECT * FROM (WITH pg_tables AS (SELECT 1) SELECT 1) x, pg_tables",
        "unknown_table",
    ),
    # expensive queries
    (
        "expensive",
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT * FROM r",
        "recursive_cte",
    ),
    ("expensive", "SELECT * FROM range(1000000000000)", "table_function"),
    ("expensive", "SELECT * FROM generate_series(1, 1000000000)", "table_function"),
    ("expensive", "SELECT generate_series(1, 100000000)", "forbidden_function"),
    # misc functions
    ("functions", "SELECT nextval('seq')", "forbidden_function"),
    ("functions", "SELECT error('boom')", "forbidden_function"),
    ("functions", "SELECT pg_sleep(100)", "forbidden_function"),
    ("functions", "SELECT current_database()", "forbidden_function"),
    # obfuscation / comments / encoding tricks
    ("obfuscation", "SELECT 1 /* ; */ ; DROP TABLE transactions", "multiple_statements"),
    ("obfuscation", "sElEcT * FrOm ReAd_CsV('/etc/passwd')", "table_function"),
    ("obfuscation", "SELECT * FROM \"read_csv\"('/etc/passwd')", "table_function"),
    ("obfuscation", "(DROP TABLE transactions)", "parse_error"),
    ("obfuscation", "SELECT 1\x00; DROP TABLE x", "parse_error"),
    ("obfuscation", "", "empty"),
    ("obfuscation", "   -- just a comment", "empty"),
    ("obfuscation", "SELECT ?", "parameter"),
    ("obfuscation", "SELECT $1", "parameter"),
    # hallucinated columns (not a security issue, but a guard behaviour the pipeline relies on)
    ("columns", "SELECT category FROM transactions", "unknown_column"),
    ("columns", "SELECT t.amount FROM transactions x", "unknown_column"),
    ("columns", 'SELECT "Success" FROM transactions', "unknown_column"),
]


@pytest.mark.parametrize(
    ("category", "sql", "code"), BLOCKED, ids=[f"{c}:{s[:40]}" for c, s, _ in BLOCKED]
)
def test_blocked_queries(category: str, sql: str, code: str) -> None:
    with pytest.raises(SqlGuardError) as info:
        validate_sql(sql, STATIC_SCHEMA)
    assert info.value.code == code, f"[{category}] {sql!r}: {info.value.code} {info.value.message}"


def test_every_attack_category_is_covered() -> None:
    categories = {c for c, _, _ in BLOCKED}
    required = {
        "destructive", "multi", "settings", "extensions", "attach", "export", "files", "system",
        "cross_workspace", "cte_scope", "expensive", "obfuscation",
    }  # fmt: skip
    assert required <= categories


def test_too_long() -> None:
    with pytest.raises(SqlGuardError) as e:
        validate_sql("SELECT " + " + ".join(["1"] * 10_000), STATIC_SCHEMA)
    assert e.value.code in {"too_long", "too_complex"}


def test_cross_join_guard() -> None:
    big = AllowedSchema.from_columns({"a": (100_000, ["x"]), "b": (100_000, ["y"])})
    with pytest.raises(SqlGuardError) as e:
        validate_sql("SELECT * FROM a, b", big)
    assert e.value.code == "cross_join"
    with pytest.raises(SqlGuardError):
        validate_sql("SELECT * FROM a CROSS JOIN b", big)
    # explicit join predicates are fine
    validate_sql("SELECT * FROM a JOIN b ON a.x = b.y", big)
    validate_sql("SELECT * FROM a, b WHERE a.x = b.y", big)
    # small cross joins are fine
    validate_sql("SELECT * FROM accounts CROSS JOIN categories", STATIC_SCHEMA)


def test_unknown_column_message_lists_columns() -> None:
    with pytest.raises(SqlGuardError) as e:
        validate_sql("SELECT a.bogus FROM accounts a", STATIC_SCHEMA)
    assert e.value.code == "unknown_column"
    with pytest.raises(SqlGuardError) as e2:
        validate_sql("SELECT accounts.bogus FROM accounts", STATIC_SCHEMA)
    assert "account_name" in e2.value.message


def test_regenerated_sql_is_executed_form() -> None:
    v = validate_sql("select 1 -- trailing comment ; drop table x", STATIC_SCHEMA)
    assert "drop" not in v.sql.lower()


@pytest.mark.parametrize(
    ("sql", "expected_fragment"),
    [
        ("SELECT * FROM transactions", "LIMIT 11"),
        ("SELECT * FROM transactions LIMIT 5", "LIMIT 5"),
        ("SELECT * FROM transactions LIMIT 500", "LIMIT 11"),
        ("SELECT 1 UNION SELECT 2", "_askdata_q LIMIT 11"),
    ],
)
def test_row_cap(sql: str, expected_fragment: str) -> None:
    out = apply_row_cap(validate_sql(sql, STATIC_SCHEMA), 10)
    assert expected_fragment in out
    assert out.count("LIMIT") == 1

"""Property-based fuzzing of the SQL validator.

Invariants for ANY input:
1. validate_sql either returns a ValidatedQuery or raises SqlGuardError, never anything else;
2. anything accepted is a single SELECT/set-operation whose tables are all allowed and which
   contains no forbidden statement nodes or non-allowlisted functions;
3. re-validating the regenerated SQL is accepted again (stable round trip).
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlglot import exp

from app.services.sqlguard import SqlGuardError, validate_sql
from app.services.sqlguard.functions import ALLOWED_ANONYMOUS, ALLOWED_FUNC_CLASSES
from app.services.sqlguard.validator import _FORBIDDEN_NODES, _ROOT_TYPES, _unwrap
from tests.security.conftest import STATIC_SCHEMA

SAFE = [
    "SELECT * FROM transactions",
    "SELECT sum(amount) FROM transactions WHERE type = 'Debit'",
    "SELECT a.account_name, count(*) FROM accounts a JOIN transactions t "
    "ON a.account_id = t.account_id GROUP BY 1",
    "WITH x AS (SELECT * FROM budgets) SELECT * FROM x",
]
DANGEROUS = [
    "; DROP TABLE transactions",
    "; DELETE FROM accounts",
    " UNION SELECT * FROM read_csv('/etc/passwd')",
    " UNION SELECT * FROM information_schema.tables",
    "; ATTACH 'x.db' AS x",
    "; COPY transactions TO 'x.csv'",
    "; SET threads=99",
    "; INSTALL httpfs; LOAD httpfs",
    " WHERE 1=1; CREATE TABLE z AS SELECT 1",
    " UNION SELECT getenv('HOME')",
    "; PRAGMA database_list",
    " UNION ALL SELECT * FROM duckdb_settings()",
    "' OR '1'='1",
    "/*",
    "*/ DROP TABLE x",
    "--",
    "\n; DROP TABLE x",
    " UNION SELECT * FROM glob('*')",
    "; CALL pragma_version()",
    "; EXPORT DATABASE 'x'",
]
TOKENS = SAFE + DANGEROUS + [
    "SELECT", "FROM", "WHERE", "(", ")", ",", "'", '"', ";", "*", "UNION", "WITH", "AS",
    "read_csv", "range(10)", "transactions", "accounts", "secret", "1", "INTO", "x",
]  # fmt: skip


def _assert_invariants(sql: str) -> None:
    try:
        v = validate_sql(sql, STATIC_SCHEMA)
    except SqlGuardError:
        return
    tree = v.tree
    assert tree is not None
    assert isinstance(_unwrap(tree), _ROOT_TYPES), sql
    for node in tree.walk():
        assert not isinstance(node, _FORBIDDEN_NODES), sql
        if isinstance(node, exp.Table):
            assert isinstance(node.this, exp.Identifier), sql
            assert not node.catalog, sql
        if isinstance(node, exp.Anonymous):
            assert node.name.lower() in ALLOWED_ANONYMOUS, sql
        elif isinstance(node, exp.Func):
            assert type(node).__name__ in ALLOWED_FUNC_CLASSES, sql
    for t in v.tables:
        assert t in STATIC_SCHEMA.tables
    validate_sql(v.sql, STATIC_SCHEMA)  # round trip stays valid


fuzz_settings = settings(
    max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


@fuzz_settings
@given(st.text(max_size=300))
def test_random_text(sql: str) -> None:
    _assert_invariants(sql)


@fuzz_settings
@given(st.lists(st.sampled_from(TOKENS), min_size=1, max_size=12))
def test_token_soup(tokens: list[str]) -> None:
    _assert_invariants(" ".join(tokens))


@fuzz_settings
@given(st.sampled_from(SAFE), st.sampled_from(DANGEROUS), st.integers(min_value=0, max_value=200))
def test_injection_into_safe_queries(base: str, payload: str, pos: int) -> None:
    pos = min(pos, len(base))
    _assert_invariants(base[:pos] + payload + base[pos:])
    _assert_invariants(base + payload)


@fuzz_settings
@given(st.sampled_from(DANGEROUS))
def test_appended_statements_never_accepted_as_multi(payload: str) -> None:
    sql = "SELECT 1" + payload
    try:
        v = validate_sql(sql, STATIC_SCHEMA)
    except SqlGuardError:
        return
    # Accepted only when the payload was neutralised (e.g. inside a comment or string).
    assert v.sql.upper().startswith(("SELECT", "WITH", "("))
    assert ";" not in v.sql

"""Allowlist-based SQL validator for DuckDB queries against a workspace.

The validator parses with sqlglot (dialect=duckdb) and accepts exactly one read-only query whose
tables are workspace tables (or CTEs in scope) and whose functions are on the allowlist. The SQL
that is executed is regenerated from the validated AST, so what runs is what was checked.

Defence in depth: the executor additionally runs every query on a read-only, external-access-
disabled, configuration-locked DuckDB connection (see app.services.execution.executor).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from app.services.sqlguard.functions import ALLOWED_ANONYMOUS, ALLOWED_FUNC_CLASSES

MAX_SQL_CHARS = 20_000
MAX_AST_NODES = 5_000

# Statement / clause node types that must never appear anywhere in the tree.
_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable", "TruncateTable",
    "Command", "Copy", "Pragma", "Set", "Attach", "Detach", "Install", "Use", "Transaction",
    "Commit", "Rollback", "Into", "LoadData", "Describe", "Summarize", "Grant", "Revoke",
    "Analyze", "Export", "Refresh", "Cache", "Uncache", "Kill", "Show",
)  # fmt: skip
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    t for name in _FORBIDDEN_NODE_NAMES if isinstance(t := getattr(exp, name, None), type)
)

_ROOT_TYPES: tuple[type[exp.Expression], ...] = (exp.Select, exp.Union, exp.Intersect, exp.Except)

# Schemas a bare table reference may be qualified with.
_ALLOWED_QUALIFIERS = {"main"}


class SqlGuardError(Exception):
    """Validation failure with a stable machine-readable code and a user-facing message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover
        return f"SqlGuardError({self.code!r}, {self.message!r})"


@dataclass(frozen=True)
class TableInfo:
    row_count: int
    columns: frozenset[str]


@dataclass(frozen=True)
class AllowedSchema:
    """The tables a query may read: lower-case name -> TableInfo."""

    tables: Mapping[str, TableInfo]

    @classmethod
    def from_columns(cls, tables: Mapping[str, tuple[int, list[str]]]) -> AllowedSchema:
        return cls(
            {
                name.lower(): TableInfo(rows, frozenset(c.lower() for c in cols))
                for name, (rows, cols) in tables.items()
            }
        )


@dataclass
class ValidatedQuery:
    sql: str  # normalised SQL regenerated from the validated AST
    tables: list[str] = field(default_factory=list)
    tree: exp.Expr | None = field(default=None, repr=False)


def _parse(sql: str) -> exp.Expr:
    if not sql or not sql.strip():
        raise SqlGuardError("empty", "The query is empty.")
    if len(sql) > MAX_SQL_CHARS:
        raise SqlGuardError("too_long", f"The query is longer than {MAX_SQL_CHARS:,} characters.")
    if "\x00" in sql:
        raise SqlGuardError("parse_error", "The query contains a NUL byte.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except (ParseError, TokenError) as e:
        raise SqlGuardError("parse_error", f"Could not parse the SQL: {_first_line(e)}") from e
    except Exception as e:  # sqlglot can raise other errors on adversarial input
        raise SqlGuardError("parse_error", "Could not parse the SQL.") from e
    if not statements:
        raise SqlGuardError("empty", "The query is empty.")
    if len(statements) != 1:
        raise SqlGuardError(
            "multiple_statements", "Only a single SELECT statement is allowed per query."
        )
    return statements[0]


def _first_line(e: Exception) -> str:
    return str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__


def _unwrap(node: exp.Expr) -> exp.Expr:
    while isinstance(node, exp.Subquery | exp.Paren) and node.this is not None:
        if isinstance(node, exp.Subquery) and (node.args.get("limit") or node.args.get("order")):
            break
        node = node.this
    return node


def _cte_in_scope(table: exp.Table, name: str) -> bool:
    node: exp.Expr | None = table.parent
    while node is not None:
        with_ = node.args.get("with_") or node.args.get("with")
        if isinstance(with_, exp.With) and any(
            cte.alias_or_name.lower() == name for cte in with_.expressions
        ):
            return True
        node = node.parent
    return False


def _check_functions(tree: exp.Expr) -> None:
    for fn in tree.find_all(exp.Func):
        if isinstance(fn, exp.Anonymous):
            fname = fn.name.lower()
            if fname not in ALLOWED_ANONYMOUS:
                raise SqlGuardError(
                    "forbidden_function", f"The function '{fn.name}' is not allowed."
                )
        elif type(fn).__name__ not in ALLOWED_FUNC_CLASSES:
            raise SqlGuardError(
                "forbidden_function",
                f"The function '{fn.sql_name().lower()}' is not allowed.",
            )


def _check_tables(tree: exp.Expr, schema: AllowedSchema) -> list[str]:
    used: list[str] = []
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SqlGuardError(
                "table_function",
                "Table functions (e.g. read_csv, range, glob) are not allowed; "
                "query workspace tables only.",
            )
        name = table.name.lower()
        catalog = table.catalog.lower() if table.catalog else ""
        db = table.db.lower() if table.db else ""
        if catalog or (db and db not in _ALLOWED_QUALIFIERS):
            raise SqlGuardError(
                "system_table", f"Access to '{table.sql(dialect='duckdb')}' is not allowed."
            )
        if not db and _cte_in_scope(table, name):
            continue
        if name not in schema.tables:
            raise SqlGuardError(
                "unknown_table",
                f"Table '{table.name}' does not exist. Available tables: "
                + ", ".join(sorted(schema.tables)),
            )
        if name not in used:
            used.append(name)
    return used


def _known_names(tree: exp.Expr, schema: AllowedSchema, used: list[str]) -> set[str]:
    names: set[str] = set()
    for t in used:
        names |= schema.tables[t].columns
        names.add(t)
    for alias in tree.find_all(exp.Alias):
        names.add(alias.alias.lower())
    for ta in tree.find_all(exp.TableAlias):
        if ta.name:
            names.add(ta.name.lower())
        for col in ta.columns:
            names.add(col.name.lower())
    for cte in tree.find_all(exp.CTE):
        names.add(cte.alias_or_name.lower())
        body = cte.this
        if isinstance(body, exp.Query):
            names |= {n.lower() for n in body.named_selects}
    for lam in tree.find_all(exp.Lambda):
        for p in lam.expressions:
            names.add(p.name.lower())
    for sub in tree.find_all(exp.Subquery):
        body = sub.this
        if isinstance(body, exp.Query):
            names |= {n.lower() for n in body.named_selects}
    return names


def _table_refs(tree: exp.Expr, used: list[str]) -> set[str]:
    refs = set(used)
    for t in tree.find_all(exp.Table):
        refs.add(t.name.lower())
        if t.alias:
            refs.add(t.alias.lower())
    for cte in tree.find_all(exp.CTE):
        refs.add(cte.alias_or_name.lower())
    for sub in tree.find_all(exp.Subquery):
        if sub.alias:
            refs.add(sub.alias.lower())
    for ta in tree.find_all(exp.TableAlias):
        if ta.name:
            refs.add(ta.name.lower())
    return refs


def _check_columns(tree: exp.Expr, schema: AllowedSchema, used: list[str]) -> None:
    known = _known_names(tree, schema, used)
    refs = _table_refs(tree, used)
    for col in tree.find_all(exp.Column):
        if isinstance(col.this, exp.Star):
            continue
        qualifier = col.table.lower() if col.table else ""
        if qualifier and qualifier not in refs:
            raise SqlGuardError(
                "unknown_column", f"'{col.sql(dialect='duckdb')}' refers to an unknown table alias."
            )
        name = col.name.lower()
        if name and name not in known:
            hint = ""
            if qualifier and qualifier in schema.tables:
                hint = f" Columns of {qualifier}: " + ", ".join(
                    sorted(schema.tables[qualifier].columns)
                )
            raise SqlGuardError("unknown_column", f"Column '{col.name}' does not exist.{hint}")


def _row_count(node: exp.Expr, schema: AllowedSchema) -> int:
    if isinstance(node, exp.Table) and node.name.lower() in schema.tables:
        return max(1, schema.tables[node.name.lower()].row_count)
    return 1


def _check_cross_joins(tree: exp.Expr, schema: AllowedSchema, max_rows: int) -> None:
    for select in tree.find_all(exp.Select):
        joins = select.args.get("joins") or []
        from_ = select.args.get("from_") or select.args.get("from")
        if not joins or from_ is None:
            continue
        unconditioned = [
            j
            for j in joins
            if not j.args.get("on")
            and not j.args.get("using")
            and (j.kind or "").upper() not in ("SEMI", "ANTI")
            and (j.side or j.kind or "CROSS").upper() in ("CROSS", "")
        ]
        if not unconditioned:
            continue
        product = _row_count(from_.this, schema)
        for j in unconditioned:
            product *= _row_count(j.this, schema)
        if product <= max_rows:
            continue
        where = select.args.get("where")
        has_join_predicate = where is not None and any(
            isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Column)
            for eq in where.find_all(exp.EQ)
        )
        if not has_join_predicate:
            raise SqlGuardError(
                "cross_join",
                f"This join has no join condition and would produce about {product:,} rows. "
                "Add an ON clause.",
            )


def validate_sql(
    sql: str, schema: AllowedSchema, *, max_cross_product_rows: int = 10_000_000
) -> ValidatedQuery:
    """Validate `sql`; return the normalised query or raise SqlGuardError."""
    tree = _parse(sql)

    if sum(1 for _ in tree.walk()) > MAX_AST_NODES:
        raise SqlGuardError("too_complex", "The query is too complex.")

    root = _unwrap(tree)
    if not isinstance(root, _ROOT_TYPES):
        kind = type(root).__name__.upper()
        raise SqlGuardError(
            "not_select", f"Only SELECT queries are allowed (got {kind}). Data cannot be modified."
        )

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlGuardError(
                "forbidden_statement",
                f"{type(node).__name__.upper()} is not allowed; only read-only SELECT queries run.",
            )
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise SqlGuardError("recursive_cte", "Recursive CTEs are not allowed.")
        if isinstance(node, exp.Placeholder | exp.Parameter):
            raise SqlGuardError("parameter", "Query parameters are not supported.")

    used = _check_tables(tree, schema)
    _check_functions(tree)
    _check_columns(tree, schema, used)
    _check_cross_joins(tree, schema, max_cross_product_rows)

    return ValidatedQuery(sql=tree.sql(dialect="duckdb", comments=False), tables=used, tree=tree)


def apply_row_cap(query: ValidatedQuery, cap: int) -> str:
    """Return SQL that yields at most cap+1 rows (the extra row signals truncation)."""
    assert query.tree is not None
    limit = cap + 1
    tree = query.tree.copy()
    if isinstance(tree, exp.Select) and not tree.args.get("fetch"):
        existing = tree.args.get("limit")
        if existing is None:
            return tree.limit(limit).sql(dialect="duckdb", comments=False)
        value = existing.expression
        if isinstance(value, exp.Literal) and value.is_int:
            if int(value.this) <= limit:
                return tree.sql(dialect="duckdb", comments=False)
            return tree.limit(limit).sql(dialect="duckdb", comments=False)
    return (
        f"SELECT * FROM ({tree.sql(dialect='duckdb', comments=False)}) AS _askdata_q LIMIT {limit}"  # noqa: S608
    )

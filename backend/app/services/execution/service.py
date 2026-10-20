"""Validate-then-execute entry point used by the pipeline and the manual SQL endpoint."""

from __future__ import annotations

from app.core.config import get_settings
from app.services.execution.executor import ExecutionResult, execute_sql
from app.services.sqlguard import AllowedSchema, apply_row_cap, validate_sql


def run_query(
    workspace_id: str,
    sql: str,
    schema: AllowedSchema,
    *,
    row_cap: int | None = None,
) -> ExecutionResult:
    """Validate `sql` against `schema`, cap rows and execute in the sandbox.

    Raises SqlGuardError (validation) or ExecutionError (runtime).
    """
    settings = get_settings()
    cap = row_cap if row_cap is not None else settings.query_row_cap
    validated = validate_sql(sql, schema, max_cross_product_rows=settings.max_cross_product_rows)
    capped = apply_row_cap(validated, cap)
    result = execute_sql(
        workspace_id,
        capped,
        row_cap=cap,
        timeout_s=settings.query_timeout_s,
        memory_limit=settings.duckdb_memory_limit,
        threads=settings.duckdb_threads,
    )
    result.sql = validated.sql
    return result

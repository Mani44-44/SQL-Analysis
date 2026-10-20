"""Sandboxed, read-only query execution against a workspace DuckDB file.

Runtime protections (independent of the SQL validator):
- the database file is opened with read_only=True;
- external access (files, HTTP, ATTACH of other files), extension install/autoload, community
  extensions and Python replacement scans are disabled;
- memory and thread limits are set and the configuration is locked, so SET/RESET fail;
- a watchdog timer interrupts queries that exceed the timeout;
- at most row_cap + 1 rows are fetched.
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import hashlib
import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import duckdb

from app.services.storage import workspace_db_path, workspace_lock

audit = logging.getLogger("askdata.audit")


class ExecutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ExecutionResult:
    columns: list[str]
    column_types: list[str]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int
    sql: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)


def sandbox_config(memory_limit: str, threads: int) -> dict[str, Any]:
    return {
        "enable_external_access": False,
        "autoload_known_extensions": False,
        "autoinstall_known_extensions": False,
        "allow_community_extensions": False,
        "allow_unsigned_extensions": False,
        "python_enable_replacements": False,
        "memory_limit": memory_limit,
        "threads": threads,
        "lock_configuration": True,
    }


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, decimal.Decimal):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode()
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return str(value)


def execute_sql(
    workspace_id: str,
    sql: str,
    *,
    row_cap: int,
    timeout_s: float,
    memory_limit: str = "512MB",
    threads: int = 2,
) -> ExecutionResult:
    """Execute already-validated (and row-capped) SQL. Never call with unvalidated input."""
    path = workspace_db_path(workspace_id)
    sql_hash = hashlib.sha256(sql.encode()).hexdigest()[:16]
    if not path.exists():
        raise ExecutionError("no_data", "This workspace has no data yet. Upload a file first.")

    start = time.perf_counter()
    status = "ok"
    rows_out = 0
    try:
        with workspace_lock(workspace_id).read():
            try:
                con = duckdb.connect(
                    str(path), read_only=True, config=sandbox_config(memory_limit, threads)
                )
            except duckdb.Error as e:
                status = "connect_error"
                raise ExecutionError("connect_error", "Could not open workspace data.") from e
            timer = threading.Timer(timeout_s, con.interrupt)
            timer.daemon = True
            timer.start()
            try:
                cur = con.execute(sql)
                description = cur.description or []
                raw_rows = cur.fetchmany(row_cap + 1)
            except duckdb.InterruptException as e:
                status = "timeout"
                raise ExecutionError(
                    "timeout", f"The query took longer than {timeout_s:g}s and was stopped."
                ) from e
            except duckdb.OutOfMemoryException as e:
                status = "memory"
                raise ExecutionError(
                    "memory", "The query needed too much memory. Try aggregating or filtering."
                ) from e
            except duckdb.Error as e:
                status = "sql_error"
                msg = str(e).strip().split("\n")[0][:500]
                raise ExecutionError("sql_error", msg) from e
            finally:
                timer.cancel()
                con.close()
    finally:
        audit.info(
            "query_executed",
            extra={
                "workspace_id": workspace_id,
                "sql_hash": sql_hash,
                "status": status,
                "duration_ms": int((time.perf_counter() - start) * 1000),
            },
        )

    truncated = len(raw_rows) > row_cap
    rows = [[to_jsonable(v) for v in r] for r in raw_rows[:row_cap]]
    rows_out = len(rows)
    duration_ms = int((time.perf_counter() - start) * 1000)
    columns = [str(d[0]) for d in description]
    types = [str(d[1]) for d in description]
    audit.info(
        "query_result",
        extra={"workspace_id": workspace_id, "sql_hash": sql_hash, "rows": rows_out},
    )
    return ExecutionResult(
        columns=columns,
        column_types=types,
        rows=rows,
        truncated=truncated,
        duration_ms=duration_ms,
        sql=sql,
    )

"""Per-workspace storage paths and DuckDB access locks.

Workspace DuckDB files live at `<data_dir>/workspaces/<workspace_id>.duckdb`. Paths are derived
only from server-generated hex IDs, never from user input.

DuckDB refuses to open the same file twice in one process with different configurations, so
readers (sandboxed executor) and the writer (ingestion) are coordinated with a per-workspace
readers-writer lock.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.config import get_settings

_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _check_id(value: str) -> str:
    if not _ID_RE.match(value):
        raise ValueError("invalid id")
    return value


def workspace_db_path(workspace_id: str) -> Path:
    return get_settings().workspaces_dir / f"{_check_id(workspace_id)}.duckdb"


def source_upload_dir(workspace_id: str, source_id: str) -> Path:
    return get_settings().uploads_dir / _check_id(workspace_id) / _check_id(source_id)


class RWLock:
    """Writer-preferring readers-writer lock."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @contextmanager
    def read(self) -> Iterator[None]:
        with self._cond:
            while self._writer or self._waiting_writers:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                self._cond.notify_all()

    @contextmanager
    def write(self) -> Iterator[None]:
        with self._cond:
            self._waiting_writers += 1
            while self._writer or self._readers:
                self._cond.wait()
            self._waiting_writers -= 1
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()


_locks: dict[str, RWLock] = {}
_locks_guard = threading.Lock()


def workspace_lock(workspace_id: str) -> RWLock:
    with _locks_guard:
        lock = _locks.get(workspace_id)
        if lock is None:
            lock = _locks[workspace_id] = RWLock()
        return lock

"""Shared fixtures: every test gets an isolated data dir, app DB and mock LLM provider."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("LOG_JSON", "false")
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import session as db_session
from app.db.models import Base
from app.services import llm
from app.services.llm import MockProvider


def _clear_caches() -> None:
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'app.sqlite').as_posix()}")
    _clear_caches()
    settings = get_settings()
    settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(db_session.get_engine())
    yield tmp_path
    db_session.get_engine().dispose()
    llm.set_provider(None)
    _clear_caches()


@pytest.fixture
def mock_llm() -> MockProvider:
    provider = MockProvider()
    llm.set_provider(provider)
    return provider


@pytest.fixture
def db() -> Iterator[Session]:
    s = db_session.get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c

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


@pytest.fixture
def demo_ws(db: Session) -> str:
    """Seeded demo workspace id (ingested from the deterministic generator)."""
    from app.demo.seed import seed_demo

    return seed_demo(db).id


def signup(
    c: TestClient, email: str = "owner@example.com", password: str = "correct-horse-1"
) -> str:
    """Register (or log in) on this client; the session cookie is kept by the client."""
    r = c.post("/api/v1/auth/register", json={"email": email, "password": password})
    if r.status_code == 409:
        r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code in (200, 201), r.text
    return str(r.json()["id"])


@pytest.fixture
def user_client(client: TestClient) -> TestClient:
    signup(client)
    return client


@pytest.fixture(autouse=True)
def _reset_limits() -> Iterator[None]:
    from app.core.limits import cost_tracker, rate_limiter

    rate_limiter().reset()
    cost_tracker().reset()
    yield

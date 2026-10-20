from __future__ import annotations

import pytest

from app.core.config import Settings


def test_defaults_are_safe() -> None:
    s = Settings(_env_file=None)
    assert s.query_row_cap > 0
    assert s.query_timeout_s > 0
    assert s.max_correction_attempts >= 1
    assert s.llm_model_strong == "claude-opus-5-5"


def test_mock_llm_selected_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert Settings(_env_file=None, llm_provider="auto").use_mock_llm is True
    assert (
        Settings(_env_file=None, llm_provider="auto", anthropic_api_key="k").use_mock_llm is False
    )
    assert Settings(_env_file=None, llm_provider="mock", anthropic_api_key="k").use_mock_llm is True
    assert Settings(_env_file=None, llm_provider="anthropic").use_mock_llm is False


def test_empty_env_values_are_safe() -> None:
    s = Settings(_env_file=None, jwt_secret="", anthropic_api_key="  ")
    assert len(s.jwt_secret.get_secret_value()) >= 32
    assert s.anthropic_api_key is None and s.use_mock_llm


def test_secret_not_in_repr() -> None:
    s = Settings(_env_file=None, anthropic_api_key="sk-secret-value")
    assert "sk-secret-value" not in repr(s)

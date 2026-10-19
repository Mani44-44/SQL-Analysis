"""LLM provider package. Use `get_provider()` to obtain the configured provider."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.services.llm.base import (
    ChatMessage,
    LLMError,
    LLMOutputError,
    LLMProvider,
    LLMRefusalError,
    LLMResult,
    LLMUnavailableError,
    Tier,
    Usage,
)
from app.services.llm.mock import MockCall, MockProvider

__all__ = [
    "ChatMessage",
    "LLMError",
    "LLMOutputError",
    "LLMProvider",
    "LLMRefusalError",
    "LLMResult",
    "LLMUnavailableError",
    "MockCall",
    "MockProvider",
    "Tier",
    "Usage",
    "build_provider",
    "get_provider",
    "set_provider",
]

_provider: LLMProvider | None = None


def build_provider(settings: Settings) -> LLMProvider:
    if settings.use_mock_llm:
        from app.services.llm.mock_fixtures import build_default_mock

        return build_default_mock()
    from app.services.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider(settings)


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = build_provider(get_settings())
    return _provider


def set_provider(provider: LLMProvider | None) -> None:
    """Override the process-wide provider (tests, eval runner)."""
    global _provider
    _provider = provider

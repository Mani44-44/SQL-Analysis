"""Provider-agnostic LLM interface.

Every LLM call in the app goes through `LLMProvider.complete_json`, which returns a validated
Pydantic object plus usage/cost. Providers: `AnthropicProvider` (real) and `MockProvider`
(deterministic, used by default in tests and CI).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Literal, Protocol, TypedDict, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Tier(StrEnum):
    STRONG = "strong"
    FAST = "fast"


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


@dataclass
class Usage:
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            model=other.model or self.model,
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass
class LLMResult(Generic[T]):
    output: T
    usage: Usage
    latency_ms: int = 0
    extra: dict[str, str] = field(default_factory=dict)


class LLMError(Exception):
    """Base error for LLM failures that the pipeline should surface gracefully."""


class LLMUnavailableError(LLMError):
    """Provider unreachable, rate limited after retries, or overloaded."""


class LLMRefusalError(LLMError):
    """The model declined the request."""


class LLMOutputError(LLMError):
    """The model returned output that could not be parsed into the requested schema."""


class LLMProvider(Protocol):
    name: str

    def model_for(self, tier: Tier) -> str: ...

    def complete_json(
        self,
        *,
        task: str,
        output_model: type[T],
        system: str,
        messages: list[ChatMessage],
        tier: Tier = Tier.STRONG,
    ) -> LLMResult[T]:
        """Run one structured-output completion.

        `task` is a stable label (e.g. "generate_sql") used for tracing and by the mock.
        """
        ...

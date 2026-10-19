"""Deterministic mock LLM provider.

Responses are produced, in priority order, by:
1. a scripted FIFO queue per task (`script(task, [...])`), used by tests to force paths;
2. a registered handler per task (`register(task, fn)`), used for fixture-driven behaviour;
3. the output model's defaults, if it can be built with no arguments.

The mock never touches the network and reports a nominal, non-zero token usage so cost
accounting code paths are exercised.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.services.llm.base import ChatMessage, LLMOutputError, LLMResult, T, Tier, Usage


@dataclass
class MockCall:
    task: str
    system: str
    messages: list[ChatMessage]
    output_model: type[BaseModel]
    tier: Tier

    @property
    def last_user(self) -> str:
        for m in reversed(self.messages):
            if m["role"] == "user":
                return m["content"]
        return ""


Handler = Callable[[MockCall], dict[str, Any] | BaseModel]


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._scripts: dict[str, deque[dict[str, Any] | BaseModel | Exception]] = defaultdict(deque)
        self.calls: list[MockCall] = []

    def model_for(self, tier: Tier) -> str:
        return f"mock-{tier.value}"

    def register(self, task: str, handler: Handler) -> None:
        self._handlers[task] = handler

    def script(self, task: str, responses: list[dict[str, Any] | BaseModel | Exception]) -> None:
        self._scripts[task].extend(responses)

    def reset(self) -> None:
        self._scripts.clear()
        self.calls.clear()

    def complete_json(
        self,
        *,
        task: str,
        output_model: type[T],
        system: str,
        messages: list[ChatMessage],
        tier: Tier = Tier.STRONG,
    ) -> LLMResult[T]:
        call = MockCall(task, system, list(messages), output_model, tier)
        self.calls.append(call)

        raw: dict[str, Any] | BaseModel | Exception | None = None
        if self._scripts.get(task):
            raw = self._scripts[task].popleft()
        elif task in self._handlers:
            raw = self._handlers[task](call)

        if isinstance(raw, Exception):
            raise raw
        try:
            if raw is None:
                output = output_model()
            elif isinstance(raw, BaseModel):
                output = output_model.model_validate(raw.model_dump())
            else:
                output = output_model.model_validate(raw)
        except ValidationError as e:
            raise LLMOutputError(f"mock output invalid for {task}: {e}") from e

        prompt_chars = len(system) + sum(len(m["content"]) for m in messages)
        usage = Usage(
            model=self.model_for(tier),
            tokens_in=max(1, prompt_chars // 4),
            tokens_out=max(1, len(output.model_dump_json()) // 4),
        )
        return LLMResult(output=output, usage=usage, latency_ms=0)

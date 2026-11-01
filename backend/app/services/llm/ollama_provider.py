"""Local model provider using Ollama's chat API with schema-constrained output.

Used for free, offline benchmark runs. Both tiers map to one local model, and cost is always 0.
Ollama's `format` field takes a JSON schema and constrains decoding to it, so the pipeline gets
the same validated Pydantic object it gets from the Anthropic provider.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.services.llm.base import (
    ChatMessage,
    LLMOutputError,
    LLMResult,
    LLMUnavailableError,
    T,
    Tier,
    Usage,
)

logger = logging.getLogger(__name__)


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_s
        )

    def model_for(self, tier: Tier) -> str:
        return self._settings.ollama_model

    def complete_json(
        self,
        *,
        task: str,
        output_model: type[T],
        system: str,
        messages: list[ChatMessage],
        tier: Tier = Tier.STRONG,
    ) -> LLMResult[T]:
        s = self._settings
        model = self.model_for(tier)
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "format": output_model.model_json_schema(),
            "stream": False,
            "think": s.ollama_think,
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": s.ollama_num_ctx},
        }
        start = time.perf_counter()
        try:
            resp = self._client.post("/api/chat", json=body)
        except httpx.HTTPError as e:
            raise LLMUnavailableError(
                f"Ollama unreachable at {s.ollama_base_url} ({type(e).__name__})"
            ) from e
        latency_ms = int((time.perf_counter() - start) * 1000)
        if resp.status_code == 404:
            raise LLMUnavailableError(
                f"Ollama model {model!r} not found; run `ollama pull {model}`"
            )
        if resp.status_code >= 400:
            raise LLMUnavailableError(f"Ollama error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        usage = Usage(
            model=model,
            tokens_in=int(data.get("prompt_eval_count") or 0),
            tokens_out=int(data.get("eval_count") or 0),
        )
        if data.get("done_reason") == "length":
            raise LLMOutputError("model output was truncated (context or length limit)")
        content = (data.get("message") or {}).get("content") or ""
        try:
            parsed = output_model.model_validate_json(content)
        except ValidationError as e:
            raise LLMOutputError(f"model output did not match the schema: {e.errors()[:1]}") from e

        logger.info(
            "llm_call",
            extra={
                "task": task,
                "model": model,
                "tokens_in": usage.tokens_in,
                "tokens_out": usage.tokens_out,
                "cost_usd": 0.0,
                "latency_ms": latency_ms,
            },
        )
        return LLMResult(output=parsed, usage=usage, latency_ms=latency_ms)

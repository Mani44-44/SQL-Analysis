"""Anthropic Claude provider using structured outputs (`beta.messages.parse`)."""

from __future__ import annotations

import logging
import time
from typing import Any

import anthropic

from app.core.config import Settings
from app.services.llm.base import (
    ChatMessage,
    LLMOutputError,
    LLMRefusalError,
    LLMResult,
    LLMUnavailableError,
    T,
    Tier,
    Usage,
)
from app.services.llm.pricing import cost_usd

logger = logging.getLogger(__name__)

# Server-side refusal fallback ("default" routing) is supported on these models only.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        if client is None:
            api_key = (
                settings.anthropic_api_key.get_secret_value()
                if settings.anthropic_api_key
                else None
            )
            client = anthropic.Anthropic(
                api_key=api_key,
                timeout=settings.llm_timeout_s,
                max_retries=settings.llm_max_retries,
            )
        self._client = client

    def model_for(self, tier: Tier) -> str:
        s = self._settings
        return s.llm_model_strong if tier is Tier.STRONG else s.llm_model_fast

    def _effort_for(self, tier: Tier) -> str:
        s = self._settings
        return s.llm_effort_strong if tier is Tier.STRONG else s.llm_effort_fast

    def complete_json(
        self,
        *,
        task: str,
        output_model: type[T],
        system: str,
        messages: list[ChatMessage],
        tier: Tier = Tier.STRONG,
    ) -> LLMResult[T]:
        model = self.model_for(tier)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self._settings.llm_max_tokens,
            # The system prompt is stable per prompt version + schema, so cache it.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": list(messages),
            "output_format": output_model,
            "output_config": {"effort": self._effort_for(tier)},
            "metadata": {"user_id": f"askdata:{task}"},
        }
        if model in _FALLBACK_MODELS:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        start = time.perf_counter()
        try:
            response = self._client.beta.messages.parse(**kwargs)
        except anthropic.BadRequestError as e:
            raise LLMOutputError(f"bad request: {e.message}") from e
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise LLMUnavailableError("LLM credentials rejected") from e
        except anthropic.RateLimitError as e:
            raise LLMUnavailableError("LLM rate limited") from e
        except anthropic.APIStatusError as e:
            raise LLMUnavailableError(f"LLM error {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise LLMUnavailableError("LLM unreachable") from e
        latency_ms = int((time.perf_counter() - start) * 1000)

        raw_usage = response.usage
        usage = Usage(
            model=getattr(response, "model", model) or model,
            tokens_in=raw_usage.input_tokens or 0,
            tokens_out=raw_usage.output_tokens or 0,
            cache_read_tokens=getattr(raw_usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(raw_usage, "cache_creation_input_tokens", 0) or 0,
        )
        usage.cost_usd = cost_usd(usage)

        if response.stop_reason == "refusal":
            raise LLMRefusalError("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMOutputError("model output was truncated (max_tokens)")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LLMOutputError("model returned no structured output")

        logger.info(
            "llm_call",
            extra={
                "task": task,
                "model": usage.model,
                "tokens_in": usage.tokens_in,
                "tokens_out": usage.tokens_out,
                "cost_usd": usage.cost_usd,
                "latency_ms": latency_ms,
            },
        )
        return LLMResult(output=parsed, usage=usage, latency_ms=latency_ms)

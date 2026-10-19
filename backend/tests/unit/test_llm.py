from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.services.llm import (
    LLMOutputError,
    LLMRefusalError,
    LLMUnavailableError,
    MockProvider,
    Tier,
    Usage,
    build_provider,
)
from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.pricing import cost_usd


class Answer(BaseModel):
    text: str = "default"
    n: int = 0


# ---------------- mock provider ----------------


def test_mock_defaults_when_nothing_registered() -> None:
    p = MockProvider()
    r = p.complete_json(task="t", output_model=Answer, system="s", messages=[])
    assert r.output == Answer()
    assert r.usage.tokens_in >= 1


def test_mock_script_takes_priority_over_handler() -> None:
    p = MockProvider()
    p.register("t", lambda call: {"text": "handler"})
    p.script("t", [{"text": "scripted", "n": 1}])
    first = p.complete_json(task="t", output_model=Answer, system="", messages=[])
    second = p.complete_json(task="t", output_model=Answer, system="", messages=[])
    assert first.output.text == "scripted"
    assert second.output.text == "handler"
    assert len(p.calls) == 2


def test_mock_handler_sees_last_user_message() -> None:
    p = MockProvider()
    p.register("t", lambda call: {"text": call.last_user.upper()})
    r = p.complete_json(
        task="t",
        output_model=Answer,
        system="",
        messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "hi"}],
    )
    assert r.output.text == "HI"


def test_mock_scripted_exception_raised() -> None:
    p = MockProvider()
    p.script("t", [LLMUnavailableError("down")])
    with pytest.raises(LLMUnavailableError):
        p.complete_json(task="t", output_model=Answer, system="", messages=[])


def test_mock_invalid_output_raises_output_error() -> None:
    p = MockProvider()
    p.script("t", [{"n": "not-an-int"}])
    with pytest.raises(LLMOutputError):
        p.complete_json(task="t", output_model=Answer, system="", messages=[])


def test_build_provider_uses_mock_without_key() -> None:
    assert build_provider(Settings(_env_file=None, llm_provider="auto")).name == "mock"


# ---------------- pricing ----------------


def test_cost_computation() -> None:
    u = Usage(model="claude-opus-5-5", tokens_in=1_000_000, tokens_out=100_000)
    assert cost_usd(u) == pytest.approx(4.0 + 2.0)
    assert cost_usd(Usage(model="unknown")) == 0.0
    cached = Usage(model="claude-opus-5-5", cache_read_tokens=1_000_000)
    assert cost_usd(cached) == pytest.approx(0.4)


# ---------------- anthropic provider with a fake client ----------------


class FakeMessages:
    def __init__(self, response: Any = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.kwargs: dict[str, Any] = {}

    def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def _fake_client(messages: FakeMessages) -> Any:
    return SimpleNamespace(beta=SimpleNamespace(messages=messages))


def _response(stop_reason: str = "end_turn", parsed: Any = None, model: str = "claude-opus-5-5"):
    usage = SimpleNamespace(
        input_tokens=100, output_tokens=50, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage, model=model)


def _settings() -> Settings:
    return Settings(_env_file=None, anthropic_api_key="test-key", llm_provider="anthropic")


def test_anthropic_success_and_request_shape() -> None:
    fm = FakeMessages(_response(parsed=Answer(text="ok", n=2)))
    p = AnthropicProvider(_settings(), client=_fake_client(fm))
    r = p.complete_json(
        task="generate_sql",
        output_model=Answer,
        system="sys",
        messages=[{"role": "user", "content": "q"}],
    )
    assert r.output.text == "ok"
    assert r.usage.tokens_in == 100
    assert r.usage.cost_usd > 0
    kw = fm.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_format"] is Answer
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["fallbacks"] == "default"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in kw and "temperature" not in kw


def test_anthropic_fast_tier_has_no_fallback() -> None:
    fm = FakeMessages(_response(parsed=Answer(), model="claude-haiku-5-5"))
    p = AnthropicProvider(_settings(), client=_fake_client(fm))
    p.complete_json(task="explain", output_model=Answer, system="", messages=[], tier=Tier.FAST)
    assert fm.kwargs["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in fm.kwargs
    assert fm.kwargs["output_config"] == {"effort": "low"}


def test_anthropic_refusal() -> None:
    fm = FakeMessages(_response(stop_reason="refusal"))
    p = AnthropicProvider(_settings(), client=_fake_client(fm))
    with pytest.raises(LLMRefusalError):
        p.complete_json(task="t", output_model=Answer, system="", messages=[])


def test_anthropic_missing_parsed_output() -> None:
    fm = FakeMessages(_response(parsed=None))
    p = AnthropicProvider(_settings(), client=_fake_client(fm))
    with pytest.raises(LLMOutputError):
        p.complete_json(task="t", output_model=Answer, system="", messages=[])


def test_anthropic_errors_mapped() -> None:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    rate = anthropic.RateLimitError(
        "slow down", response=httpx.Response(429, request=req), body=None
    )
    conn = anthropic.APIConnectionError(request=req)
    for exc in (rate, conn):
        p = AnthropicProvider(_settings(), client=_fake_client(FakeMessages(exc=exc)))
        with pytest.raises(LLMUnavailableError):
            p.complete_json(task="t", output_model=Answer, system="", messages=[])

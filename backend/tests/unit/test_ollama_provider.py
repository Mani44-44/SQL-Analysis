from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.services.llm import LLMOutputError, LLMUnavailableError, build_provider
from app.services.llm.ollama_provider import OllamaProvider
from app.services.text2sql.models import GenerationOutput

GOOD = {
    "kind": "sql",
    "standalone_question": "total spend",
    "sql": "SELECT 1",
    "reasoning": "r",
    "assumptions": [],
    "tables_used": ["transactions"],
    "confidence": 0.9,
    "clarifying_question": "",
    "missing_data": "",
}


def _provider(handler, **settings) -> tuple[OllamaProvider, list[dict]]:  # type: ignore[no-untyped-def]
    seen: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    s = Settings(_env_file=None, llm_provider="ollama", **settings)
    client = httpx.Client(base_url=s.ollama_base_url, transport=httpx.MockTransport(wrapped))
    return OllamaProvider(s, client=client), seen


def _call(p: OllamaProvider):  # type: ignore[no-untyped-def]
    return p.complete_json(
        task="generate_sql",
        output_model=GenerationOutput,
        system="schema here",
        messages=[{"role": "user", "content": "q"}],
    )


def test_structured_call_and_request_shape() -> None:
    def ok(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": json.dumps(GOOD)},
                "done_reason": "stop",
                "prompt_eval_count": 1200,
                "eval_count": 80,
            },
        )

    p, seen = _provider(ok, ollama_model="qwen3.5:9b", ollama_num_ctx=4096)
    r = _call(p)
    assert r.output.sql == "SELECT 1"
    assert (r.usage.tokens_in, r.usage.tokens_out, r.usage.cost_usd) == (1200, 80, 0.0)
    body = seen[0]
    assert body["model"] == "qwen3.5:9b" and body["stream"] is False and body["think"] is False
    assert body["messages"][0] == {"role": "system", "content": "schema here"}
    assert body["format"]["properties"]["kind"]
    assert body["options"] == {"temperature": 0, "num_ctx": 4096}


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(404, json={"error": "model not found"}), LLMUnavailableError),
        (httpx.Response(500, text="boom"), LLMUnavailableError),
        (httpx.Response(200, json={"message": {"content": "{not json"}}), LLMOutputError),
        (
            httpx.Response(200, json={"message": {"content": "{}"}, "done_reason": "length"}),
            LLMOutputError,
        ),
    ],
)
def test_errors_are_mapped(response: httpx.Response, error: type[Exception]) -> None:
    p, _ = _provider(lambda _: response)
    with pytest.raises(error):
        _call(p)


def test_unreachable_server() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    p, _ = _provider(down)
    with pytest.raises(LLMUnavailableError, match="unreachable"):
        _call(p)


def test_factory_selects_ollama() -> None:
    s = Settings(_env_file=None, llm_provider="ollama", anthropic_api_key="k")
    assert not s.use_mock_llm
    assert build_provider(s).name == "ollama"

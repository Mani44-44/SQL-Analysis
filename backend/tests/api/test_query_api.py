from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.demo.questions import DEMO_QUESTIONS
from app.services.llm import MockProvider


def test_ask_demo_question_default_mock(client: TestClient, demo_ws: str) -> None:
    r = client.post(
        f"/api/v1/workspaces/{demo_ws}/ask", json={"question": DEMO_QUESTIONS[0].question}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["columns"] == ["month", "spend"]
    assert body["row_count"] == 18
    assert body["conversation_id"] and body["query_run_id"]
    assert body["sql"].upper().startswith("SELECT")
    assert body["attempts"][0]["number"] == 1


def test_follow_up_uses_conversation_history(
    client: TestClient, demo_ws: str, mock_llm: MockProvider
) -> None:
    from app.services.llm.mock_fixtures import extract_question

    def handler(call):  # type: ignore[no-untyped-def]
        return {
            "kind": "sql", "standalone_question": extract_question(call.last_user), "sql": "SELECT 1 AS x", "reasoning": "",
            "assumptions": [], "tables_used": [], "confidence": 1, "clarifying_question": "",
            "missing_data": "",
        }  # fmt: skip

    mock_llm.register("generate_sql", handler)
    first = client.post(
        f"/api/v1/workspaces/{demo_ws}/ask", json={"question": "total spend in 2025"}
    ).json()
    client.post(
        f"/api/v1/workspaces/{demo_ws}/ask",
        json={"question": "now by month", "conversation_id": first["conversation_id"]},
    )
    last_gen = [c for c in mock_llm.calls if c.task == "generate_sql"][-1]
    assert "total spend in 2025" in last_gen.last_user
    assert "<history>" in last_gen.last_user


def test_unknown_conversation_404(client: TestClient, demo_ws: str) -> None:
    r = client.post(
        f"/api/v1/workspaces/{demo_ws}/ask", json={"question": "x", "conversation_id": "f" * 32}
    )
    assert r.status_code == 404


def test_ask_validation(client: TestClient, demo_ws: str) -> None:
    assert (
        client.post(f"/api/v1/workspaces/{demo_ws}/ask", json={"question": ""}).status_code == 422
    )


def test_ask_sse_stream(client: TestClient, demo_ws: str) -> None:
    with client.stream(
        "POST",
        f"/api/v1/workspaces/{demo_ws}/ask",
        json={"question": DEMO_QUESTIONS[1].question},
        headers={"Accept": "text/event-stream"},
    ) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    events = [
        line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("event:")
    ]
    assert events[0] == "status"
    assert events.index("sql") < events.index("rows") < events.index("result")
    assert events[-1] == "done"
    data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    result = next(json.loads(d) for d in data_lines if d.startswith("{") and '"query_run_id"' in d)
    assert result["status"] == "ok" and result["row_count"] == 5


def test_run_sql_ok_and_errors(client: TestClient, demo_ws: str) -> None:
    ok = client.post(
        f"/api/v1/workspaces/{demo_ws}/sql/run",
        json={"sql": "SELECT type, count(*) AS n FROM transactions GROUP BY 1 ORDER BY 1"},
    ).json()
    assert ok["status"] == "ok" and ok["columns"] == ["type", "n"] and ok["row_count"] == 2
    bad = client.post(
        f"/api/v1/workspaces/{demo_ws}/sql/run", json={"sql": "SELECT nope FROM transactions"}
    ).json()
    assert bad["status"] == "error" and bad["error_code"] == "unknown_column"
    attack = client.post(
        f"/api/v1/workspaces/{demo_ws}/sql/run",
        json={"sql": "SELECT * FROM read_csv('/etc/passwd')"},
    ).json()
    assert attack["status"] == "error" and attack["error_code"] == "table_function"
    drop = client.post(
        f"/api/v1/workspaces/{demo_ws}/sql/run", json={"sql": "DROP TABLE transactions"}
    ).json()
    assert drop["error_code"] == "not_select"

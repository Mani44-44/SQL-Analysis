from __future__ import annotations

from fastapi.testclient import TestClient

from app.demo.questions import DEMO_QUESTIONS
from app.services.llm import MockProvider
from tests.conftest import signup


def _ask(client: TestClient, ws: str, q: str, conv: str | None = None) -> dict:  # type: ignore[type-arg]
    r = client.post(f"/api/v1/workspaces/{ws}/ask", json={"question": q, "conversation_id": conv})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_ask_includes_chart_and_explanation(client: TestClient, demo_ws: str) -> None:
    body = _ask(client, demo_ws, DEMO_QUESTIONS[0].question)
    assert body["chart"]["type"] == "line"
    assert body["chart"]["x"] == "month"
    assert body["explanation"]


def test_explanation_uses_llm_output(
    client: TestClient, demo_ws: str, mock_llm: MockProvider
) -> None:
    from app.services.llm.mock_fixtures import _generate

    mock_llm.register("generate_sql", _generate)
    mock_llm.register("explain", lambda c: {"answer": "You spent the most on rent."})
    body = _ask(client, demo_ws, DEMO_QUESTIONS[1].question)
    assert body["explanation"] == "You spent the most on rent."
    explain_call = next(c for c in mock_llm.calls if c.task == "explain")
    assert "<result>" in explain_call.last_user


def test_conversation_history_endpoints(client: TestClient, demo_ws: str) -> None:
    signup(client)
    first = _ask(client, demo_ws, DEMO_QUESTIONS[0].question)
    _ask(client, demo_ws, DEMO_QUESTIONS[1].question, first["conversation_id"])
    convs = client.get(f"/api/v1/workspaces/{demo_ws}/conversations").json()
    assert convs[0]["id"] == first["conversation_id"] and convs[0]["turns"] == 2
    detail = client.get(f"/api/v1/conversations/{first['conversation_id']}").json()
    assert [r["question"] for r in detail["runs"]] == [q.question for q in DEMO_QUESTIONS[:2]]
    run = client.get(f"/api/v1/query-runs/{first['query_run_id']}").json()
    assert run["prompt_version"] == "generate_sql@v1"
    stages = [t["stage"] for t in run["trace"]]
    assert "generate_sql" in stages and "execute" in stages and "attempt" in stages
    assert client.get("/api/v1/conversations/" + "0" * 32).status_code == 404


def test_feedback(client: TestClient, demo_ws: str) -> None:
    run = _ask(client, demo_ws, DEMO_QUESTIONS[0].question)["query_run_id"]
    r = client.post(f"/api/v1/query-runs/{run}/feedback", json={"rating": 1})
    assert r.status_code == 201
    r = client.post(
        f"/api/v1/query-runs/{run}/feedback",
        json={
            "rating": -1,
            "corrected_sql": "select count(*) from transactions",
            "comment": "wrong",
        },
    )
    assert r.status_code == 201 and r.json()["corrected_sql"].startswith("SELECT")
    bad = client.post(
        f"/api/v1/query-runs/{run}/feedback", json={"rating": -1, "corrected_sql": "DROP TABLE x"}
    )
    assert bad.status_code == 422
    assert client.post(f"/api/v1/query-runs/{run}/feedback", json={"rating": 5}).status_code == 422
    conv = client.get(f"/api/v1/query-runs/{run}").json()
    assert conv["rating"] == -1


def test_export_csv(client: TestClient, demo_ws: str) -> None:
    run = _ask(client, demo_ws, DEMO_QUESTIONS[4].question)["query_run_id"]
    r = client.get(f"/api/v1/query-runs/{run}/export?format=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "payment_mode,failed_transactions"
    assert len(lines) == 6


def test_export_rejects_failed_runs(client: TestClient, demo_ws: str) -> None:
    run = client.post(
        f"/api/v1/workspaces/{demo_ws}/sql/run", json={"sql": "SELECT nope FROM transactions"}
    ).json()
    assert client.get(f"/api/v1/query-runs/{run['query_run_id']}/export").status_code == 409


def test_saved_queries(client: TestClient) -> None:
    signup(client)
    ws = client.post("/api/v1/workspaces", json={"name": "w"}).json()["id"]
    client.post(
        f"/api/v1/workspaces/{ws}/sources/upload",
        files={"file": ("t.csv", b"a,b\n1,x\n2,y\n", "text/csv")},
    )
    r = client.post(
        f"/api/v1/workspaces/{ws}/saved-queries", json={"title": "All", "sql": "select * from t"}
    )
    assert r.status_code == 201
    sid = r.json()["id"]
    assert (
        client.post(
            f"/api/v1/workspaces/{ws}/saved-queries", json={"title": "x", "sql": "DELETE FROM t"}
        ).status_code
        == 422
    )
    assert [s["title"] for s in client.get(f"/api/v1/workspaces/{ws}/saved-queries").json()] == [
        "All"
    ]
    assert client.delete(f"/api/v1/saved-queries/{sid}").status_code == 204
    assert client.get(f"/api/v1/workspaces/{ws}/saved-queries").json() == []


def test_manual_run_has_chart(client: TestClient, demo_ws: str) -> None:
    r = client.post(
        f"/api/v1/workspaces/{demo_ws}/sql/run",
        json={"sql": "SELECT payment_mode, count(*) AS n FROM transactions GROUP BY 1"},
    ).json()
    assert r["chart"]["type"] == "bar"


def test_suggestions(client: TestClient, demo_ws: str) -> None:
    demo = client.get(f"/api/v1/workspaces/{demo_ws}/suggestions").json()
    signup(client)
    assert demo[0] == DEMO_QUESTIONS[0].question
    ws = client.post("/api/v1/workspaces", json={"name": "w"}).json()["id"]
    client.post(
        f"/api/v1/workspaces/{ws}/sources/upload",
        files={
            "file": (
                "sales.csv",
                b"day,region,amount\n2025-01-01,N,5\n2025-01-02,S,7\n",
                "text/csv",
            )
        },
    )
    out = client.get(f"/api/v1/workspaces/{ws}/suggestions").json()
    assert any("by month" in s for s in out)

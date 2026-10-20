"""Auth flows, tenant isolation, demo read-only rules, rate limits and cost caps."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_token, decode_token, hash_password, verify_password
from app.demo.questions import DEMO_QUESTIONS
from tests.conftest import signup

API = "/api/v1"


def _client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def _workspace_with_data(c: TestClient, name: str = "secret ws") -> tuple[str, str]:
    ws = c.post(f"{API}/workspaces", json={"name": name}).json()["id"]
    src = c.post(
        f"{API}/workspaces/{ws}/sources/upload",
        files={"file": ("salaries.csv", b"name,salary\nalice,100\nbob,200\n", "text/csv")},
    ).json()["id"]
    return ws, src


# ------------------------------------------------------------------ primitives


def test_password_hashing() -> None:
    h = hash_password("correct-horse-1")
    assert h != "correct-horse-1" and h.startswith("$argon2")
    assert verify_password(h, "correct-horse-1")
    assert not verify_password(h, "wrong-password")
    assert not verify_password("not-a-hash", "x")


def test_tokens_expire_and_resist_tampering() -> None:
    t = create_token("u1")
    assert decode_token(t) == "u1"
    assert decode_token(create_token("u1", ttl=timedelta(seconds=-1))) is None
    head, body, sig = t.split(".")
    assert decode_token(f"{head}.{body}.{sig[:-2]}xx") is None
    assert decode_token("garbage") is None


# ------------------------------------------------------------------ auth flow


def test_register_login_logout_me(client: TestClient) -> None:
    assert client.get(f"{API}/auth/me").status_code == 401
    r = client.post(
        f"{API}/auth/register", json={"email": "A@Example.com", "password": "correct-horse-1"}
    )
    assert r.status_code == 201 and r.json()["email"] == "a@example.com"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get(f"{API}/auth/me").json()["email"] == "a@example.com"
    assert (
        client.post(
            f"{API}/auth/register", json={"email": "a@example.com", "password": "another-pass-1"}
        ).status_code
        == 409
    )
    assert client.post(f"{API}/auth/logout").status_code == 204
    client.cookies.clear()
    assert client.get(f"{API}/auth/me").status_code == 401
    bad = client.post(
        f"{API}/auth/login", json={"email": "a@example.com", "password": "wrong-password"}
    )
    assert bad.status_code == 401
    ok = client.post(
        f"{API}/auth/login", json={"email": "a@example.com", "password": "correct-horse-1"}
    )
    assert ok.status_code == 200


@pytest.mark.parametrize(
    "body",
    [{"email": "nope", "password": "correct-horse-1"}, {"email": "a@b.co", "password": "short"}],
)
def test_register_validation(client: TestClient, body: dict[str, str]) -> None:
    assert client.post(f"{API}/auth/register", json=body).status_code == 422


def test_bearer_token_also_accepted(client: TestClient) -> None:
    uid = signup(client)
    client.cookies.clear()
    r = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {create_token(uid)}"})
    assert r.status_code == 200


def test_login_brute_force_limited(client: TestClient) -> None:
    signup(client, "victim@example.com")
    codes = [
        client.post(
            f"{API}/auth/login", json={"email": "victim@example.com", "password": "wrong-pass-x"}
        ).status_code
        for _ in range(12)
    ]
    assert 429 in codes


# ------------------------------------------------------------------ tenancy


def test_anonymous_cannot_create_or_open_private_workspaces(client: TestClient) -> None:
    assert client.post(f"{API}/workspaces", json={"name": "x"}).status_code == 401
    signup(client)
    ws, _ = _workspace_with_data(client)
    client.cookies.clear()
    assert client.get(f"{API}/workspaces/{ws}").status_code == 401
    assert client.get(f"{API}/workspaces/{ws}/schema").status_code == 401
    assert ws not in {w["id"] for w in client.get(f"{API}/workspaces").json()}


def test_cross_workspace_access_denied(client: TestClient, demo_ws: str) -> None:
    signup(client, "alice@example.com")
    ws, src = _workspace_with_data(client)
    run = client.post(
        f"{API}/workspaces/{ws}/sql/run", json={"sql": "SELECT * FROM salaries"}
    ).json()
    asked = client.post(f"{API}/workspaces/{ws}/ask", json={"question": "anything"}).json()
    schema = client.get(f"{API}/workspaces/{ws}/schema").json()
    col_id = schema["tables"][0]["columns"][0]["id"]
    table_id = schema["tables"][0]["id"]
    term = client.post(
        f"{API}/workspaces/{ws}/glossary", json={"term": "t", "definition": "d"}
    ).json()["id"]
    saved = client.post(
        f"{API}/workspaces/{ws}/saved-queries", json={"title": "s", "sql": "select 1"}
    ).json()["id"]

    mallory = _client()
    signup(mallory, "mallory@example.com")
    denied = [
        mallory.get(f"{API}/workspaces/{ws}"),
        mallory.get(f"{API}/workspaces/{ws}/schema"),
        mallory.get(f"{API}/workspaces/{ws}/sources"),
        mallory.get(f"{API}/sources/{src}"),
        mallory.delete(f"{API}/sources/{src}"),
        mallory.post(f"{API}/workspaces/{ws}/ask", json={"question": "show salaries"}),
        mallory.post(f"{API}/workspaces/{ws}/sql/run", json={"sql": "SELECT * FROM salaries"}),
        mallory.get(f"{API}/workspaces/{ws}/conversations"),
        mallory.get(f"{API}/conversations/{asked['conversation_id']}"),
        mallory.get(f"{API}/query-runs/{run['query_run_id']}"),
        mallory.get(f"{API}/query-runs/{run['query_run_id']}/export"),
        mallory.post(f"{API}/query-runs/{run['query_run_id']}/feedback", json={"rating": 1}),
        mallory.patch(f"{API}/columns/{col_id}", json={"description": "pwned"}),
        mallory.patch(f"{API}/tables/{table_id}", json={"description": "pwned"}),
        mallory.delete(f"{API}/glossary/{term}"),
        mallory.get(f"{API}/workspaces/{ws}/saved-queries"),
        mallory.delete(f"{API}/saved-queries/{saved}"),
        mallory.delete(f"{API}/workspaces/{ws}"),
        mallory.get(f"{API}/metrics?workspace_id={ws}"),
    ]
    for r in denied:
        assert r.status_code == 404, (r.request.method, r.request.url, r.status_code, r.text[:200])
    # mallory's own SQL can't reach alice's tables either
    mws = mallory.post(f"{API}/workspaces", json={"name": "m"}).json()["id"]
    leak = mallory.post(
        f"{API}/workspaces/{mws}/sql/run", json={"sql": "SELECT * FROM salaries"}
    ).json()
    assert leak["status"] == "error"
    # alice still has everything
    assert client.get(f"{API}/workspaces/{ws}/schema").json()["tables"][0]["description"] is None


def test_demo_is_public_and_read_only(client: TestClient, demo_ws: str) -> None:
    r = client.post(
        f"{API}/workspaces/{demo_ws}/ask", json={"question": DEMO_QUESTIONS[0].question}
    )
    assert r.status_code == 200 and r.json()["status"] == "ok"
    schema = client.get(f"{API}/workspaces/{demo_ws}/schema").json()
    col = schema["tables"][0]["columns"][0]["id"]
    signup(client)
    assert client.patch(f"{API}/columns/{col}", json={"description": "x"}).status_code == 403
    assert client.delete(f"{API}/workspaces/{demo_ws}").status_code == 403
    assert (
        client.post(
            f"{API}/workspaces/{demo_ws}/saved-queries", json={"title": "x", "sql": "select 1"}
        ).status_code
        == 403
    )
    up = client.post(
        f"{API}/workspaces/{demo_ws}/sources/upload",
        files={"file": ("a.csv", b"a\n1\n", "text/csv")},
    )
    assert up.status_code == 403


def test_demo_conversations_are_private(client: TestClient, demo_ws: str) -> None:
    signup(client, "first@example.com")
    mine = client.post(
        f"{API}/workspaces/{demo_ws}/ask", json={"question": DEMO_QUESTIONS[1].question}
    ).json()
    assert [c["id"] for c in client.get(f"{API}/workspaces/{demo_ws}/conversations").json()] == [
        mine["conversation_id"]
    ]

    other = _client()
    signup(other, "second@example.com")
    assert other.get(f"{API}/workspaces/{demo_ws}/conversations").json() == []
    assert other.get(f"{API}/conversations/{mine['conversation_id']}").status_code == 404
    assert other.get(f"{API}/query-runs/{mine['query_run_id']}").status_code == 404
    hijack = other.post(
        f"{API}/workspaces/{demo_ws}/ask",
        json={"question": "now by month", "conversation_id": mine["conversation_id"]},
    )
    assert hijack.status_code == 404
    anon = _client()
    assert anon.get(f"{API}/workspaces/{demo_ws}/conversations").json() == []


def test_workspace_list_scoped_to_user(client: TestClient, demo_ws: str) -> None:
    signup(client, "a1@example.com")
    ws, _ = _workspace_with_data(client, "a1 ws")
    mine = {w["id"]: w for w in client.get(f"{API}/workspaces").json()}
    assert mine[ws]["role"] == "owner" and demo_ws in mine
    other = _client()
    signup(other, "b1@example.com")
    ids = {w["id"] for w in other.get(f"{API}/workspaces").json()}
    assert ws not in ids and demo_ws in ids


# ------------------------------------------------------------------ limits


def test_rate_limit(client: TestClient, demo_ws: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 3)
    codes = [
        client.post(f"{API}/workspaces/{demo_ws}/sql/run", json={"sql": "SELECT 1"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    r = client.post(f"{API}/workspaces/{demo_ws}/sql/run", json={"sql": "SELECT 1"})
    assert int(r.headers["retry-after"]) >= 1


def test_daily_cost_cap(client: TestClient, demo_ws: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.core.limits import cost_tracker

    monkeypatch.setattr(get_settings(), "daily_cost_cap_usd", 0.5)
    cost_tracker().add("ip:testclient", 0.6)
    r = client.post(f"{API}/workspaces/{demo_ws}/ask", json={"question": "x"})
    assert r.status_code == 429 and "Daily usage limit" in r.json()["detail"]
    signup(client)  # a signed-in user has their own budget
    assert client.post(f"{API}/workspaces/{demo_ws}/ask", json={"question": "x"}).status_code == 200


def test_prod_requires_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "prod")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app()
    monkeypatch.setenv("JWT_SECRET", "short")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        create_app()
    monkeypatch.setenv("JWT_SECRET", "a-real-secret-value-for-tests-0123456789abcdef")
    get_settings.cache_clear()
    create_app()


def test_spoofed_forwarded_for_does_not_reset_limits(
    client: TestClient, demo_ws: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 2)
    codes = [
        client.post(
            f"{API}/workspaces/{demo_ws}/sql/run",
            json={"sql": "SELECT 1"},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        ).status_code
        for i in range(4)
    ]
    assert codes[2] == 429


def test_trusted_proxy_hop_selects_proxy_appended_address(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request

    from app.api.deps import client_ip
    from app.core.config import get_settings

    def req(xff: str) -> Request:
        return Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", xff.encode())],
                "client": ("192.0.2.1", 1234),
            }
        )

    assert client_ip(req("6.6.6.6, 203.0.113.9")) == "192.0.2.1"
    monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 1)
    assert client_ip(req("6.6.6.6, 203.0.113.9")) == "203.0.113.9"
    assert client_ip(req("")) == "192.0.2.1"

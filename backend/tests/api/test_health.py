from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_reports_mock_provider(client: TestClient) -> None:
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["llm_provider"] == "mock"


def test_request_id_generated_and_echoed(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert len(r.headers["X-Request-ID"]) == 32
    r2 = client.get("/api/v1/health", headers={"X-Request-ID": "my-req.1"})
    assert r2.headers["X-Request-ID"] == "my-req.1"


def test_invalid_request_id_replaced(client: TestClient) -> None:
    r = client.get("/api/v1/health", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["X-Request-ID"] != "bad id with spaces"

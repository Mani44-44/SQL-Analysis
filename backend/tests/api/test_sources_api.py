from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import signup

CSV = 'Name,Amount,Date\nalpha,"₹1,000",2025-01-02\nbeta,Rs. 50,03/01/2025\n'.encode()


def _ws(client: TestClient, name: str = "mine") -> str:
    signup(client)
    r = client.post("/api/v1/workspaces", json={"name": name})
    assert r.status_code == 201
    return str(r.json()["id"])


def test_upload_ingest_schema_flow(client: TestClient) -> None:
    ws = _ws(client)
    r = client.post(
        f"/api/v1/workspaces/{ws}/sources/upload",
        files={"file": ("sales data.csv", CSV, "text/csv")},
    )
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    # TestClient runs background tasks before returning.
    src = client.get(f"/api/v1/sources/{sid}").json()
    assert src["status"] == "ready", src
    assert src["tables"] == ["sales_data"]

    schema = client.get(f"/api/v1/workspaces/{ws}/schema").json()
    cols = {c["name"]: c for c in schema["tables"][0]["columns"]}
    assert cols["amount"]["type"] == "currency"
    assert cols["date"]["type"] == "date"

    # edit description
    r = client.patch(f"/api/v1/columns/{cols['name']['id']}", json={"description": "Product"})
    assert r.status_code == 200
    # override type -> reload keeps description
    r = client.patch(f"/api/v1/columns/{cols['amount']['id']}", json={"type_override": "text"})
    assert r.status_code == 200
    new_cols = {c["name"]: c for c in r.json()["tables"][0]["columns"]}
    assert new_cols["amount"]["type"] == "text"
    assert new_cols["amount"]["type_overridden"] is True
    assert new_cols["name"]["description"] == "Product"

    table_id = r.json()["tables"][0]["id"]
    r = client.patch(f"/api/v1/tables/{table_id}", json={"description": "Sales"})
    assert r.json()["tables"][0]["description"] == "Sales"

    assert client.delete(f"/api/v1/sources/{sid}").status_code == 204
    assert client.get(f"/api/v1/workspaces/{ws}/schema").json()["tables"] == []


def test_upload_rejects_unsupported_and_empty(client: TestClient) -> None:
    ws = _ws(client)
    r = client.post(
        f"/api/v1/workspaces/{ws}/sources/upload", files={"file": ("x.exe", b"MZ", "x")}
    )
    assert r.status_code == 415
    r = client.post(f"/api/v1/workspaces/{ws}/sources/upload", files={"file": ("x.csv", b"", "x")})
    assert r.status_code == 400


def test_upload_size_limit(client: TestClient, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    ws = _ws(client)
    r = client.post(
        f"/api/v1/workspaces/{ws}/sources/upload", files={"file": ("x.csv", b"a\n1\n", "x")}
    )
    assert r.status_code == 413


def test_path_traversal_filename_is_sanitised(client: TestClient) -> None:
    ws = _ws(client)
    r = client.post(
        f"/api/v1/workspaces/{ws}/sources/upload",
        files={"file": ("../../etc/passwd.csv", b"a\n1\n", "text/csv")},
    )
    assert r.status_code == 202
    assert r.json()["filename"] == "passwd.csv"


def test_glossary_crud(client: TestClient) -> None:
    ws = _ws(client)
    r = client.post(f"/api/v1/workspaces/{ws}/glossary", json={"term": "spend", "definition": "x"})
    assert r.status_code == 201
    tid = r.json()["id"]
    assert [g["term"] for g in client.get(f"/api/v1/workspaces/{ws}/glossary").json()] == ["spend"]
    assert client.delete(f"/api/v1/glossary/{tid}").status_code == 204
    assert client.get(f"/api/v1/workspaces/{ws}/glossary").json() == []


def test_demo_workspace_is_read_only(client: TestClient, demo_ws: str) -> None:
    demo = client.get("/api/v1/workspaces/demo").json()
    assert demo["id"] == demo_ws and demo["is_demo"] is True
    r = client.post(
        f"/api/v1/workspaces/{demo_ws}/sources/upload", files={"file": ("a.csv", b"a\n1\n", "x")}
    )
    assert r.status_code == 403
    assert client.delete(f"/api/v1/workspaces/{demo_ws}").status_code == 403
    schema = client.get(f"/api/v1/workspaces/{demo_ws}/schema").json()
    col_id = schema["tables"][0]["columns"][0]["id"]
    assert client.patch(f"/api/v1/columns/{col_id}", json={"description": "x"}).status_code == 403
    assert len(client.get(f"/api/v1/workspaces/{demo_ws}/glossary").json()) >= 5


def test_delete_workspace_removes_data(client: TestClient) -> None:
    from app.services.storage import workspace_db_path

    ws = _ws(client)
    client.post(
        f"/api/v1/workspaces/{ws}/sources/upload", files={"file": ("a.csv", b"a\n1\n", "x")}
    )
    assert workspace_db_path(ws).exists()
    assert client.delete(f"/api/v1/workspaces/{ws}").status_code == 204
    assert not workspace_db_path(ws).exists()
    assert client.get(f"/api/v1/workspaces/{ws}").status_code == 404


def test_unknown_workspace_404(client: TestClient) -> None:
    assert client.get("/api/v1/workspaces/" + "0" * 32 + "/schema").status_code == 404

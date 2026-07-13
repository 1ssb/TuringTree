"""Smoke tests for the FastAPI surface (read-only, no Ollama needed)."""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    ctype = r.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        # dev mode (no built UI): the JSON landing payload
        assert r.json()["docs"] == "/docs"
    else:
        # packaged/app mode: the built single-page app is served at "/"
        assert "text/html" in ctype


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "ollama" in body
    assert "dataset" in body


def test_index_status_shape():
    r = client.get("/api/index/status")
    assert r.status_code == 200
    body = r.json()
    assert "built" in body
    assert "documents" in body


def test_ingest_log_shape():
    r = client.get("/api/ingest/log")
    assert r.status_code == 200
    body = r.json()
    assert "count" in body
    assert "items" in body

"""Smoke test: the app imports and /api/healthz responds."""

from __future__ import annotations

from fastapi.testclient import TestClient

def test_app_imports_and_healthz():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

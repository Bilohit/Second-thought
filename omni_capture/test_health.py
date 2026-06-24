"""Smoke test for /health's readiness shape (P1-1)."""
from fastapi.testclient import TestClient

import server


def test_health_shape_before_and_after_ready():
    client = TestClient(server.app)

    server._MODEL_READY = False
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "ready": False}

    server._MODEL_READY = True
    resp = client.get("/health")
    assert resp.json() == {"ok": True, "ready": True}

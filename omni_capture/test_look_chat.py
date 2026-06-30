# omni_capture/test_look_chat.py
from fastapi.testclient import TestClient
from unittest import mock
import server

def test_vault_refusal_when_no_match():
    with mock.patch("rag_engine.hybrid_retrieve", return_value=([], 0.0, "none")):
        client = TestClient(server.app)
        r = client.post("/look/chat", json={"question": "anything"})
        body = r.text
    assert "Information not found in vault" in body
    assert "event: done" in body

def test_talk_mode_skips_retrieval():
    with mock.patch("rag_engine.hybrid_retrieve") as retrieve:
        client = TestClient(server.app)
        r = client.post("/look/chat", json={"question": "/talk hello"})
        body = r.text
    retrieve.assert_not_called()
    assert '"tier": "talk"' in body or '"tier":"talk"' in body
    assert "event: done" in body

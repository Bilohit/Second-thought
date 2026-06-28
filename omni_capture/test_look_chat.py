# omni_capture/test_look_chat.py
from fastapi.testclient import TestClient
from unittest import mock
import server

def test_refusal_streams_when_not_answerable():
    with mock.patch("rag_engine.hybrid_retrieve", return_value=([], False)):
        client = TestClient(server.app)
        r = client.post("/look/chat", json={"question": "anything"})
        body = r.text
    assert "Information not found in vault" in body
    assert "event: done" in body

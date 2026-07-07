"""
test_llm_timeout.py
--------------------
P0: client-side timeout on the Ollama structured chat-completion call.

Covers:
  1. config.toml/config.py expose cfg.ollama.request_timeout_s, default 60.
  2. run_llm_engine() passes that value as the `timeout=` kwarg into
     _make_client().chat.completions.create(...), so a hung Ollama call
     raises within a bounded time instead of blocking forever.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from unittest import mock

from config import get_config
from llm_engine import run_llm_engine
from models import EnrichedPayload


def test_default_request_timeout_s_is_60():
    cfg = get_config()
    assert cfg.ollama.request_timeout_s == 60


def test_create_call_receives_configured_timeout():
    enriched = EnrichedPayload(
        raw_input="hello world",
        input_type="text",
        enriched_text="hello world",
    )
    category_descriptions = {"notes": "General notes."}

    stub_client = mock.MagicMock()
    stub_client.chat.completions.create = mock.MagicMock(return_value=mock.MagicMock())

    with mock.patch("llm_engine._make_client", return_value=stub_client):
        run_llm_engine(enriched, category_descriptions)

    stub_client.chat.completions.create.assert_called_once()
    kwargs = stub_client.chat.completions.create.call_args.kwargs
    assert "timeout" in kwargs
    assert kwargs["timeout"] == get_config().ollama.request_timeout_s


if __name__ == "__main__":
    test_default_request_timeout_s_is_60()
    print("[T1] default ollama.request_timeout_s == 60  PASS")
    test_create_call_receives_configured_timeout()
    print("[T2] create() call receives configured timeout kwarg  PASS")

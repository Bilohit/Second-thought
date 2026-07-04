"""
test_voice_unique.py
---------------------
Voice recordings must always create a new timestamped file — never merge
or append into an existing note, even when the LLM suggests the same
filename slug twice in a row.

Run:  pytest omni_capture/test_voice_unique.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from models import CaptureOutput
from storage_engine import write_to_vault


def _out(text):
    return CaptureOutput(
        category="Notes",
        suggested_filename="voice-note",
        markdown_content=text,
        confidence=0.95,
    )


def test_voice_capture_always_new_timestamped_file(tmp_path):
    (tmp_path / "Notes").mkdir(parents=True)
    meta = {"audio_path": "a.webm", "whisper_model": "base"}
    p1 = write_to_vault(_out("first recording"), vault_root=tmp_path, source_metadata=meta)
    p2 = write_to_vault(_out("second recording"), vault_root=tmp_path, source_metadata=meta)
    assert p1 != p2
    assert "first recording" in p1.read_text(encoding="utf-8")
    assert "second recording" in p2.read_text(encoding="utf-8")

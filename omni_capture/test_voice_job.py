"""Voice pipeline helpers: transcript append + long-recording threshold."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from models import EnrichedPayload


def _audio_payload(text: str) -> EnrichedPayload:
    return EnrichedPayload(raw_input="x.webm", input_type="audio", enriched_text=text)


def test_append_transcript_adds_section_once():
    from server import _append_transcript
    body = _append_transcript("# Note\n\nSummary.", _audio_payload("hello world"))
    assert body.count("## Transcript") == 1
    assert body.rstrip().endswith("hello world")


def test_append_transcript_noop_for_non_audio():
    from server import _append_transcript
    payload = EnrichedPayload(raw_input="t", input_type="text", enriched_text="hello")
    assert _append_transcript("# Note", payload) == "# Note"


def test_voice_job_threshold():
    from server import _voice_needs_summarize_job
    assert _voice_needs_summarize_job(token_count=500, threshold=6000) is False
    assert _voice_needs_summarize_job(token_count=9000, threshold=6000) is True

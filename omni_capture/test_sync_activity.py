"""
test_sync_activity.py — Phase-1 Task 1.2.

Covers the two things the activity feed can get wrong: presenting an indexed
vault FILE as if it were a capture EVENT, and folding `sync_scheduler`'s
pass-level aggregate counts in as if each were a row. Plus the server-side
limit clamp and the X-Omni-Secret guard on the new route.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
GUI_SECRET = "omni-test-secret-0123456789abcdef"
os.environ["OMNI_GUI_SECRET"] = GUI_SECRET

from fastapi.testclient import TestClient

import capture_log
import server
import sync_activity
from index_writer import log_capture_db, upsert_capture_from_file

SECRET = "sync-activity-test-secret"
HEADERS = {"X-Omni-Secret": SECRET}


class _FakeVault:
    def __init__(self, root: Path) -> None:
        self.root = root


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self.vault = _FakeVault(root)


@pytest.fixture
def gui(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setenv("OMNI_GUI_SECRET", SECRET)
    monkeypatch.setattr(server, "_get_vault_root", lambda: vault)
    # read_activity resolves the vault through capture_log.read_log, which reads
    # get_config().vault.root -- the same value server._get_vault_root returns.
    monkeypatch.setattr(capture_log, "get_config", lambda: _FakeConfig(vault))
    return TestClient(server.app), vault


def _capture(vault: Path, name: str, ts: str, input_type: str = "url",
             filename: str | None = "cap") -> None:
    note = vault / f"{name}.md"
    note.write_text("body\n", encoding="utf-8")
    log_capture_db(
        {"timestamp": ts, "project": "Tech_Notes", "filepath": str(note),
         "filename": filename, "input_type": input_type,
         "source_url": "https://example.com/a", "model": "m", "confidence": 0.9},
        vault,
    )


# -- pure shaping -------------------------------------------------------------

def test_limit_is_clamped_both_ends():
    assert sync_activity._clamp_limit(0) == 1
    assert sync_activity._clamp_limit(-99) == 1
    assert sync_activity._clamp_limit(5) == 5
    assert sync_activity._clamp_limit(10_000) == sync_activity.MAX_LIMIT
    assert sync_activity._clamp_limit(None) == sync_activity.DEFAULT_LIMIT


def test_kind_separates_capture_events_from_indexed_vault_files():
    """captures.db is written by two paths; only capture_log sets input_type.
    A row without it is a file the reindexer saw, not an event."""
    assert sync_activity._shape_row({"input_type": "clipboard"})["kind"] == "capture"
    assert sync_activity._shape_row({"input_type": None})["kind"] == "note"
    assert sync_activity._shape_row({})["kind"] == "note"


def test_failed_capture_is_marked_not_dropped():
    row = sync_activity._shape_row({"input_type": "text", "filename": None})
    assert row["status"] == "failed"
    assert sync_activity._shape_row({"input_type": "text", "filename": "x"})["status"] == "ok"
    # A row with no input_type is a vault file, never a "failed capture".
    assert sync_activity._shape_row({"filename": None})["status"] == "ok"


# -- endpoint -----------------------------------------------------------------

def test_activity_is_newest_first_and_bounded(gui):
    client, vault = gui
    _capture(vault, "old", "2026-08-01T09:00:00")
    _capture(vault, "mid", "2026-08-02T09:00:00")
    _capture(vault, "new", "2026-08-03T09:00:00")

    r = client.get("/sync/activity", params={"limit": 2}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 2
    assert body["count"] == 2
    ats = [e["at"] for e in body["events"]]
    assert ats == sorted(ats, reverse=True)
    assert ats[0].startswith("2026-08-03")


def test_activity_clamps_an_absurd_limit(gui):
    client, _ = gui
    r = client.get("/sync/activity", params={"limit": 100000}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["limit"] == sync_activity.MAX_LIMIT


def test_indexed_note_appears_as_a_note_not_a_capture(gui):
    client, vault = gui
    _capture(vault, "cap", "2026-08-01T09:00:00")
    plain = vault / "plain.md"
    plain.write_text("---\nid: n1\norigin: note\n---\nbody\n", encoding="utf-8")
    upsert_capture_from_file(vault, plain)

    events = client.get("/sync/activity", headers=HEADERS).json()["events"]
    by_path = {Path(e["path"]).name: e for e in events}
    assert by_path["plain.md"]["kind"] == "note"
    assert by_path["cap.md"]["kind"] == "capture"


def test_pass_level_counts_are_never_folded_in_as_events(gui):
    """sync_scheduler.status()['history'] rows are aggregate counts with no note
    ids. The activity feed must not carry them -- rendering one as an event
    would invent a row that never existed."""
    client, vault = gui
    _capture(vault, "cap", "2026-08-01T09:00:00")
    events = client.get("/sync/activity", headers=HEADERS).json()["events"]
    assert events
    aggregate_keys = {"uploaded", "reconciled", "conflicts", "pulled",
                      "inbox_ingested", "enriched", "errors", "duration_s"}
    for e in events:
        assert not (aggregate_keys & set(e)), e
        assert e["path"], "every activity event names a real file"


def test_activity_requires_the_secret(gui):
    client, _ = gui
    assert client.get("/sync/activity").status_code in (401, 403)
    assert client.get("/sync/activity", headers={"X-Omni-Secret": "wrong"}).status_code == 403


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

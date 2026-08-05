"""
test_sync_pending.py — Phase-1 Task 1.3.

The panel this backs can lie in seven distinct ways; each one has a test here.

  1. F-1 notes pending forever                -> test_hub_f1_note_is_blocked_not_uploading
  2. direction inverted on an advanced head   -> test_hub_advanced_head_*
  3. sidecar loss reads as mass-pending       -> test_sidecar_loss_lands_in_unknown_not_changed
  4. ignore-set corruption reads as all-synced-> test_unreadable_ignore_set_*
  5. captures invisible until a flag flips    -> test_captures_are_never_counted_and_never_written
  6. enrichment makes notes "pending"         -> test_resting_label_never_claims_a_user_edit
  7. attachments structurally invisible       -> test_scope_declares_attachments_uncounted

Plus the two hard invariants: the resting read issues ZERO network calls, and
this whole module is read-only (note bytes and the sidecar are byte-identical
after a call).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
GUI_SECRET = "omni-test-secret-0123456789abcdef"
os.environ["OMNI_GUI_SECRET"] = GUI_SECRET

from fastapi.testclient import TestClient

import config
import drive_auth
import mobile_sync_agent
import server
import sync_pending

SECRET = "sync-pending-test-secret"
HEADERS = {"X-Omni-Secret": SECRET}


class _FakeSync:
    def __init__(self, mirror_captures: bool = False) -> None:
        self.mirror_captures = mirror_captures


class _FakeConfig:
    def __init__(self, mirror_captures: bool = False) -> None:
        self.sync = _FakeSync(mirror_captures)


def _write_note(vault: Path, name: str, note_id: str, body: str = "body\n") -> Path:
    d = vault / "Tech_Notes"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(f"---\nid: {note_id}\norigin: note\n---\n{body}", encoding="utf-8")
    return p


def _sidecar(vault: Path, rows: dict) -> Path:
    d = vault / ".omni_capture"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "mobile_sync_state.json"
    p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return p


def _hash_of(vault: Path, note_id: str) -> str:
    return mobile_sync_agent.read_vault_notes(str(vault), False)[note_id]["hash"]


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    v.mkdir(parents=True)
    monkeypatch.setattr(config, "get_config", lambda: _FakeConfig())
    # Any Drive construction at all is a bug in the resting path.
    monkeypatch.setattr(
        drive_auth, "get_drive_service",
        lambda *a, **k: pytest.fail("resting /sync/pending constructed a Drive client"),
    )
    return v


@pytest.fixture
def gui(vault, monkeypatch):
    monkeypatch.setenv("OMNI_GUI_SECRET", SECRET)
    monkeypatch.setattr(server, "_get_vault_root", lambda: vault)
    return TestClient(server.app), vault


# -- resting posture ----------------------------------------------------------

def test_resting_read_is_local_only_and_splits_changed_from_unknown(vault):
    _write_note(vault, "synced", "n-synced")
    _write_note(vault, "edited", "n-edited")
    _write_note(vault, "fresh", "n-fresh")
    _sidecar(vault, {
        "n-synced": {"drive_file_id": "d1", "base_rev": "r1",
                     "local_hash": _hash_of(vault, "n-synced")},
        "n-edited": {"drive_file_id": "d2", "base_rev": "r2", "local_hash": "STALE"},
    })

    out = sync_pending.local_pending(vault)

    assert out["status"] == "ok"
    assert out["label"] == "Changed since last sync"
    assert out["changed"] == 1                       # n-edited
    assert out["unknown"] == 1                       # n-fresh, no sidecar row
    ids = {i["id"]: i["reason"] for i in out["items"]}
    assert ids == {"n-edited": "content_changed", "n-fresh": "no_sync_record"}
    assert out["hub"] is None


def test_resting_label_never_uses_the_word_queue(vault):
    """The word promises drain semantics a local-only source cannot honour."""
    _write_note(vault, "a", "n-a")
    out = sync_pending.local_pending(vault)
    assert "queue" not in json.dumps(out).lower()


def test_resting_label_never_claims_a_user_edit(vault):
    """Lie 6: enrich_notes rewrites frontmatter with no user edit, and the
    sidecar stores one whole-content hash -- so 'changed' must never be worded
    as 'you edited' and must never be worded as 'will upload'."""
    _write_note(vault, "a", "n-a")
    _sidecar(vault, {"n-a": {"drive_file_id": "d", "base_rev": "r", "local_hash": "STALE"}})
    out = sync_pending.local_pending(vault)
    assert out["changed"] == 1
    text = json.dumps(out).lower()
    assert "will upload" not in text and "will_upload" not in text


def test_sidecar_loss_lands_in_unknown_not_changed(vault):
    """Lie 3: a lost sidecar is NOT mass-pending -- reconcile_changes quietly
    adopts the hub file when the bytes already match
    (mobile_sync_agent.py:959-974). So a missing sidecar must never inflate the
    one number that means 'locally edited'."""
    for i in range(4):
        _write_note(vault, f"n{i}", f"n-{i}")
    out = sync_pending.local_pending(vault)
    assert out["changed"] == 0
    assert out["unknown"] == 4
    assert out["sidecar_present"] is False
    assert out["sidecar_rows"] == 0


def test_ignored_notes_are_excluded(vault):
    _write_note(vault, "public", "n-pub")
    p = _write_note(vault, "private", "n-priv")
    from sync_ignore import set_ignored
    set_ignored(vault, str(p), True)

    out = sync_pending.local_pending(vault)
    assert {i["id"] for i in out["items"]} == {"n-pub"}
    assert out["scope"]["notes_scanned"] == 1


def test_delete_prompts_are_surfaced(vault):
    _write_note(vault, "a", "n-a")
    from delete_detect import save_delete_prompts
    state_path = str(vault / ".omni_capture" / "mobile_sync_state.json")
    (vault / ".omni_capture").mkdir(parents=True, exist_ok=True)
    save_delete_prompts(state_path, {"prompts": {"n-gone": {"kind": "inbound"}},
                                     "pending_fs": {}, "keep_here": {}})
    assert sync_pending.local_pending(vault)["deletes_pending"] == 1


# -- lie 4: the refusal state -------------------------------------------------

def test_unreadable_ignore_set_returns_blocked_with_no_count(vault):
    """The single most dangerous failure on this surface: filter_ignored_notes
    returns {} on a corrupt ignore set (sync_ignore.py:114), so a naive panel
    renders ZERO pending at the exact moment run_pass refuses the whole sync
    (mobile_sync_agent.py:1941-1942)."""
    _write_note(vault, "a", "n-a")
    _write_note(vault, "b", "n-b")
    (vault / ".omni_capture").mkdir(parents=True, exist_ok=True)
    (vault / ".omni_capture" / "sync_ignore.json").write_text("{not json", encoding="utf-8")

    out = sync_pending.local_pending(vault)

    assert out["status"] == "blocked"
    assert out["reason"] == "ignore_set_unreadable"
    assert out["error"]
    for numeric in ("changed", "unknown", "deletes_pending", "items", "sidecar_rows"):
        assert numeric not in out, f"refusal state leaked {numeric!r}"


def test_unreadable_ignore_set_blocks_the_hub_upgrade_too(vault, monkeypatch):
    _write_note(vault, "a", "n-a")
    (vault / ".omni_capture").mkdir(parents=True, exist_ok=True)
    (vault / ".omni_capture" / "sync_ignore.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        drive_auth, "has_cached_credentials",
        lambda *a, **k: pytest.fail("refused sync still reached Drive"),
    )
    out = sync_pending.pending_with_hub(vault)
    assert out["status"] == "blocked"
    assert "changed" not in out


# -- lie 5 + read-only --------------------------------------------------------

def test_captures_are_never_counted_and_never_written(vault, monkeypatch):
    """A capture with no id would be REWRITTEN by read_vault_notes(mirror=True)
    to mint one. A read-only panel may not write to the vault to answer a
    question, so captures are excluded and the payload says so."""
    monkeypatch.setattr(config, "get_config", lambda: _FakeConfig(mirror_captures=True))
    cap = vault / "Tech_Notes" / "cap.md"
    cap.parent.mkdir(parents=True, exist_ok=True)
    cap.write_text("---\ntitle: a capture\n---\nbody\n", encoding="utf-8")
    before = cap.read_bytes()

    out = sync_pending.local_pending(vault)

    assert cap.read_bytes() == before, "read-only panel minted an id into a capture"
    assert out["scope"]["captures_counted"] is False
    assert out["scope"]["mirror_captures_enabled"] is True
    assert out["items"] == []


def test_scope_declares_attachments_uncounted(vault):
    """Lie 7: attachments are presence-is-state with no sidecar row, so they are
    structurally invisible here. The payload declares it rather than implying
    the count is complete."""
    _write_note(vault, "a", "n-a")
    assert sync_pending.local_pending(vault)["scope"]["attachments_counted"] is False


def test_resting_read_mutates_nothing(vault):
    note = _write_note(vault, "a", "n-a")
    side = _sidecar(vault, {"n-a": {"drive_file_id": "d", "base_rev": "r",
                                    "local_hash": "STALE"}})
    note_before, side_before = note.read_bytes(), side.read_bytes()

    sync_pending.local_pending(vault)

    assert note.read_bytes() == note_before
    assert side.read_bytes() == side_before


# -- lies 1 + 2: the hub upgrade ---------------------------------------------

def _wire_hub(monkeypatch, hub_files: dict):
    monkeypatch.setattr(drive_auth, "has_cached_credentials", lambda *a, **k: True)
    monkeypatch.setattr(drive_auth, "get_drive_service", lambda *a, **k: object())
    monkeypatch.setattr(sync_pending, "_find_hub_folder", lambda drive, name=None: "hub-id")
    monkeypatch.setattr(mobile_sync_agent, "get_hub_notes",
                        lambda drive, hub_id: hub_files)


def test_hub_f1_note_is_blocked_not_uploading(vault, monkeypatch):
    """Lie 1: a note with no sidecar row that the hub ALREADY holds is skipped
    by mirror_to_hub (:1144) and owned by reconcile -- it is never an upload,
    and calling it one makes it look stuck forever."""
    _write_note(vault, "f1", "n-f1")
    _write_note(vault, "new", "n-new")
    _wire_hub(monkeypatch, {"n-f1": {"headRevisionId": "rX"}})

    hub = sync_pending.pending_with_hub(vault)["hub"]
    assert hub["status"] == "ok"
    assert [i["id"] for i in hub["will_upload"]] == ["n-new"]
    assert hub["blocked"] == [{"id": "n-f1", "path": hub["blocked"][0]["path"],
                              "reason": "reconcile_owns_no_base_rev"}]


def test_hub_advanced_head_with_local_edit_is_blocked(vault, monkeypatch):
    """Lie 2a: the :1151 guard means mirror_to_hub will NOT upload this."""
    _write_note(vault, "a", "n-a")
    _sidecar(vault, {"n-a": {"drive_file_id": "d", "base_rev": "r1", "local_hash": "STALE"}})
    _wire_hub(monkeypatch, {"n-a": {"headRevisionId": "r2"}})

    hub = sync_pending.pending_with_hub(vault)["hub"]
    assert hub["counts"] == {"will_upload": 0, "blocked": 1, "to_pull": 0}
    assert hub["blocked"][0]["reason"] == "hub_head_advanced"


def test_hub_advanced_head_without_local_edit_is_inbound(vault, monkeypatch):
    """Lie 2b (the inverted direction): the local hash still matches, so the
    resting diff cannot see this note at all -- and the work is a PULL, the
    opposite of what a naive 'pending upload' panel would claim."""
    _write_note(vault, "a", "n-a")
    _sidecar(vault, {"n-a": {"drive_file_id": "d", "base_rev": "r1",
                             "local_hash": _hash_of(vault, "n-a")}})
    _wire_hub(monkeypatch, {"n-a": {"headRevisionId": "r2"}})

    out = sync_pending.pending_with_hub(vault)
    assert out["changed"] == 0 and out["unknown"] == 0      # invisible at rest
    assert out["hub"]["counts"] == {"will_upload": 0, "blocked": 0, "to_pull": 1}
    assert out["hub"]["to_pull"][0]["reason"] == "hub_head_advanced"


def test_hub_only_notes_are_pulls_but_local_trash_is_not(vault, monkeypatch):
    trash = vault / "_trash"
    trash.mkdir()
    (trash / "gone.md").write_text("---\nid: n-gone\norigin: note\n---\nx\n", encoding="utf-8")
    _wire_hub(monkeypatch, {"n-hub": {"headRevisionId": "r"},
                            "n-gone": {"headRevisionId": "r"}})

    hub = sync_pending.pending_with_hub(vault)["hub"]
    assert [i["id"] for i in hub["to_pull"]] == ["n-hub"]


def test_hub_offline_and_not_synced_carry_no_buckets(vault, monkeypatch):
    _write_note(vault, "a", "n-a")

    monkeypatch.setattr(drive_auth, "has_cached_credentials", lambda *a, **k: False)
    off = sync_pending.pending_with_hub(vault)
    assert off["hub"] == {"status": "offline"}
    assert off["status"] == "ok" and off["unknown"] == 1   # resting half still answers

    monkeypatch.setattr(drive_auth, "has_cached_credentials", lambda *a, **k: True)
    monkeypatch.setattr(drive_auth, "get_drive_service", lambda *a, **k: object())
    monkeypatch.setattr(sync_pending, "_find_hub_folder", lambda drive, name=None: None)
    ns = sync_pending.pending_with_hub(vault)
    assert ns["hub"] == {"status": "not_synced"}


def test_hub_failure_degrades_to_offline_not_a_5xx(vault, monkeypatch):
    _write_note(vault, "a", "n-a")
    monkeypatch.setattr(drive_auth, "has_cached_credentials", lambda *a, **k: True)

    def _boom(*a, **k):
        raise RuntimeError("token revoked")

    monkeypatch.setattr(drive_auth, "get_drive_service", _boom)
    out = sync_pending.pending_with_hub(vault)
    assert out["hub"]["status"] == "offline"
    assert "token revoked" in out["hub"]["error"]


# -- endpoint -----------------------------------------------------------------

def test_endpoint_serves_the_resting_payload(gui):
    client, vault = gui
    _write_note(vault, "a", "n-a")
    r = client.get("/sync/pending", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["label"] == "Changed since last sync"
    assert r.json()["hub"] is None


def test_endpoint_requires_the_secret(gui):
    client, _ = gui
    assert client.get("/sync/pending").status_code in (401, 403)
    assert client.get("/sync/pending", headers={"X-Omni-Secret": "wrong"}).status_code == 403


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

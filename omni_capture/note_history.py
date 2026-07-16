"""
note_history.py — F-3 desktop version history: Drive `revisions.list` for one
note + a revision-body preview, backing the NoteEditor history instrument.

Read-only. Restore is NOT implemented here -- the GUI fetches a past
revision's body via `get_revision_body` and writes it back through the
existing `note_editor.write_note_body` path (PUT /note), so a restore is a
completely ordinary user file-write: body-sacred and the next Drive sync
pass uploads it like any other edit. This module never touches the vault.

Version token is Drive's `headRevisionId` (workspace CLAUDE.md shared lock) --
never mtime. Local vault<->Drive identity is resolved via the frontmatter
`id` field through the same `.omni_capture/mobile_sync_state.json` sidecar
mobile_sync_agent.py already maintains (drive_file_id per note id); this
module only ever READS that sidecar, never writes it.

Three legitimate empty states (not errors -- the GUI renders each distinctly,
mock 05-desktop-history.html): "offline" (no cached Drive auth, or Drive
unreachable), "not_synced" (note has no frontmatter id yet, or has never been
uploaded to the hub).
"""
from __future__ import annotations

from pathlib import Path

from frontmatter import read_all_fields, strip_frontmatter
from note_editor import resolve_note_path

STATUS_OK = "ok"
STATUS_OFFLINE = "offline"
STATUS_NOT_SYNCED = "not_synced"


def _sync_state_path(vault_root: Path) -> Path:
    # Mirrors mobile_sync_agent.run_pass()'s own default (B-4: vault-anchored,
    # never CWD-relative).
    return vault_root / ".omni_capture" / "mobile_sync_state.json"


def _sync_entry(vault_root: Path, note_id: str) -> dict | None:
    from mobile_sync_agent import load_state
    state = load_state(str(_sync_state_path(vault_root)))
    entry = state.get(note_id)
    if not entry or not entry.get("drive_file_id"):
        return None
    return entry


def get_note_history(vault_root: Path, path_str: str) -> dict:
    """List Drive revisions for one note, newest first. Never raises for the
    legitimate empty states -- only for a missing/invalid path."""
    path = resolve_note_path(vault_root, path_str)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    from drive_auth import has_cached_credentials
    if not has_cached_credentials():
        return {"status": STATUS_OFFLINE, "revisions": []}

    fields = read_all_fields(path.read_text(encoding="utf-8", errors="ignore"))
    note_id = fields.get("id")
    if not note_id:
        return {"status": STATUS_NOT_SYNCED, "revisions": []}

    entry = _sync_entry(vault_root, note_id)
    if entry is None:
        return {"status": STATUS_NOT_SYNCED, "revisions": []}

    try:
        from drive_auth import get_drive_service
        drive = get_drive_service()
        result = (
            drive.revisions()
            .list(
                fileId=entry["drive_file_id"],
                fields="revisions(id,modifiedTime,size,lastModifyingUser)",
            )
            .execute()
        )
    except Exception:
        # Drive unreachable / token revoked mid-session -- same "offline" state
        # the mock renders, not a 5xx.
        return {"status": STATUS_OFFLINE, "revisions": []}

    revs = result.get("revisions", [])
    out = []
    for i, r in enumerate(revs):
        out.append({
            "id": r["id"],
            "modified_time": r.get("modifiedTime"),
            "size": int(r.get("size") or 0),
            # ponytail: Drive's revisions.list doesn't expose the note's own
            # `device` frontmatter field without downloading each revision's
            # body (N downloads just to render a device label) -- the API's
            # lastModifyingUser (Google account display name) is the nearest
            # free signal. Swap for the frontmatter `device` field only if a
            # per-revision body fetch becomes cheap (e.g. cached).
            "author": (r.get("lastModifyingUser") or {}).get("displayName"),
            "current": i == len(revs) - 1,
        })
    out.reverse()  # newest first, matches the mock
    return {"status": STATUS_OK, "revisions": out}


def get_revision_body(vault_root: Path, path_str: str, revision_id: str) -> str:
    """Fetch one past revision's BODY (frontmatter stripped) for preview/restore."""
    path = resolve_note_path(vault_root, path_str)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    fields = read_all_fields(path.read_text(encoding="utf-8", errors="ignore"))
    note_id = fields.get("id")
    if not note_id:
        raise FileNotFoundError("note has no sync id")
    entry = _sync_entry(vault_root, note_id)
    if entry is None:
        raise FileNotFoundError("note is not synced")

    from drive_auth import get_drive_service
    drive = get_drive_service()
    raw = (
        drive.revisions()
        .get_media(fileId=entry["drive_file_id"], revisionId=revision_id)
        .execute()
    )
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    return strip_frontmatter(text)


# ---------------------------------------------------------------------------
# Smoke test  (python note_history.py) -- exercises the two empty states with
# no real Drive credentials required; the "ok" path is covered by
# test_note_history.py with a mocked Drive service.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        cat = vault / "Tech_Notes"
        cat.mkdir()
        note = cat / "example.md"
        note.write_text(
            "---\ntitle: Example note\ncategory: Tech_Notes\n---\n# Example note\n\nBody.\n",
            encoding="utf-8",
        )

        # T1: no cached Drive auth -> offline, no exception, no browser popup.
        with patch("drive_auth.has_cached_credentials", return_value=False):
            result = get_note_history(vault, str(note))
        assert result == {"status": STATUS_OFFLINE, "revisions": []}
        print("[T1] get_note_history offline  PASS")

        # T2: cached auth but note has no frontmatter id -> not_synced.
        with patch("drive_auth.has_cached_credentials", return_value=True):
            result = get_note_history(vault, str(note))
        assert result == {"status": STATUS_NOT_SYNCED, "revisions": []}
        print("[T2] get_note_history not_synced (no id)  PASS")

        # T3: has an id but never uploaded (absent from sync state sidecar) -> not_synced.
        note2 = cat / "example2.md"
        note2.write_text(
            "---\nid: 01ABCDE\ntitle: Example two\ncategory: Tech_Notes\n---\n# Two\n\nBody two.\n",
            encoding="utf-8",
        )
        with patch("drive_auth.has_cached_credentials", return_value=True):
            result = get_note_history(vault, str(note2))
        assert result == {"status": STATUS_NOT_SYNCED, "revisions": []}
        print("[T3] get_note_history not_synced (never uploaded)  PASS")

    print("\nAll note_history.py smoke tests passed.")

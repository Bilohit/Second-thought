"""test_note_history.py — F-3 version-history backend. The empty states
(offline/not_synced) are covered by note_history.py's own smoke block; this
file covers the "ok" path with a mocked Drive service (no real credentials)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from note_history import get_note_history, get_revision_body, STATUS_OK


@pytest.fixture
def vault(tmp_path):
    cat = tmp_path / "Tech_Notes"
    cat.mkdir()
    note = cat / "example.md"
    note.write_text(
        "---\nid: 01SYNCEDID\ntitle: Example note\ncategory: Tech_Notes\n---\n"
        "# Example note\n\nCurrent body.\n",
        encoding="utf-8",
    )
    state_dir = tmp_path / ".omni_capture"
    state_dir.mkdir()
    (state_dir / "mobile_sync_state.json").write_text(
        json.dumps({"01SYNCEDID": {"drive_file_id": "drivefile123", "base_rev": "rev2"}}),
        encoding="utf-8",
    )
    return tmp_path, note


def test_get_note_history_lists_revisions_newest_first(vault):
    root, note = vault
    fake_drive = MagicMock()
    fake_drive.revisions.return_value.list.return_value.execute.return_value = {
        "revisions": [
            {"id": "rev1", "modifiedTime": "2026-07-10T08:15:00Z", "size": "900"},
            {"id": "rev2", "modifiedTime": "2026-07-12T14:02:00Z", "size": "1200",
             "lastModifyingUser": {"displayName": "desk-a1b2"}},
        ]
    }
    with patch("drive_auth.has_cached_credentials", return_value=True), \
         patch("drive_auth.get_drive_service", return_value=fake_drive):
        result = get_note_history(root, str(note))

    assert result["status"] == STATUS_OK
    revs = result["revisions"]
    assert [r["id"] for r in revs] == ["rev2", "rev1"]  # newest first
    assert revs[0]["current"] is True
    assert revs[1]["current"] is False
    assert revs[0]["author"] == "desk-a1b2"


def test_get_note_history_drive_error_is_offline_not_5xx(vault):
    root, note = vault
    fake_drive = MagicMock()
    fake_drive.revisions.return_value.list.return_value.execute.side_effect = RuntimeError("no network")
    with patch("drive_auth.has_cached_credentials", return_value=True), \
         patch("drive_auth.get_drive_service", return_value=fake_drive):
        result = get_note_history(root, str(note))
    assert result == {"status": "offline", "revisions": []}


def test_get_revision_body_strips_frontmatter(vault):
    root, note = vault
    fake_drive = MagicMock()
    fake_drive.revisions.return_value.get_media.return_value.execute.return_value = (
        b"---\nid: 01SYNCEDID\ntitle: Example note\n---\n# Example note\n\nOlder body.\n"
    )
    with patch("drive_auth.get_drive_service", return_value=fake_drive):
        body = get_revision_body(root, str(note), "rev1")
    assert body == "# Example note\n\nOlder body.\n"
    assert "id: 01SYNCEDID" not in body


def test_get_note_history_missing_note_raises(vault):
    root, _note = vault
    with patch("drive_auth.has_cached_credentials", return_value=True):
        with pytest.raises(FileNotFoundError):
            get_note_history(root, str(root / "Tech_Notes" / "nope.md"))

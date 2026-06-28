import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from index_writer import init_db, upsert_capture_from_file
from vault_sync import purge_orphan_index_entries, sync_vault_indexes


def test_purge_orphan_index_entries_removes_missing_files():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        ghost = vault / "Tech" / "gone.md"
        conn = init_db(vault)
        conn.execute(
            "INSERT INTO captures (timestamp, category, path, hash, filename, body_excerpt) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("2025-01-01T00:00:00", "Tech", str(ghost), "deadbeef", "gone.md", "ghost"),
        )
        conn.commit()
        conn.close()

        removed = purge_orphan_index_entries(vault)

        conn = init_db(vault)
        rows = conn.execute("SELECT path FROM captures").fetchall()
        conn.close()
        assert removed == 1
        assert rows == []


def test_sync_vault_indexes_adds_new_file_and_skips_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "Notes" / "fresh.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Fresh\nNew note body", encoding="utf-8")

        with mock.patch("vault_sync.index_note") as mock_index:
            result = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        assert result["added"] == 1
        assert result["removed"] == 0
        assert mock_index.call_count == 1

        with mock.patch("vault_sync.index_note") as mock_index:
            result2 = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        assert result2["skipped"] == 1
        assert result2["added"] == 0
        mock_index.assert_not_called()


def test_sync_vault_indexes_removes_orphan_on_disk_delete():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "Notes" / "temp.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Temp\nTo be deleted", encoding="utf-8")
        upsert_capture_from_file(vault, note)

        note.unlink()

        with mock.patch("vault_sync.index_note"):
            result = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        conn = init_db(vault)
        rows = conn.execute("SELECT path FROM captures").fetchall()
        conn.close()
        assert result["removed"] == 1
        assert rows == []

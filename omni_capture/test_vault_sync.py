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


def test_sync_preserves_chunk_embeddings_for_existing_files():
    """Chunk rows (id '<parent>::c<i>') must survive a sync while the parent
    file exists, and be purged (counted once) when it is deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "Notes" / "big.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Big\nlong body", encoding="utf-8")
        upsert_capture_from_file(vault, note)

        from vector_store import _connect
        with _connect(vault) as conn:
            for i in range(2):
                conn.execute(
                    "INSERT INTO embeddings (id, embedding, document, category) VALUES (?,?,?,?)",
                    (f"Notes/big.md::c{i}", b"\x00\x00\x80\x3f", "chunk", "Notes"),
                )

        with mock.patch("vault_sync.index_note"):
            result = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        with _connect(vault) as conn:
            n = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert n == 2, f"chunk embeddings wrongly purged (left {n})"
        assert result["removed"] == 0

        # Delete the file: one note removed, counted once (not once per chunk).
        note.unlink()
        with mock.patch("vault_sync.index_note"):
            result2 = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        with _connect(vault) as conn:
            n2 = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert n2 == 0


def test_startup_purge_removes_embeddings_only_orphans():
    """An embedding row with no captures row and no file must be purged at
    startup; one whose file exists must survive."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        keep = vault / "Notes" / "keep.md"
        keep.parent.mkdir(parents=True)
        keep.write_text("# Keep", encoding="utf-8")

        from vector_store import _connect
        with _connect(vault) as conn:
            conn.execute(
                "INSERT INTO embeddings (id, embedding, document, category) VALUES (?,?,?,?)",
                ("Notes/keep.md", b"\x00\x00\x80\x3f", "keep", "Notes"),
            )
            conn.execute(
                "INSERT INTO embeddings (id, embedding, document, category) VALUES (?,?,?,?)",
                ("Notes/ghost.md::c0", b"\x00\x00\x80\x3f", "ghost chunk", "Notes"),
            )

        removed = purge_orphan_index_entries(vault)

        with _connect(vault) as conn:
            ids = {r[0] for r in conn.execute("SELECT id FROM embeddings").fetchall()}
        assert removed == 1
        assert ids == {"Notes/keep.md"}

# test_provisional_index.py
"""
Contract §11 — LAN provisional notes are indexed for search/RAG display ONLY.
Hard lock (CLAUDE.md "files are the source of truth"): a provisional row must
NEVER be usable as dedup/merge/link authority. Every existing dedup/merge/link
read must exclude provisional=1 rows.
"""
from unittest import mock

import index_writer as iw
import vector_store as vs


def _fake_embed(text: str, base_url: str, model: str = vs._DEFAULT_EMBED_MODEL):
    """Deterministic bag-of-words embedding so 'provisional body about x' and
    'real body' land at different points but both are non-zero vectors."""
    import hashlib
    words = text.lower().split()
    vec = [0.0] * 8
    for word in words:
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        for i in range(8):
            vec[i] += ((h >> (i * 4)) & 0xF) / 15.0
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


def test_provisional_row_is_flagged_and_excluded_from_dedup(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = iw.init_db(vault)

    iw.upsert_provisional(
        db, "op1", "noteA", "---\ntags: [x]\n---\nprovisional body\n",
        {"modified": "2026-07-11T00:00:00Z", "category": "Tech_Notes"},
    )

    row = db.execute(
        "SELECT provisional, note_id, body_excerpt FROM captures WHERE note_id = ?",
        ("noteA",),
    ).fetchone()
    assert row is not None
    assert row["provisional"] == 1
    assert row["note_id"] == "noteA"
    assert "provisional body" in row["body_excerpt"]

    # Search/RAG DOES surface it (that's the point of indexing it).
    hits = iw.search("provisional", vault)
    assert any(h["note_id"] == "noteA" for h in hits)

    # But it must never be usable as merge/dedup/link authority. merge.py's
    # find_merge_target is backed by vector_store.best_match() for semantic
    # merge — a provisional-tagged embedding must be excluded from that query.
    cat_dir = vault / "Tech_Notes"
    cat_dir.mkdir()
    real_note = cat_dir / "existing.md"
    real_note.write_text("---\ntags:\n  - x\n---\n\nreal body\n", encoding="utf-8")

    with mock.patch.object(vs, "_embed", side_effect=_fake_embed):
        vs.index_note(vault, cat_dir / "provisional-noteA.md",
                       "provisional body about x", "http://localhost:11434",
                       provisional=True)

        conn = vs._get_conn(vault)
        prov_rows = conn.execute(
            "SELECT provisional FROM embeddings WHERE id LIKE ?", ("%provisional-noteA%",)
        ).fetchall()
        conn.close()
        assert prov_rows and prov_rows[0][0] == 1

        match = vs.best_match(vault, "provisional body about x", "http://localhost:11434",
                               category="Tech_Notes")
    # best_match must never resolve to the provisional-tagged embedding.
    assert match is None or "provisional-noteA" not in match[0]


def test_reindex_bodies_leaves_provisional_body_intact(tmp_path):
    """reindex_bodies() SELECTs canonical rows only (provisional = 0). A
    provisional row's synthetic path can't be read as a real file, so if it
    were included the UPDATE would null out its body_excerpt."""
    vault = tmp_path / "vault"
    vault.mkdir()
    db = iw.init_db(vault)

    iw.upsert_provisional(
        db, "op1", "noteA", "---\n---\nprovisional body\n",
        {"modified": "2026-07-11T00:00:00Z", "category": "Tech_Notes"},
    )
    db.close()

    updated = iw.reindex_bodies(vault)
    assert updated == 0  # no canonical rows to backfill

    conn = iw.init_db(vault)
    row = conn.execute(
        "SELECT body_excerpt FROM captures WHERE note_id = ?", ("noteA",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["body_excerpt"] is not None
    assert "provisional body" in row["body_excerpt"]


def test_stats_total_excludes_provisional_rows(tmp_path):
    """stats()'s dashboard/digest counts must not be inflated by not-yet-
    canonical LAN provisional rows (contract §11)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    db = iw.init_db(vault)

    iw.upsert_provisional(
        db, "op1", "noteA", "---\n---\nprovisional body\n",
        {"modified": "2026-07-11T00:00:00Z", "category": "Tech_Notes"},
    )
    db.close()

    result = iw.stats(vault)
    assert result["total"] == 0
    assert result["recent"] == []


def test_clear_provisional_removes_the_row(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = iw.init_db(vault)

    iw.upsert_provisional(db, "op1", "noteA", "---\n---\nbody\n", {})
    row = db.execute("SELECT id FROM captures WHERE note_id = ?", ("noteA",)).fetchone()
    assert row is not None

    iw.clear_provisional(db, "op1")

    row_after = db.execute("SELECT id FROM captures WHERE note_id = ?", ("noteA",)).fetchone()
    assert row_after is None
    # FTS shadow row is also gone (via the existing AFTER DELETE trigger).
    fts_hits = db.execute(
        "SELECT rowid FROM captures_fts WHERE body MATCH 'body'"
    ).fetchall()
    assert fts_hits == []

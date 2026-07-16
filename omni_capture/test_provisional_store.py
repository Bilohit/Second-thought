# test_provisional_store.py
import json, os
import pytest
import provisional_store as ps
import index_writer as iw

def test_stage_writes_file_and_sidecar(tmp_path):
    sd = str(tmp_path / ".sync")
    body = "---\nt: 1\n---\nHello\n"
    p = ps.stage(sd, "op1", "noteA", body, {"device": "phone", "modified": "2026-07-11T00:00:00Z"})
    assert os.path.isfile(p)
    assert open(p, encoding="utf-8").read() == body            # body byte-identical
    rows = ps.list_provisional(sd)
    assert len(rows) == 1 and rows[0]["note_id"] == "noteA" and rows[0]["op_id"] == "op1"

def test_stage_is_idempotent_on_same_body(tmp_path):
    sd = str(tmp_path / ".sync")
    body = "---\nx: 1\n---\nSame body\n"
    ps.stage(sd, "op1", "noteA", body, {})
    assert ps.stage(sd, "op2", "noteA", body, {}) is None       # same note_id+body-hash → no-op
    assert len(ps.list_provisional(sd)) == 1

def test_different_body_stages_separately(tmp_path):
    sd = str(tmp_path / ".sync")
    ps.stage(sd, "op1", "noteA", "---\n---\nv1\n", {})
    ps.stage(sd, "op2", "noteA", "---\n---\nv2\n", {})
    assert len(ps.list_provisional(sd)) == 2

def test_read_body_roundtrip(tmp_path):
    sd = str(tmp_path / ".sync")
    body = "---\n---\nexact\n"
    ps.stage(sd, "op1", "noteA", body, {})
    assert ps.read_body(sd, "op1") == body

def test_supersede_drops_all_for_note(tmp_path):
    sd = str(tmp_path / ".sync")
    ps.stage(sd, "op1", "noteA", "---\n---\nv1\n", {})
    ps.stage(sd, "op2", "noteA", "---\n---\nv2\n", {})
    ps.stage(sd, "op3", "noteB", "---\n---\nother\n", {})
    dropped = ps.supersede(sd, "noteA")
    assert sorted(dropped) == ["op1", "op2"]
    remaining = ps.list_provisional(sd)
    assert [r["op_id"] for r in remaining] == ["op3"]
    assert not os.path.exists(os.path.join(sd, "provisional", "op1.md"))   # file gone

def test_sweep_drops_orphans_by_ttl(tmp_path):
    sd = str(tmp_path / ".sync")
    ps.stage(sd, "old", "noteA", "---\n---\nx\n", {"staged_at": 100.0})
    ps.stage(sd, "new", "noteB", "---\n---\ny\n", {"staged_at": 10_000.0})
    dropped = ps.sweep(sd, now_ts=10_050.0, ttl_seconds=1000.0)
    assert dropped == ["old"]
    assert [r["op_id"] for r in ps.list_provisional(sd)] == ["new"]

def test_read_body_preserves_crlf(tmp_path):
    sd = str(tmp_path / ".sync")
    body = "---\n---\nline1\r\nline2\r\n"
    ps.stage(sd, "op1", "noteA", body, {})
    assert ps.read_body(sd, "op1") == body


# B-12: a LAN-supplied op_id becoming a filesystem path (<op_id>.md) must never escape the
# staging dir — a forged push with path separators / ".." is rejected before it touches disk.
@pytest.mark.parametrize("bad_op_id", ["../../evil", "..\\evil", "/etc/passwd", "a/b", ""])
def test_stage_rejects_unsafe_op_id(tmp_path, bad_op_id):
    sd = str(tmp_path / ".sync")
    with pytest.raises(ValueError):
        ps.stage(sd, bad_op_id, "noteA", "---\n---\nx\n", {})
    # Nothing escaped the staging dir.
    assert not os.path.exists(tmp_path / "evil.md")
    assert not os.path.exists(tmp_path.parent / "evil.md")


# B-10: staging a LAN provisional must also index it into captures.db (production wiring for
# index_writer.upsert_provisional — previously only the test fixture exercised it).
def test_stage_indexes_provisional_row_into_captures_db(tmp_path):
    sd = str(tmp_path / ".sync")
    body = "---\n---\nprovisional body\n"
    ps.stage(sd, "op1", "noteA", body, {"modified": "2026-07-11T00:00:00Z", "category": "Tech_Notes"})

    db = iw.init_db(tmp_path)
    row = db.execute(
        "SELECT provisional, note_id, body_excerpt FROM captures WHERE note_id = ?", ("noteA",)
    ).fetchone()
    db.close()
    assert row is not None
    assert row["provisional"] == 1
    assert row["note_id"] == "noteA"
    assert "provisional body" in row["body_excerpt"]

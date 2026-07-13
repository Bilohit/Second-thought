# test_provisional_store.py
import json, os
import provisional_store as ps

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

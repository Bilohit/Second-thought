import pytest
from reconcile import Note, reconcile


def mk(**o) -> Note:
    base = dict(
        id="n1", created="2026-01-01T00:00:00Z", origin="note", title="Note",
        aliases=[], tags=[], remind_at=None, category=None, enriched=False,
        enrich_source=None, modified="2026-01-01T00:00:00Z", device="phone-a1",
        attachments=[], extra={}, body="base body",
    )
    base.update(o)
    return Note(**base)


# --- body reconciliation ---
def test_c1_body_edited_both_conflicted_copy():
    base, local = mk(body="b0"), mk(body="local edit")
    remote = mk(body="remote edit", device="desktop", modified="2026-02-02T00:00:00Z")
    r = reconcile(base, local, remote, "n2")
    assert r.merged.body == "local edit"            # local stays in place
    assert r.conflicted_copy is not None
    assert r.conflicted_copy.body == "remote edit"  # remote body preserved
    assert r.conflicted_copy.id == "n2"             # fresh id (C9)
    assert "(conflicted copy desktop" in r.conflicted_copy.title
    assert r.conflicted_copy.enriched is False


def test_body_edited_only_local():
    r = reconcile(mk(body="b0"), mk(body="b1"), mk(body="b0"))
    assert r.merged.body == "b1"
    assert r.conflicted_copy is None


def test_c8_remote_advanced():
    r = reconcile(mk(body="b0"), mk(body="b0"), mk(body="b0-rev5"))
    assert r.merged.body == "b0-rev5"
    assert r.conflicted_copy is None


def test_identical_edits_no_conflict():
    r = reconcile(mk(body="b0"), mk(body="same"), mk(body="same"))
    assert r.merged.body == "same"
    assert r.conflicted_copy is None


def test_never_fabricates_body():
    r = reconcile(mk(body="b0"), mk(body="LEFT"), mk(body="RIGHT"), "x")
    assert r.merged.body in ("LEFT", "RIGHT")  # body-sacred: verbatim one input


def test_body_conflict_without_fresh_id_raises():
    with pytest.raises(ValueError):
        reconcile(mk(body="b0"), mk(body="L"), mk(body="R"))


# --- enrichment frontmatter (silent merge) ---
def test_c2_phone_body_desktop_enrich_clean_merge():
    base, local = mk(body="b0"), mk(body="phone edit")
    remote = mk(body="b0", tags=["finance"], category="work",
                enriched=True, enrich_source="desktop-llm")
    r = reconcile(base, local, remote)
    assert r.conflicted_copy is None
    assert r.merged.body == "phone edit"
    assert "finance" in r.merged.tags
    assert r.merged.category == "work"
    assert r.merged.enriched is True


def test_c3_tags_union_dropped_tag_survives():
    base = mk(tags=["family", "todo"])
    local = mk(tags=["family", "todo", "urgent"])
    remote = mk(tags=["family"])
    assert reconcile(base, local, remote).merged.tags == ["family", "todo", "urgent"]


def test_c4_category_desktop_enriched_wins():
    base = mk(category=None)
    local = mk(category="personal", enrich_source="phone-heuristic")
    remote = mk(category="work", enriched=True, enrich_source="desktop-llm")
    r = reconcile(base, local, remote)
    assert r.merged.category == "work"
    assert r.merged.enrich_source == "desktop-llm"


def test_neither_enriched_category_lww():
    r = reconcile(mk(category="a"), mk(category="b"), mk(category="a"))
    assert r.merged.category == "b"


# --- K-1: user category override beats machine, never reverted (mirrors reconcile.test.ts) ---
def test_k1_user_override_beats_enriched():
    base = mk(category="work", enriched=True, enrich_source="desktop-llm")
    local = mk(category="personal", extra={"category_source": "user"})
    remote = mk(category="work", enriched=True, enrich_source="desktop-llm")
    r = reconcile(base, local, remote)
    assert r.merged.category == "personal"
    assert r.merged.extra["category_source"] == "user"


def test_k1_user_override_on_remote_wins():
    base = mk(category="work")
    local = mk(category="work", enriched=True, enrich_source="desktop-llm")
    remote = mk(category="ideas", extra={"category_source": "user"})
    assert reconcile(base, local, remote).merged.category == "ideas"


def test_k1_both_user_newest_modified_wins():
    local = mk(category="L", modified="2026-07-09T12:00:00Z", extra={"category_source": "user"})
    remote = mk(category="R", modified="2026-07-09T08:00:00Z", extra={"category_source": "user"})
    r = reconcile(mk(category="b"), local, remote)
    assert r.merged.category == "L"
    assert r.merged.extra["category_source"] == "user"


def test_k1_legacy_absent_source_machine_path():
    r = reconcile(mk(category="a"), mk(category="b"), mk(category="a"))
    assert r.merged.extra["category_source"] == "machine"


# --- title, remind_at, identity ---
def test_c6_retitle_id_immutable():
    r = reconcile(mk(title="Old"), mk(title="New"), mk(title="Old"))
    assert r.merged.title == "New"
    assert r.merged.id == "n1"


def test_remind_at_rules():
    t1, t2 = "2026-07-08T09:00:00Z", "2026-07-09T09:00:00Z"
    assert reconcile(mk(), mk(remind_at=t1), mk()).merged.remind_at == t1
    assert reconcile(mk(), mk(), mk(remind_at=t2)).merged.remind_at == t2
    newer_local = reconcile(
        mk(),
        mk(remind_at=t1, modified="2026-07-09T12:00:00Z"),
        mk(remind_at=t2, modified="2026-07-09T08:00:00Z"),
    )
    assert newer_local.merged.remind_at == t1
    newer_remote = reconcile(
        mk(),
        mk(remind_at=t1, modified="2026-07-09T08:00:00Z"),
        mk(remind_at=t2, modified="2026-07-09T12:00:00Z"),
    )
    assert newer_remote.merged.remind_at == t2
    tie = reconcile(mk(), mk(remind_at=t1), mk(remind_at=t2))
    assert tie.merged.remind_at == t2  # equal modified → remote (advancing) wins
    assert reconcile(mk(remind_at=t1), mk(), mk()).merged.remind_at is None
    assert reconcile(mk(), mk(remind_at=t2), mk(remind_at=t2)).merged.remind_at == t2


def test_mixed_iso_precision_ties_compare_equal():
    # peers emit mixed precision; instant compare, not lexicographic (§6.3)
    t1, t2 = "2026-07-08T09:00:00Z", "2026-07-09T09:00:00Z"
    r = reconcile(
        mk(),
        mk(remind_at=t1, modified="2026-07-09T12:00:00.000Z"),
        mk(remind_at=t2, modified="2026-07-09T12:00:00Z"),
    )
    assert r.merged.remind_at == t2  # equal instants → remote wins, precision ignored


def test_identity_immutable_from_base():
    base = mk(id="keep", created="2020-01-01T00:00:00Z", origin="note")
    local = mk(id="hacked", created="1999-01-01T00:00:00Z", origin="capture")
    r = reconcile(base, local, mk())
    assert r.merged.id == "keep"
    assert r.merged.created == "2020-01-01T00:00:00Z"
    assert r.merged.origin == "note"


def test_preserves_unknown_extra_keys_both_sides():
    local = mk(extra={"phone_key": " p"})
    remote = mk(extra={"desktop_key": " d"})
    r = reconcile(mk(), local, remote)
    assert r.merged.extra["phone_key"] == " p"
    assert r.merged.extra["desktop_key"] == " d"


# --- capture-origin (v2.x Track A) ---
def cap(**o) -> Note:
    return mk(**{"origin": "capture", "body": "captured body", **o})


def test_capture_body_both_edited_conflicted_copy_keeps_capture_origin():
    base = cap()
    local = cap(body="phone edit of a capture")
    remote = cap(body="desktop dedupe/merge rewrite", device="desktop",
                 modified="2026-02-02T00:00:00Z")
    r = reconcile(base, local, remote, "c2")
    assert r.merged.body == "phone edit of a capture"
    assert r.conflicted_copy.body == "desktop dedupe/merge rewrite"
    assert r.merged.origin == "capture"
    assert r.conflicted_copy.origin == "capture"
    assert r.conflicted_copy.id == "c2"


def test_capture_frontmatter_only_zero_conflict():
    base = cap(tags=[])
    local = cap(body="edited capture text")
    remote = cap(tags=["clipping"], category="inbox", enriched=True,
                 enrich_source="desktop-llm")
    r = reconcile(base, local, remote)
    assert r.conflicted_copy is None
    assert r.merged.body == "edited capture text"
    assert "clipping" in r.merged.tags
    assert r.merged.origin == "capture"


def test_origin_capture_immutable_through_reconcile():
    base = cap()
    local = cap(origin="note", body="edited")  # hostile/buggy local claim
    r = reconcile(base, local, cap())
    assert r.merged.origin == "capture"


def test_body_sacred_conflicted_copy_body_verbatim():
    base, local = mk(body="ORIGINAL"), mk(body="PHONE BODY")
    remote = mk(body="DESKTOP BODY")
    r = reconcile(base, local, remote, "z")
    assert r.merged.body == "PHONE BODY"
    assert r.conflicted_copy.body == "DESKTOP BODY"

"""Overnight QA stress-audit (Fable S23) — cross-device sync edge cases.

Failing tests here document SUSPECTED BUGS (source untouched, report-only run).
Passing tests confirm edge-case correctness the existing suite doesn't pin down.
"""
from unittest.mock import MagicMock

import pytest

from note_model import parse_note, serialize_note
from reconcile import Note, reconcile
from mobile_sync_agent import (
    mirror_to_hub,
    pull_new_hub_notes,
    reconcile_changes,
)


def _mk(body="b", modified="2026-01-01T00:00:00Z", remind=None, tags=None,
        category=None, enriched=False, extra=None, device="d"):
    return Note(id="01A", created="2026-01-01T00:00:00Z", origin="note", title="T",
                aliases=[], tags=tags or [], remind_at=remind, category=category,
                enriched=enriched, enrich_source=None, modified=modified,
                device=device, attachments=[], extra=dict(extra or {}), body=body)


NOTE_FM = (
    "---\nid: 01A\ntitle: T\norigin: note\ncreated: 2026-01-01T00:00:00Z\n"
    "modified: {modified}\ndevice: {device}\ntags: []\naliases: []\nattachments: []\n"
    "enriched: {enriched}\ncategory: {category}\ncategory_source: {source}\n---\n{body}"
)


# ---------- SUSPECTED BUG 1 (K-1 broken end-to-end): category_source parsed from a real
# note file carries a leading space in Note.extra (" user"), so reconcile's
# `== "user"` check never fires for phone/standard-written notes. ----------

def test_k1_user_override_detected_when_parsed_from_note_text():
    base = parse_note(NOTE_FM.format(modified="2026-01-01T00:00:00Z", device="p",
                                     enriched="false", category="Inbox",
                                     source="machine", body="b"))
    local = parse_note(NOTE_FM.format(modified="2026-01-02T00:00:00Z", device="p",
                                      enriched="false", category="Finance",
                                      source="user", body="b"))     # user re-categorized
    remote = parse_note(NOTE_FM.format(modified="2026-01-03T00:00:00Z", device="d",
                                       enriched="true", category="Random",
                                       source="machine", body="b"))  # desktop LLM
    merged = reconcile(base, local, remote).merged
    # K-1: user override beats desktop-llm enriched category
    assert merged.category == "Finance"


def test_reconcile_serializes_category_source_with_yaml_space():
    base = _mk(extra={"category_source": "machine"})
    local = _mk(category="Finance", extra={"category_source": "user"},
                modified="2026-01-02T00:00:00Z")
    remote = _mk(category="Random", enriched=True, extra={"category_source": "machine"})
    merged = reconcile(base, local, remote).merged
    text = serialize_note(merged)
    assert "category_source: user\n" in text  # today emits "category_source:user" (invalid YAML)


# ---------- SUSPECTED BUG 2: reconcile() crashes (ValueError from _instant) when
# `modified` is empty/absent and remind_at (or both-user category) diverged on both
# sides — desktop notes without a modified stamp poison the reconcile pass. ----------

def test_reconcile_survives_empty_modified_on_remind_at_divergence():
    base = _mk(modified="", remind=None)
    local = _mk(modified="", remind="2026-08-01T00:00:00Z")
    remote = _mk(modified="", remind="2026-09-01T00:00:00Z")
    result = reconcile(base, local, remote)  # today: ValueError from fromisoformat("")
    assert result.merged.remind_at in ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")


# ---------- SUSPECTED BUG 3: when reconcile of a both-changed note FAILS (transient
# download error), the same pass's mirror_to_hub blind-uploads local content over the
# ADVANCED hub head and advances base_rev — the remote edit silently vanishes from
# the canonical head (non-destructive lock). ----------

def test_reconcile_failure_does_not_let_mirror_clobber_advanced_head():
    content = "---\nid: 01A\norigin: note\n---\nlocal edit"
    vault_notes = {"01A": {"id": "01A", "path": "/v/x.md", "content": content,
                           "body": "local edit", "hash": "NEWHASH", "category": None}}
    state = {"01A": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": "OLDHASH"}}
    hub_files = {"01A": {"id": "F1", "headRevisionId": "rev9"}}  # remote advanced

    drive = MagicMock()
    drive.files().get_media().execute.side_effect = RuntimeError("transient 500")

    reconciled, conflicts, failed, state2 = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub",
        write_file=lambda p, c: None, new_id=lambda: "X")
    assert failed == 1  # reconcile could not run

    up_drive = MagicMock()
    up_drive.files().update().execute.return_value = {"id": "F1", "headRevisionId": "rev10"}
    mirror_to_hub(vault_notes, hub_files, state2, up_drive, "hub")
    # Desired: an un-reconciled note whose hub head advanced past base_rev must NOT be
    # blind-uploaded (that discards the remote edit from the canonical head).
    up_drive.files().update().execute.assert_not_called()


# ---------- SUSPECTED BUG 4: pull_new_hub_notes trusts hub frontmatter `category`
# (and `id`) as path components — "../.." escapes the vault root. ----------

def test_pull_never_writes_outside_vault_root(tmp_path):
    evil = "---\nid: 01EVIL\norigin: note\ncategory: ../../outside\n---\nbody"
    hub_files = {"01EVIL": {"id": "FEVIL", "headRevisionId": "r1"}}
    written = {}
    pull_new_hub_notes(
        {}, hub_files, {}, drive=None, vault_root=str(tmp_path / "vault"),
        scratchpad_folder="_scratchpad",
        write_file=lambda p, c: written.__setitem__(p, c),
        download=lambda fid: evil,
    )
    import os
    root = os.path.abspath(str(tmp_path / "vault"))
    for p in written:
        assert os.path.abspath(p).startswith(root + os.sep), f"escaped vault: {p}"


# ---------- Edge-case confirmations (expected to PASS) ----------

def test_crlf_body_conflicted_copy_byte_verbatim():
    base = _mk(body="line1\r\nline2\r\n")
    local = _mk(body="line1\r\nlocal\r\n")
    remote = _mk(body="line1\r\nremote\r\n", device="desktop")
    r = reconcile(base, local, remote, "FRESH")
    assert r.merged.body == "line1\r\nlocal\r\n"
    assert r.conflicted_copy.body == "line1\r\nremote\r\n"
    # serialize round-trip keeps CRLF bytes
    assert parse_note(serialize_note(r.merged)).body == "line1\r\nlocal\r\n"


def test_unicode_body_conflict_verbatim():
    base = _mk(body="héllo ☕\n")
    local = _mk(body="héllo ☕ local\n")
    remote = _mk(body="héllo ☕ remote 中文\n")
    r = reconcile(base, local, remote, "FRESH")
    assert r.conflicted_copy.body == "héllo ☕ remote 中文\n"
    assert r.merged.body == "héllo ☕ local\n"


def test_empty_local_body_vs_remote_edit_is_a_real_conflict():
    """Emptying the body locally is still a user edit — remote must not silently win."""
    base = _mk(body="content\n")
    local = _mk(body="")
    remote = _mk(body="remote rewrite\n")
    r = reconcile(base, local, remote, "FRESH")
    assert r.merged.body == ""                       # local emptying kept in place
    assert r.conflicted_copy is not None
    assert r.conflicted_copy.body == "remote rewrite\n"


def test_note_without_frontmatter_body_sacred_through_reconcile():
    raw = "just a bare body\nno frontmatter\n"
    n = parse_note(raw)
    assert n.body == raw
    merged = reconcile(n, n, n).merged
    assert merged.body == raw


def test_lan_nonce_consume_empty_and_replay():
    import lan_sync
    assert lan_sync._consume_nonce("") is False
    nonce, _exp = lan_sync._issue_nonce()
    assert lan_sync._consume_nonce(nonce) is True
    assert lan_sync._consume_nonce(nonce) is False   # single-use


def test_lan_nonce_cap_evicts_oldest():
    import lan_sync
    lan_sync._nonces.clear()
    minted = [lan_sync._issue_nonce()[0] for _ in range(lan_sync._NONCE_CAP + 10)]
    assert len(lan_sync._nonces) <= lan_sync._NONCE_CAP
    assert lan_sync._consume_nonce(minted[-1]) is True
    lan_sync._nonces.clear()


def test_provisional_stage_rejects_traversal_op_id(tmp_path):
    import provisional_store as ps
    with pytest.raises(ValueError):
        ps.stage(str(tmp_path / ".sync"), "../evil", "01A", "body", {"staged_at": 1.0})


def test_lan_crypto_rejects_short_and_empty_key():
    import lan_crypto
    with pytest.raises(lan_crypto.LanKeyError):
        lan_crypto.seal("x", "")
    with pytest.raises(lan_crypto.LanKeyError):
        lan_crypto.seal("x", "c2hvcnQ=")  # "short"


def test_scheduler_single_flight_second_caller_409(monkeypatch):
    import threading
    from sync_scheduler import SyncScheduler, SyncBusy
    started = threading.Event()
    release = threading.Event()

    def slow_pass():
        started.set()
        release.wait(5)
        return {"ok": True}

    s = SyncScheduler(slow_pass, cfg_fn=lambda: object())
    t = threading.Thread(target=s.run_now)
    t.start()
    started.wait(5)
    with pytest.raises(SyncBusy):
        s.run_now()
    release.set()
    t.join(5)


# ---------- BODY-SACRED: local note writes must be byte-verbatim. write_text with default
# newline=None translates \n -> os.linesep (Windows: a hub \r\n body lands as \r\r\n), then
# the stored local_hash mismatches disk and the corrupted body re-uploads to the hub. ----------

MIXED_BODY = "line1\r\nline2\nline3 — café ☕\r\nfim\n"

# §3.3 adversarial extension: the same two write paths, driven by a table of hostile-but-possible
# bodies. Each row must land on disk byte-identical to the hub bytes — no newline translation, no
# encoding fixup, no truncation at a NUL, no re-fencing of a body that looks like frontmatter.
_ADVERSARIAL_BODIES = [
    ("mixed_crlf_lf", MIXED_BODY),                       # the original s23 regression guard
    ("lone_cr", "line1\rline2\rfim\r"),                  # old-Mac endings: never rewritten
    ("cr_at_eof", "text\r"),
    ("crlf_only", "a\r\nb\r\n"),
    ("no_trailing_newline", "no newline at eof"),
    ("body_looks_like_frontmatter", "---\nid: FAKE\ntitle: not really\n---\nreal body\n"),
    ("body_is_only_a_fence", "---\n"),
    ("nul_byte", "before\x00after\n"),
    ("many_nul_bytes", "\x00\x00\x00\n"),
    ("emoji_rtl_zero_width", "🚀 ‫טקסט בעברית‬ ​zwsp\U0001F469‍\U0001F4BB\n"),
    ("combining_marks", "é́́ café\n"),
    ("empty_body", ""),
    ("whitespace_only", "   \n\t\n"),
    ("ten_mb", "x" * (10 * 1024 * 1024)),
]


@pytest.mark.parametrize("name,body", _ADVERSARIAL_BODIES, ids=[c[0] for c in _ADVERSARIAL_BODIES])
def test_pull_and_reconcile_write_hostile_bodies_verbatim(tmp_path, name, body):
    """Both default write_file paths, byte-for-byte, over the adversarial body table."""
    content = "---\nid: 01B\ntitle: T\norigin: note\ncategory: Inbox\n---\n" + body

    pulled, failed, _ = pull_new_hub_notes(
        {}, {"01B": {"id": "F1", "headRevisionId": "r1"}}, {}, None,
        str(tmp_path), "Scratchpad", download=lambda fid: content)
    assert (pulled, failed) == (1, 0), name
    written = list(tmp_path.rglob("01B.md"))
    assert len(written) == 1
    assert written[0].read_bytes() == content.encode("utf-8"), name

    local_path = tmp_path / "Inbox" / "01B.md"
    vault_notes = {"01B": {"id": "01B", "path": str(local_path), "content": "old",
                           "body": "old", "hash": "H1", "category": "Inbox"}}
    state = {"01B": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": "H1"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = content.encode("utf-8")
    reconciled, conflicts, failed = reconcile_changes(
        vault_notes, {"01B": {"id": "F1", "headRevisionId": "r2"}}, state, drive, "hub")[:3]
    assert (reconciled, conflicts, failed) == (1, 0, 0), name
    assert local_path.read_bytes() == content.encode("utf-8"), name

    # ...and the round-trip through the codec never touches the body either.
    assert parse_note(content).body == body, name
    assert serialize_note(parse_note(content)).endswith(body), name


def test_pull_and_reconcile_write_note_bytes_verbatim(tmp_path):
    content = ("---\nid: 01B\ntitle: T\norigin: note\ncategory: Inbox\n---\n" + MIXED_BODY)

    # pull_new_hub_notes: brand-new hub note written to disk byte-identical.
    pulled, failed, _ = pull_new_hub_notes(
        {}, {"01B": {"id": "F1", "headRevisionId": "r1"}}, {}, None,
        str(tmp_path), "Scratchpad", download=lambda fid: content)
    assert (pulled, failed) == (1, 0)
    written = list(tmp_path.rglob("01B.md"))
    assert len(written) == 1
    assert written[0].read_bytes() == content.encode("utf-8")

    # reconcile_changes PULL branch (remote advanced, local unchanged): default write_file
    # must also be byte-verbatim.
    local_path = tmp_path / "Inbox" / "01B.md"
    vault_notes = {"01B": {"id": "01B", "path": str(local_path), "content": "old",
                           "body": "old", "hash": "H1", "category": "Inbox"}}
    state = {"01B": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": "H1"}}
    hub_files = {"01B": {"id": "F1", "headRevisionId": "r2"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = content.encode("utf-8")
    reconciled, conflicts, failed, _ = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub")
    assert (reconciled, conflicts, failed) == (1, 0, 0)
    assert local_path.read_bytes() == content.encode("utf-8")

"""test_adversarial_inputs.py — §3.3 depth-QA: hostile-but-possible inputs against the
parse / serialize / path / name / time / Drive-misbehavior surfaces of the sync agent.

Table-driven on purpose: each category below is a `_CASES` list + a small number of oracles
applied across every row, so a new hostile input is one row, not one test.

Every test runs on tmp_path or an injected fake. Nothing here touches a real vault or Drive.

The five oracles (one per category):
  1. frontmatter  — parse→serialize is byte-stable for VALID input; invalid input never crashes a
                    sync pass (skip+log) and NEVER rewrites the file's bytes on disk.
  2. bodies       — disk bytes verbatim through every sync path.
                    (lives in test_fable_s23_sync.py::test_pull_and_reconcile_write_note_bytes_verbatim,
                     extended there rather than forked here)
  3. names/paths  — every write lands under the vault root (`resolved.is_relative_to(vault)`).
  4. time         — reconcile decisions never depend on wall-clock ordering; headRevisionId decides.
  5. drive        — a misbehaving hub never marks an op done and never spins a tight loop.

Documented ceilings this file LOCKS IN rather than fixes (see the individual tests):
  - note_model.py:41 — a stray no-colon frontmatter line is absorbed into the PRECEDING key's value.
  - mobile_sync_agent.py:512 — `_safe_path_component` is a CONTAINMENT guard (separator/traversal/
    drive-colon), not a Windows-name sanitizer: CON/NUL/aux/trailing-dot/long/emoji pass through.
  - a BOM-prefixed note file parses as frontmatter-less → read_vault_notes treats it as a capture.
"""
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mobile_sync_agent import (
    _download_content,
    _safe_path_component,
    _sha256,
    mirror_to_hub,
    pull_new_hub_notes,
    read_vault_notes,
    reconcile_changes,
)
from note_model import parse_note, serialize_note
from reconcile import Note, reconcile

# =============================================================================================
# 1. FRONTMATTER / YAML
# =============================================================================================


def _note(**over) -> Note:
    base = dict(
        id="01ABC", created="", origin="note", title="T", aliases=[], tags=[], remind_at=None,
        category=None, enriched=False, enrich_source=None, modified="", device="",
        attachments=[], extra={}, body="body\n",
    )
    base.update(over)
    return Note(**base)


# --- 1a. VALID (canonical) input carrying hostile VALUES. Oracle: byte-stable round-trip. -------

_VALID_VALUE_CASES = [
    ("colon_space_in_title", _note(title="Meeting: notes at 3")),
    ("colon_space_in_extra", _note(extra={"summary": " a: b"})),
    ("tab_in_title", _note(title="a\tb")),
    ("tab_in_tag", _note(tags=["a\tb"])),
    ("list_tags_flow", _note(tags=["one", "two", "three"])),
    ("tag_with_comma_and_quote", _note(tags=['a, b', 'c"d'])),
    ("emoji_rtl_zero_width_title", _note(title="🚀 ‫טקסט‬ ​ end")),
    ("emoji_body", _note(body="🚀​‫שלום‬\n")),
    ("empty_title", _note(title="")),
    ("hash_and_brackets_title", _note(title="#[{]} tricky")),
    ("ten_thousand_tags", _note(tags=[f"t{i}" for i in range(10_000)])),
    ("one_mb_frontmatter_value", _note(title="x" * 1_000_000)),
    ("one_mb_extra_value", _note(extra={"blob": " " + "y" * 1_000_000})),
]


@pytest.mark.parametrize("name,note", _VALID_VALUE_CASES, ids=[c[0] for c in _VALID_VALUE_CASES])
def test_valid_input_round_trips_byte_stable(name, note):
    """Oracle 1a: for VALID input, parse→serialize is byte-identical (and the body is verbatim)."""
    text = serialize_note(note)          # canonical text by construction
    again = serialize_note(parse_note(text))
    assert again == text, f"{name}: canonical text is not byte-stable across a round-trip"
    assert parse_note(text).body == note.body


# --- 1b. INVALID / degenerate STRUCTURE. Oracle: never raises; serialize∘parse reaches a fixed
#         point in one pass (so a note can never oscillate between two forms across syncs). -------

_STRAY = "---\nid: 01ABC\nSTRAY LINE WITH NO COLON\ntitle: T\norigin: note\n---\nbody\n"

_RAW_TEXT_CASES = [
    ("empty_file", ""),
    ("frontmatter_only_empty_body", "---\nid: 01A\ntitle: T\norigin: note\n---\n"),
    ("empty_frontmatter_block", "---\n---\nbody\n"),
    ("no_closing_fence", "---\nid: 01A\ntitle: T\norigin: note\nbody text\n"),
    ("bom_prefixed", "﻿---\nid: 01A\ntitle: T\norigin: note\n---\nbody\n"),
    ("stray_no_colon_line", _STRAY),
    ("duplicate_keys", "---\nid: 01A\ntitle: first\ntitle: second\norigin: note\n---\nbody\n"),
    ("duplicate_id_keys", "---\nid: 01A\nid: 02B\norigin: note\n---\nbody\n"),
    ("tags_block_list", "---\nid: 01A\norigin: note\ntags:\n  - a\n  - b\n---\nbody\n"),
    ("tags_bare_scalar", "---\nid: 01A\norigin: note\ntags: solo\n---\nbody\n"),
    ("tags_scalar_where_list_expected", "---\nid: 01A\norigin: note\ntags: []\n---\nbody\n"),
    ("tab_indented_frontmatter", "---\n\tid: 01A\n\ttitle: T\n---\nbody\n"),
    ("body_starts_like_frontmatter", "---\nid: 01A\norigin: note\n---\n---\nfake: yes\n---\nreal\n"),
    ("crlf_frontmatter", "---\r\nid: 01A\r\norigin: note\r\n---\r\nbody\r\n"),
    ("only_fences", "---\n"),
    ("garbage_not_markdown", "\x00\x01\x02 not a note at all"),
    ("fence_with_trailing_space", "---  \nid: 01A\norigin: note\n---  \nbody\n"),
]


@pytest.mark.parametrize("name,text", _RAW_TEXT_CASES, ids=[c[0] for c in _RAW_TEXT_CASES])
def test_degenerate_frontmatter_never_raises_and_reaches_a_fixed_point(name, text):
    """Oracle 1b: parse/serialize never raise on hostile structure, and one serialize pass is a
    fixed point — a degenerate note can never flip-flop between two forms on successive syncs
    (which would be an infinite re-upload loop against the hub)."""
    note = parse_note(text)
    once = serialize_note(note)
    twice = serialize_note(parse_note(once))
    assert twice == once, f"{name}: serialize∘parse is not idempotent → sync flip-flop risk"


@pytest.mark.parametrize("name,text", _RAW_TEXT_CASES, ids=[c[0] for c in _RAW_TEXT_CASES])
def test_degenerate_frontmatter_body_survives_reparse(name, text):
    """The body captured by the first parse survives the round-trip verbatim, whatever the
    frontmatter did (body-sacred holds even for input we could not understand)."""
    body = parse_note(text).body
    assert parse_note(serialize_note(parse_note(text))).body == body


# --- 1c. The KNOWN, DELIBERATE lossy case. Locked, not fixed. ---------------------------------


def test_stray_no_colon_line_is_absorbed_into_the_previous_key_still():
    """CEILING LOCK (note_model.py:41 `_split_entries`: a non-key line is a continuation of the
    preceding key). A stray no-colon frontmatter line is NOT dropped and NOT preserved as its own
    line — it is folded into the value above it. Verified STILL lossy on purpose; do not "fix".

    Consequence documented here so nobody rediscovers it: the fold can corrupt `id`.
    Mitigation already in place: read_vault_notes/pull_new_hub_notes read ids through
    frontmatter.read_all_fields (line-based, no continuation), which is unaffected.
    """
    note = parse_note(_STRAY)
    assert note.id == "01ABC\nSTRAY LINE WITH NO COLON"   # folded, not dropped
    assert "STRAY LINE WITH NO COLON" in serialize_note(note)  # survives, but inside the id value
    # and it is at least STABLE — the corruption does not grow on each round-trip
    assert serialize_note(parse_note(serialize_note(note))) == serialize_note(note)


def test_read_all_fields_is_immune_to_the_stray_line_fold():
    """The path-deciding reader (frontmatter.read_all_fields) is line-based, so the stray-line
    ceiling above can never leak a corrupted id into a vault path."""
    from frontmatter import read_all_fields
    assert read_all_fields(_STRAY)["id"] == "01ABC"


# --- 1d. THE REAL ORACLE: a hostile vault never crashes a sync pass and never rewrites disk. ----


def _fake_drive(rev="rev1", file_id="F1"):
    drive = MagicMock()
    drive.files().create().execute.return_value = {"id": file_id, "headRevisionId": rev}
    drive.files().update().execute.return_value = {"id": file_id, "headRevisionId": rev}
    return drive


def test_hostile_vault_never_crashes_a_sync_pass_and_never_touches_disk_bytes(tmp_path):
    """Oracle 1 (the load-bearing half): seed a vault with EVERY degenerate frontmatter case, run
    the read + mirror halves of a real pass, and assert (a) no crash, (b) every file's bytes on
    disk are byte-identical afterwards — nothing truncated, nothing normalized, no body altered."""
    before: dict[Path, bytes] = {}
    for i, (name, text) in enumerate(_RAW_TEXT_CASES):
        p = tmp_path / f"{i:02d}_{name}.md"
        p.write_text(text, encoding="utf-8", newline="")
        before[p] = p.read_bytes()

    notes = read_vault_notes(str(tmp_path))            # must not raise
    uploaded, failed, _ = mirror_to_hub(notes, {}, {}, _fake_drive(), "hub")  # must not raise
    assert failed == 0
    assert uploaded == len(notes)

    for p, raw in before.items():
        assert p.read_bytes() == raw, f"{p.name}: a read-only sync pass rewrote the file"


def test_bom_prefixed_note_syncs_and_is_left_byte_identical(tmp_path):
    """SYNC-08 (fixed in Batch 7): a UTF-8 BOM used to defeat the `\\A---` frontmatter match, so the
    file read as having NO frontmatter → no `id` → read_vault_notes skipped it and the note was
    invisible to sync forever. read_vault_notes now parses AROUND the BOM: the note is seen, its
    body excludes the frontmatter, and the file on disk is still byte-identical (the BOM is never
    rewritten away — that would churn bytes and cause a re-upload loop)."""
    p = tmp_path / "bom.md"
    text = "﻿---\nid: 01BOM\ntitle: T\norigin: note\n---\nbody\n"
    p.write_text(text, encoding="utf-8", newline="")
    notes = read_vault_notes(str(tmp_path))
    assert list(notes) == ["01BOM"]
    assert notes["01BOM"]["body"] == "body\n"
    assert notes["01BOM"]["content"] == text              # hashed/uploaded bytes stay verbatim
    assert p.read_text(encoding="utf-8", newline="") == text  # and untouched on disk


def test_unreadable_note_degrades_to_skip_not_crash(tmp_path):
    """Invalid UTF-8 in a vault .md → skip+log, never an exception out of the pass."""
    (tmp_path / "bad.md").write_bytes(b"---\nid: 01A\norigin: note\n---\n\xff\xfe body")
    (tmp_path / "good.md").write_text(
        "---\nid: 01G\norigin: note\n---\nok\n", encoding="utf-8", newline="")
    notes = read_vault_notes(str(tmp_path))
    assert list(notes) == ["01G"]   # the bad file is skipped, the good one still syncs


# =============================================================================================
# 3. NAMES / PATHS   (category 2 — bodies — lives in test_fable_s23_sync.py, extended there)
# =============================================================================================

# (name, note_id, category, guard_rejects, pull_writes_a_file)
#   guard_rejects      → `_safe_path_component` raises on the hostile component (containment fires)
#   pull_writes_a_file → after pull_new_hub_notes, a .md is expected to exist inside the vault
# The two differ on purpose in two places, both documented:
#   - empty_id: an empty frontmatter `id` is not a path component at all — pull falls back to the
#     hub key, so the guard never sees "" and the note lands normally.
#   - name_300: passes the guard (contained) but the OS refuses the write → degrades to failed.
_NAME_CASES = [
    ("dotdot_id",            "..",              "Inbox", True,  False),
    ("dotdot_traversal_id",  "../evil",         "Inbox", True,  False),
    ("dotdot_deep_id",       "../../../evil",   "Inbox", True,  False),
    ("single_dot_id",        ".",               "Inbox", True,  False),
    ("drive_letter_id",      "C:\\evil",        "Inbox", True,  False),
    ("drive_letter_bare_id", "C:evil",          "Inbox", True,  False),
    ("backslash_id",         "sub\\evil",       "Inbox", True,  False),
    ("forward_slash_id",     "sub/evil",        "Inbox", True,  False),
    ("unc_id",               "\\\\host\\share", "Inbox", True,  False),
    ("empty_id",             "",                "Inbox", True,  True),   # → falls back to hub key
    ("dotdot_category",      "01A",             "..",    True,  False),
    ("traversal_category",   "01A",             "../..", True,  False),
    ("abs_category",         "01A",             "/etc",  True,  False),
    ("drive_category",       "01A",             "D:\\",  True,  False),
    # --- pass the guard: reserved Windows device names ---
    ("reserved_con",         "CON",             "Inbox", False, True),
    ("reserved_nul",         "NUL",             "Inbox", False, True),
    ("reserved_aux",         "aux",             "Inbox", False, True),
    ("reserved_com1",        "COM1",            "Inbox", False, True),
    ("reserved_category",    "01A",             "CON",   False, True),
    # --- pass the guard: trailing dot / space, long names, emoji, exotic-but-contained ---
    ("trailing_dot",         "note.",           "Inbox", False, True),
    ("trailing_space",       "note ",           "Inbox", False, True),
    ("leading_space",        " note",           "Inbox", False, True),
    ("triple_dot",           "...",             "Inbox", False, True),
    ("name_255",             "n" * 255,         "Inbox", False, False),  # OS refuses → failed+log
    ("name_300",             "n" * 300,         "Inbox", False, False),  # OS refuses → failed+log
    ("emoji_id",             "note-🚀-🎉",       "Inbox", False, True),
    ("emoji_category",       "01A",             "📁cat", False, True),
    ("wildcard_id",          "note*?",          "Inbox", False, False),  # OS refuses → failed+log
    ("nul_byte_id",          "no\x00te",        "Inbox", False, False),  # OS refuses → failed+log
]


@pytest.mark.parametrize(
    "name,note_id,category,rejects,writes", _NAME_CASES, ids=[c[0] for c in _NAME_CASES]
)
def test_safe_path_component_guard_table(name, note_id, category, rejects, writes):
    """Locks exactly WHICH hostile components `_safe_path_component` refuses. It is a containment
    guard (separator / traversal / drive-colon), NOT a Windows-name sanitizer — the rows with
    rejects=False are the documented pass-through set (see the module docstring). They are safe
    because the containment oracle below still holds for every one of them."""
    hostile = note_id if category == "Inbox" else category
    if rejects:
        with pytest.raises(ValueError):
            _safe_path_component(hostile)
    else:
        assert _safe_path_component(hostile) == hostile


@pytest.mark.parametrize(
    "name,note_id,category,rejects,writes", _NAME_CASES, ids=[c[0] for c in _NAME_CASES]
)
def test_pull_never_writes_outside_the_vault_root(tmp_path, name, note_id, category, rejects, writes):
    """Oracle 3 (universal, applies to EVERY row): a hub-supplied id/category can never place a
    write outside the vault root, and a rejected/undoable one degrades to failed+log — never an
    exception out of the pass, never a partial file elsewhere on the disk.

    Runs against the REAL default write_file on a real tmp vault (no injected writer) so the OS
    path semantics — not a mock's — are what is under test.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"           # canary: must stay empty
    outside.mkdir()
    (outside / "canary.txt").write_text("untouched", encoding="utf-8")

    content = f"---\nid: {note_id}\ntitle: T\norigin: note\ncategory: {category}\n---\nphone body\n"
    pulled, failed, state = pull_new_hub_notes(
        {}, {"HUBKEY": {"id": "F1", "headRevisionId": "r1"}}, {}, None,
        str(vault), "Scratchpad", download=lambda fid: content,
    )

    # Never crashes: the note is either pulled or accounted as failed, never both, never neither.
    assert pulled + failed == 1

    # CONTAINMENT — the load-bearing assertion. Every file that exists is under the vault root.
    for f in vault.rglob("*"):
        assert f.resolve().is_relative_to(vault.resolve()), f"{name}: escaped the vault → {f}"
    # ...and nothing was created anywhere else under tmp_path.
    assert sorted(p.name for p in outside.iterdir()) == ["canary.txt"]
    assert (outside / "canary.txt").read_text(encoding="utf-8") == "untouched"
    assert not (tmp_path / "evil.md").exists()

    if writes:
        assert (pulled, failed) == (1, 0)
        assert len(list(vault.rglob("*.md"))) == 1
    else:
        assert (pulled, failed) == (0, 1)          # guard or OS refused → nothing written
        assert list(vault.rglob("*.md")) == []
        assert state == {}                          # and no state recorded for a refused note


def test_pull_rejects_traversal_before_any_write(tmp_path):
    """The guard runs BEFORE write_file — a rejected component must not even reach the writer."""
    writes: list[str] = []
    pulled, failed, _ = pull_new_hub_notes(
        {}, {"K": {"id": "F1", "headRevisionId": "r1"}}, {}, None,
        str(tmp_path), "Scratchpad",
        write_file=lambda p, c: writes.append(p),
        download=lambda fid: "---\nid: ../../evil\norigin: note\n---\nx\n",
    )
    assert (pulled, failed) == (0, 1)
    assert writes == []


def test_pull_oversized_name_degrades_to_failed_and_leaves_no_partial_file(tmp_path):
    """A 300-char id passes the containment guard but the OS refuses the write → the pass must
    account it failed and leave NO partial file behind (documented degrade, not a crash)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    long_id = "n" * 300
    content = f"---\nid: {long_id}\norigin: note\ncategory: Inbox\n---\nbody\n"
    pulled, failed, state = pull_new_hub_notes(
        {}, {"K": {"id": "F1", "headRevisionId": "r1"}}, {}, None,
        str(vault), "Scratchpad", download=lambda fid: content)
    assert (pulled, failed) == (0, 1)
    assert list(vault.rglob("*.md")) == []
    assert state == {}


def test_pull_emoji_and_reserved_names_land_inside_the_vault(tmp_path):
    """The pass-through set (emoji / reserved device names / trailing dot) still lands under the
    vault root with verbatim bytes — locking the CURRENT, safe behavior of the ceiling."""
    vault = tmp_path / "vault"
    vault.mkdir()
    for nid in ("note-🚀", "CON", "trailing."):
        content = f"---\nid: {nid}\norigin: note\ncategory: Inbox\n---\nbody\n"
        pulled, failed, _ = pull_new_hub_notes(
            {}, {nid: {"id": "F1", "headRevisionId": "r1"}}, {}, None,
            str(vault), "Scratchpad", download=lambda fid, c=content: c)
        assert (pulled, failed) == (1, 0), f"{nid!r} unexpectedly failed to pull"
    for f in vault.rglob("*.md"):
        assert f.resolve().is_relative_to(vault.resolve())
        assert f.read_bytes().endswith(b"body\n")


# =============================================================================================
# 4. TIME
# =============================================================================================

_TIME_CASES = [
    ("empty", ""),                                   # s23 regression: `modified:` with no value
    ("null_literal", "null"),
    ("far_future", "9999-12-31T23:59:59Z"),
    ("pre_1970", "1900-01-01T00:00:00Z"),
    ("year_zero", "0001-01-01T00:00:00Z"),
    ("tz_less", "2026-07-15T10:00:00"),
    ("offset_tz", "2026-07-15T10:00:00+05:30"),
    ("mixed_precision", "2026-07-15T10:00:00.000000Z"),
    ("garbage", "not a timestamp at all"),
    ("numeric_epoch", "1752570000"),
    ("whitespace", "   "),
    ("emoji", "🕐"),
]


@pytest.mark.parametrize("name,stamp", _TIME_CASES, ids=[c[0] for c in _TIME_CASES])
def test_reconcile_never_crashes_on_a_hostile_modified(name, stamp):
    """Oracle 4a: `modified` is INFORMATIONAL (reconcile.py §Note). Any value at all — empty
    (the s23 fix), garbage, pre-1970, tz-less — must merge without raising and without touching
    the body. `_instant` degrades an unparseable stamp to epoch."""
    base = _note(body="base\n", modified=stamp)
    local = _note(body="base\n", modified=stamp, tags=["local"])
    remote = _note(body="base\n", modified=stamp, tags=["remote"])
    r = reconcile(base, local, remote, "cid")
    assert r.merged.body == "base\n"                    # body-sacred
    assert set(r.merged.tags) == {"local", "remote"}    # tags still union
    assert r.conflicted_copy is None


@pytest.mark.parametrize("name,stamp", _TIME_CASES, ids=[c[0] for c in _TIME_CASES])
def test_hostile_modified_reaches_a_fixed_point_in_the_codec(name, stamp):
    """A hostile stamp must not oscillate across syncs. Note the ONE deliberate normalization the
    codec applies (note_model._parse_scalar): the YAML null literals `null` / `~` / empty parse to
    None and re-serialize as `""`. That is a one-way settle on the FIRST pass, stable forever
    after — not a flip-flop — so the fixed point is taken after one serialize."""
    once = serialize_note(parse_note(serialize_note(_note(modified=stamp))))
    assert serialize_note(parse_note(once)) == once


@pytest.mark.parametrize(
    "local_mod,remote_mod",
    [
        ("2026-07-18T00:00:00Z", "2026-07-12T00:00:00Z"),  # local clock +3d ahead of remote
        ("2026-07-12T00:00:00Z", "2026-07-18T00:00:00Z"),  # local clock -3d behind remote
        ("", ""),                                          # both stamps missing
        ("garbage", "9999-01-01T00:00:00Z"),               # unparseable vs far-future
    ],
    ids=["skew_local_ahead", "skew_local_behind", "both_empty", "garbage_vs_future"],
)
def test_pull_decision_is_headrevisionid_not_wall_clock(tmp_path, local_mod, remote_mod):
    """Oracle 4b (the lock): `headRevisionId` is the ONLY version token. Under ±3 days of peer
    clock skew — in EITHER direction, and with unparseable stamps — a remote whose head advanced
    past our base_rev is still pulled verbatim. No mtime/`modified` comparison gates it."""
    local_path = tmp_path / "01T.md"
    local_text = f"---\nid: 01T\norigin: note\nmodified: {local_mod}\n---\nlocal body\n"
    local_path.write_text(local_text, encoding="utf-8", newline="")
    remote_text = f"---\nid: 01T\norigin: note\nmodified: {remote_mod}\n---\nremote body\n"

    drive = MagicMock()
    drive.files().get_media().execute.return_value = remote_text.encode("utf-8")
    vault_notes = {"01T": {"id": "01T", "path": str(local_path), "content": local_text,
                           "body": "local body\n", "hash": _sha256(local_text),
                           "category": None}}
    state = {"01T": {"drive_file_id": "F1", "base_rev": "r1",
                     "local_hash": _sha256(local_text)}}   # local UNCHANGED since last sync
    hub_files = {"01T": {"id": "F1", "headRevisionId": "r2"}}   # head advanced → pull

    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub")
    assert (reconciled, conflicts, failed) == (1, 0, 0)
    assert local_path.read_bytes() == remote_text.encode("utf-8")   # pulled verbatim
    assert new_state["01T"]["base_rev"] == "r2"


def test_upload_decision_ignores_file_mtime_entirely(tmp_path):
    """Oracle 4b (upload half): file mtime is not an input. An ancient mtime and a far-future
    mtime on identical content produce the identical no-upload decision (hash == last-synced)."""
    import os

    results = []
    for mtime in (0, 4_102_444_800):        # 1970-01-01 and 2100-01-01
        p = tmp_path / f"n{mtime}.md"
        text = "---\nid: 01M\norigin: note\n---\nsame body\n"
        p.write_text(text, encoding="utf-8", newline="")
        os.utime(p, (mtime, mtime))
        notes = read_vault_notes(str(tmp_path))
        state = {"01M": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": _sha256(text)}}
        drive = _fake_drive()
        uploaded, failed, _ = mirror_to_hub(notes, {}, state, drive, "hub")
        results.append((uploaded, failed))
        p.unlink()
    assert results == [(0, 0), (0, 0)]      # mtime skew changed nothing


# =============================================================================================
# 5. DRIVE API MISBEHAVIOR (fake-hub injection)
# =============================================================================================


def _vault_note(nid, text, path="/vault/x.md", category=None):
    # title=nid keeps this fixture's resolved hub filename == "<nid>.md" (title-based naming,
    # Task 2.4) so the existing id-keyed assertions below don't need to track a separate title.
    return {nid: {"id": nid, "path": path, "content": text, "body": "b\n",
                  "hash": _sha256(text), "category": category, "title": nid, "created": ""}}


def _n_notes(n):
    out = {}
    for i in range(n):
        nid = f"0{i}"
        text = f"---\nid: {nid}\norigin: note\n---\nb\n"
        out.update(_vault_note(nid, text, path=f"/vault/{nid}.md"))
    return out


class _HttpishError(Exception):
    """Stand-in for googleapiclient.errors.HttpError — the agent catches by Exception, so the
    concrete type is irrelevant; only the status it carries matters for this table."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504], ids=lambda s: f"status_{s}")
def test_hub_error_storm_never_marks_an_op_done_and_never_tight_loops(status):
    """Oracle 5a: under a 429/5xx storm the pass must (a) mark NOTHING done — no state entry, so
    the next pass re-uploads — and (b) attempt each note exactly ONCE per pass. The backoff is the
    scheduler's interval (sync_scheduler), NOT an in-pass retry loop: any in-pass retry would be a
    tight loop against a rate-limited hub."""
    calls = []
    drive = MagicMock()
    def _boom(**kw):
        calls.append(kw)
        raise _HttpishError(status)
    drive.files().create.side_effect = _boom
    drive.files().update.side_effect = _boom

    notes = _n_notes(3)
    uploaded, failed, new_state = mirror_to_hub(notes, {}, {}, drive, "hub")

    assert (uploaded, failed) == (0, 3)
    assert new_state == {}                  # no op marked done → next pass retries all three
    assert len(calls) == 3                  # exactly one attempt per note — NO tight loop


def test_5xx_mid_batch_does_not_abort_the_remaining_notes():
    """Oracle 5b: a 5xx on note #2 must not poison #1/#3 — the failure is per-note, the pass
    completes, and only the failed note is absent from the new state."""
    seen = []
    drive = MagicMock()
    def _create(body=None, **kw):
        name = body["name"]
        seen.append(name)
        if name == "01.md":
            raise _HttpishError(503)
        return MagicMock(execute=MagicMock(return_value={"id": f"F-{name}", "headRevisionId": "r1"}))
    drive.files().create.side_effect = _create

    uploaded, failed, new_state = mirror_to_hub(_n_notes(3), {}, {}, drive, "hub")
    assert (uploaded, failed) == (2, 1)
    assert sorted(new_state) == ["00", "02"]      # the 503'd note stays un-synced
    assert seen == ["00.md", "01.md", "02.md"]    # the batch was not aborted


def test_head_revision_unchanged_but_content_changed_is_trusted_and_ignored():
    """Oracle 5d: `headRevisionId` unchanged while the bytes changed is IMPOSSIBLE per Drive
    semantics. We trust the rev: reconcile_changes must skip the note entirely — no download, no
    write, no state churn. (The lock: headRevisionId is the ONLY version token.)"""
    drive = MagicMock()
    local_text = "---\nid: 01A\norigin: note\n---\nlocal\n"
    writes = {}
    vault_notes = _vault_note("01A", local_text)
    state = {"01A": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": _sha256(local_text)}}
    hub_files = {"01A": {"id": "F1", "headRevisionId": "r1"}}   # SAME rev, hub bytes differ

    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub", write_file=lambda p, c: writes.update({p: c}))

    assert (reconciled, conflicts, failed) == (0, 0, 0)
    assert writes == {}
    assert new_state == state
    drive.files().get_media.assert_not_called()   # we never even looked at the bytes


def test_truncated_download_cannot_destroy_a_locally_edited_body():
    """Oracle 5c: a truncated/corrupt media download (Drive returns 200 with short bytes) is
    NOT detectable — there is no download integrity check anywhere in the pull path (reported).
    What must hold regardless is body-sacred: with a local edit present, the truncated remote
    goes to a CONFLICTED COPY and the local body stays byte-intact in place."""
    local_text = "---\nid: 01A\norigin: note\ndevice: desk\n---\nthe full local body\n"
    base_text = "---\nid: 01A\norigin: note\ndevice: desk\n---\nbase body\n"
    truncated = "---\nid: 01A\norigin: no"      # download cut off mid-frontmatter

    drive = MagicMock()
    drive.files().get_media().execute.return_value = truncated.encode("utf-8")
    drive.revisions().get_media().execute.return_value = base_text.encode("utf-8")
    drive.files().update().execute.return_value = {"id": "F1", "headRevisionId": "r3"}
    drive.files().create().execute.return_value = {"id": "F2", "headRevisionId": "r1"}

    writes: dict[str, str] = {}
    vault_notes = {"01A": {"id": "01A", "path": "/vault/01A.md", "content": local_text,
                           "body": "the full local body\n", "hash": "LOCAL-CHANGED",
                           "category": None}}
    state = {"01A": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": "OLD"}}
    hub_files = {"01A": {"id": "F1", "headRevisionId": "r2"}}

    reconciled, conflicts, failed, _ = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub",
        write_file=lambda p, c: writes.update({p: c}), new_id=lambda: "CC1")

    assert (reconciled, conflicts, failed) == (1, 1, 0)
    # the local body is still there, byte-for-byte — the truncation did not eat it
    assert parse_note(writes["/vault/01A.md"]).body == "the full local body\n"
    # ...and the truncated remote was kept, not silently dropped
    assert "CC1" in "".join(writes)


def test_truncated_download_on_an_unedited_note_is_rejected_by_md5_guard():
    """OF-33 (was a documented gap, now CLOSED): the pull branch used to trust the hub and write a
    truncated 200 verbatim, hashing it as the new base so the next pass never self-healed. With
    Drive's `md5Checksum` now consulted (`_download_content` verifies raw bytes before decode), a
    truncated download no longer matches the hub's checksum → it raises → the reconcile `except`
    holds the state (base_rev NOT advanced) so the next pass retries. Nothing is written.
    """
    full_remote = "---\nid: 01A\norigin: note\n---\nfull remote body\n"
    truncated = "---\nid: 01A\norigin: no"
    hub_md5 = hashlib.md5(full_remote.encode("utf-8")).hexdigest()

    drive = MagicMock()
    drive.files().get_media().execute.return_value = truncated.encode("utf-8")
    writes: dict[str, str] = {}
    local_text = "---\nid: 01A\norigin: note\n---\nfull body\n"
    vault_notes = _vault_note("01A", local_text, path="/vault/01A.md")
    state = {"01A": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": _sha256(local_text)}}
    hub_files = {"01A": {"id": "F1", "headRevisionId": "r2", "md5Checksum": hub_md5}}

    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub", write_file=lambda p, c: writes.update({p: c}))

    assert (reconciled, conflicts, failed) == (0, 0, 1)   # rejected as transient, not adopted
    assert writes == {}                                   # nothing written to the vault
    assert new_state["01A"]["base_rev"] == "r1"           # base held → next pass retries


def test_download_content_md5_guard_passes_matching_bytes_and_rejects_mismatch():
    """OF-33 unit: `_download_content(expected_md5=...)` returns the decoded text when the bytes
    hash to the hub checksum, and raises (transient) when they do not. Omitting the checksum keeps
    the old always-decode behavior (pure superset)."""
    body = "---\nid: n1\norigin: note\n---\nhello\n"
    raw = body.encode("utf-8")
    good_md5 = hashlib.md5(raw).hexdigest()

    drive = MagicMock()
    drive.files().get_media().execute.return_value = raw

    # matching checksum → decoded text
    assert _download_content(drive, "F1", good_md5) == body
    # no checksum → unchanged legacy behavior (still decodes)
    assert _download_content(drive, "F1") == body
    # wrong checksum → raises (caller treats as transient)
    with pytest.raises(ValueError):
        _download_content(drive, "F1", "deadbeef" * 4)


def test_download_failure_holds_the_state_so_the_next_pass_retries():
    """The transient counterpart: a download that RAISES (network/5xx) must leave state untouched
    so the note is retried, rather than being marked reconciled at the new rev."""
    drive = MagicMock()
    drive.files().get_media().execute.side_effect = _HttpishError(503)
    local_text = "---\nid: 01A\norigin: note\n---\nlocal\n"
    state = {"01A": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": _sha256(local_text)}}
    reconciled, conflicts, failed, new_state = reconcile_changes(
        _vault_note("01A", local_text), {"01A": {"id": "F1", "headRevisionId": "r2"}},
        state, drive, "hub", write_file=lambda p, c: None)
    assert (reconciled, conflicts, failed) == (0, 0, 1)
    assert new_state["01A"]["base_rev"] == "r1"      # base NOT advanced → next pass retries

"""test_crash_seams.py — §3.2 crash-window durability / fault injection (desktop).

A kill at ANY write seam must never lose or corrupt data beyond a documented self-heal window.

Method: NO real process kills. Each test injects a fault by monkeypatching ONE seam — do step A,
raise `SimulatedCrash` before step B — and then re-runs the NORMAL startup/sync path (`run_once`)
against the on-disk state the crash left behind, asserting recovery. Everything runs on tmp_path
against the in-memory `FakeHub`; no real vault, no real Drive.

The fake hub (a revision-history-carrying in-memory Drive) and its note/vault helpers are IMPORTED
from `test_fuzz_races` rather than re-authored — a third competing fake is exactly what that
module's docstring warns against. Only the FUZZ-gated *tests* there are skipped without FUZZ=1;
the helpers import fine (`test_sync_sidecar_recovery.py` relies on the same thing).

Per-seam oracle (each test asserts all three):
  1. body-sacred   — no note body is lost, and every surviving body is byte-identical to one an
                     editor actually authored (never truncated, never fabricated).
  2. no hub clobber— recovery never overwrites a hub head it has no proof is stale.
  3. dup uploads   — recovery costs AT MOST ONE extra upload per note, and it is idempotent by
                     content (a byte-identical re-upload that burns a headRevisionId is a defect —
                     a bumped head makes every peer re-pull an unchanged note).

Seams covered (see each test's docstring for the exact A/B split):
  S1  upload succeeded → crash before `save_state` persisted `base_rev`
  S2  sidecar corrupt on disk (truncated JSON / byte-flip) → hub-adopt fallback
  S3  vault file fully written → crash before the sidecar (ledger) recorded it
  S4  vault file written PARTIALLY (truncated body) → next scan must not push it   [BODY-SACRED]
  S5  conflicted copy written → crash before it was uploaded / recorded
"""
from __future__ import annotations

from pathlib import Path

import pytest

from frontmatter import strip_frontmatter
from mobile_sync_agent import (
    get_hub_notes,
    load_state,
    pull_new_hub_notes,
    read_vault_notes,
    reconcile_changes,
    run_once,
    save_state,
)
from note_model import parse_note, serialize_note

# Reuse the §3.1 fake hub + vault helpers; never author a competing fake.
from test_fuzz_races import (
    SCRATCHPAD,
    _bodies_on_disk,
    _fresh,
    _note_with_category,
    _sync_note,
)


class SimulatedCrash(RuntimeError):
    """The injected kill. Raised at a seam in place of a real process death."""


# --------------------------------------------------------------------------- helpers
def _hub_bodies(hub) -> set[str]:
    return {strip_frontmatter(hub.text(r["id"])) for r in hub.all_note_recs()}


def _surviving(hub, vault: Path) -> set[str]:
    """Every body byte-string that still exists ANYWHERE (local disk ∪ hub head)."""
    return _bodies_on_disk(vault) | _hub_bodies(hub)


def _uploads(hub, fid: str) -> int:
    """How many revisions the hub has ever issued for `fid` — one per upload of that file."""
    return len(hub.recs[fid]["revisions"])


def _set_body(path: Path, body: str) -> None:
    """A local editor save: replace the body, leave the frontmatter alone (byte-verbatim IO)."""
    note = parse_note(path.read_text(encoding="utf-8", newline=""))
    note.body = body
    path.write_text(serialize_note(note), encoding="utf-8", newline="")


def _hub_edit(hub, fid: str, body: str) -> None:
    """The peer edits the note on the hub — the head advances past our base_rev."""
    note = parse_note(hub.text(fid))
    note.body = body
    note.device = "phone"
    hub.overwrite(fid, serialize_note(note))


def _recover(vault: Path, state_path: str, hub) -> tuple:
    """The normal startup/sync path, re-run on whatever the crash left on disk."""
    return run_once(str(vault), state_path, hub,
                    vault_root=str(vault), scratchpad_folder=SCRATCHPAD)


def _reconcile_pass(vault: Path, state_path: str, hub, write_file=None) -> tuple:
    """One reconcile pass wired exactly as run_once wires it, but with `write_file` injectable
    (that seam is injected in production precisely so the merge logic is testable without disk).
    Persists the returned state, as run_once would."""
    vault_notes = read_vault_notes(str(vault))
    hub_files = get_hub_notes(hub, "HUB")
    state = load_state(state_path)
    rec, con, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, hub, "HUB", write_file=write_file)
    save_state(state_path, new_state)
    return rec, con, failed


# ===========================================================================
# S1 · hub upload succeeded → crash BEFORE save_state persisted base_rev
# ===========================================================================
def test_s1_crash_after_upload_before_save_state_never_clobbers_a_newer_head(tmp_path, monkeypatch):
    """A: mirror_to_hub uploads the local edit (the hub head advances).
    B: save_state persists the new base_rev.  ← killed here.

    The sidecar is therefore STALE: it still names the pre-upload base_rev and the pre-edit
    local_hash, so the next pass sees "local changed AND remote changed" for a note whose remote
    change is its OWN upload. If the peer then edits the note before we recover, the recovery pass
    must NOT re-upload our (now diverged) body over that newer head — it must reconcile and keep
    both bodies.
    """
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)

    _set_body(Path(local_path), "desktop edit\n")

    def _crash_save_state(_path, _state):
        raise SimulatedCrash("killed after upload, before base_rev was persisted")

    monkeypatch.setattr("mobile_sync_agent.save_state", _crash_save_state)
    with pytest.raises(SimulatedCrash):
        _recover(vault, state_path, hub)
    monkeypatch.undo()

    # The seam really is where we claim: the upload landed, the sidecar never learned of it.
    assert strip_frontmatter(hub.text(fid)) == "desktop edit\n"
    assert load_state(state_path)["s01"]["local_hash"] != _sha_of(local_path)

    # The peer now edits the note — the head moves past anything the desktop has ever seen.
    _hub_edit(hub, fid, "phone edit — never pulled to this desktop\n")
    uploads_before = _uploads(hub, fid)

    _recover(vault, state_path, hub)

    surviving = _surviving(hub, vault)
    assert "phone edit — never pulled to this desktop\n" in surviving, (
        "recovery blind-uploaded a stale body over a head the peer had advanced — the remote edit "
        "is gone from both sides with no conflicted copy; non-destructive lock violated")
    assert "desktop edit\n" in surviving, "the desktop's own edit was dropped by recovery"
    assert _uploads(hub, fid) - uploads_before <= 1, (
        "recovery cost more than one upload for the note — not idempotent")


def test_s1_crash_after_upload_reconverges_without_a_duplicate_upload(tmp_path, monkeypatch):
    """The quiet half of S1: nobody else touched the note while we were dead. Recovery must
    re-establish base_rev and converge — the local body is ALREADY the hub head (we uploaded it),
    so a content compare should make this a no-op rather than another write."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)
    _set_body(Path(local_path), "desktop edit\n")

    monkeypatch.setattr("mobile_sync_agent.save_state",
                        lambda p, s: (_ for _ in ()).throw(SimulatedCrash("killed pre-save_state")))
    with pytest.raises(SimulatedCrash):
        _recover(vault, state_path, hub)
    monkeypatch.undo()

    uploads_before = _uploads(hub, fid)
    _recover(vault, state_path, hub)

    assert strip_frontmatter(hub.text(fid)) == "desktop edit\n"     # body-sacred, unchanged
    assert _uploads(hub, fid) - uploads_before <= 1, (
        "recovery re-uploaded more than once for an already-landed edit")
    # The sidecar is rebuilt and the note is settled: a further quiet pass must be free.
    settled = _uploads(hub, fid)
    _recover(vault, state_path, hub)
    assert _uploads(hub, fid) == settled, (
        "a quiet pass after recovery still re-uploads — the sidecar never reconverged, so every "
        "future pass burns a headRevisionId and makes every peer re-pull an unchanged note")


def _sha_of(path: str) -> str:
    from mobile_sync_agent import _sha256
    return _sha256(Path(path).read_text(encoding="utf-8", newline=""))


# ===========================================================================
# S2 · sidecar corrupt on disk (crash mid-save_state / external byte-flip)
# ===========================================================================
@pytest.mark.parametrize("corrupt", [
    pytest.param(b'{"s01": {"drive_file_id": "F0001", "base_re', id="truncated-json"),
    pytest.param(b'{"s01": {"drive_file_id": "F0\xff\xfe01"}}', id="non-utf8-byte-flip"),
    pytest.param(b"", id="zero-length"),
])
def test_s2_corrupt_sidecar_degrades_to_empty_and_never_blind_uploads(tmp_path, corrupt):
    """A: save_state opens the sidecar for writing.  B: the bytes are all flushed.  ← killed here.

    A3 made save_state atomic (tmp sibling + os.replace, mobile_sync_agent.py:146-154), so the LIVE
    sidecar can no longer be left half-written by this module — but the file is still just a file
    (an external truncation, a disk-level tear, a byte-flip), so the corrupt-on-disk state must
    still be survivable. This pins the CURRENT design, and asserts the F-1 window is CLOSED:
    load_state degrades to empty, and the empty sidecar routes to reconcile's baseless-adopt path
    (base_rev stays None) instead of the old fallback's `base_rev = current head`, which made the
    advanced-head guard compare the head against itself and blind-uploaded over an un-pulled edit.
    """
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)
    body_before = strip_frontmatter(Path(local_path).read_text(encoding="utf-8", newline=""))

    _hub_edit(hub, fid, "phone edit — never pulled to this desktop\n")
    Path(state_path).write_bytes(corrupt)          # crash mid-write / byte-flip

    assert load_state(state_path) == {}, "corrupt sidecar must degrade to empty, never raise"

    _recover(vault, state_path, hub)

    # The desktop never edited its own body — recovery may merge machine-owned frontmatter, never a body.
    assert strip_frontmatter(
        Path(local_path).read_text(encoding="utf-8", newline="")) == body_before
    surviving = _surviving(hub, vault)
    assert "phone edit — never pulled to this desktop\n" in surviving, (
        "F-1 window OPEN: a corrupt sidecar let the desktop revert the peer's un-pulled edit")
    assert body_before in surviving, "the desktop's own body was discarded instead"
    # The rebuilt sidecar may only ever name a revision the hub actually issued (never a guess).
    # (Task 3.1: state may also carry the flat "hub_names_migrated" bool flag — skip it, it is
    # not a per-note record.)
    for entry in load_state(state_path).values():
        if not isinstance(entry, dict):
            continue
        rev = entry.get("base_rev")
        assert rev is None or rev in hub.issued_revs, (
            f"rebuilt sidecar claims base_rev={rev!r}, a revision the hub never issued")


def test_s2_corrupt_sidecar_on_an_unchanged_note_is_a_no_op(tmp_path):
    """The idempotence half: a corrupt sidecar with nothing else wrong must cost ZERO uploads.
    (The pre-fix fallback set local_hash=None and re-uploaded byte-identical content, burning a
    headRevisionId per note per corruption.)"""
    hub, vault, state_path = _fresh(tmp_path)
    fid, _ = _sync_note(hub, vault, state_path)
    uploads_before, content_before = _uploads(hub, fid), hub.recs[fid]["content"]

    Path(state_path).write_bytes(b'{"s01": {"drive_file_id": "F0001", "base_re')

    _recover(vault, state_path, hub)

    assert hub.recs[fid]["content"] == content_before
    assert _uploads(hub, fid) == uploads_before, (
        "sidecar corruption re-uploaded identical bytes and burned a headRevisionId — not idempotent")
    assert load_state(state_path).get("s01", {}).get("base_rev"), "sidecar not rebuilt"


# ===========================================================================
# S3 · vault file fully written → crash BEFORE the sidecar (ledger) recorded it
# ===========================================================================
def test_s3_crash_after_vault_write_before_ledger_update_self_heals(tmp_path):
    """A: pull_new_hub_notes writes the pulled note's bytes into the vault.
    B: the sidecar records drive_file_id/base_rev/local_hash for it.  ← killed here.

    The note now exists locally with NO ledger entry — the classic "did it land?" window. The next
    scan must self-heal: adopt the existing hub file (never re-create it as a duplicate orphan),
    never write a second copy of the note into the vault, and never re-upload identical bytes.
    """
    hub, vault, state_path = _fresh(tmp_path)
    hub_body = "phone body — created on the phone\n"
    fid = hub.put("p01.md", _note_with_category("p01", hub_body, "Personal"),
                  hub.folder("Personal"), note_id="p01")

    def _write_then_crash(path: str, content: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8", newline="")   # A: the file lands
        raise SimulatedCrash("killed after the vault write, before the ledger update")

    vault_notes = read_vault_notes(str(vault))
    hub_files = get_hub_notes(hub, "HUB")
    pulled, failed, new_state = pull_new_hub_notes(
        vault_notes, hub_files, {}, hub, str(vault), SCRATCHPAD, write_file=_write_then_crash)
    # This test exercises the pull-crash self-heal window, not Task 3.1's hub-filename migration —
    # p01.md's title ("T", from _note_with_category) legitimately mismatches its legacy filename,
    # which would otherwise make _recover's first run_once pass do a one-time (correct, but
    # orthogonal to what this test pins) migration rename + revision bump. Pre-mark migrated.
    new_state["hub_names_migrated"] = True
    save_state(state_path, new_state)

    assert (pulled, failed) == (0, 1)                       # the pull never completed...
    assert "p01" not in load_state(state_path)              # ...so the ledger has no record
    landed = list(vault.rglob("p01.md"))
    assert len(landed) == 1                                 # ...but the bytes are on disk

    uploads_before = _uploads(hub, fid)
    _recover(vault, state_path, hub)

    copies = list(vault.rglob("*.md"))
    assert len(copies) == 1, f"rescan duplicated the note: {[p.name for p in copies]}"
    assert strip_frontmatter(
        copies[0].read_text(encoding="utf-8", newline="")) == hub_body   # body-sacred
    own = [r["id"] for r in hub.all_note_recs()
           if (r.get("appProperties") or {}).get("noteId") == "p01"]
    assert own == [fid], f"rescan duplicated the hub file for p01: {own}"
    assert _uploads(hub, fid) == uploads_before, (
        "rescan re-uploaded a note whose bytes already ARE the hub head — not idempotent")
    assert load_state(state_path)["p01"]["base_rev"] in hub.issued_revs   # ledger rebuilt, truthfully


# ===========================================================================
# S4 · vault file written PARTIALLY (truncated body)          [BODY-SACRED]
# ===========================================================================
_LONG_BODY = "".join(f"line {i} — café ☕ the quick brown fox\n" for i in range(40))


def test_s4_crash_mid_vault_write_never_pushes_a_truncated_body(tmp_path, monkeypatch):
    """A: reconcile pulls the peer's edit and starts writing it over the local file.
    B: the write completes.  ← killed here, part-way through the bytes.

    The kill is injected INSIDE the production write (Path.write_text, the byte-level call the
    sync-owned default write_file makes) rather than by replacing the injectable `write_file`
    seam — that seam is a pure path→bytes sink for the merge unit tests, so replacing it would
    test the fault, not the write path. Atomicity is the disk writer's property, so only the real
    default can prove it.

    Body-sacred: a truncated body was authored by nobody. The sync-owned write lands via a temp
    SIBLING + os.replace, so a kill mid-write can only tear the temp file — the live note keeps
    its last complete body, and the next scan therefore has nothing mangled to mistake for the
    user's edit and push. The hub head must still hold a body an editor really wrote.
    """
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path, body=_LONG_BODY)

    remote_body = "phone edit — the peer's real body\n"
    _hub_edit(hub, fid, remote_body)

    real_write_text = Path.write_text

    def _partial_write_text(self, data, *a, **kw):
        # A kill mid-write: the frontmatter and part of the body reached the disk, the rest did not.
        head, sep, body = data.partition("\n---\n")
        real_write_text(self, head + sep + body[: len(body) // 2], *a, **kw)
        raise SimulatedCrash("killed mid vault write — partial file on disk")

    monkeypatch.setattr(Path, "write_text", _partial_write_text)
    _reconcile_pass(vault, state_path, hub)      # the DEFAULT write_file — the production path
    monkeypatch.undo()

    on_disk = Path(local_path).read_text(encoding="utf-8", newline="")
    assert strip_frontmatter(on_disk) == _LONG_BODY, (
        "the kill tore the LIVE note: the sync-owned vault write is not atomic, so a truncated "
        "body no editor authored is now indistinguishable from a real local edit")
    assert parse_note(on_disk).id == "s01", "the note no longer parses after the torn write"

    _recover(vault, state_path, hub)

    hub_head = strip_frontmatter(hub.text(fid))
    assert hub_head in (_LONG_BODY, remote_body), (
        f"body-sacred VIOLATED: the hub head now holds a truncated body no editor authored "
        f"({hub_head[:60]!r}...). A kill mid-vault-write propagated corruption to the canonical hub.")
    assert remote_body in _surviving(hub, vault), "the peer's real body was lost entirely"


def test_s4_truncated_frontmatter_is_skipped_not_pushed(tmp_path):
    """The other half of the same non-atomic write: killed EARLIER, so even the frontmatter is
    cut. read_vault_notes finds no `id` and skips the file, so nothing reaches the hub — the
    truncated bytes are contained. Documents the self-heal ceiling: the file is NOT repaired (it
    sits mangled in the vault forever), but the hub head and the peer's edit are untouched."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path, body=_LONG_BODY)
    remote_body = "phone edit — the peer's real body\n"
    _hub_edit(hub, fid, remote_body)

    def _partial_write(path: str, content: str) -> None:
        Path(path).write_text(content[: len(content) // 4], encoding="utf-8", newline="")
        raise SimulatedCrash("killed mid vault write — frontmatter itself truncated")

    _reconcile_pass(vault, state_path, hub, write_file=_partial_write)
    assert read_vault_notes(str(vault)) == {}, "test bug: the truncated file still parses"

    uploads_before = _uploads(hub, fid)
    _recover(vault, state_path, hub)

    assert strip_frontmatter(hub.text(fid)) == remote_body, (
        "an unparseable local file still reached the hub head")
    assert _uploads(hub, fid) == uploads_before, "an unparseable local file triggered an upload"


# ===========================================================================
# S5 · conflicted copy written → crash before it was uploaded / recorded
# ===========================================================================
def test_s5_crash_between_conflicted_copy_write_and_its_upload_self_heals(tmp_path):
    """A: reconcile resolves a body-vs-body divergence — it writes the merged note, uploads it,
    records it, then writes the conflicted copy beside it.
    B: the conflicted copy is uploaded and recorded in the sidecar.  ← killed here.

    The copy now exists ONLY on local disk, with no hub file and no ledger entry — the window where
    the keep-both promise is half-kept. The next scan must finish the job: both bodies intact, the
    copy created on the hub exactly once, the original never re-created as a duplicate.
    """
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)

    _set_body(Path(local_path), "local body — typed on the desktop\n")
    _hub_edit(hub, fid, "remote body — typed on the phone\n")

    written: list[str] = []

    def _crash_on_copy_write(path: str, content: str) -> None:
        Path(path).write_text(content, encoding="utf-8", newline="")
        written.append(path)
        if Path(path) != Path(local_path):
            # A: the conflicted copy has landed on disk. B (its upload + ledger row) never runs.
            raise SimulatedCrash("killed after the conflicted copy was written, before its upload")

    rec, con, failed = _reconcile_pass(vault, state_path, hub, write_file=_crash_on_copy_write)
    assert failed == 1 and con == 0, "test bug: the crash did not land in the conflicted-copy window"

    copies = [p for p in vault.rglob("*.md") if p != Path(local_path)]
    assert len(copies) == 1, "test bug: the conflicted copy was never written"
    copy_path = copies[0]
    copy_body = strip_frontmatter(copy_path.read_text(encoding="utf-8", newline=""))
    assert copy_body == "remote body — typed on the phone\n"
    assert copy_path.stem not in load_state(state_path)          # the copy has no ledger row
    assert copy_path.stem not in {(r.get("appProperties") or {}).get("noteId")
                                  for r in hub.all_note_recs()}  # ...and no hub file

    _recover(vault, state_path, hub)

    surviving = _surviving(hub, vault)
    assert "local body — typed on the desktop\n" in surviving
    assert "remote body — typed on the phone\n" in surviving, (
        "the conflicted copy's body was lost — the keep-both promise stayed half-kept after recovery")
    # The copy reached the hub exactly once, and the original was never duplicated.
    ids = [(r.get("appProperties") or {}).get("noteId") or Path(r["name"]).stem
           for r in hub.all_note_recs()]
    assert len(ids) == len(set(ids)), f"recovery duplicated a hub file: {ids}"
    assert copy_path.stem in ids, "the orphaned conflicted copy never reached the hub"
    assert strip_frontmatter(
        copy_path.read_text(encoding="utf-8", newline="")) == copy_body   # body-sacred, untouched


def test_s5_recovery_of_an_orphaned_copy_is_idempotent(tmp_path):
    """A second quiet pass after the S5 recovery must cost nothing — the healed copy is settled,
    not re-uploaded every pass."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)
    _set_body(Path(local_path), "local body — typed on the desktop\n")
    _hub_edit(hub, fid, "remote body — typed on the phone\n")

    def _crash_on_copy_write(path: str, content: str) -> None:
        Path(path).write_text(content, encoding="utf-8", newline="")
        if Path(path) != Path(local_path):
            raise SimulatedCrash("killed before the conflicted copy was uploaded")

    _reconcile_pass(vault, state_path, hub, write_file=_crash_on_copy_write)
    _recover(vault, state_path, hub)

    before = {r["id"]: r["headRevisionId"] for r in hub.all_note_recs()}
    _recover(vault, state_path, hub)
    after = {r["id"]: r["headRevisionId"] for r in hub.all_note_recs()}

    assert after == before, (
        f"a quiet pass after conflicted-copy recovery still writes to the hub: "
        f"{[f for f in before if before[f] != after.get(f)]}")

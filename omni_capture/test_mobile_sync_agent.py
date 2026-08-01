import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mobile_sync_agent import (
    read_vault_notes,
    load_state,
    save_state,
    mirror_to_hub,
    reconcile_changes,
    enrich_notes,
    _sha256,
    _hub_filename,
    _resolve_hub_names,
    _reap_tmp_orphans,
    _upload_note,
    _FOLDER_MIME,
)
from frontmatter import read_all_fields, strip_frontmatter
from projects import LOOSE_DIR
import project_registry

FM = "---\nid: {id}\ntitle: {title}\norigin: note\n---\n{body}"


def _write(dirpath: Path, fname: str, note_id: str, body: str) -> Path:
    p = dirpath / fname
    p.write_text(FM.format(id=note_id, title="T", body=body), encoding="utf-8", newline="")
    return p


def _reg(*names) -> dict:
    """An in-memory registry holding exactly `names` — what `resolve_project` needs to turn a
    `#project@<name>` body tag into that project rather than into loose."""
    return {"schema": 1, "projects": {n: {"description": ""} for n in names}}


def _write_registry(vault_root: Path, *names) -> dict:
    """The same, written to `<vault>/.projects.toml` for code paths that load it themselves."""
    reg = _reg(*names)
    Path(vault_root).mkdir(parents=True, exist_ok=True)
    project_registry.save(Path(vault_root), reg)
    return reg


def test_read_vault_notes_keys_by_frontmatter_id(tmp_path):
    _write(tmp_path, "anything.md", "01ABC", "Body here")
    notes = read_vault_notes(str(tmp_path))
    assert "01ABC" in notes           # keyed by id, NOT filename stem
    assert "anything" not in notes
    assert notes["01ABC"]["body"] == "Body here"


def test_reap_tmp_orphans_removes_only_md_tmp(tmp_path):
    # OF-19: crash-orphaned <note>.md.tmp files accumulate; the reaper clears them without touching
    # real notes or the state file's own .tmp convention.
    real = _write(tmp_path, "note.md", "01REAL", "keep me")
    orphan = tmp_path / "note.md.tmp"
    orphan.write_text("torn write", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    nested = tmp_path / "sub" / "other.md.tmp"
    nested.write_text("torn too", encoding="utf-8")
    state_tmp = tmp_path / "state.json.tmp"  # NOT a note tmp — must survive
    state_tmp.write_text("{}", encoding="utf-8")

    reaped = _reap_tmp_orphans(str(tmp_path))

    assert reaped == 2
    assert not orphan.exists()
    assert not nested.exists()
    assert real.exists() and real.read_text(encoding="utf-8").endswith("keep me")
    assert state_tmp.exists()


def test_read_vault_notes_skips_files_without_id(tmp_path):
    (tmp_path / "no_id.md").write_text("---\ntitle: X\n---\nBody", encoding="utf-8", newline="")
    assert read_vault_notes(str(tmp_path)) == {}


def test_read_vault_notes_ignores_sync_provisional_staging(tmp_path):
    # N2 live QA (2026-07-12, S4): .sync/provisional/<op_id>.md carries the same
    # frontmatter id as the real note (lan_push stages note["content"] verbatim) —
    # unfiltered rglob let it clobber the real vault entry in the reconcile dict.
    real = _write(tmp_path, "real.md", "01ABC", "Real vault body")
    staging_dir = tmp_path / ".sync" / "provisional"
    staging_dir.mkdir(parents=True)
    _write(staging_dir, "op1.md", "01ABC", "Stale provisional body")

    notes = read_vault_notes(str(tmp_path))

    assert notes["01ABC"]["path"] == str(real)
    assert notes["01ABC"]["body"] == "Real vault body"


# ---------------------------------------------------------------------------
# K-2 · opt-in capture mirroring
# ---------------------------------------------------------------------------

def _write_capture(dirpath: Path, fname: str, body: str, extra_fm: str = "") -> Path:
    """A desktop capture as storage_engine._build_frontmatter actually writes one: no id,
    no origin field at all (origin absent == capture, per contract §2 K-2)."""
    p = dirpath / fname
    p.write_text(f"---\ncategory: Tech_Notes\n{extra_fm}---\n{body}", encoding="utf-8", newline="")
    return p


def test_read_vault_notes_mirror_off_skips_idless_capture(tmp_path):
    # (a) mirror_captures=False (default) -> an id-less capture is skipped, unchanged behaviour.
    cap = _write_capture(tmp_path, "clip.md", "Some clipped text.\n")
    before = cap.read_text(encoding="utf-8")

    notes = read_vault_notes(str(tmp_path), mirror_captures=False)

    assert notes == {}
    assert cap.read_text(encoding="utf-8") == before   # untouched — no id minted while opted out


def test_read_vault_notes_mirror_on_mints_id_and_origin(tmp_path):
    # (b) mirror_captures=True -> the capture gets id+origin minted (frontmatter-only), body
    # byte-identical, and it appears in the returned mirror set (closes B-15).
    body = "Some clipped text.\n"
    cap = _write_capture(tmp_path, "clip.md", body)

    notes = read_vault_notes(str(tmp_path), mirror_captures=True)

    written = cap.read_text(encoding="utf-8")
    fields = read_all_fields(written)
    assert fields["origin"] == "capture"
    assert fields["id"]                                  # a ULID-style id was minted
    assert strip_frontmatter(written) == body            # BODY SACRED — byte-identical
    assert fields["id"] in notes
    assert notes[fields["id"]]["body"] == body


def test_read_vault_notes_mirror_on_id_stable_across_reads(tmp_path):
    # Re-scanning after minting must not mint a second id (idempotent).
    cap = _write_capture(tmp_path, "clip.md", "Body.\n")
    notes1 = read_vault_notes(str(tmp_path), mirror_captures=True)
    id1 = next(iter(notes1))
    notes2 = read_vault_notes(str(tmp_path), mirror_captures=True)
    assert list(notes2.keys()) == [id1]


def test_read_vault_notes_note_with_id_unaffected_by_mirror_flag(tmp_path):
    # (c) an already-id'd origin:note is unaffected either way.
    _write(tmp_path, "n1.md", "01NOTE", "Note body")

    off = read_vault_notes(str(tmp_path), mirror_captures=False)
    on = read_vault_notes(str(tmp_path), mirror_captures=True)

    assert off.keys() == {"01NOTE"} == on.keys()
    assert off["01NOTE"]["body"] == on["01NOTE"]["body"] == "Note body"


def test_read_vault_notes_mirror_off_still_skips_already_minted_capture(tmp_path):
    # Turning mirror_captures back off must keep excluding a capture even if it was minted
    # (has id+origin:capture) during an earlier opted-in pass — "OFF: captures stay
    # desktop-local" applies regardless of a prior id.
    _write_capture(tmp_path, "clip.md", "Body.\n", extra_fm="id: alreadymintedid\norigin: capture\n")
    assert read_vault_notes(str(tmp_path), mirror_captures=False) == {}


def test_mirrored_capture_never_reaches_enrich_fn(tmp_path):
    # A mirrored capture must never be enriched via the note path (notes-are-not-captures).
    cap = _write_capture(tmp_path, "clip.md", "Body.\n")
    vault_notes = read_vault_notes(str(tmp_path), mirror_captures=True)
    assert len(vault_notes) == 1   # sanity: the capture really is in the mirror set

    def classify(text):
        raise AssertionError("must not classify a mirrored capture")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify)
    assert (enriched, failed) == (0, 0)


def test_upload_sync_file_creates_then_updates():
    # §11.8-B: the ONE `.sync/` file (lan_endpoint.json) uploads to the hub. First call creates,
    # second (file now present) updates in place. Fake drive distinguishes the folder-lookup query
    # (mimeType == folder) from the child-list query (mimeType != folder).
    from mobile_sync_agent import upload_sync_file, _FOLDER_MIME

    class _Exec:
        def __init__(self, r): self.r = r
        def execute(self): return self.r

    state = {"children": []}
    calls = {"create": 0, "update": 0}

    class _Files:
        def list(self, q=None, fields=None, pageToken=None):
            if f"mimeType='{_FOLDER_MIME}'" in q:
                return _Exec({"files": [{"id": "syncfolder"}]})   # find-or-create → exists
            return _Exec({"files": list(state["children"])})       # _list_children (mime != folder)
        def update(self, fileId=None, media_body=None):
            calls["update"] += 1
            return _Exec({"id": fileId})
        def create(self, body=None, media_body=None, fields=None):
            calls["create"] += 1
            state["children"].append({"id": "newid", "name": body["name"]})
            return _Exec({"id": "newid"})

    class _Drive:
        def files(self): return _Files()

    drive = _Drive()
    upload_sync_file(drive, "hub", "lan_endpoint.json", '{"device":"d"}')
    assert (calls["create"], calls["update"]) == (1, 0)   # first → create
    upload_sync_file(drive, "hub", "lan_endpoint.json", '{"device":"d2"}')
    assert (calls["create"], calls["update"]) == (1, 1)   # second → update in place


def test_purge_expired_hub_trash_deletes_only_old():
    # OF-16: the desktop is the hub-side purge authority. Sweep _trash/, deleting only notes past the
    # 30-day window (by Drive modifiedTime); a missing timestamp is kept (safe default).
    from datetime import datetime, timezone
    from mobile_sync_agent import purge_expired_hub_trash, _FOLDER_MIME, _PURGE_AFTER_SECONDS

    NOW = 1_000_000_000.0
    old_iso = datetime.fromtimestamp(NOW - (_PURGE_AFTER_SECONDS + 3600), tz=timezone.utc).isoformat()
    fresh_iso = datetime.fromtimestamp(NOW - 3600, tz=timezone.utc).isoformat()
    deleted: list[str] = []

    class _Exec:
        def __init__(self, r): self.r = r
        def execute(self): return self.r

    class _Files:
        def list(self, q=None, fields=None, pageToken=None):
            if f"mimeType='{_FOLDER_MIME}'" in q:  # list_hub_tree folder scan → the _trash folder
                return _Exec({"files": [{"id": "trashfolder", "name": "_trash"}]})
            return _Exec({"files": [                # _list_children of _trash (mimeType != folder)
                {"id": "old1", "name": "old.md", "modifiedTime": old_iso},
                {"id": "fresh1", "name": "fresh.md", "modifiedTime": fresh_iso},
                {"id": "nostamp", "name": "x.md"},  # no modifiedTime → never purged
            ]})
        def delete(self, fileId=None):
            deleted.append(fileId)
            return _Exec({})

    class _Drive:
        def files(self): return _Files()

    n = purge_expired_hub_trash(_Drive(), "hub", now_ts=NOW)
    assert n == 1
    assert deleted == ["old1"]  # only the expired one; fresh + timestamp-less are kept


def test_purge_expired_hub_trash_no_trash_folder_is_noop():
    from mobile_sync_agent import purge_expired_hub_trash, _FOLDER_MIME

    class _Exec:
        def __init__(self, r): self.r = r
        def execute(self): return self.r

    class _Files:
        def list(self, q=None, fields=None, pageToken=None):
            return _Exec({"files": []})  # no folders at all → no _trash

    class _Drive:
        def files(self): return _Files()

    assert purge_expired_hub_trash(_Drive(), "hub") == 0


def test_state_roundtrip(tmp_path):
    sp = str(tmp_path / "state.json")
    assert load_state(sp) == {}                       # absent → empty
    save_state(sp, {"01ABC": {"local_hash": "h", "drive_file_id": "f", "base_rev": "r"}})
    assert load_state(sp)["01ABC"]["base_rev"] == "r"


def test_load_state_corrupt_returns_empty(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text("{not json", encoding="utf-8", newline="")
    assert load_state(str(sp)) == {}                  # derived cache, safe rebuild


def test_load_state_non_utf8_returns_empty(tmp_path):
    # A byte-flip (not just bad JSON) raises UnicodeDecodeError, which is neither
    # JSONDecodeError nor OSError — it used to escape load_state and park the sync
    # pass in `error` forever, contradicting the docstring's "Absent/corrupt → empty".
    sp = tmp_path / "state.json"
    sp.write_bytes(b'{"01ABC": {"local_hash": "\xff\xfe h"}}')
    assert load_state(str(sp)) == {}                  # derived cache, safe rebuild


def test_save_state_crash_mid_write_leaves_old_state_intact(tmp_path, monkeypatch):
    # A3: the write is temp-sibling + os.replace, so a death between the two leaves the live
    # sidecar untouched (never truncated) — no blind re-upload of the whole vault next pass.
    sp = str(tmp_path / "state.json")
    save_state(sp, {"01ABC": {"local_hash": "h", "drive_file_id": "f", "base_rev": "r"}})

    def _boom(src, dst):
        raise OSError("crash between write and rename")

    monkeypatch.setattr("mobile_sync_agent.os.replace", _boom)
    with pytest.raises(OSError):
        save_state(sp, {"01ABC": {"local_hash": "h2", "drive_file_id": "f", "base_rev": "r2"}})
    assert load_state(sp)["01ABC"]["base_rev"] == "r"  # old state, parseable — not half-written


def _mock_drive(rev="rev1", file_id="F1"):
    drive = MagicMock()
    drive.files().create().execute.return_value = {"id": file_id, "headRevisionId": rev}
    drive.files().update().execute.return_value = {"id": file_id, "headRevisionId": rev}
    return drive


def test_mirror_creates_missing_note():
    notes = read_vault_notes  # noqa: F841  (documents the source of the shape below)
    vault_notes = {
        "01ABC": {"id": "01ABC", "path": "/x.md", "content": "---\nid: 01ABC\n---\nBody",
                  "body": "Body", "hash": "hashA"}
    }
    drive = _mock_drive(rev="rev1")
    uploaded, failed, new_state = mirror_to_hub(vault_notes, {}, {}, drive, "hub")
    assert (uploaded, failed) == (1, 0)
    assert new_state["01ABC"] == {
        "drive_file_id": "F1", "base_rev": "rev1", "local_hash": "hashA",
        "hub_name": "Untitled.md",   # no title in this fixture -> Untitled fallback
        # v3.0: an untagged note is LOOSE, and loose is `_loose/`, never the hub root.
        "base_parent": LOOSE_DIR,
    }


def test_mirror_skips_unchanged_by_hash_not_mtime():
    """A note already synced with the same content hash is skipped — mtime is irrelevant."""
    vault_notes = {
        "01ABC": {"id": "01ABC", "path": "/x.md", "content": "---\nid: 01ABC\n---\nBody",
                  "body": "Body", "hash": "hashA"}
    }
    state = {"01ABC": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": "hashA"}}
    drive = _mock_drive()
    uploaded, failed, new_state = mirror_to_hub(vault_notes, {}, state, drive, "hub")
    assert uploaded == 0
    drive.files().create().execute.assert_not_called()


def test_mirror_reuploads_when_hash_changed():
    vault_notes = {
        "01ABC": {"id": "01ABC", "path": "/x.md", "content": "---\nid: 01ABC\n---\nNew",
                  "body": "New", "hash": "hashB"}
    }
    state = {"01ABC": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": "hashA"}}
    drive = _mock_drive(rev="rev2")
    uploaded, failed, new_state = mirror_to_hub(vault_notes, {}, state, drive, "hub")
    assert uploaded == 1
    assert new_state["01ABC"]["base_rev"] == "rev2"      # new headRevisionId stored
    assert new_state["01ABC"]["local_hash"] == "hashB"


def test_mirror_never_uploads_a_note_it_never_observed_a_sync_for():
    """F-1: sidecar absent/corrupt but the note already exists on the hub -> mirror must NOT
    upload. It has no base_rev for the note, so it cannot know its body is newer than the head;
    uploading here reverted a peer's un-pulled edit. mirror used to adopt the hub listing with
    base_rev = the CURRENT head, which made its own advanced-head guard below compare the head
    against itself. reconcile_changes owns this case now (it adopts the file id, so the note is
    still updated in place rather than duplicated — see the adopt tests below)."""
    vault_notes = {
        "01ABC": {"id": "01ABC", "path": "/x.md", "content": "---\nid: 01ABC\n---\nBody",
                  "body": "Body", "hash": "hashA"}
    }
    hub_files = {"01ABC": {"id": "HUBF1", "headRevisionId": "rev9"}}
    drive = _mock_drive(file_id="HUBF1")
    uploaded, failed, new_state = mirror_to_hub(vault_notes, hub_files, {}, drive, "hub")
    assert (uploaded, failed) == (0, 0)
    # _mock_drive() itself calls create()/update() once during setup to wire
    # return values (but never .execute()), so assert on .execute (the real
    # invocation), not the top-level mock call count — mirrors the existing
    # convention in test_mirror_skips_unchanged_by_hash_not_mtime.
    drive.files().update().execute.assert_not_called()
    drive.files().create().execute.assert_not_called()
    assert new_state == {}, "no sync was observed — the sidecar must not claim one"


def test_mirror_still_creates_a_note_the_hub_does_not_have_when_state_empty():
    """The other half of the same branch: an empty sidecar is not a reason to skip a note the
    hub has never seen — there is no head to clobber, so it is created normally."""
    vault_notes = {
        "01ABC": {"id": "01ABC", "path": "/x.md", "content": "---\nid: 01ABC\n---\nBody",
                  "body": "Body", "hash": "hashA"}
    }
    drive = _mock_drive(rev="rev1")
    uploaded, failed, new_state = mirror_to_hub(vault_notes, {"09OTHER": {"id": "F9"}}, {}, drive, "hub")
    assert (uploaded, failed) == (1, 0)
    drive.files().create().execute.assert_called()
    assert new_state["01ABC"]["base_rev"] == "rev1"


def test_upload_asserts_body_sacred():
    """A note whose cached 'body' disagrees with its content's real body is rejected."""
    vault_notes = {
        "01ABC": {"id": "01ABC", "path": "/x.md", "content": "---\nid: 01ABC\n---\nReal body",
                  "body": "TAMPERED", "hash": "hashA"}
    }
    drive = _mock_drive()
    # The AssertionError inside _upload_note is caught by mirror_to_hub → counted as failed.
    uploaded, failed, _ = mirror_to_hub(vault_notes, {}, {}, drive, "hub")
    assert (uploaded, failed) == (0, 1)


# --- D2: pull + three-way reconcile ---
def _note_text(nid="01ABC", body="body", tags="[]", enriched="false", device="d",
               modified="2026-01-01T00:00:00Z"):
    return (
        f"---\nid: {nid}\ntitle: T\norigin: note\ncreated: 2026-01-01T00:00:00Z\n"
        f"modified: {modified}\ndevice: {device}\ntags: {tags}\naliases: []\n"
        f"attachments: []\nenriched: {enriched}\n---\n{body}"
    )


def _recon_drive(remote_text, base_text=None, up_rev="rev2", up_id="F1"):
    drive = MagicMock()
    drive.files().get_media().execute.return_value = remote_text.encode("utf-8")
    if base_text is not None:
        drive.revisions().get_media().execute.return_value = base_text.encode("utf-8")
    drive.files().create().execute.return_value = {"id": up_id, "headRevisionId": up_rev}
    drive.files().update().execute.return_value = {"id": up_id, "headRevisionId": up_rev}
    return drive


# v3.0: EVERY note lives at depth 1 -- `<project>/<file>.md` or `_loose/<file>.md`, never the
# vault root. These fixtures carry no `#project@` tag, so their directory is `_loose/`.
_LOOSE_PATH = str(Path("/vault") / LOOSE_DIR / "x.md")


def _vault_note(content, path=_LOOSE_PATH, nid="01ABC", h="NEW"):
    return {nid: {"id": nid, "path": path, "content": content,
                  "body": content.split("---\n", 2)[-1], "hash": h, "folder": LOOSE_DIR}}


def test_reconcile_pull_remote_only_change_no_upload():
    """Remote advanced, local unchanged → overwrite local verbatim, advance state, no upload."""
    remote_text = _note_text(body="edited on phone")
    vault_notes = _vault_note(_note_text(body="stale local"), h="SAME")
    state = {"01ABC": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": "SAME"}}
    hub_files = {"01ABC": {"id": "F1", "headRevisionId": "rev9"}}
    drive = _recon_drive(remote_text)
    written = {}
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub",
        write_file=lambda p, c: written.__setitem__(p, c), new_id=lambda: "X",
    )
    assert (reconciled, conflicts, failed) == (1, 0, 0)
    assert written[_LOOSE_PATH] == remote_text           # verbatim pull
    assert new_state["01ABC"]["base_rev"] == "rev9"
    assert new_state["01ABC"]["local_hash"] == _sha256(remote_text)
    drive.files().update().execute.assert_not_called()     # pull never uploads
    drive.revisions().get_media().execute.assert_not_called()  # no base fetch needed


def test_reconcile_both_changed_clean_merge_uploads():
    """Phone body edit ∥ desktop enrich → clean field merge, no conflicted copy, merged uploaded."""
    base_text = _note_text(body="b0", tags="[]", enriched="false")
    remote_text = _note_text(body="b0", tags="[finance]", enriched="true")  # desktop enriched
    local_text = _note_text(body="phone edit", tags="[]", enriched="false")  # phone body edit
    vault_notes = _vault_note(local_text, h="NEW")
    state = {"01ABC": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": "OLD"}}
    hub_files = {"01ABC": {"id": "F1", "headRevisionId": "rev9"}}
    drive = _recon_drive(remote_text, base_text=base_text, up_rev="rev2")
    written = {}
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub",
        write_file=lambda p, c: written.__setitem__(p, c), new_id=lambda: "X",
    )
    assert (reconciled, conflicts, failed) == (1, 0, 0)
    merged = written[_LOOSE_PATH]
    assert "phone edit" in merged                 # local body kept (body-sacred)
    assert "finance" in merged                    # desktop enrichment merged in
    assert "enriched: true" in merged
    assert new_state["01ABC"]["base_rev"] == "rev2"   # advanced to the merged upload's head
    drive.files().update().execute.assert_called()    # merged pushed back


def test_reconcile_body_conflict_writes_conflicted_copy():
    """Body edited on both → merged keeps local, remote body spun off as a conflicted copy."""
    base_text = _note_text(body="b0")
    remote_text = _note_text(body="remote body", device="desktop")
    local_text = _note_text(body="local body")
    vault_notes = _vault_note(local_text, h="NEW")
    state = {"01ABC": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": "OLD"}}
    hub_files = {"01ABC": {"id": "F1", "headRevisionId": "rev9"}}
    drive = _recon_drive(remote_text, base_text=base_text)
    written = {}
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub",
        write_file=lambda p, c: written.__setitem__(p, c), new_id=lambda: "CONFLICT1",
    )
    assert (reconciled, conflicts, failed) == (1, 1, 0)
    assert "local body" in written[_LOOSE_PATH]                     # local kept in place
    # s114/x04: the copy is named from its TITLE, not `<id>.md` -- a hex-blob filename beside the
    # note is what made a correct keep-both look like data loss to someone reading the vault.
    cc_path = next(k for k in written if k != _LOOSE_PATH)
    assert "conflicted copy desktop" in cc_path                       # recognisable on disk
    assert "CONFLICT1" not in cc_path                                 # the id is not the filename
    cc = written[cc_path]
    assert "remote body" in cc                                        # remote body preserved
    assert "id: CONFLICT1" in cc                                      # fresh id still minted
    assert "conflicted copy desktop" in cc
    assert "CONFLICT1" in new_state                                   # copy tracked in state
    assert new_state["CONFLICT1"]["hub_name"] == Path(cc_path).name   # SYNC-21: names agree


def test_reconcile_adopts_hub_file_when_state_empty_and_bytes_match():
    """F-1 adopt, in-sync case: the sidecar has no record but our bytes ARE the hub head, so the
    head is a revision we have now observed a sync at — record it and upload nothing. (The old
    mirror-side fallback re-uploaded byte-identical content here and burned a headRevisionId.)"""
    same_text = _note_text(body="body")
    vault_notes = _vault_note(same_text, h="H1")
    hub_files = {"01ABC": {"id": "HUBF1", "headRevisionId": "rev9"}}
    drive = _recon_drive(same_text)
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, {}, drive, "hub", write_file=lambda p, c: None,
    )
    assert (reconciled, conflicts, failed) == (0, 0, 0)   # nothing changed on either side
    drive.files().update().execute.assert_not_called()
    assert new_state["01ABC"] == {
        "drive_file_id": "HUBF1", "base_rev": "rev9", "local_hash": "H1",
        "base_parent": None,   # hub folder at last sync (this fixture's hub record has none)
    }


def test_reconcile_adopt_with_no_base_keeps_both_bodies():
    """F-1 adopt, divergent case: no sidecar record → no base_rev was ever observed, so there is
    no common ancestor. The divergence must resolve as a body-vs-body conflict (keep-both) on the
    note's EXISTING hub file — never a blind upload of the local body over the head."""
    remote_text = _note_text(body="remote body", device="phone")
    local_text = _note_text(body="local body")
    vault_notes = _vault_note(local_text, h="NEW")
    hub_files = {"01ABC": {"id": "HUBF1", "headRevisionId": "rev9"}}
    drive = _recon_drive(remote_text, up_id="HUBF1")
    written = {}
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, {}, drive, "hub",
        write_file=lambda p, c: written.__setitem__(p, c), new_id=lambda: "CONFLICT1",
    )
    assert (reconciled, conflicts, failed) == (1, 1, 0)
    assert "local body" in written[_LOOSE_PATH]                  # local kept in place
    # s114/x04: title-derived filename, not `<id>.md` -- see the body-conflict test above.
    cc = written[next(k for k in written if k != _LOOSE_PATH)]
    assert "remote body" in cc                                     # the head's body survives
    drive.revisions().get_media().execute.assert_not_called()      # no base rev exists to fetch
    assert new_state["01ABC"]["drive_file_id"] == "HUBF1"           # updated in place, no orphan
    assert new_state["01ABC"]["base_rev"] == "rev2"                 # a head the hub really issued


def test_reconcile_ignores_a_note_the_hub_does_not_have():
    """The adopt path is hub-listing-driven: a never-synced note that is not on the hub is still
    mirror_to_hub's to create, not reconcile's."""
    vault_notes = _vault_note(_note_text(body="x"), h="NEW")
    drive = _recon_drive(_note_text())
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, {}, {}, drive, "hub",
    )
    assert (reconciled, conflicts, failed) == (0, 0, 0)
    assert new_state == {}
    drive.files().get_media().execute.assert_not_called()


def test_reconcile_skips_when_remote_unchanged():
    """Hub head == our base_rev → nothing to reconcile (mirror handles local-only change)."""
    vault_notes = _vault_note(_note_text(body="x"), h="NEW")
    state = {"01ABC": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": "OLD"}}
    hub_files = {"01ABC": {"id": "F1", "headRevisionId": "rev1"}}   # same rev
    drive = _recon_drive(_note_text())
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub",
    )
    assert (reconciled, conflicts, failed) == (0, 0, 0)
    drive.files().get_media().execute.assert_not_called()          # nothing downloaded


def test_reconcile_skips_never_synced_note():
    """A note with no prior state is a new local note — mirror_to_hub creates it, not reconcile."""
    vault_notes = _vault_note(_note_text(), h="NEW")
    hub_files = {"01ABC": {"id": "F1", "headRevisionId": "rev9"}}
    drive = _recon_drive(_note_text())
    reconciled, conflicts, failed, _ = reconcile_changes(
        vault_notes, hub_files, {}, drive, "hub",
    )
    assert (reconciled, conflicts, failed) == (0, 0, 0)


# --- D3: hub-tree helpers ---
from mobile_sync_agent import (
    list_hub_tree,
    _find_or_create_subfolder,
    _download_bytes,
    _RESERVED_FOLDERS,
    get_hub_notes,
)


def _folder_list_drive(files):
    """MagicMock whose files().list() returns one page of `files` (no next page)."""
    drive = MagicMock()
    drive.files().list().execute.return_value = {"files": files, "nextPageToken": None}
    return drive


def test_list_hub_tree_splits_categories_from_reserved():
    drive = _folder_list_drive([
        {"id": "c1", "name": "personal", "mimeType": _FOLDER_MIME},
        {"id": "c2", "name": "work", "mimeType": _FOLDER_MIME},
        {"id": "t1", "name": "_trash", "mimeType": _FOLDER_MIME},
        {"id": "i1", "name": "_mobile_inbox", "mimeType": _FOLDER_MIME},
    ])
    categories, reserved = list_hub_tree(drive, "HUB")
    assert categories == {"personal": "c1", "work": "c2"}
    assert reserved == {"_trash": "t1", "_mobile_inbox": "i1"}


def test_find_or_create_subfolder_returns_existing():
    drive = MagicMock()
    drive.files().list().execute.return_value = {"files": [{"id": "EXIST"}]}
    assert _find_or_create_subfolder(drive, "HUB", "personal") == "EXIST"
    drive.files().create().execute.assert_not_called()


def test_find_or_create_subfolder_creates_when_absent():
    drive = MagicMock()
    drive.files().list().execute.return_value = {"files": []}
    drive.files().create().execute.return_value = {"id": "NEW"}
    assert _find_or_create_subfolder(drive, "HUB", "ideas") == "NEW"


def test_download_bytes_is_not_decoded():
    drive = MagicMock()
    drive.files().get_media().execute.return_value = b"\x00\x01raw"
    assert _download_bytes(drive, "F1") == b"\x00\x01raw"


def _tree_drive(categories, files_by_folder):
    """MagicMock whose files().list() returns folders for the hub root and
    files for each category folder, dispatched by the `q` kwarg's parent id."""
    drive = MagicMock()

    def _list(**kw):
        q = kw.get("q", "")
        resp = MagicMock()
        if f"'HUB' in parents" in q:
            resp.execute.return_value = {
                "files": [{"id": fid, "name": n, "mimeType": _FOLDER_MIME}
                          for n, fid in categories.items()],
                "nextPageToken": None,
            }
        else:
            folder_id = next((fid for fid in files_by_folder if f"'{fid}' in parents" in q), None)
            resp.execute.return_value = {
                "files": files_by_folder.get(folder_id, []),
                "nextPageToken": None,
            }
        return resp

    drive.files().list.side_effect = _list
    return drive


def test_get_hub_notes_walks_note_folders_and_normalizes_keys():
    drive = _tree_drive(
        categories={"personal": "c1", "_trash": "t1"},
        files_by_folder={
            # phone-origin: <id>.md, NO appProperties
            "c1": [{"id": "F1", "name": "01ABC.md", "headRevisionId": "r1"},
                   # desktop-origin: appProperties.noteId set
                   {"id": "F2", "name": "01XYZ.md", "headRevisionId": "r2",
                    "appProperties": {"noteId": "01XYZ"}}],
            # _trash is reserved → never walked
            "t1": [{"id": "T9", "name": "deleted.md", "headRevisionId": "r9"}],
        },
    )
    notes = get_hub_notes(drive, "HUB")
    assert set(notes) == {"01ABC", "01XYZ"}     # both keyed by bare id; trash excluded
    assert notes["01ABC"]["folder"] == "personal"
    assert notes["01ABC"]["headRevisionId"] == "r1"


def test_get_hub_notes_scans_root_level_notes():
    # B-5: v3.0 never PUTS a note at the hub root (a loose note goes to `_loose/`), but a
    # legacy/foreign root file (folder=None) must still be scanned + reconciled,
    # not silently invisible. Dispatch: the root FILE query carries `mimeType!=folder`; the folder-list
    # query carries `mimeType=folder`.
    drive = MagicMock()

    def _list(**kw):
        q = kw.get("q", "")
        resp = MagicMock()
        if "'HUB' in parents" in q and f"mimeType!='{_FOLDER_MIME}'" in q:
            resp.execute.return_value = {"files": [
                {"id": "R1", "name": "01ROOT.md", "headRevisionId": "rr"}], "nextPageToken": None}
        elif "'HUB' in parents" in q:  # folder-list (list_hub_tree)
            resp.execute.return_value = {"files": [
                {"id": "c1", "name": "personal", "mimeType": _FOLDER_MIME}], "nextPageToken": None}
        elif "'c1' in parents" in q:
            resp.execute.return_value = {"files": [
                {"id": "F1", "name": "01CAT.md", "headRevisionId": "r1"}], "nextPageToken": None}
        else:
            resp.execute.return_value = {"files": [], "nextPageToken": None}
        return resp

    drive.files().list.side_effect = _list
    notes = get_hub_notes(drive, "HUB")
    assert set(notes) == {"01CAT", "01ROOT"}       # both the folder note AND the root note
    assert notes["01CAT"]["folder"] == "personal"
    assert notes["01ROOT"]["folder"] is None        # at the hub root


def test_get_hub_notes_prefers_appProperties_noteId_and_logs_filename_stem_fallback(capsys):
    # Title-based universal filenames (0.3): a hub file WITH appProperties.noteId keys on the
    # id, never on its (now human-readable) filename stem. A file WITHOUT appProperties (legacy
    # or foreign) still falls back to the filename stem, but must log that it did so.
    drive = MagicMock()

    def _list(**kw):
        q = kw.get("q", "")
        resp = MagicMock()
        if "'HUB' in parents" in q and f"mimeType!='{_FOLDER_MIME}'" in q:
            # root-level file, NO appProperties -> legacy fallback to stem "01J9"
            resp.execute.return_value = {"files": [
                {"id": "R1", "name": "01J9.md", "headRevisionId": "rr"}], "nextPageToken": None}
        elif "'HUB' in parents" in q:  # folder-list (list_hub_tree)
            resp.execute.return_value = {"files": [
                {"id": "c1", "name": "personal", "mimeType": _FOLDER_MIME}], "nextPageToken": None}
        elif "'c1' in parents" in q:
            # category-level file WITH appProperties.noteId -> keyed on "01H8", not "Grocery List"
            resp.execute.return_value = {"files": [
                {"id": "F1", "name": "Grocery List.md", "headRevisionId": "r1",
                 "appProperties": {"noteId": "01H8"}}], "nextPageToken": None}
        else:
            resp.execute.return_value = {"files": [], "nextPageToken": None}
        return resp

    drive.files().list.side_effect = _list
    notes = get_hub_notes(drive, "HUB")

    assert "01H8" in notes
    assert "Grocery List" not in notes            # never keyed by title-derived filename stem
    assert "01J9" in notes                        # legacy file with no appProperties still falls back

    out = capsys.readouterr().out
    assert "no appProperties" in out
    assert out.count("no appProperties") == 1     # only the fallback (01J9.md), not the F1 note


def test_read_vault_notes_folder_is_derived_from_the_body_tag(tmp_path):
    # v3.0 (§1.3): `folder` is note_dir_for(resolve_project(body, reg)) — the note's project or
    # `_loose`. Derived from the BODY TAG, never from the file's parent dir and never from a
    # legacy `category:` line.
    _write_registry(tmp_path, "work")
    workd = tmp_path / "work"
    workd.mkdir()
    # tagged + registered -> its project
    (workd / "a.md").write_text("---\nid: 01A\ntitle: T\norigin: note\n---\nB #project@work",
                                encoding="utf-8", newline="")
    # no tag -> loose, and a legacy `category: ideas` line changes nothing
    (tmp_path / "b.md").write_text(
        "---\nid: 01B\ntitle: T\norigin: note\ncategory: ideas\n---\nB", encoding="utf-8", newline="")
    # tag naming an UNREGISTERED project -> dangling reads as loose, whatever folder it sits in
    (workd / "c.md").write_text(
        "---\nid: 01C\ntitle: T\norigin: note\n---\nB #project@ideas", encoding="utf-8", newline="")
    notes = read_vault_notes(str(tmp_path))
    assert notes["01A"]["folder"] == "work"
    assert notes["01B"]["folder"] == LOOSE_DIR   # untagged, wherever it sits
    assert notes["01C"]["folder"] == LOOSE_DIR   # dangling tag reads as loose


def test_mirror_places_new_note_in_its_project_folder():
    vault_notes = {
        "01A": {"id": "01A", "path": "/v/work/a.md", "content": "---\nid: 01A\ntitle: Groceries\n---\nB",
                "body": "B", "hash": "h", "folder": "work", "title": "Groceries", "created": ""}
    }
    drive = MagicMock()
    drive.files().list().execute.return_value = {"files": []}            # category folder absent
    drive.files().create().execute.return_value = {"id": "F1", "headRevisionId": "r1"}
    uploaded, failed, new_state = mirror_to_hub(vault_notes, {}, {}, drive, "HUB")
    assert (uploaded, failed) == (1, 0)
    # the note-create body must carry parents = [the work-folder id], not [HUB]
    create_calls = [c for c in drive.files().create.call_args_list if c.kwargs.get("body", {}).get("name") == "Groceries.md"]
    assert create_calls, "note was not created with name Groceries.md (title-based naming)"
    assert create_calls[0].kwargs["body"]["parents"] != ["HUB"]          # placed in a project folder


from mobile_sync_agent import pull_new_hub_notes


def _hub_note_text(nid, project=None, body="phone body"):
    """v3.0: a note's project is the `#project@<name>` BODY tag — there is no project
    frontmatter field to author. `project=None` is a loose note."""
    tag = f" #project@{project}" if project else ""
    return f"---\nid: {nid}\ntitle: T\norigin: note\n---\n{body}{tag}"


def test_pull_places_new_note_under_the_hub_resolved_title_name():
    """Task 2.4: pull_new_hub_notes must mirror the HUB FILE'S OWN resolved `name` (get_hub_notes
    already carries it, clash-unique on the hub) rather than recomputing/hardcoding <id>.md."""
    hub_files = {"01NEW": {"id": "F1", "headRevisionId": "r1", "folder": "personal", "name": "T.md"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = _hub_note_text("01NEW", "work").encode("utf-8")
    written = {}
    pulled, failed, new_state = pull_new_hub_notes(
        {}, hub_files, {}, drive, "/vault",
        write_file=lambda p, c: written.__setitem__(p, c), reg=_reg("work"),
    )
    assert (pulled, failed) == (1, 0)
    # v3.0: placement comes from the BODY TAG (`#project@work`), NOT the hub parent folder
    # ("personal"). Filename = the hub's resolved name (T.md). Body verbatim.
    assert written == {str(Path("/vault/work/T.md")): _hub_note_text("01NEW", "work")}
    assert new_state["01NEW"] == {
        "drive_file_id": "F1", "base_rev": "r1",
        "local_hash": _sha256(_hub_note_text("01NEW", "work")),
        "hub_name": "T.md",
        "base_parent": "personal",   # the hub folder it was pulled from, still just bookkeeping
    }


def test_pull_falls_back_to_id_name_when_hub_record_has_no_name():
    """Guard: a hub record with no usable `name` (missing/unsafe) never crashes the pull — it
    falls back to the legacy <id>.md local filename."""
    hub_files = {"01NEW": {"id": "F1", "headRevisionId": "r1", "folder": "personal"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = _hub_note_text("01NEW", "work").encode("utf-8")
    written = {}
    pulled, failed, new_state = pull_new_hub_notes(
        {}, hub_files, {}, drive, "/vault",
        write_file=lambda p, c: written.__setitem__(p, c), reg=_reg("work"),
    )
    assert (pulled, failed) == (1, 0)
    # v3.0: the body tag drives placement, not the hub parent folder ("personal").
    assert written == {str(Path("/vault/work/01NEW.md")): _hub_note_text("01NEW", "work")}
    assert new_state["01NEW"] == {
        "drive_file_id": "F1", "base_rev": "r1",
        "local_hash": _sha256(_hub_note_text("01NEW", "work")),
        "hub_name": None,
        "base_parent": "personal",
    }


def test_pull_files_an_untagged_note_into_loose_never_the_vault_root():
    # v3.0 (§1.3): a note with no `#project@` tag is LOOSE, and loose lives at depth 1 in
    # `_loose/` -- never the vault root, which would break its `../_attachments/` body refs.
    # The old scratchpad fallback is gone with the category concept.
    hub_files = {"01NC": {"id": "F2", "headRevisionId": "r2", "folder": None, "name": "T.md"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = _hub_note_text("01NC").encode("utf-8")
    written = {}
    pulled, failed, _ = pull_new_hub_notes(
        {}, hub_files, {}, drive, "/vault",
        write_file=lambda p, c: written.__setitem__(p, c),
    )
    assert (pulled, failed) == (1, 0)
    assert str(Path("/vault") / LOOSE_DIR / "T.md") in written


def test_pull_files_a_dangling_tag_into_loose():
    # A tag naming a project the registry does not hold reads as loose (§1.3 "dangling reads as
    # loose") -- it never creates the directory and never errors.
    hub_files = {"01DG": {"id": "F3", "headRevisionId": "r3", "folder": "personal", "name": "T.md"}}
    written = {}
    pulled, failed, _ = pull_new_hub_notes(
        {}, hub_files, {}, MagicMock(), "/vault",
        download=lambda fid: _hub_note_text("01DG", "not-registered"),
        write_file=lambda p, c: written.__setitem__(p, c),
    )
    assert (pulled, failed) == (1, 0)
    assert str(Path("/vault") / LOOSE_DIR / "T.md") in written


def test_pull_skips_notes_already_local_or_tracked():
    hub_files = {"01A": {"id": "F1", "headRevisionId": "r1", "folder": "personal", "name": "T.md"}}
    drive = MagicMock()
    # already in the vault
    p1, _, _ = pull_new_hub_notes({"01A": {}}, hub_files, {}, drive, "/vault",
                                  write_file=lambda p, c: None)
    # already tracked in state
    p2, _, _ = pull_new_hub_notes({}, hub_files, {"01A": {}}, drive, "/vault",
                                  write_file=lambda p, c: None)
    assert p1 == 0 and p2 == 0


def test_pull_skips_a_locally_trashed_id(tmp_path):
    """ISS-046: a hub note whose id is sitting in the local `_trash/` must NOT be re-pulled as a
    fresh active copy (which would leave a duplicate active+trashed pair). A live hub copy going
    live again — peer restore / out-of-order delete after the state row was dropped — is skipped
    when local_trashed_ids carries that id; a note NOT locally trashed still pulls normally."""
    content = "---\nid: 01TR\ntitle: Trashed\norigin: note\n---\nbody #project@personal"
    hub_files = {"01TR": {"id": "F1", "headRevisionId": "r1", "folder": "personal", "name": "Trashed.md"}}
    vault = tmp_path / "vault"
    # id is in local _trash/ -> skipped, nothing written, no active copy minted
    pulled, failed, new_state = pull_new_hub_notes(
        {}, hub_files, {}, MagicMock(), str(vault),
        download=lambda fid: content, local_trashed_ids={"01TR"}, reg=_reg("personal"),
    )
    assert (pulled, failed) == (0, 0)
    assert "01TR" not in new_state
    assert not (vault / "personal" / "Trashed.md").exists()
    # sanity: the SAME note with no local-trash entry pulls as before (guard is scoped, not blanket)
    pulled2, _, state2 = pull_new_hub_notes(
        {}, hub_files, {}, MagicMock(), str(vault),
        download=lambda fid: content, local_trashed_ids=set(), reg=_reg("personal"),
    )
    assert pulled2 == 1 and "01TR" in state2


def test_pull_writes_hub_resolved_name_not_id_and_pins_hub_name_in_state(tmp_path):
    """Task 2.4 focused test: a hub note titled 'Pulled Note' with no local file → after
    pull_new_hub_notes the local file exists at <vault>/<cat>/Pulled Note.md (NOT <id>.md),
    body byte-identical to the hub content, and the new sync-state entry carries
    hub_name='Pulled Note.md' — so a later reconcile/_maybe_rename_local never renames it."""
    content = "---\nid: 01PN\ntitle: Pulled Note\norigin: note\n---\nphone body #project@personal"
    hub_files = {"01PN": {"id": "F9", "headRevisionId": "r9", "folder": "personal", "name": "Pulled Note.md"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = content.encode("utf-8")
    vault = tmp_path / "vault"
    pulled, failed, new_state = pull_new_hub_notes(
        {}, hub_files, {}, drive, str(vault),
        download=lambda fid: content, reg=_reg("personal"),
    )
    assert (pulled, failed) == (1, 0)
    dest = vault / "personal" / "Pulled Note.md"
    assert dest.exists()
    assert not (vault / "personal" / "01PN.md").exists()
    assert dest.read_bytes() == content.encode("utf-8")
    assert new_state["01PN"]["hub_name"] == "Pulled Note.md"


from mobile_sync_agent import intake_mobile_inbox

_ATTACH_STUB = "---\norigin: capture\ncreated: 2026-01-01T00:00:00Z\ndevice: d\n---\n[capture attachment: 20260101T000000Z-v.m4a]"
_TEXT_STUB = "---\norigin: capture\ncreated: 2026-01-01T00:00:00Z\ndevice: d\n---\nhello from phone"


def _inbox_drive(files, stub_texts):
    """files: list of {id,name} in the inbox. stub_texts: {file_id: utf-8 text} for .md reads."""
    drive = MagicMock()
    drive.files().list().execute.return_value = {"files": files, "nextPageToken": None}

    def _get_media(fileId=None):
        resp = MagicMock()
        resp.execute.return_value = stub_texts[fileId].encode("utf-8")
        return resp

    drive.files().get_media.side_effect = _get_media
    return drive


def test_intake_text_capture_feeds_pipeline_and_deletes():
    drive = _inbox_drive(
        files=[{"id": "S1", "name": "20260101T000000Z-hi.md"}],
        stub_texts={"S1": _TEXT_STUB},
    )
    calls, deleted = [], []
    ingested, skipped, failed = intake_mobile_inbox(
        drive, "INBOX",
        run_pipeline=lambda **kw: calls.append(kw) or {},
        download_bytes=lambda fid: b"",
        delete_file=lambda fid: deleted.append(fid),
    )
    assert (ingested, skipped, failed) == (1, 0, 0)
    assert calls == [{"text": "hello from phone"}]
    assert deleted == ["S1"]


def test_intake_binary_capture_stages_bytes_and_deletes_pair(tmp_path):
    drive = _inbox_drive(
        files=[{"id": "S1", "name": "20260101T000000Z-v.m4a.md"},
               {"id": "B1", "name": "20260101T000000Z-v.m4a"}],
        stub_texts={"S1": _ATTACH_STUB},
    )
    calls, deleted = [], []
    ingested, skipped, failed = intake_mobile_inbox(
        drive, "INBOX",
        run_pipeline=lambda **kw: calls.append(kw) or {},
        download_bytes=lambda fid: b"RAWAUDIO",
        delete_file=lambda fid: deleted.append(fid),
        stage_dir=str(tmp_path),
    )
    assert (ingested, skipped, failed) == (1, 0, 0)
    assert set(calls[0]) == {"audio"}                      # voice ext → audio= kwarg
    assert Path(calls[0]["audio"]).read_bytes() == b"RAWAUDIO"
    assert set(deleted) == {"S1", "B1"}                    # stub + sibling both removed


def test_intake_missing_sibling_skips_without_fail_or_delete():
    drive = _inbox_drive(
        files=[{"id": "S1", "name": "20260101T000000Z-v.m4a.md"}],   # sibling not arrived yet
        stub_texts={"S1": _ATTACH_STUB},
    )
    calls, deleted = [], []
    ingested, skipped, failed = intake_mobile_inbox(
        drive, "INBOX",
        run_pipeline=lambda **kw: calls.append(kw),
        download_bytes=lambda fid: b"",
        delete_file=lambda fid: deleted.append(fid),
    )
    assert (ingested, skipped, failed) == (0, 1, 0)
    assert calls == [] and deleted == []                    # nothing ingested, nothing deleted


from mobile_sync_agent import HUB_FOLDER_NAME, run_once


def test_run_once_pulls_then_intakes_then_mirrors(tmp_path, monkeypatch):
    # one hub-only note in personal/, one text capture in the inbox, empty local vault
    vault = tmp_path / "vault"
    vault.mkdir()
    state_path = str(tmp_path / "state.json")

    hub_note = _hub_note_text("01NEW", "personal", "phone body")
    drive = MagicMock()

    def _list(**kw):
        q = kw.get("q", "")
        resp = MagicMock()
        if "'HUB' in parents" in q and _FOLDER_MIME in q:
            resp.execute.return_value = {"files": [
                {"id": "c1", "name": "personal", "mimeType": _FOLDER_MIME},
                {"id": "i1", "name": "_mobile_inbox", "mimeType": _FOLDER_MIME},
            ], "nextPageToken": None}
        elif "'c1' in parents" in q:
            resp.execute.return_value = {"files": [
                {"id": "F1", "name": "01NEW.md", "headRevisionId": "r1"}], "nextPageToken": None}
        elif "'i1' in parents" in q:
            resp.execute.return_value = {"files": [
                {"id": "S1", "name": "20260101T000000Z-hi.md"}], "nextPageToken": None}
        else:
            resp.execute.return_value = {"files": [], "nextPageToken": None}
        return resp

    drive.files().list.side_effect = _list

    def _get_media(fileId=None):
        resp = MagicMock()
        resp.execute.return_value = {"F1": hub_note, "S1": _TEXT_STUB}[fileId].encode("utf-8")
        return resp

    drive.files().get_media.side_effect = _get_media
    drive.files().delete().execute.return_value = {}

    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    pipeline_calls = []
    uploaded, failed, reconciled, conflicts, pulled, ingested, enriched = run_once(
        str(vault), state_path, drive,
        vault_root=str(vault),
        run_pipeline=lambda **kw: pipeline_calls.append(kw) or {},
    )
    assert pulled == 1                                   # hub-only note pulled
    # v3.0: the pulled body carries no `#project@` tag, so it is LOOSE -- filed under `_loose/`,
    # not under the hub's `personal/` parent (the tag is the truth, the hub folder is not).
    assert (vault / LOOSE_DIR / "01NEW.md").exists()
    assert ingested == 1 and pipeline_calls == [{"text": "hello from phone"}]


# ---------------------------------------------------------------------------
# N2/T8 · LAN provisional supersede wired into the Drive pull
# ---------------------------------------------------------------------------
def _pull_one_drive(monkeypatch, hub_note, nid, fid="F1"):
    """Fake `drive` that delivers exactly one hub-only note `nid` (in personal/), no inbox.
    Mirrors the setup of test_run_once_pulls_then_intakes_then_mirrors, minus the capture stub."""
    drive = MagicMock()

    def _list(**kw):
        q = kw.get("q", "")
        resp = MagicMock()
        if "'HUB' in parents" in q and _FOLDER_MIME in q:
            resp.execute.return_value = {"files": [
                {"id": "c1", "name": "personal", "mimeType": _FOLDER_MIME},
            ], "nextPageToken": None}
        elif "'c1' in parents" in q:
            resp.execute.return_value = {"files": [
                {"id": fid, "name": f"{nid}.md", "headRevisionId": "r1"}], "nextPageToken": None}
        else:
            resp.execute.return_value = {"files": [], "nextPageToken": None}
        return resp

    drive.files().list.side_effect = _list

    def _get_media(fileId=None):
        resp = MagicMock()
        resp.execute.return_value = {fid: hub_note}[fileId].encode("utf-8")
        return resp

    drive.files().get_media.side_effect = _get_media
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")
    return drive


def test_run_once_supersedes_provisionals_on_pull(tmp_path, monkeypatch):
    import provisional_store as ps
    vault = tmp_path / "vault"
    vault.mkdir()
    state_path = str(tmp_path / "state.json")
    sd = str(vault / ".sync")
    ps.stage(sd, "op1", "noteA", "---\n---\nprovisional body\n", {"staged_at": 1.0})

    superseded = []
    def provisional_fn(note_id):
        superseded.extend(ps.supersede(sd, note_id))

    drive = _pull_one_drive(monkeypatch, _hub_note_text("noteA", "personal", "phone body"), "noteA")
    uploaded, failed, reconciled, conflicts, pulled, ingested, enriched = run_once(
        str(vault), state_path, drive,
        vault_root=str(vault),
        provisional_fn=provisional_fn,
    )
    assert pulled == 1                          # hub-only note pulled to canonical
    assert "op1" in superseded                  # its provisional overlay was dropped
    assert ps.list_provisional(sd) == []        # nothing left staged for noteA


def test_run_once_swallows_raising_provisional_fn(tmp_path, monkeypatch):
    # A provisional_fn that raises for a pulled note must not abort the pass: run_once still
    # completes and returns its normal 7-tuple (best-effort supersede; TTL sweep is backstop).
    vault = tmp_path / "vault"
    vault.mkdir()
    state_path = str(tmp_path / "state.json")

    def provisional_fn(note_id):
        raise RuntimeError(f"boom on {note_id}")

    drive = _pull_one_drive(monkeypatch, _hub_note_text("noteA", "personal", "phone body"), "noteA")
    result = run_once(
        str(vault), state_path, drive,
        vault_root=str(vault),
        provisional_fn=provisional_fn,
    )
    assert len(result) == 7                      # pass completed, 7-tuple contract intact
    uploaded, failed, reconciled, conflicts, pulled, ingested, enriched = result
    assert pulled == 1                            # the pull itself still succeeded


def test_run_once_without_provisional_fn_is_unchanged(tmp_path, monkeypatch):
    # Default (provisional_fn=None): the existing 7-tuple behavior is untouched.
    drive = _mock_empty_drive()
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")
    result = run_once(str(tmp_path), str(tmp_path / "state.json"), drive)
    assert len(result) == 7                      # 7-tuple contract intact
    assert result == (0, 0, 0, 0, 0, 0, 0)


def test_run_once_threads_mirror_captures_into_both_reads(tmp_path, monkeypatch):
    # run_once re-reads read_vault_notes twice (initial + post-intake/enrich); both calls must
    # honour the mirror_captures flag it was given.
    drive = _mock_empty_drive()
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    seen = []
    real_read = read_vault_notes

    def spy(vault_path, mirror_captures=False, reg=None):
        seen.append(mirror_captures)
        return real_read(vault_path, mirror_captures, reg)

    monkeypatch.setattr("mobile_sync_agent.read_vault_notes", spy)

    run_once(str(tmp_path), str(tmp_path / "state.json"), drive, mirror_captures=True)

    assert seen == [True, True]


def test_provisional_supersede_never_edits_body(tmp_path, monkeypatch):
    import provisional_store as ps
    vault = tmp_path / "vault"
    vault.mkdir()
    state_path = str(tmp_path / "state.json")
    sd = str(vault / ".sync")
    # Provisional body deliberately DIFFERS from the canonical Drive body.
    ps.stage(sd, "op1", "noteA", "---\n---\nprovisional body\n", {"staged_at": 1.0})
    staging_file = Path(sd) / "provisional" / "op1.md"
    assert staging_file.exists()

    hub_note = _hub_note_text("noteA", "personal", "phone body")   # exact bytes Drive delivers
    def provisional_fn(note_id):
        ps.supersede(sd, note_id)

    drive = _pull_one_drive(monkeypatch, hub_note, "noteA")
    run_once(str(vault), state_path, drive,
             vault_root=str(vault),
             provisional_fn=provisional_fn)

    # Canonical mirror is byte-identical to the Drive-delivered note — body sacred.
    # v3.0: `personal` is not in this vault's (absent) registry, so the tag DANGLES and the note
    # is loose -> `_loose/`. The filename mirrors the hub's own resolved name (T.md).
    canonical = (vault / LOOSE_DIR / "noteA.md").read_text(encoding="utf-8")
    assert canonical == hub_note
    # Supersede only deleted the staging file; it never wrote through to the canonical mirror.
    assert not staging_file.exists()
    assert ps.list_provisional(sd) == []


# ---------------------------------------------------------------------------
# D4 · note-only enrichment
# ---------------------------------------------------------------------------
from mobile_sync_agent import enrich_notes


def _note_file(dirpath: Path, name: str, frontmatter: str, body: str) -> Path:
    p = dirpath / name
    p.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8", newline="")
    return p


def _vault_notes_from(dirpath: Path):
    return read_vault_notes(str(dirpath))


def test_enrich_notes_enriches_unenriched_note(tmp_path):
    body = "# My note\n\nSome body text.\n"
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\nenriched: false\ntags:\n  - keep\ncategory: personal", body)
    vault_notes = _vault_notes_from(tmp_path)
    captured = {}

    def classify(text):
        captured["text"] = text
        return "research"

    embedded = []
    def embed(path, content):
        embedded.append((path, content))

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify,
                                    embed=embed, reg=_reg("research"))

    assert (enriched, failed) == (1, 0)
    from note_model import parse_note
    from frontmatter import strip_frontmatter
    from machine_tags import strip_trailing_tags_line
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    note = parse_note(written)
    assert note.enriched is True
    assert note.enrich_source == "desktop-llm"
    assert note.origin_device == "desktop"           # legacy null note backfilled + stamped (§2.1)
    # Projects S1: the legacy `category: personal` seed never reaches the struct and is dropped
    # at save; the concept is gone.
    assert not hasattr(note, "category")
    assert "category:" not in written
    # §7: the assignment is the `#project@` tag on the machine trailing body line, and NOTHING
    # else -- the key_signals-derived descriptive tags are deleted.
    assert "\ntags: #project@research\n" in strip_frontmatter(written)
    # §1.3: structural tags are EXCLUDED from the derived `tags:` cache, and the seeded
    # frontmatter `keep` is not in the body, so the recomputed cache is empty.
    assert note.tags == []
    # ...and `project:` is the always-present, always-bracketed derived frontmatter cache.
    assert "project: [research]" in written
    assert strip_trailing_tags_line(strip_frontmatter(written)) == body  # BODY SACRED above the line
    assert captured["text"] == body                  # classify saw the user body, not frontmatter
    assert embedded == [(str(tmp_path / "n1.md"), written)]
    assert vault_notes["n1"]["content"] == written   # in-memory dict updated for same-pass mirror
    assert vault_notes["n1"]["hash"] == _sha256(written)


def test_enrich_notes_skips_already_enriched(tmp_path):
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\nenriched: true\nenrich_source: desktop-llm", "Body.\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("must not classify an already-enriched note")

    assert enrich_notes(vault_notes, str(tmp_path), classify) == (0, 0)


def test_enrich_notes_skips_captures(tmp_path):
    _note_file(tmp_path, "c1.md",
               "id: c1\norigin: capture\nenriched: false", "Clip body.\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("must not classify a capture")

    assert enrich_notes(vault_notes, str(tmp_path), classify) == (0, 0)


def test_enrich_notes_failsoft_on_classify_error(tmp_path):
    body = "Body stays.\n"
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)
    before = (tmp_path / "n1.md").read_text(encoding="utf-8")

    def classify(text):
        raise RuntimeError("ollama down")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify)
    assert (enriched, failed) == (0, 1)
    assert (tmp_path / "n1.md").read_text(encoding="utf-8") == before   # untouched, retried next pass


def test_enrich_writes_the_project_tag_to_the_trailing_body_line(tmp_path):
    # ISS-051 §3 + §7: the desktop's assignment lands in the BODY as the machine trailing
    # `tags:` line, never as a frontmatter field the user cannot see.
    body = "# My note\n\nSome body text.\n"
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\norigin_device: desktop\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)
    seen = {}

    def classify(text):
        seen["text"] = text
        return "papers"

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify, reg=_reg("papers"))
    assert (enriched, failed) == (1, 0)
    from note_model import parse_note
    from frontmatter import strip_frontmatter
    from machine_tags import strip_trailing_tags_line
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    note = parse_note(written)
    assert note.enriched is True and note.enrich_source == "desktop-llm"
    assert note.origin_device == "desktop"
    # the project tag is in the body trailing line...
    assert "\ntags: #project@papers\n" in strip_frontmatter(written)
    # ...the user body ABOVE it is byte-identical (body-sacred, amended §3)...
    assert strip_trailing_tags_line(strip_frontmatter(written)) == body
    # ...`tags:` excludes it (structural, §1.3) and `project:` caches it.
    assert note.tags == []
    assert "project: [papers]" in written
    assert seen["text"] == body  # classify saw the user body


def test_enrich_writes_no_tag_other_than_project(tmp_path):
    # §7: "auto-enrichment writes a `#project@<name>` tag and NOTHING else" -- the
    # key_signals-derived descriptive tag generation is deleted, so a classifier that returns
    # something that is not a registry-eligible, REGISTERED project writes no tag at all and
    # the note stays loose (degrades to loose, never a guess).
    from frontmatter import strip_frontmatter
    body = "# My note\n\nSome body text.\n"
    # unregistered name · a reserved `_`-prefixed name the name rule forbids · nothing picked
    for i, picked in enumerate(("not-registered", "_loose", None)):
        d = tmp_path / f"case{i}"
        d.mkdir()
        _note_file(d, "n.md", "id: n\norigin: note\norigin_device: desktop\nenriched: false", body)
        vault_notes = _vault_notes_from(d)
        enriched, failed = enrich_notes(vault_notes, str(d), lambda text, v=picked: v,
                                        reg=_reg("papers"))
        assert (enriched, failed) == (1, 0), picked
        written = (d / "n.md").read_text(encoding="utf-8")
        assert strip_frontmatter(written) == body, picked  # BODY untouched: no tag line at all
        assert "project: [-]" in written, picked           # cached as loose


def test_enrich_never_overrides_a_project_tag_the_user_typed(tmp_path):
    # §1.3: the user's tag IS the truth. The machine may assign a project to a note that has
    # none; it may never reclassify one the user already tagged.
    body = "# My note\n\nabout #project@papers\n"
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\norigin_device: desktop\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("must not classify a note the user already tagged")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify,
                                    reg=_reg("papers", "research"))
    assert (enriched, failed) == (1, 0)
    from frontmatter import strip_frontmatter
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    assert strip_frontmatter(written) == body          # BODY SACRED, byte-identical
    assert "project: [papers]" in written              # cache follows the user's own tag


def test_enrich_skips_phone_origin_note(tmp_path):
    # Provenance gate (§2.2): the desktop never enriches phone-origin content.
    body = "phone note body\n"
    _note_file(tmp_path, "p1.md",
               "id: p1\norigin: note\norigin_device: phone\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)
    before = (tmp_path / "p1.md").read_text(encoding="utf-8")

    def classify(text):
        raise AssertionError("must not classify a phone-origin note")

    assert enrich_notes(vault_notes, str(tmp_path), classify) == (0, 0)
    assert (tmp_path / "p1.md").read_text(encoding="utf-8") == before  # untouched


def test_enrich_backfills_phone_from_heuristic_marker_and_skips(tmp_path):
    # A legacy null-origin note carrying the phone-heuristic marker backfills to phone → gate skips it.
    _note_file(tmp_path, "p2.md",
               "id: p2\norigin: note\nenriched: false\nenrich_source: phone-heuristic", "hi\n")
    vault_notes = _vault_notes_from(tmp_path)
    before = (tmp_path / "p2.md").read_text(encoding="utf-8")

    def classify(text):
        raise AssertionError("phone-heuristic legacy note must not be enriched by desktop")

    assert enrich_notes(vault_notes, str(tmp_path), classify) == (0, 0)
    assert (tmp_path / "p2.md").read_text(encoding="utf-8") == before


def test_enrich_backfills_desktop_and_stamps_legacy_null_note(tmp_path):
    # A legacy null-origin note with no phone marker is a desktop-vault note → enriched + stamped.
    _note_file(tmp_path, "d1.md", "id: d1\norigin: note\nenriched: false", "desktop note\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        return "tasks"

    assert enrich_notes(vault_notes, str(tmp_path), classify, reg=_reg("tasks")) == (1, 0)
    from note_model import parse_note
    note = parse_note((tmp_path / "d1.md").read_text(encoding="utf-8"))
    assert note.origin_device == "desktop"
    assert note.enriched is True


def test_enrich_re_enrich_replaces_trailing_line_user_body_survives(tmp_path):
    # A note already carrying a machine trailing line, re-enriched: the line is replaced, the user
    # body above it stays byte-identical.
    user_body = "the real content\n"
    _note_file(tmp_path, "r1.md",
               "id: r1\norigin: note\norigin_device: desktop\nenriched: false",
               user_body + "\ntags: #stale\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        assert text == user_body  # never the prior machine line
        return "fresh"

    assert enrich_notes(vault_notes, str(tmp_path), classify, reg=_reg("fresh")) == (1, 0)
    from frontmatter import strip_frontmatter
    from machine_tags import strip_trailing_tags_line
    written = (tmp_path / "r1.md").read_text(encoding="utf-8")
    assert "\ntags: #project@fresh\n" in strip_frontmatter(written)
    assert "#stale" not in written
    assert strip_trailing_tags_line(strip_frontmatter(written)) == user_body


def test_enrich_notes_empty_body_skips_llm_and_marks_enriched(tmp_path):
    # A note with an empty body is the recurring poison: classify has nothing to work with and the
    # model times out synthesizing every schema field from nothing. Guard: mark it enriched WITHOUT
    # an LLM call so it stops re-hitting Ollama every pass. Body stays byte-identical (empty).
    # A DESKTOP-origin empty note (phone-origin empties are handled by the provenance gate instead).
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\norigin_device: desktop\nenriched: false\nenrich_source: phone-heuristic\ncategory: _scratchpad", "")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("must not classify an empty-body note")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify)
    assert (enriched, failed) == (1, 0)          # counted done, NOT failed — no timeout, no retry
    from note_model import parse_note
    from frontmatter import strip_frontmatter
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    note = parse_note(written)
    assert note.enriched is True                 # marked done → not retried next pass
    assert note.enrich_source == "phone-heuristic"  # left as-is (no desktop-LLM pass actually ran)
    assert not hasattr(note, "category")         # legacy `category: _scratchpad` never read
    assert "category:" not in written            # never re-emitted to frontmatter
    assert strip_frontmatter(written) == ""      # BODY SACRED — still empty, byte-identical


def test_enrich_notes_whitespace_only_body_treated_as_empty(tmp_path):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", "   \n\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("whitespace-only body must not be classified")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify)
    assert (enriched, failed) == (1, 0)          # no classify call, marked enriched
    from note_model import parse_note
    from frontmatter import strip_frontmatter
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    assert parse_note(written).enriched is True
    assert strip_frontmatter(written) == "   \n\n"   # BODY SACRED — whitespace preserved


def test_enrich_notes_embed_failure_does_not_lose_enrichment(tmp_path):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", "Body.\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        return "personal"
    def embed(path, content):
        raise RuntimeError("embed server down")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify, embed=embed,
                                    reg=_reg("personal"))
    from note_model import parse_note
    assert parse_note((tmp_path / "n1.md").read_text(encoding="utf-8")).enriched is True
    assert enriched == 1        # embed failure is not an enrichment failure


def test_build_enrich_fn_reads_out_project_from_a_real_CaptureOutput(tmp_path, monkeypatch):
    """The classifier seam is bound against the REAL `CaptureOutput` shape, unpatched.

    Regression: `_build_enrich_fn.classify` used to read `out.category`, a field Task 9 deleted
    from the model. Every existing test faked the `run_llm_engine` seam with a duck-typed stub,
    so the suite stayed green while a real enrichment pass would have raised AttributeError.
    This test returns a genuine `models.CaptureOutput`, so touching any deleted attribute fails.
    """
    import mobile_sync_agent as agent
    from mobile_sync_agent import _build_enrich_fn
    from models import CaptureOutput

    body = "Note body.\n"
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", body)
    _write_registry(tmp_path, "research", "personal")
    vault_notes = _vault_notes_from(tmp_path)

    class _Ollama:  base_url = "http://localhost:11434"
    class _Vector:  embed_model = "nomic-embed-text"
    class _Vault:   root = tmp_path
    class _Cfg:     ollama = _Ollama(); vector = _Vector(); vault = _Vault()

    seen = {}
    def fake_run_llm_engine(enriched, registry, **kw):
        seen["input_type"] = enriched.input_type
        # the second argument is the REGISTRY now, not a folder-name map
        seen["projects"] = sorted((registry.get("projects") or {}).keys())
        return CaptureOutput(project="research", suggested_filename="x",
                             markdown_content=enriched.enriched_text)
    embeds = []
    def fake_index_note(root, path, content, base_url, embed_model):
        embeds.append((str(path), base_url, embed_model))

    monkeypatch.setattr(agent, "run_llm_engine", fake_run_llm_engine, raising=False)
    monkeypatch.setattr(agent, "index_note", fake_index_note, raising=False)

    enrich_fn = _build_enrich_fn(_Cfg(), str(tmp_path))
    enriched, failed = enrich_fn(vault_notes, str(tmp_path))

    assert (enriched, failed) == (1, 0)
    assert seen["input_type"] == "note"
    assert seen["projects"] == ["personal", "research"]   # live registry, not a hardcoded list
    assert embeds == [(str(tmp_path / "n1.md"), "http://localhost:11434", "nomic-embed-text")]
    from frontmatter import strip_frontmatter
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    assert "\ntags: #project@research\n" in strip_frontmatter(written)


def test_build_enrich_fn_leaves_a_note_loose_when_the_engine_picks_nothing(tmp_path, monkeypatch):
    import mobile_sync_agent as agent
    from mobile_sync_agent import _build_enrich_fn
    from models import CaptureOutput

    body = "Note body.\n"
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", body)
    _write_registry(tmp_path, "research")
    vault_notes = _vault_notes_from(tmp_path)

    class _Cfg:
        class ollama:  base_url = "http://localhost:11434"
        class vector:  embed_model = "nomic-embed-text"
        class vault:   root = tmp_path

    monkeypatch.setattr(agent, "run_llm_engine",
                        lambda enriched, registry, **kw: CaptureOutput(
                            project=None, suggested_filename="x", markdown_content=""),
                        raising=False)
    monkeypatch.setattr(agent, "index_note", lambda *a, **k: None, raising=False)

    enriched, failed = _build_enrich_fn(_Cfg(), str(tmp_path))(vault_notes, str(tmp_path))
    assert (enriched, failed) == (1, 0)
    from frontmatter import strip_frontmatter
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    assert strip_frontmatter(written) == body      # no tag written at all
    assert "project: [-]" in written


def _mock_empty_drive():
    """MagicMock drive: empty hub root (no category folders, no reserved folders, no notes).
    create/update return serializable ids so mirror's upload + any dest-folder create work."""
    drive = MagicMock()
    resp = MagicMock()
    resp.execute.return_value = {"files": [], "nextPageToken": None}
    drive.files().list.return_value = resp
    drive.files().create().execute.return_value = {"id": "F1", "headRevisionId": "r1"}
    drive.files().update().execute.return_value = {"id": "F1", "headRevisionId": "r1"}
    return drive


def test_run_once_runs_enrich_between_pull_and_mirror(tmp_path, monkeypatch):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", "Body.\n")
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    calls = []
    def fake_enrich_fn(vault_notes, vault_root):
        calls.append(sorted(vault_notes.keys()))
        from note_model import parse_note, serialize_note
        n = parse_note(vault_notes["n1"]["content"])
        n.enriched = True; n.enrich_source = "desktop-llm"
        new = serialize_note(n)
        vault_notes["n1"]["content"] = new
        vault_notes["n1"]["hash"] = _sha256(new)
        return (1, 0)

    drive = _mock_empty_drive()
    result = run_once(str(tmp_path), str(tmp_path / ".state.json"), drive,
                      vault_root=str(tmp_path), enrich_fn=fake_enrich_fn)

    assert len(result) == 7
    assert result[6] == 1        # enriched count propagated
    assert calls == [["n1"]]     # enrich saw the note, between pull and mirror


def test_run_once_enrich_none_skips(tmp_path, monkeypatch):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", "B.\n")
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")
    drive = _mock_empty_drive()
    result = run_once(str(tmp_path), str(tmp_path / ".s.json"), drive,
                      vault_root=str(tmp_path))   # enrich_fn defaults None
    assert len(result) == 7
    assert result[6] == 0        # enriched == 0 when no enrich_fn


# ---------------------------------------------------------------------------
# v3.0 (contract §1.2 as amended): K-1 and the machine refile are RETIRED. Enrichment assigns a
# project by writing a `#project@` tag and NEVER moves a file. The hub parent follows on the next
# mirror; the LOCAL file is moved by the tidy pass, not by sync.
# ---------------------------------------------------------------------------

def _project_enrich_fn(picked="research"):
    """A run_once-injectable enrich_fn forwarding to the real enrich_notes with a fake classifier."""
    def enrich_fn(vault_notes, vault_root):
        return enrich_notes(vault_notes, vault_root, lambda text: picked)
    return enrich_fn


def test_enrich_never_moves_a_file(tmp_path):
    # The one thing K-1's deletion must not silently take with it: enrichment used to os.replace
    # the note into the classified folder. It must now leave the file exactly where it is.
    body = "# Note\n\nBody text.\n"
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_registry(tmp_path, "research")
    _note_file(inbox, "n1.md",
               "id: n1\norigin: note\norigin_device: desktop\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)
    assert vault_notes["n1"]["folder"] == LOOSE_DIR   # untagged on the way in

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), lambda text: "research")

    assert (enriched, failed) == (1, 0)
    assert (inbox / "n1.md").exists()                # NOT moved -- tidy owns that
    assert not (tmp_path / "research" / "n1.md").exists()
    assert not (tmp_path / "research").exists()      # and no directory was created
    # ...but the note's derived folder now tracks the tag it just wrote, so the same pass's
    # mirror files it into the right hub folder.
    assert vault_notes["n1"]["folder"] == "research"
    from note_model import parse_note
    from machine_tags import strip_trailing_tags_line
    written = (inbox / "n1.md").read_text(encoding="utf-8")
    note = parse_note(written)
    assert note.enriched is True
    assert note.modified == ""                       # no move -> no mover stamp (K-1 retired)
    assert note.device == ""
    assert strip_trailing_tags_line(strip_frontmatter(written)) == body   # BODY SACRED


def test_run_once_reparents_the_hub_file_when_enrichment_assigns_a_project(
        tmp_path, monkeypatch):
    _write_registry(tmp_path, "research")
    loose = tmp_path / LOOSE_DIR
    loose.mkdir()
    p = _note_file(loose, "n1.md",
                   "id: n1\norigin: note\norigin_device: desktop\nenriched: false", "Body.\n")
    content = p.read_text(encoding="utf-8", newline="")
    state_path = tmp_path / ".state.json"
    # hub_name = the resolved title-based name (titleless -> Untitled.md) so no rename interleaves;
    # hub_names_migrated pre-set so the one-time Task 3.1 migration doesn't rename mid-test.
    save_state(str(state_path), {"hub_names_migrated": True,
                                 "n1": {"drive_file_id": "FID1", "base_rev": "r1",
                                        "local_hash": _sha256(content),
                                        "hub_name": "Untitled.md",
                                        "base_parent": LOOSE_DIR}})
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")
    drive = _mock_empty_drive()
    drive.files().get().execute.return_value = {"parents": ["OLDFOLDER"]}  # _move_file_to_folder read

    result = run_once(str(tmp_path), str(state_path), drive,
                      vault_root=str(tmp_path), enrich_fn=_project_enrich_fn())

    assert result[6] == 1                                  # enriched
    assert (loose / "n1.md").exists()                      # sync never moves the local file
    # Hub side: a METADATA-ONLY re-parent happened (addParents, no media_body).
    reparents = [c for c in drive.files().update.call_args_list
                 if c.kwargs.get("addParents")]
    assert len(reparents) == 1
    assert reparents[0].kwargs["fileId"] == "F1"           # the id the byte upload returned
    assert reparents[0].kwargs.get("removeParents") == "OLDFOLDER"
    assert "media_body" not in reparents[0].kwargs         # bytes never re-uploaded on the move
    # base_parent recorded in the saved sidecar (survives mirror's row rewrite).
    final = load_state(str(state_path))
    assert final["n1"]["base_parent"] == "research"


def test_run_once_unsynced_note_uploads_straight_into_its_project_folder(
        tmp_path, monkeypatch):
    # A note the hub has never seen: no re-parent call at all -- mirror CREATES it directly
    # inside the project folder the tag names, and records base_parent.
    _write_registry(tmp_path, "research")
    loose = tmp_path / LOOSE_DIR
    loose.mkdir()
    _note_file(loose, "n1.md",
               "id: n1\norigin: note\norigin_device: desktop\nenriched: false", "Body.\n")
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")
    drive = _mock_empty_drive()
    state_path = tmp_path / ".state.json"

    result = run_once(str(tmp_path), str(state_path), drive,
                      vault_root=str(tmp_path), enrich_fn=_project_enrich_fn())

    assert result[6] == 1
    assert (loose / "n1.md").exists()                      # local file untouched by sync
    # No hub re-parent for an unsynced note (nothing to move yet)...
    assert not [c for c in drive.files().update.call_args_list if c.kwargs.get("addParents")]
    # ...instead the upload creates it inside the project folder (find-or-create id "F1").
    note_creates = [c for c in drive.files().create.call_args_list
                    if c.kwargs.get("body") and c.kwargs["body"].get("appProperties")]
    assert len(note_creates) == 1
    assert note_creates[0].kwargs["body"]["parents"] == ["F1"]
    final = load_state(str(state_path))
    assert final["n1"]["base_parent"] == "research"


    final = load_state(str(state_path))
    assert final["n1"]["base_parent"] == "research"


def test_reconcile_pull_records_base_parent():
    # base_parent starts being recorded at every state-row rewrite (contract v2.3 rollout):
    # reconcile's pull path stores the hub file's parent folder.
    remote = "---\nid: n1\norigin: note\n---\nRemote body"
    vault_notes = {
        "n1": {"id": "n1", "path": str(Path("/v") / LOOSE_DIR / "n1.md"),
               "content": "---\nid: n1\norigin: note\n---\nOld",
               "body": "Old", "hash": "h1", "folder": LOOSE_DIR, "title": "", "created": ""}
    }
    hub_files = {"n1": {"id": "F1", "headRevisionId": "r2", "folder": "research"}}
    state = {"n1": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": "h1"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = remote.encode("utf-8")
    writes = []
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub",
        write_file=lambda p, c: writes.append((p, c)),
    )
    assert (reconciled, conflicts, failed) == (1, 0, 0)
    assert new_state["n1"]["base_parent"] == "research"


def test_reconcile_pull_relocates_local_file_when_the_incoming_body_changes_project(tmp_path):
    # A peer edited the note's `#project@` tag. The pulled body is the truth, so the desktop --
    # the only device that re-paths -- moves its local mirror into the directory that tag implies
    # BEFORE writing the bytes. Regression: the pull branch wrote the bytes back to the OLD folder,
    # leaving the file where sync-state said it was not.
    _write_registry(tmp_path, "work")
    scratch = tmp_path / LOOSE_DIR
    scratch.mkdir()
    seed = (
        "---\nid: n1\ntitle: T\norigin: note\ncreated: 2026-01-01T00:00:00Z\n"
        "modified: 2026-01-01T00:00:00Z\ndevice: phone\ntags: []\naliases: []\n"
        "attachments: []\nenriched: true\n---\nUnchanged body"
    )
    old_path = scratch / "T.md"
    old_path.write_text(seed, encoding="utf-8")
    # The remote gained a `#project@work` tag (and the mover's `modified` stamp).
    remote = seed.replace(
        "modified: 2026-01-01T00:00:00Z", "modified: 2026-01-02T00:00:00Z"
    ).replace("Unchanged body", "Unchanged body #project@work")
    vault_notes = {
        "n1": {"id": "n1", "path": str(old_path), "content": seed, "body": "Unchanged body",
               "hash": _sha256(seed), "folder": LOOSE_DIR, "title": "T",
               "created": "2026-01-01T00:00:00Z"}
    }
    hub_files = {"n1": {"id": "F1", "headRevisionId": "rev9", "folder": LOOSE_DIR}}
    state = {"n1": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": _sha256(seed),
                    "base_parent": LOOSE_DIR, "hub_name": "T.md"}}
    drive = _recon_drive(remote)
    reconciled, conflicts, failed, new_state = reconcile_changes(
        vault_notes, hub_files, state, drive, "hub", reg=_reg("work"),
    )
    assert (reconciled, conflicts, failed) == (1, 0, 0)
    assert (tmp_path / "work" / "T.md").exists()        # relocated into the tag's project folder
    assert not old_path.exists()                        # moved out of _loose/
    assert (tmp_path / "work" / "T.md").read_text(encoding="utf-8") == remote  # remote bytes verbatim
    assert new_state["n1"]["base_parent"] == LOOSE_DIR  # the hub parent we pulled from, unchanged


def test_pull_new_hub_notes_records_base_parent(tmp_path):
    from mobile_sync_agent import pull_new_hub_notes
    remote = "---\nid: n1\norigin: note\n---\nBody"
    hub_files = {"n1": {"id": "F1", "headRevisionId": "r1", "folder": "research",
                        "name": "n1.md"}}
    pulled, failed, new_state = pull_new_hub_notes(
        {}, hub_files, {}, None, str(tmp_path),
        download=lambda fid: remote,
    )
    assert (pulled, failed) == (1, 0)
    assert new_state["n1"]["base_parent"] == "research"


def test_run_once_reconciles_reminders_with_vault_notes(tmp_path, monkeypatch):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nremind_at: 2030-01-01T09:00", "Body.\n")
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    seen = {}
    def fake_reminders_fn(vault_notes):
        seen["paths"] = sorted(n["path"] for n in vault_notes.values())
        return {"created": 1, "updated": 0, "removed": 0}

    drive = _mock_empty_drive()
    result = run_once(str(tmp_path), str(tmp_path / ".state.json"), drive,
                      vault_root=str(tmp_path), reminders_fn=fake_reminders_fn)

    assert len(result) == 7                          # return arity unchanged
    assert len(seen["paths"]) == 1                   # reminders_fn saw the re-read vault_notes
    assert seen["paths"][0].endswith("n1.md")


def test_run_once_reminders_failsoft(tmp_path, monkeypatch):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note", "B.\n")
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    def boom(_vault_notes):
        raise RuntimeError("reminders db locked")

    drive = _mock_empty_drive()
    # must NOT raise — a reminders failure never aborts the sync pass
    result = run_once(str(tmp_path), str(tmp_path / ".s.json"), drive,
                      vault_root=str(tmp_path), reminders_fn=boom)
    assert len(result) == 7


def test_build_reminders_fn_reconciles_db(tmp_path, monkeypatch):
    from mobile_sync_agent import _build_reminders_fn
    from reminders import list_reminders
    from index_writer import get_db_path
    import reminders as reminders_mod

    # WS-4: synced reminders now request delivery="os", which on Windows would fire a real schtasks
    # subprocess. Stub it so this reconcile test stays hermetic (it asserts DB reconcile, not delivery).
    monkeypatch.setattr(reminders_mod, "_create_schtask", lambda *a, **k: None)

    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\ntitle: Call\nremind_at: 2030-06-01T09:00", "Body.\n")
    vault_notes = read_vault_notes(str(tmp_path))
    out = _build_reminders_fn(str(tmp_path))(vault_notes)
    assert out == {"created": 1, "updated": 0, "removed": 0}
    rows = list_reminders(get_db_path(Path(tmp_path)))
    assert len(rows) == 1 and rows[0]["fire_at"] == "2030-06-01T09:00"


# ---------------------------------------------------------------------------
# B8 · LAN accelerator wired into the live run_once caller (main())
# ---------------------------------------------------------------------------

def test_build_provisional_fn_drops_staging_and_index(tmp_path):
    """_build_provisional_fn's callback drops BOTH the on-disk staging (T7/T8) and the
    search/RAG provisional index row (T13) together for a given note_id."""
    import provisional_store as ps
    from index_writer import init_db, upsert_provisional
    from mobile_sync_agent import _build_provisional_fn

    vault = tmp_path / "vault"
    vault.mkdir()
    sync_dir = str(vault / ".sync")
    ps.stage(sync_dir, "op1", "noteA", "---\n---\nprovisional body\n", {"staged_at": 1.0})

    db = init_db(vault)
    upsert_provisional(db, "op1", "noteA", "---\n---\nprovisional body\n", {})
    rows = db.execute(
        "SELECT * FROM captures WHERE path = ?", ("__lan_provisional__/op1",)
    ).fetchall()
    assert len(rows) == 1   # sanity: indexed before supersede

    provisional_fn = _build_provisional_fn(str(vault))
    provisional_fn("noteA")

    assert ps.list_provisional(sync_dir) == []            # on-disk staging dropped
    rows = db.execute(
        "SELECT * FROM captures WHERE path = ?", ("__lan_provisional__/op1",)
    ).fetchall()
    assert rows == []                                       # index row dropped too


def _fake_cfg(vault_root: Path, lan_enabled: bool):
    import types
    return types.SimpleNamespace(
        vault=types.SimpleNamespace(root=vault_root, scratchpad_folder="_scratchpad"),
        lan=types.SimpleNamespace(enabled=lan_enabled, host="", port=7071),
        sync=types.SimpleNamespace(mirror_captures=False, interval_minutes=60),
    )


def _patch_main_seams(monkeypatch, vault: Path, lan_enabled: bool):
    """Stub every collaborator main() reaches out to (auth, config, pipeline, run_once)
    so the wiring itself — what gets passed to run_once, whether LAN work fires — can be
    asserted without touching real Drive/Ollama/DB services."""
    # run_pass() calls reload_config() (fresh config every pass so a GUI toggle / manual sync-now
    # picks up the latest [sync]/[lan]); get_config kept stubbed for any other caller.
    monkeypatch.setattr("config.get_config", lambda: _fake_cfg(vault, lan_enabled))
    monkeypatch.setattr("config.reload_config", lambda *a, **k: _fake_cfg(vault, lan_enabled))
    monkeypatch.setattr("drive_auth.get_drive_service", lambda: MagicMock())
    monkeypatch.setattr("main.run_pipeline", lambda **kw: {})


def test_main_wires_provisional_fn_and_refreshes_outbound_when_lan_enabled(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OMNI_VAULT", str(vault))
    monkeypatch.setenv("OMNI_SYNC_STATE", str(tmp_path / "state.json"))
    _patch_main_seams(monkeypatch, vault, lan_enabled=True)

    captured = {}

    def fake_run_once(*args, **kwargs):
        captured["provisional_fn"] = kwargs.get("provisional_fn")
        return (0, 0, 0, 0, 0, 0, 0)

    monkeypatch.setattr("mobile_sync_agent.run_once", fake_run_once)

    refreshed = []
    monkeypatch.setattr("lan_sync.refresh_outbound", lambda vp: refreshed.append(vp))
    swept = []
    monkeypatch.setattr(
        "provisional_store.sweep",
        lambda sd, now_ts, ttl_seconds: swept.append((sd, ttl_seconds)),
    )

    from mobile_sync_agent import main as sync_main
    sync_main()

    assert captured["provisional_fn"] is not None      # LAN enabled -> provisional_fn wired
    assert refreshed == [str(vault)]                    # refresh_outbound fired once
    assert swept and swept[0][0] == str(vault / ".sync")  # TTL sweep fired once


def test_main_no_lan_work_when_disabled(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OMNI_VAULT", str(vault))
    monkeypatch.setenv("OMNI_SYNC_STATE", str(tmp_path / "state.json"))
    _patch_main_seams(monkeypatch, vault, lan_enabled=False)

    captured = {}

    def fake_run_once(*args, **kwargs):
        captured["provisional_fn"] = kwargs.get("provisional_fn")
        return (0, 0, 0, 0, 0, 0, 0)

    monkeypatch.setattr("mobile_sync_agent.run_once", fake_run_once)

    refreshed = []
    monkeypatch.setattr("lan_sync.refresh_outbound", lambda vp: refreshed.append(vp))
    swept = []
    monkeypatch.setattr("provisional_store.sweep", lambda *a, **k: swept.append(1))

    from mobile_sync_agent import main as sync_main
    sync_main()

    assert captured["provisional_fn"] is None    # LAN disabled -> exactly the old behavior
    assert refreshed == []                        # no refresh_outbound call
    assert swept == []                            # no sweep call


def test_hub_filename_parity_table():
    C = "2026-07-19T15:30:00Z"
    assert _hub_filename("Grocery List", C) == "Grocery List.md"
    assert _hub_filename("", C) == "Untitled 2026-07-19 1530.md"
    assert _hub_filename("   ", C) == "Untitled 2026-07-19 1530.md"
    assert _hub_filename("a/b:c", C) == "a-b-c.md"
    assert _hub_filename("///", C) == "Untitled 2026-07-19 1530.md"
    assert _hub_filename("CON", C) == "CON_.md"
    assert _hub_filename("x" * 200, C) == "x" * 120 + ".md"
    assert _hub_filename("  ..dots.. ", C) == "dots.md"
    # Untitled uses the LITERAL wall-clock digits — a naive-local (desktop-written) and a Z (phone-
    # written) created with the same digits MUST give the same filename (no timezone conversion).
    assert _hub_filename("", "2026-07-19T10:30:00") == "Untitled 2026-07-19 1030.md"
    assert _hub_filename("", "2026-07-19T10:30:00Z") == "Untitled 2026-07-19 1030.md"


def test_resolve_hub_names_suffixes_the_later_created_loser():
    notes = [
        {"id": "01AAAAAA", "title": "Meeting", "created": "2026-07-19T10:00:00Z", "category": "Work"},
        {"id": "01BBBBBB", "title": "Meeting", "created": "2026-07-19T11:00:00Z", "category": "Work"},
        {"id": "01CCCCCC", "title": "Solo",    "created": "2026-07-19T10:00:00Z", "category": "Work"},
    ]
    out = _resolve_hub_names(notes)
    assert out["01AAAAAA"] == "Meeting.md"
    assert out["01BBBBBB"] == "Meeting (2026-07-19 1100).md"   # loser suffixed with its created date+time
    assert out["01CCCCCC"] == "Solo.md"


def test_resolve_hub_names_same_minute_losers_disambiguate_by_id():
    # two losers sharing the title AND the same minute -> the second gets its short id appended so the
    # local filename stays unique (a bare date+time would collide -> overwrite -> body loss). Parity w/ phone.
    notes = [
        {"id": "01AAAAAA", "title": "Meeting", "created": "2026-07-19T10:00:00Z", "category": "Work"},
        {"id": "01BBBBBB", "title": "Meeting", "created": "2026-07-19T10:05:00Z", "category": "Work"},
        {"id": "01CCCCCC", "title": "Meeting", "created": "2026-07-19T10:05:40Z", "category": "Work"},
    ]
    out = _resolve_hub_names(notes)
    assert out["01AAAAAA"] == "Meeting.md"                          # winner (earliest)
    assert out["01BBBBBB"] == "Meeting (2026-07-19 1005).md"        # first loser keeps the clean stamp
    assert out["01CCCCCC"] == "Meeting (2026-07-19 1005 CCCCCC).md" # same minute -> id appended


# ---------------------------------------------------------------------------
# Task 2.4 · name uploads by title, rename in place, local rename on title change
# ---------------------------------------------------------------------------

def test_upload_note_names_by_title_and_renames_in_place():
    # existing file id F1; note title now "New" -> update carries name="New.md", SAME file id
    # (no create call at all -- rename in place, never a new note).
    captured = {}

    class _Exec:
        def __init__(self, r):
            self.r = r
        def execute(self):
            return self.r

    class _Files:
        def update(self, **k):
            captured.update(k)
            return _Exec({"id": "F1", "headRevisionId": "r2", "name": "New.md"})
        def create(self, **k):
            raise AssertionError("must not create a new file — this is a rename in place")

    class _Drive:
        def files(self):
            return _Files()

    note = {
        "id": "01H8", "title": "New", "created": "2026-07-19T10:00:00Z",
        "content": "---\nid: 01H8\ntitle: New\ncreated: 2026-07-19T10:00:00Z\n---\nbody\n",
        "body": "body\n",
    }
    result = _upload_note(_Drive(), note, "DEST", {"drive_file_id": "F1"})
    assert result == {"id": "F1", "headRevisionId": "r2", "name": "New.md"}
    assert captured["fileId"] == "F1"                 # same file id -- rename in place
    assert captured["body"]["name"] == "New.md"       # renamed to the new title
    assert captured["body"]["appProperties"] == {"noteId": "01H8"}


def test_upload_note_skips_needless_rename_when_name_unchanged():
    """Existing file whose LAST synced name already matches the resolved name -> `name` is
    dropped from the update body (no needless headRevisionId bump on a pure content edit)."""
    captured = {}

    class _Exec:
        def __init__(self, r):
            self.r = r
        def execute(self):
            return self.r

    class _Files:
        def update(self, **k):
            captured.update(k)
            return _Exec({"id": "F1", "headRevisionId": "r3"})

    class _Drive:
        def files(self):
            return _Files()

    note = {
        "id": "01H8", "title": "Same", "created": "2026-07-19T10:00:00Z",
        "content": "---\nid: 01H8\n---\nbody2\n", "body": "body2\n",
    }
    _upload_note(_Drive(), note, "DEST", {"drive_file_id": "F1", "hub_name": "Same.md"},
                hub_name="Same.md")
    assert "name" not in captured["body"]
    assert captured["body"]["appProperties"] == {"noteId": "01H8"}


def test_mirror_renames_local_vault_file_on_title_change(tmp_path):
    """A note retitled locally: mirror_to_hub renames the vault file in place (os.replace) BEFORE
    upload, body byte-identical, old path gone, no duplicate left behind."""
    category = tmp_path / "Inbox"
    category.mkdir()
    old_path = category / "Old.md"
    content = "---\nid: 01H8\ntitle: New\ncreated: 2026-07-19T10:00:00Z\n---\nsame body\n"
    old_path.write_text(content, encoding="utf-8", newline="")

    vault_notes = {
        "01H8": {"id": "01H8", "path": str(old_path), "content": content, "body": "same body\n",
                 "hash": "HNEW", "folder": "Inbox", "title": "New",
                 "created": "2026-07-19T10:00:00Z"}
    }
    # Prior sync tracked this note under its OLD resolved name "Old.md" -- the retitle is the
    # only thing that changed since, so the mismatch against the freshly resolved "New.md" is a
    # genuine title change, not a first-ever-sync placeholder.
    state = {"01H8": {"drive_file_id": "F1", "base_rev": "rev1", "local_hash": "HOLD",
                       "hub_name": "Old.md", "base_parent": "Inbox"}}
    drive = MagicMock()
    drive.files().update().execute.return_value = {"id": "F1", "headRevisionId": "rev2",
                                                    "name": "New.md"}

    uploaded, failed, new_state = mirror_to_hub(vault_notes, {}, state, drive, "hub")

    assert (uploaded, failed) == (1, 0)
    new_path = category / "New.md"
    assert new_path.exists()
    assert not old_path.exists()                       # old path gone, no duplicate
    assert new_path.read_text(encoding="utf-8", newline="") == content   # body byte-identical
    assert new_state["01H8"]["hub_name"] == "New.md"
    # the hub side was renamed in place too (same file id F1, no create call)
    drive.files().create.assert_not_called()
    assert drive.files().update.call_args.kwargs["body"]["name"] == "New.md"


# ---------------------------------------------------------------------------
# Task 3.1 · one-time hub-filename migration
# ---------------------------------------------------------------------------

from mobile_sync_agent import migrate_hub_filenames


def _migrate_note_text(nid, title, created="2026-01-01T10:00:00Z"):
    return f"---\nid: {nid}\ntitle: {title}\ncreated: {created}\norigin: note\n---\nbody\n"


def _migrate_drive(categories, files_by_folder, contents, root_files=None):
    """Fake drive for migrate_hub_filenames tests. Tracks LIVE file state (name/appProperties) in
    a registry that update() mutates and list() reads back from — needed so a rename performed by
    one call is visible to a later call in the same test (resumability tests need this; a static
    MagicMock fixture like other tests use would not reflect the drive-side rename)."""
    registry: dict = {}
    folder_of: dict = {}
    for fid, files in files_by_folder.items():
        for f in files:
            registry[f["id"]] = dict(f)
            folder_of[f["id"]] = fid
    for f in (root_files or []):
        registry[f["id"]] = dict(f)
        folder_of[f["id"]] = "HUB"

    drive = MagicMock()

    def _list(**kw):
        q = kw.get("q", "")
        resp = MagicMock()
        if "'HUB' in parents" in q:
            if f"mimeType='{_FOLDER_MIME}'" in q:
                resp.execute.return_value = {
                    "files": [{"id": fid, "name": n, "mimeType": _FOLDER_MIME}
                              for n, fid in categories.items()],
                    "nextPageToken": None,
                }
            else:
                resp.execute.return_value = {
                    "files": [f for fid, f in registry.items() if folder_of.get(fid) == "HUB"],
                    "nextPageToken": None,
                }
        else:
            parent = next((fid for fid in files_by_folder if f"'{fid}' in parents" in q), None)
            resp.execute.return_value = {
                "files": [f for fid, f in registry.items() if folder_of.get(fid) == parent],
                "nextPageToken": None,
            }
        return resp

    drive.files().list.side_effect = _list

    def _get_media(fileId=None):
        resp = MagicMock()
        resp.execute.return_value = contents[fileId].encode("utf-8")
        return resp

    drive.files().get_media.side_effect = _get_media

    updates = []

    def _update(**kw):
        updates.append(kw)
        fid = kw["fileId"]
        body = kw["body"]
        if "name" in body:
            registry[fid]["name"] = body["name"]
        if "appProperties" in body:
            registry[fid]["appProperties"] = body["appProperties"]
        resp = MagicMock()
        resp.execute.return_value = {"id": fid, "headRevisionId": "rX", "name": registry[fid]["name"]}
        return resp

    drive.files().update.side_effect = _update
    drive._updates = updates
    drive._registry = registry
    return drive


def test_migrate_renames_legacy_files_to_title_and_stamps_note_id():
    contents = {
        "F1": _migrate_note_text("01AAA", "Alpha", "2026-01-01T10:00:00Z"),
        "F2": _migrate_note_text("01BBB", "Beta", "2026-01-02T10:00:00Z"),
    }
    drive = _migrate_drive(
        categories={"personal": "c1"},
        files_by_folder={"c1": [
            {"id": "F1", "name": "01AAA.md", "headRevisionId": "r1"},
            {"id": "F2", "name": "01BBB.md", "headRevisionId": "r2"},  # neither has appProperties
        ]},
        contents=contents,
    )

    new_state = migrate_hub_filenames(drive, "HUB", {})

    assert new_state["hub_names_migrated"] is True
    renamed = {u["fileId"]: u["body"] for u in drive._updates}
    assert renamed["F1"] == {"name": "Alpha.md", "appProperties": {"noteId": "01AAA"}}
    assert renamed["F2"] == {"name": "Beta.md", "appProperties": {"noteId": "01BBB"}}
    assert drive._registry["F1"]["name"] == "Alpha.md"
    assert drive._registry["F2"]["name"] == "Beta.md"


def test_migrate_guard_skips_when_already_migrated():
    drive = MagicMock()
    state = {"hub_names_migrated": True}
    result = migrate_hub_filenames(drive, "HUB", state)
    assert result == state
    drive.files().list.assert_not_called()
    drive.files().update.assert_not_called()
    drive.files().get_media.assert_not_called()


def test_migrate_idempotent_second_run_is_zero_update_calls():
    contents = {"F1": _migrate_note_text("01AAA", "Alpha")}
    drive = _migrate_drive(
        categories={"personal": "c1"},
        files_by_folder={"c1": [{"id": "F1", "name": "01AAA.md", "headRevisionId": "r1"}]},
        contents=contents,
    )
    state1 = migrate_hub_filenames(drive, "HUB", {})
    assert len(drive._updates) == 1

    state2 = migrate_hub_filenames(drive, "HUB", state1)
    assert state2 is state1              # top-level guard short-circuits, no rescan at all
    assert len(drive._updates) == 1      # unchanged


def test_migrate_per_file_noop_on_second_scan_before_flag_persisted():
    """Simulate a resumed migration where the flag was NOT yet persisted (crash before save) but
    the file itself was already renamed+stamped on Drive in the earlier attempt: a fresh scan must
    treat it as a no-op (zero update calls for that file) — this is what makes resuming cheap."""
    contents = {"F1": _migrate_note_text("01AAA", "Alpha")}
    drive = _migrate_drive(
        categories={"personal": "c1"},
        files_by_folder={"c1": [{"id": "F1", "name": "01AAA.md", "headRevisionId": "r1"}]},
        contents=contents,
    )
    migrate_hub_filenames(drive, "HUB", {})
    assert len(drive._updates) == 1

    # Re-scan with an empty state (as if the flag write never landed) — per-file check must still
    # skip the already-renamed, already-stamped file.
    migrate_hub_filenames(drive, "HUB", {})
    assert len(drive._updates) == 1


def test_migrate_resumable_after_mid_pass_failure():
    contents = {
        "F1": _migrate_note_text("01AAA", "Alpha"),
        "F2": _migrate_note_text("01BBB", "Beta"),
    }
    drive = _migrate_drive(
        categories={"personal": "c1"},
        files_by_folder={"c1": [
            {"id": "F1", "name": "01AAA.md", "headRevisionId": "r1"},
            {"id": "F2", "name": "01BBB.md", "headRevisionId": "r2"},
        ]},
        contents=contents,
    )

    real_update = drive.files().update.side_effect

    def _flaky_update(**kw):
        if kw["fileId"] == "F2":
            raise RuntimeError("simulated Drive failure")
        return real_update(**kw)

    drive.files().update.side_effect = _flaky_update

    with pytest.raises(RuntimeError):
        migrate_hub_filenames(drive, "HUB", {})
    assert len(drive._updates) == 1                     # F1 renamed before the failure hit F2
    assert drive._registry["F1"]["name"] == "Alpha.md"  # F1's rename stuck despite the raise

    # flag never set -> caller re-runs migrate_hub_filenames on next pass, same (unset) state
    drive.files().update.side_effect = real_update
    state = migrate_hub_filenames(drive, "HUB", {})
    assert state["hub_names_migrated"] is True
    assert len(drive._updates) == 2       # only F2 updated this pass -- F1 was already a no-op
    assert drive._registry["F2"]["name"] == "Beta.md"


def test_migrate_records_hub_name_for_an_already_tracked_note():
    """A note this desktop already has a prior sync-state record for (drive_file_id/base_rev
    already tracked from an earlier ordinary sync) gets state["hub_name"] set to the resolved
    name -- this is what run_once's local-rename step (reusing its own vault_notes read) keys off
    to converge the local vault mirror afterwards. Migration itself does no local/vault IO."""
    contents = {"F1": _migrate_note_text("01AAA", "Alpha")}
    drive = _migrate_drive(
        categories={"personal": "c1"},
        files_by_folder={"c1": [{"id": "F1", "name": "01AAA.md", "headRevisionId": "r1"}]},
        contents=contents,
    )
    prior_state = {"01AAA": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": "H"}}

    state = migrate_hub_filenames(drive, "HUB", prior_state)

    assert state["01AAA"]["hub_name"] == "Alpha.md"
    assert state["01AAA"]["base_rev"] == "r1"      # pre-existing fields survive the update
    assert drive._registry["F1"]["name"] == "Alpha.md"


def test_migrate_never_pulled_note_leaves_state_untouched_for_pull_to_still_claim_it():
    """A hub note the desktop has NEVER pulled (no prior state entry) must NOT get a state entry
    from migration alone -- pull_new_hub_notes' "already tracked" skip
    (`if key in vault_notes or key in state: continue`) would otherwise treat a bare hub_name-only
    stub as already-synced and silently swallow the note's first pull forever. Also: a state entry
    with `hub_name` but no `base_rev` would KeyError in reconcile_changes' non-adopted 3-way-merge
    path (`prior["base_rev"]` is bare-key indexed there), which only pre-existing entries avoid."""
    contents = {"F1": _migrate_note_text("01AAA", "Alpha")}
    drive = _migrate_drive(
        categories={"personal": "c1"},
        files_by_folder={"c1": [{"id": "F1", "name": "01AAA.md", "headRevisionId": "r1"}]},
        contents=contents,
    )
    state = migrate_hub_filenames(drive, "HUB", {})
    assert "01AAA" not in state          # hub file was still renamed...
    assert drive._registry["F1"]["name"] == "Alpha.md"
    assert state["hub_names_migrated"] is True


def test_run_once_migration_renames_hub_and_local_file_for_a_tracked_note(tmp_path, monkeypatch):
    """Integration: run_once wires migrate_hub_filenames (hub-side rename) + its own local-rename
    step (reusing the vault_notes it already read) so an already-tracked legacy note converges on
    BOTH sides in one pass, and the second pass is a clean no-op (flag set, per-file no-op)."""
    vault = tmp_path / "vault"
    cat = vault / "personal"
    cat.mkdir(parents=True)
    local_content = _migrate_note_text("01AAA", "Alpha")
    local_path = cat / "01AAA.md"
    local_path.write_text(local_content, encoding="utf-8", newline="")

    state_path = str(tmp_path / "state.json")
    save_state(state_path, {
        "01AAA": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": _sha256(local_content)},
    })

    drive = _migrate_drive(
        categories={"personal": "c1"},
        files_by_folder={"c1": [{"id": "F1", "name": "01AAA.md", "headRevisionId": "r1"}]},
        contents={"F1": local_content},
    )
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    run_once(str(vault), state_path, drive, vault_root=str(vault))

    new_local = cat / "Alpha.md"
    assert new_local.exists()
    assert not local_path.exists()
    assert new_local.read_text(encoding="utf-8", newline="") == local_content
    assert drive._registry["F1"]["name"] == "Alpha.md"

    final_state = load_state(state_path)
    assert final_state["hub_names_migrated"] is True
    assert final_state["01AAA"]["hub_name"] == "Alpha.md"

    # second pass: pure no-op migration-wise (flag set) -- no further Drive update calls, no
    # further local rename (already converged).
    drive._updates.clear()
    run_once(str(vault), state_path, drive, vault_root=str(vault))
    assert drive._updates == []


# ---------------------------------------------------------------------------
# PKG-ATTACH legs 3+4 (spec §4.3): desktop <-> hub attachment bytes.
# An attachment is NOT a note op — no base_rev, no reconcile entry, no sync_state row.
# Identity is (note_id, filename); PRESENCE IS THE ENTIRE STATE MODEL.
# ---------------------------------------------------------------------------

from mobile_sync_agent import _sync_note_attachments, _ATTACHMENTS_FOLDER


class _AttachExec:
    def __init__(self, value):
        self._value = value

    def execute(self):
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


class _AttachFiles:
    def __init__(self, drive):
        self.d = drive

    def list(self, q=None, fields=None, pageToken=None):
        self.d.calls.append(("list", q))
        return _AttachExec(self.d._do_list(q))

    def create(self, body=None, media_body=None, fields=None):
        self.d.calls.append(("create", (body or {}).get("name")))
        return _AttachExec(self.d._do_create(body or {}, media_body))

    def get_media(self, fileId=None):
        self.d.calls.append(("get_media", fileId))
        if fileId in self.d.fail_download_for:
            return _AttachExec(RuntimeError(f"network died on {fileId}"))
        return _AttachExec(self.d.blobs[fileId]["data"])


class _AttachDrive:
    """Fake Drive covering exactly the primitives the attachment path uses: find-or-create
    subfolder, list children, binary create, get_media. `calls` records EVERY Drive call so
    the zero-call guarantee is assertable."""

    def __init__(self):
        self.folders = {}        # (parent_id, name) -> folder_id
        self.blobs = {}          # file_id -> {"name", "parent", "data"}
        self.calls = []
        self.fail_download_for = set()
        self._seq = 0

    def files(self):
        return _AttachFiles(self)

    def add_folder(self, parent_id, name):
        self._seq += 1
        fid = f"folder{self._seq}"
        self.folders[(parent_id, name)] = fid
        return fid

    def add_blob(self, parent_id, name, data):
        self._seq += 1
        fid = f"blob{self._seq}"
        self.blobs[fid] = {"name": name, "parent": parent_id, "data": data}
        return fid

    def _do_list(self, q):
        import re as _re
        parent = _re.search(r"'([^']+)' in parents", q).group(1)
        name_m = _re.search(r"name='([^']*)'", q)
        if name_m:                       # _find_or_create_subfolder probe
            fid = self.folders.get((parent, name_m.group(1)))
            return {"files": ([{"id": fid}] if fid else []), "nextPageToken": None}
        files = [
            {"id": fid, "name": b["name"], "mimeType": "application/octet-stream"}
            for fid, b in self.blobs.items() if b["parent"] == parent
        ]
        return {"files": files, "nextPageToken": None}

    def _do_create(self, body, media_body):
        if body.get("mimeType") == _FOLDER_MIME:
            return {"id": self.add_folder(body["parents"][0], body["name"])}
        data = media_body.getbytes(0, media_body.size())
        return {"id": self.add_blob(body["parents"][0], body["name"], data)}


def _ref(note_id, filename, alt="photo"):
    return f"![{alt}](../_attachments/{note_id}/{filename})"


def _attach_local(vault_root: Path, note_id: str, name: str, data: bytes) -> Path:
    d = vault_root / _ATTACHMENTS_FOLDER / note_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def test_attach_no_refs_and_no_local_dir_makes_zero_drive_calls(tmp_path):
    drive = _AttachDrive()
    result = _sync_note_attachments(drive, "HUB", "n1", "just a plain body\n", str(tmp_path), {})
    assert result == (0, 0, 0)
    assert drive.calls == []            # the common case costs NOTHING on the wire


def test_attach_uploads_referenced_local_file(tmp_path):
    drive = _AttachDrive()
    _attach_local(tmp_path, "n1", "photo-1.jpg", b"JPEGBYTES")
    body = f"see {_ref('n1', 'photo-1.jpg')}\n"

    assert _sync_note_attachments(drive, "HUB", "n1", body, str(tmp_path), {}) == (1, 0, 0)

    stored = [b for b in drive.blobs.values() if b["name"] == "photo-1.jpg"]
    assert len(stored) == 1 and stored[0]["data"] == b"JPEGBYTES"


def test_attach_downloads_remote_missing_locally(tmp_path):
    drive = _AttachDrive()
    root = drive.add_folder("HUB", _ATTACHMENTS_FOLDER)
    sub = drive.add_folder(root, "n1")
    drive.add_blob(sub, "memo.m4a", b"AUDIO")

    assert _sync_note_attachments(
        drive, "HUB", "n1", _ref("n1", "memo.m4a", "voice memo"), str(tmp_path), {}) == (0, 1, 0)
    landed = tmp_path / _ATTACHMENTS_FOLDER / "n1" / "memo.m4a"
    assert landed.read_bytes() == b"AUDIO"
    assert list((tmp_path / _ATTACHMENTS_FOLDER / "n1").glob("*.tmp")) == []


def test_attach_both_directions_in_one_call(tmp_path):
    drive = _AttachDrive()
    root = drive.add_folder("HUB", _ATTACHMENTS_FOLDER)
    sub = drive.add_folder(root, "n1")
    drive.add_blob(sub, "theirs.png", b"THEIRS")
    _attach_local(tmp_path, "n1", "mine.png", b"MINE")

    assert _sync_note_attachments(
        drive, "HUB", "n1", _ref("n1", "mine.png"), str(tmp_path), {}) == (1, 1, 0)
    assert (tmp_path / _ATTACHMENTS_FOLDER / "n1" / "theirs.png").read_bytes() == b"THEIRS"
    assert any(b["name"] == "mine.png" for b in drive.blobs.values())


def test_attach_already_in_sync_transfers_nothing(tmp_path):
    drive = _AttachDrive()
    root = drive.add_folder("HUB", _ATTACHMENTS_FOLDER)
    sub = drive.add_folder(root, "n1")
    drive.add_blob(sub, "photo.jpg", b"REMOTE")
    _attach_local(tmp_path, "n1", "photo.jpg", b"LOCAL")

    assert _sync_note_attachments(
        drive, "HUB", "n1", _ref("n1", "photo.jpg"), str(tmp_path), {}) == (0, 0, 0)
    assert [c for c in drive.calls if c[0] == "get_media"] == []
    assert len(drive.blobs) == 1                                  # nothing re-uploaded
    assert (tmp_path / _ATTACHMENTS_FOLDER / "n1" / "photo.jpg").read_bytes() == b"LOCAL"


def test_attach_unreferenced_local_file_is_never_uploaded(tmp_path):
    # An orphan (a ref the user deleted from the body) stays local. Never pushed, never deleted.
    drive = _AttachDrive()
    _attach_local(tmp_path, "n1", "orphan.jpg", b"ORPHAN")

    assert _sync_note_attachments(
        drive, "HUB", "n1", "no refs here\n", str(tmp_path), {}) == (0, 0, 0)
    assert drive.blobs == {}
    assert (tmp_path / _ATTACHMENTS_FOLDER / "n1" / "orphan.jpg").exists()   # never deleted


def test_attach_failed_download_leaves_no_file_and_no_tmp(tmp_path):
    # Presence IS the state model, so a truncated file that "exists" would never be retried.
    drive = _AttachDrive()
    root = drive.add_folder("HUB", _ATTACHMENTS_FOLDER)
    sub = drive.add_folder(root, "n1")
    bad = drive.add_blob(sub, "big.m4a", b"PARTIAL")
    drive.add_blob(sub, "good.jpg", b"OK")
    drive.fail_download_for.add(bad)
    body = _ref("n1", "big.m4a", "voice memo") + "\n" + _ref("n1", "good.jpg")

    up, down, failed = _sync_note_attachments(drive, "HUB", "n1", body, str(tmp_path), {})

    assert (up, down, failed) == (0, 1, 1)          # fail-soft: the sibling still landed
    d = tmp_path / _ATTACHMENTS_FOLDER / "n1"
    assert not (d / "big.m4a").exists()             # no truncated file at the final path
    assert list(d.glob("*.tmp")) == []              # and no stray temp sibling
    assert (d / "good.jpg").read_bytes() == b"OK"


def test_attach_never_overwrites_existing_local_bytes(tmp_path):
    drive = _AttachDrive()
    root = drive.add_folder("HUB", _ATTACHMENTS_FOLDER)
    sub = drive.add_folder(root, "n1")
    drive.add_blob(sub, "same.jpg", b"REMOTE-DIFFERENT-BYTES")
    _attach_local(tmp_path, "n1", "same.jpg", b"LOCAL")

    assert _sync_note_attachments(drive, "HUB", "n1", "", str(tmp_path), {}) == (0, 0, 0)
    assert (tmp_path / _ATTACHMENTS_FOLDER / "n1" / "same.jpg").read_bytes() == b"LOCAL"


def test_attach_filename_with_space_round_trips(tmp_path):
    # The phone permits spaces (mirror.ts isSafeAttachmentName); both legs must carry them.
    drive = _AttachDrive()
    _attach_local(tmp_path, "n1", "beach day.jpg", b"SAND")
    body = _ref("n1", "beach day.jpg")
    assert _sync_note_attachments(drive, "HUB", "n1", body, str(tmp_path), {}) == (1, 0, 0)

    other = tmp_path / "peer"           # …and back down into a fresh vault
    other.mkdir()
    assert _sync_note_attachments(drive, "HUB", "n1", body, str(other), {}) == (0, 1, 0)
    assert (other / _ATTACHMENTS_FOLDER / "n1" / "beach day.jpg").read_bytes() == b"SAND"


def test_attach_root_folder_is_cached_across_notes(tmp_path):
    drive = _AttachDrive()
    cache = {}
    _attach_local(tmp_path, "n1", "a.jpg", b"A")
    _attach_local(tmp_path, "n2", "b.jpg", b"B")
    _sync_note_attachments(drive, "HUB", "n1", _ref("n1", "a.jpg"), str(tmp_path), cache)
    _sync_note_attachments(drive, "HUB", "n2", _ref("n2", "b.jpg"), str(tmp_path), cache)

    root_probes = [c for c in drive.calls
                   if c[0] == "list" and f"name='{_ATTACHMENTS_FOLDER}'" in c[1]]
    assert len(root_probes) == 1        # root find-or-created once per pass, then cached


# --- T7: wired as run_once phase 6 -----------------------------------------

def test_run_once_attachment_phase_runs_after_mirror(tmp_path, monkeypatch):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note", "Body.\n")
    drive = _mock_empty_drive()
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    order = []
    real_mirror = mirror_to_hub

    def spy_mirror(*a, **k):
        order.append("mirror")
        return real_mirror(*a, **k)

    monkeypatch.setattr("mobile_sync_agent.mirror_to_hub", spy_mirror)
    monkeypatch.setattr(
        "mobile_sync_agent._sync_note_attachments",
        lambda d, h, nid, b, vr, c: order.append(f"attach:{nid}") or (0, 0, 0),
    )

    run_once(str(tmp_path), str(tmp_path / "s.json"), drive, vault_root=str(tmp_path))

    assert order == ["mirror", "attach:n1"]


def test_run_once_attachment_failure_does_not_abort_pass(tmp_path, monkeypatch):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note", "Body.\n")
    drive = _mock_empty_drive()
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    def boom(*a, **k):
        raise RuntimeError("drive on fire")

    monkeypatch.setattr("mobile_sync_agent._sync_note_attachments", boom)

    result = run_once(str(tmp_path), str(tmp_path / "s.json"), drive, vault_root=str(tmp_path))

    assert len(result) == 7                    # tuple contract intact
    assert result[0] == 1                      # the note's own sync still succeeded
    assert result[1] == 0                      # …and an attachment failure is NOT a note failure


def test_run_once_attachment_failure_on_one_note_still_syncs_the_others(tmp_path, monkeypatch):
    """Per-NOTE containment: a Drive-level failure on one note must not cost every note after
    it in the same pass. Presence is the state, so the failed one just retries next pass."""
    for nid in ("n1", "n2", "n3"):
        _note_file(tmp_path, f"{nid}.md", f"id: {nid}\norigin: note", "Body.\n")
    drive = _mock_empty_drive()
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    seen = []

    def flaky(d, h, nid, b, vr, c):
        seen.append(nid)
        if nid == "n2":
            raise RuntimeError("drive on fire")
        return (1, 0, 0)

    monkeypatch.setattr("mobile_sync_agent._sync_note_attachments", flaky)

    result = run_once(str(tmp_path), str(tmp_path / "s.json"), drive, vault_root=str(tmp_path))

    assert sorted(seen) == ["n1", "n2", "n3"]   # every note was attempted, none skipped
    assert len(result) == 7 and result[1] == 0  # tuple intact, not counted as a note failure


def test_run_once_attachment_phase_skips_sync_ignored_note(tmp_path, monkeypatch):
    # F-5: an ignored note never leaves this machine — nor do its bytes.
    from sync_ignore import set_ignored
    p1 = _note_file(tmp_path, "n1.md", "id: n1\norigin: note", "Body.\n")
    _note_file(tmp_path, "n2.md", "id: n2\norigin: note", "Body.\n")
    set_ignored(tmp_path, str(p1), True)

    drive = _mock_empty_drive()
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")
    seen = []
    monkeypatch.setattr("mobile_sync_agent._sync_note_attachments",
                        lambda d, h, nid, b, vr, c: seen.append(nid) or (0, 0, 0))

    run_once(str(tmp_path), str(tmp_path / "s.json"), drive, vault_root=str(tmp_path))

    assert seen == ["n2"]


# --- T8: `attachments:` derived from the body on the sync-agent save path ---

def test_enrich_derives_attachments_from_body(tmp_path):
    body = f"Hi {_ref('n1', 'beach day.jpg')}\n\n[attachment: legacy.m4a]\n"
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\norigin_device: desktop\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), lambda t: None)

    assert (enriched, failed) == (1, 0)
    from note_model import parse_note
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    assert parse_note(written).attachments == ["beach day.jpg", "legacy.m4a"]


def test_enrich_attachments_recompute_keeps_body_byte_identical(tmp_path):
    body = f"Trip notes.\n\n{_ref('n1', 'photo.jpg')}\n"
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\norigin_device: desktop\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)
    before = (tmp_path / "n1.md").read_text(encoding="utf-8")

    enrich_notes(vault_notes, str(tmp_path), lambda t: None)

    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    from machine_tags import strip_trailing_tags_line
    # BODY SACRED: the user body is byte-identical; only frontmatter moved.
    assert strip_trailing_tags_line(strip_frontmatter(written)) == body
    assert written != before                  # sanity: the pass really did rewrite the note


def test_enrich_no_refs_serializes_empty_attachments_list(tmp_path):
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\norigin_device: desktop\nenriched: false",
               "Nothing attached.\n")
    vault_notes = _vault_notes_from(tmp_path)

    enrich_notes(vault_notes, str(tmp_path), lambda t: None)

    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    assert "attachments: []" in written        # empty list, not a dropped key


# ---------------------------------------------------------------------------
# s114 / flow-review x04 — a conflicted copy has to be recognisable on disk
# ---------------------------------------------------------------------------

def test_conflicted_copy_is_named_from_its_title(tmp_path):
    """The lock ("body-vs-body -> conflicted copy, both intact") held in the
    field: both bodies survived. But the copy was written as `<random-id>.md`,
    so an operator auditing the vault saw an unreadable hex blob beside the note
    and filed a P0 data-loss report against behaviour that was correct. The name
    is now derived from the title reconcile.py already built."""
    from mobile_sync_agent import _conflicted_copy_name

    class _CC:
        id = "3887fbfb641b4ce786855cffb6"
        title = "CrossDeviceTest x01 (conflicted copy phone-gkkn48 2026-07-30T12:08:23.596Z)"
        created = "2026-07-30T11:53:22.746Z"

    name = _conflicted_copy_name(_CC(), tmp_path)
    assert name.startswith("CrossDeviceTest x01 (conflicted copy phone-gkkn48")
    assert name.endswith(".md")
    assert ":" not in name, "must survive the Windows illegal-character sanitizer"
    assert _CC.id not in name


def test_conflicted_copy_never_collides_with_an_existing_file(tmp_path):
    """Two conflicted copies of one note in one folder: fall back to the short
    id rather than overwrite a body -- the same idiom _resolve_hub_names uses."""
    from mobile_sync_agent import _conflicted_copy_name

    class _CC:
        id = "3887fbfb641b4ce786855cffb6"
        title = "Note (conflicted copy phone-a 2026-07-30T12:08:23.596Z)"
        created = "2026-07-30T11:53:22.746Z"

    first = _conflicted_copy_name(_CC(), tmp_path)
    (tmp_path / first).write_text("already here", encoding="utf-8")
    second = _conflicted_copy_name(_CC(), tmp_path)
    assert second != first
    assert _CC.id[-6:] in second


def test_conflicted_copy_name_falls_back_when_the_title_is_empty(tmp_path):
    """A title-less copy must still get a usable filename, never ".md"."""
    from mobile_sync_agent import _conflicted_copy_name

    class _CC:
        id = "abc123def456"
        title = ""
        created = "2026-07-30T11:53:22.746Z"

    name = _conflicted_copy_name(_CC(), tmp_path)
    assert name.endswith(".md")
    assert len(name) > 3


# ---------------------------------------------------------------------------
# Contract SS13.2 - `.projects.toml` three-way merge + `base_projects` sync state
# ---------------------------------------------------------------------------

from mobile_sync_agent import (
    BASE_PROJECTS_KEY,
    PROJECTS_REV_KEY,
    sync_project_registry,
)
import project_registry as _pr


class _RegistryHub:
    """Minimal fake Drive holding exactly one hub root file: `.projects.toml`.

    Tracks calls so a test can assert the version token actually SKIPS work: `downloads` counts
    `get_media`, `writes` counts content uploads.
    """

    def __init__(self, text=None, rev="r1"):
        self.text = text
        self.rev = rev
        self.downloads = 0
        self.writes = 0
        self._n = 1

    # -- drive shim ---------------------------------------------------------
    def files(self):
        return self

    def list(self, q=None, fields=None, pageToken=None):
        files = []
        if self.text is not None and "mimeType!=" in (q or ""):
            files = [{"id": "REGFILE", "name": _pr.REGISTRY_FILENAME,
                      "headRevisionId": self.rev}]
        return _Ret({"files": files, "nextPageToken": None})

    def get_media(self, fileId=None):
        self.downloads += 1
        return _Ret(self.text.encode("utf-8"))

    def create(self, body=None, media_body=None, fields=None):
        self.writes += 1
        self.text = media_body.getbytes(0, media_body.size()).decode("utf-8")
        self._n += 1
        self.rev = f"r{self._n}"
        return _Ret({"id": "REGFILE", "headRevisionId": self.rev})

    def update(self, fileId=None, media_body=None, fields=None, **kw):
        self.writes += 1
        self.text = media_body.getbytes(0, media_body.size()).decode("utf-8")
        self._n += 1
        self.rev = f"r{self._n}"
        return _Ret({"id": "REGFILE", "headRevisionId": self.rev})


class _Ret:
    def __init__(self, r): self._r = r
    def execute(self): return self._r


def _toml(**projects) -> str:
    return _pr.dumps({"schema": 1, "projects": {
        n: {"description": d, "modified": m} for n, (d, m) in projects.items()}})


def test_registry_sync_merges_per_entry_never_last_writer_wins(tmp_path):
    """SS13.2's headline: two devices adding DIFFERENT projects in one batch window write the same
    file. A whole-file rule silently discards one of them; the per-entry merge keeps both."""
    base = {"schema": 1, "projects": {"shared": {"description": "s", "modified": "2026-01-01"}}}
    _pr.save(tmp_path, {"schema": 1, "projects": {
        "shared": {"description": "s", "modified": "2026-01-01"},
        "local-only": {"description": "L", "modified": "2026-01-02"}}})
    hub = _RegistryHub(_toml(shared=("s", "2026-01-01"), remote_only=("R", "2026-01-03")))

    merged, new_state = sync_project_registry(
        hub, "HUB", str(tmp_path), {BASE_PROJECTS_KEY: base, PROJECTS_REV_KEY: "r0"})

    assert sorted(merged["projects"]) == ["local-only", "remote_only", "shared"]
    # ...written back to BOTH sides, so neither peer loses its own addition.
    assert sorted(_pr.load(tmp_path)["projects"]) == ["local-only", "remote_only", "shared"]
    assert sorted(_pr.parse(hub.text)["projects"]) == ["local-only", "remote_only", "shared"]
    # ...and the merged result becomes the next pass's base.
    assert new_state[BASE_PROJECTS_KEY] == merged


def test_registry_sync_version_token_is_headrevisionid_never_mtime(tmp_path):
    """SS13: the hub head still equal to `projects_rev` means the remote IS `base_projects` --
    so the pass costs ZERO downloads and ZERO writes, no matter what the file's mtime says."""
    reg = {"schema": 1, "projects": {"a": {"description": "A", "modified": "2026-01-01"}}}
    _pr.save(tmp_path, reg)
    hub = _RegistryHub(_toml(a=("A", "2026-01-01")), rev="rHEAD")
    # touch the local file far into the future: an mtime-based rule would see a local "edit"
    import os
    os.utime(tmp_path / _pr.REGISTRY_FILENAME, (4_102_444_800, 4_102_444_800))

    merged, new_state = sync_project_registry(
        hub, "HUB", str(tmp_path),
        {BASE_PROJECTS_KEY: reg, PROJECTS_REV_KEY: "rHEAD"})

    assert (hub.downloads, hub.writes) == (0, 0)      # nothing moved in either direction
    assert new_state[PROJECTS_REV_KEY] == "rHEAD"
    assert merged == reg


def test_registry_sync_advanced_head_is_downloaded_and_merged(tmp_path):
    reg = {"schema": 1, "projects": {"a": {"description": "A", "modified": "2026-01-01"}}}
    _pr.save(tmp_path, reg)
    hub = _RegistryHub(_toml(a=("A2", "2026-02-01")), rev="rNEW")

    merged, new_state = sync_project_registry(
        hub, "HUB", str(tmp_path),
        {BASE_PROJECTS_KEY: reg, PROJECTS_REV_KEY: "rOLD"})

    assert hub.downloads == 1                                    # head moved -> fetched
    assert merged["projects"]["a"]["description"] == "A2"        # newer `modified` wins (row 5)
    assert _pr.load(tmp_path)["projects"]["a"]["description"] == "A2"
    assert new_state[PROJECTS_REV_KEY] == "rNEW"                 # remote already matched -> no write
    assert hub.writes == 0


def test_registry_sync_first_run_creates_the_hub_file_without_reading_base_as_deletes(tmp_path):
    """A hub with no registry yet has never synced anything, so a recorded base must NOT be read
    as 'every project was deleted remotely' -- that would wipe the local file on first run."""
    _pr.save(tmp_path, {"schema": 1, "projects": {"a": {"description": "A"}}})
    hub = _RegistryHub(None)
    stale_base = {"schema": 1, "projects": {"a": {"description": "A"},
                                            "b": {"description": "B"}}}

    merged, new_state = sync_project_registry(
        hub, "HUB", str(tmp_path), {BASE_PROJECTS_KEY: stale_base, PROJECTS_REV_KEY: "rX"})

    assert sorted(merged["projects"]) == ["a"]         # local kept, nothing silently deleted
    assert hub.writes == 1                              # created on the hub
    assert sorted(_pr.parse(hub.text)["projects"]) == ["a"]
    assert _pr.load(tmp_path)["projects"]["a"]["description"] == "A"


def test_registry_sync_holds_one_lock_across_the_whole_load_merge_save(tmp_path, monkeypatch):
    """SS13.2: 'the lock must be held across the ENTIRE load -> merge -> save cycle -- acquired
    before the read, released after the write. A lock around the save alone does not close the
    race.' Records the real ordering rather than trusting the comment."""
    import contextlib
    import mobile_sync_agent as agent

    events = []
    lock_paths = []
    real_load, real_save = _pr.load, _pr.save

    @contextlib.contextmanager
    def spy_lock(lock_path, timeout=10.0):
        lock_paths.append(Path(lock_path).name)
        events.append("acquire")
        try:
            yield
        finally:
            events.append("release")

    monkeypatch.setattr(agent, "_vault_lock", spy_lock)
    monkeypatch.setattr(_pr, "load", lambda vr: events.append("load") or real_load(vr))
    monkeypatch.setattr(_pr, "save", lambda vr, r: events.append("save") or real_save(vr, r))

    hub = _RegistryHub(_toml(remote_only=("R", "2026-01-03")))
    sync_project_registry(hub, "HUB", str(tmp_path), {})

    assert events == ["acquire", "load", "save", "release"]
    assert lock_paths == [".projects.lock"]             # its own path, not an unrelated cycle's


def test_base_projects_is_never_mistaken_for_a_note_row(tmp_path, monkeypatch):
    """`base_projects` is a dict living beside per-note dicts in the same sidecar. Every state
    iteration guards on `drive_file_id`, which it lacks -- and it must survive a save/load."""
    _write_registry(tmp_path, "research")
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: true", "Body.\n")
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")
    drive = _mock_empty_drive()
    state_path = tmp_path / ".state.json"

    run_once(str(tmp_path), str(state_path), drive, vault_root=str(tmp_path))

    final = load_state(str(state_path))                 # round-trips through JSON
    assert "research" in final[BASE_PROJECTS_KEY]["projects"]
    assert "drive_file_id" not in final[BASE_PROJECTS_KEY]
    assert final["n1"]["drive_file_id"] == "F1"         # the real note row is untouched beside it


# ---------------------------------------------------------------------------
# SYNC IS PURE TRANSPORT (SS1.3, user priority s125) - stronger than body-sacred:
# the pass moves bytes and writes bookkeeping, and NEVER edits file content in
# EITHER direction. Frontmatter writes are legal only from a local save/enrich.
# ---------------------------------------------------------------------------

def test_a_sync_pass_leaves_a_synced_notes_bytes_untouched(tmp_path, monkeypatch):
    """A full run_once over an already-synced note must not rewrite one byte of it -- not the
    body, and not the derived `project:`/`tags:` frontmatter caches either."""
    _write_registry(tmp_path, "research")
    loose = tmp_path / LOOSE_DIR
    loose.mkdir()
    # Deliberately INCONSISTENT caches: the body says `#project@research`, the frontmatter says
    # `[stale]` and carries a `tags:` entry the body does not. A local save would rebuild both.
    # A sync pass must leave every byte alone -- recomputing here would be an edit.
    content = ("---\nid: n1\ntitle: T\norigin: note\nproject: [stale]\ntags: [ghost]\n"
               "enriched: true\nenrich_source: desktop-llm\norigin_device: desktop\n"
               "---\nreal body #project@research\n")
    p = loose / "T.md"
    p.write_text(content, encoding="utf-8", newline="")
    save_state(str(tmp_path / ".state.json"),
               {"hub_names_migrated": True,
                "n1": {"drive_file_id": "F1", "base_rev": "r1",
                       "local_hash": _sha256(content), "hub_name": "T.md",
                       "base_parent": "research"}})
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")

    before = p.read_bytes()
    run_once(str(tmp_path), str(tmp_path / ".state.json"), _mock_empty_drive(),
             vault_root=str(tmp_path))

    assert p.read_bytes() == before, "a sync pass rewrote a note it was only supposed to transport"


def _reconcile_pull_drive(monkeypatch, remote_text, folder="research", fid="F1"):
    """Fake drive whose hub holds ONE note, in `folder`, at an ADVANCED head — so run_once takes
    reconcile_changes' PULL branch (remote moved, local unchanged) rather than pull_new/mirror."""
    drive = MagicMock()

    def _list(**kw):
        q = kw.get("q", "")
        resp = MagicMock()
        if "'HUB' in parents" in q and f"mimeType='{_FOLDER_MIME}'" in q:
            resp.execute.return_value = {"files": [
                {"id": "c1", "name": folder, "mimeType": _FOLDER_MIME}], "nextPageToken": None}
        elif "'c1' in parents" in q:
            resp.execute.return_value = {"files": [
                {"id": fid, "name": "T.md", "headRevisionId": "rNEW",
                 "appProperties": {"noteId": "n1"}}], "nextPageToken": None}
        else:
            resp.execute.return_value = {"files": [], "nextPageToken": None}
        return resp

    drive.files().list.side_effect = _list
    drive.files().get_media.side_effect = lambda fileId=None: _Ret2(remote_text.encode("utf-8"))
    monkeypatch.setattr("mobile_sync_agent.ensure_hub_folder", lambda d, name=HUB_FOLDER_NAME: "HUB")
    return drive


class _Ret2:
    def __init__(self, r): self._r = r
    def execute(self): return self._r


def test_run_once_pull_branch_writes_the_hub_bytes_verbatim(tmp_path, monkeypatch):
    """The downward direction through the REAL run_once -> reconcile_changes PULL branch.

    The arriving bytes carry a `project:` cache that disagrees with their own body tag AND a
    `tags:` entry the body does not contain. Sync must write them EXACTLY as delivered: repairing
    a peer's derived caches here would be an edit, and edits are the one thing transport may not do.
    """
    _write_registry(tmp_path, "research")
    loose = tmp_path / LOOSE_DIR
    loose.mkdir()
    local = ("---\nid: n1\ntitle: T\norigin: note\norigin_device: phone\nenriched: true\n"
             "---\nold body\n")
    p = loose / "T.md"
    p.write_text(local, encoding="utf-8", newline="")
    remote = ("---\nid: n1\ntitle: T\norigin: note\norigin_device: phone\nenriched: true\n"
              "project: [wrong]\ntags: [ghost]\n---\nnew body #project@research\n")
    state_path = tmp_path / ".state.json"
    save_state(str(state_path), {"hub_names_migrated": True,
                                 "n1": {"drive_file_id": "F1", "base_rev": "rOLD",
                                        "local_hash": _sha256(local), "hub_name": "T.md",
                                        "base_parent": "research"}})

    drive = _reconcile_pull_drive(monkeypatch, remote)
    _u, _f, reconciled, _c, _p2, _i, _e = run_once(
        str(tmp_path), str(state_path), drive, vault_root=str(tmp_path))

    assert reconciled == 1                       # the PULL branch really ran (not a vacuous pass)
    # re-pathed by the incoming TAG (moving a file is not editing one)...
    dest = tmp_path / "research" / "T.md"
    assert dest.exists() and not p.exists()
    # ...and the bytes are the hub's, verbatim, stale caches and all.
    assert dest.read_bytes() == remote.encode("utf-8")


def test_a_pull_writes_the_hub_bytes_verbatim_even_when_the_caches_disagree(tmp_path):
    """The downward direction. A peer's note whose `project:` cache disagrees with its body tag
    is written to disk EXACTLY as it arrived -- sync does not 'repair' the other device's file."""
    hub_bytes = ("---\nid: 01P\ntitle: T\norigin: note\nproject: [wrong]\ntags: [ghost]\n"
                 "---\nphone body #project@research\n")
    written = {}
    pulled, failed, _ = pull_new_hub_notes(
        {}, {"01P": {"id": "F1", "headRevisionId": "r1", "folder": "personal", "name": "T.md"}},
        {}, MagicMock(), str(tmp_path),
        download=lambda fid: hub_bytes,
        write_file=lambda pth, c: written.__setitem__(pth, c),
        reg=_reg("research"),
    )
    assert (pulled, failed) == (1, 0)
    # placed by the TAG (research/), and byte-identical -- the stale `project: [wrong]` line rides
    # along untouched, to be rebuilt by whichever device next SAVES the note.
    assert written == {str(tmp_path / "research" / "T.md"): hub_bytes}


def test_an_upload_ships_the_disk_bytes_verbatim(tmp_path):
    """The upward direction: mirror_to_hub uploads `content` as read off disk. `_upload_note`'s
    body-sacred guard covers the body; this pins the WHOLE file, frontmatter included."""
    content = ("---\nid: 01U\ntitle: T\norigin: note\nproject: [stale]\n"
               "---\nbody #project@research\n")
    vault_notes = {"01U": {"id": "01U", "path": str(tmp_path / "research" / "T.md"),
                           "content": content, "body": "body #project@research\n",
                           "hash": "H", "folder": "research", "title": "T", "created": ""}}
    drive = MagicMock()
    drive.files().list().execute.return_value = {"files": [], "nextPageToken": None}
    drive.files().create().execute.return_value = {"id": "F1", "headRevisionId": "r1"}

    uploaded, failed, _ = mirror_to_hub(vault_notes, {}, {}, drive, "HUB")

    assert (uploaded, failed) == (1, 0)
    note_create = next(c for c in drive.files().create.call_args_list
                       if (c.kwargs.get("body") or {}).get("appProperties"))
    media = note_create.kwargs["media_body"]
    assert media.getbytes(0, media.size()) == content.encode("utf-8")

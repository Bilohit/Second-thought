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
    _FOLDER_MIME,
)
from frontmatter import read_all_fields, strip_frontmatter

FM = "---\nid: {id}\ntitle: {title}\norigin: note\n---\n{body}"


def _write(dirpath: Path, fname: str, note_id: str, body: str) -> Path:
    p = dirpath / fname
    p.write_text(FM.format(id=note_id, title="T", body=body), encoding="utf-8", newline="")
    return p


def test_read_vault_notes_keys_by_frontmatter_id(tmp_path):
    _write(tmp_path, "anything.md", "01ABC", "Body here")
    notes = read_vault_notes(str(tmp_path))
    assert "01ABC" in notes           # keyed by id, NOT filename stem
    assert "anything" not in notes
    assert notes["01ABC"]["body"] == "Body here"


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

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify, vocab={})
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
        "drive_file_id": "F1", "base_rev": "rev1", "local_hash": "hashA"
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


def _vault_note(content, path="/vault/x.md", nid="01ABC", h="NEW"):
    return {nid: {"id": nid, "path": path, "content": content,
                  "body": content.split("---\n", 2)[-1], "hash": h}}


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
    assert written["/vault/x.md"] == remote_text           # verbatim pull
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
    merged = written["/vault/x.md"]
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
    assert "local body" in written["/vault/x.md"]                     # local kept in place
    cc = written[next(k for k in written if "CONFLICT1" in k)]        # copy beside it, fresh id
    assert "remote body" in cc                                        # remote body preserved
    assert "id: CONFLICT1" in cc
    assert "conflicted copy desktop" in cc
    assert "CONFLICT1" in new_state                                   # copy tracked in state


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
        "drive_file_id": "HUBF1", "base_rev": "rev9", "local_hash": "H1"
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
    assert "local body" in written["/vault/x.md"]                  # local kept in place
    cc = written[next(k for k in written if "CONFLICT1" in k)]
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


def test_get_hub_notes_walks_category_folders_and_normalizes_keys():
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
    assert notes["01ABC"]["category"] == "personal"
    assert notes["01ABC"]["headRevisionId"] == "r1"


def test_get_hub_notes_scans_root_level_uncategorised_notes():
    # B-5: an uncategorised note lives at the hub ROOT (category=None). It must be scanned + reconciled,
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
    assert set(notes) == {"01CAT", "01ROOT"}       # both the category note AND the root note
    assert notes["01CAT"]["category"] == "personal"
    assert notes["01ROOT"]["category"] is None      # uncategorised


def test_read_vault_notes_category_from_frontmatter_then_folder(tmp_path):
    # note in a category subfolder, no category field → folder name is the category
    workd = tmp_path / "work"
    workd.mkdir()
    (workd / "a.md").write_text("---\nid: 01A\ntitle: T\norigin: note\n---\nB", encoding="utf-8", newline="")
    # note with explicit category frontmatter → field wins
    (tmp_path / "b.md").write_text(
        "---\nid: 01B\ntitle: T\norigin: note\ncategory: ideas\n---\nB", encoding="utf-8", newline="")
    notes = read_vault_notes(str(tmp_path))
    assert notes["01A"]["category"] == "work"
    assert notes["01B"]["category"] == "ideas"


def test_mirror_places_new_note_in_category_folder():
    vault_notes = {
        "01A": {"id": "01A", "path": "/v/work/a.md", "content": "---\nid: 01A\n---\nB",
                "body": "B", "hash": "h", "category": "work"}
    }
    drive = MagicMock()
    drive.files().list().execute.return_value = {"files": []}            # category folder absent
    drive.files().create().execute.return_value = {"id": "F1", "headRevisionId": "r1"}
    uploaded, failed, new_state = mirror_to_hub(vault_notes, {}, {}, drive, "HUB")
    assert (uploaded, failed) == (1, 0)
    # the note-create body must carry parents = [the work-folder id], not [HUB]
    create_calls = [c for c in drive.files().create.call_args_list if c.kwargs.get("body", {}).get("name") == "01A.md"]
    assert create_calls, "note was not created with name 01A.md"
    assert create_calls[0].kwargs["body"]["parents"] != ["HUB"]          # placed in a category folder


from mobile_sync_agent import pull_new_hub_notes


def _hub_note_text(nid, category=None, body="phone body"):
    cat = f"category: {category}\n" if category else ""
    return f"---\nid: {nid}\ntitle: T\norigin: note\n{cat}---\n{body}"


def test_pull_places_new_note_in_category_folder():
    hub_files = {"01NEW": {"id": "F1", "headRevisionId": "r1", "category": "personal"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = _hub_note_text("01NEW", "work").encode("utf-8")
    written = {}
    pulled, failed, new_state = pull_new_hub_notes(
        {}, hub_files, {}, drive, "/vault", "_scratchpad",
        write_file=lambda p, c: written.__setitem__(p, c),
    )
    assert (pulled, failed) == (1, 0)
    # placement uses the FRONTMATTER category ("work"), filename = <id>.md
    assert written == {str(Path("/vault/work/01NEW.md")): _hub_note_text("01NEW", "work")}
    assert new_state["01NEW"] == {
        "drive_file_id": "F1", "base_rev": "r1",
        "local_hash": _sha256(_hub_note_text("01NEW", "work")),
    }


def test_pull_falls_back_to_scratchpad_without_category():
    hub_files = {"01NC": {"id": "F2", "headRevisionId": "r2", "category": "personal"}}
    drive = MagicMock()
    drive.files().get_media().execute.return_value = _hub_note_text("01NC").encode("utf-8")
    written = {}
    pulled, failed, _ = pull_new_hub_notes(
        {}, hub_files, {}, drive, "/vault", "_scratchpad",
        write_file=lambda p, c: written.__setitem__(p, c),
    )
    assert (pulled, failed) == (1, 0)
    assert str(Path("/vault/_scratchpad/01NC.md")) in written


def test_pull_skips_notes_already_local_or_tracked():
    hub_files = {"01A": {"id": "F1", "headRevisionId": "r1", "category": "personal"}}
    drive = MagicMock()
    # already in the vault
    p1, _, _ = pull_new_hub_notes({"01A": {}}, hub_files, {}, drive, "/vault", "_scratchpad",
                                  write_file=lambda p, c: None)
    # already tracked in state
    p2, _, _ = pull_new_hub_notes({}, hub_files, {"01A": {}}, drive, "/vault", "_scratchpad",
                                  write_file=lambda p, c: None)
    assert p1 == 0 and p2 == 0


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
        vault_root=str(vault), scratchpad_folder="_scratchpad",
        run_pipeline=lambda **kw: pipeline_calls.append(kw) or {},
    )
    assert pulled == 1                                   # hub-only note pulled
    assert (vault / "personal" / "01NEW.md").exists()    # placed by category
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
        vault_root=str(vault), scratchpad_folder="_scratchpad",
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
        vault_root=str(vault), scratchpad_folder="_scratchpad",
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

    def spy(vault_path, mirror_captures=False):
        seen.append(mirror_captures)
        return real_read(vault_path, mirror_captures)

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
             vault_root=str(vault), scratchpad_folder="_scratchpad",
             provisional_fn=provisional_fn)

    # Canonical mirror is byte-identical to the Drive-delivered note — body sacred.
    canonical = (vault / "personal" / "noteA.md").read_text(encoding="utf-8")
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
        return (["ml", "keep"], "research")

    embedded = []
    def embed(path, content):
        embedded.append((path, content))

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify,
                                    vocab={}, embed=embed)

    assert (enriched, failed) == (1, 0)
    from note_model import parse_note
    from frontmatter import strip_frontmatter
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    note = parse_note(written)
    assert note.enriched is True
    assert note.enrich_source == "desktop-llm"
    assert note.category == "research"
    assert set(note.tags) == {"keep", "ml"}          # existing 'keep' unioned with key_signals
    assert strip_frontmatter(written) == body        # BODY SACRED — byte-identical
    assert captured["text"] == body                  # classify saw the body, not frontmatter
    assert embedded == [(str(tmp_path / "n1.md"), written)]
    assert vault_notes["n1"]["content"] == written   # in-memory dict updated for same-pass mirror
    assert vault_notes["n1"]["hash"] == _sha256(written)


def test_enrich_notes_skips_already_enriched(tmp_path):
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\nenriched: true\nenrich_source: desktop-llm", "Body.\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("must not classify an already-enriched note")

    assert enrich_notes(vault_notes, str(tmp_path), classify, vocab={}) == (0, 0)


def test_enrich_notes_skips_captures(tmp_path):
    _note_file(tmp_path, "c1.md",
               "id: c1\norigin: capture\nenriched: false", "Clip body.\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("must not classify a capture")

    assert enrich_notes(vault_notes, str(tmp_path), classify, vocab={}) == (0, 0)


def test_enrich_notes_failsoft_on_classify_error(tmp_path):
    body = "Body stays.\n"
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)
    before = (tmp_path / "n1.md").read_text(encoding="utf-8")

    def classify(text):
        raise RuntimeError("ollama down")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify, vocab={})
    assert (enriched, failed) == (0, 1)
    assert (tmp_path / "n1.md").read_text(encoding="utf-8") == before   # untouched, retried next pass


def test_enrich_notes_empty_body_skips_llm_and_marks_enriched(tmp_path):
    # A note with an empty body is the recurring poison: classify has nothing to work with and the
    # model times out synthesizing every schema field from nothing. Guard: mark it enriched WITHOUT
    # an LLM call so it stops re-hitting Ollama every pass. Body stays byte-identical (empty).
    _note_file(tmp_path, "n1.md",
               "id: n1\norigin: note\nenriched: false\nenrich_source: phone-heuristic\ncategory: _scratchpad", "")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("must not classify an empty-body note")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify, vocab={})
    assert (enriched, failed) == (1, 0)          # counted done, NOT failed — no timeout, no retry
    from note_model import parse_note
    from frontmatter import strip_frontmatter
    written = (tmp_path / "n1.md").read_text(encoding="utf-8")
    note = parse_note(written)
    assert note.enriched is True                 # marked done → not retried next pass
    assert note.enrich_source == "phone-heuristic"  # left as-is (no desktop-LLM pass actually ran)
    assert note.category == "_scratchpad"        # category left as-is (nothing to classify)
    assert strip_frontmatter(written) == ""      # BODY SACRED — still empty, byte-identical


def test_enrich_notes_whitespace_only_body_treated_as_empty(tmp_path):
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", "   \n\n")
    vault_notes = _vault_notes_from(tmp_path)

    def classify(text):
        raise AssertionError("whitespace-only body must not be classified")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify, vocab={})
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
        return ([], "personal")
    def embed(path, content):
        raise RuntimeError("embed server down")

    enriched, failed = enrich_notes(vault_notes, str(tmp_path), classify, vocab={}, embed=embed)
    from note_model import parse_note
    assert parse_note((tmp_path / "n1.md").read_text(encoding="utf-8")).enriched is True
    assert enriched == 1        # embed failure is not an enrichment failure


def test_build_enrich_fn_uses_live_categories_and_embeds(tmp_path, monkeypatch):
    import mobile_sync_agent as agent
    from mobile_sync_agent import _build_enrich_fn

    body = "Note body.\n"
    _note_file(tmp_path, "n1.md", "id: n1\norigin: note\nenriched: false", body)
    vault_notes = _vault_notes_from(tmp_path)

    class _Ollama:  base_url = "http://localhost:11434"
    class _Vector:  embed_model = "nomic-embed-text"
    class _Vault:   root = tmp_path
    class _Cfg:     ollama = _Ollama(); vector = _Vector(); vault = _Vault()

    seen = {}
    def fake_run_llm_engine(enriched, category_descriptions, **kw):
        seen["input_type"] = enriched.input_type
        seen["cats"] = list(category_descriptions.keys())
        class _Out:  key_signals = ["ml"]; category = "research"
        return _Out()
    def fake_categories(vault_root, scratchpad_folder="_scratchpad"):
        return {"research": "d", "personal": "d"}
    embeds = []
    def fake_index_note(root, path, content, base_url, embed_model):
        embeds.append((str(path), base_url, embed_model))

    monkeypatch.setattr(agent, "run_llm_engine", fake_run_llm_engine, raising=False)
    monkeypatch.setattr(agent, "build_category_descriptions", fake_categories, raising=False)
    monkeypatch.setattr(agent, "index_note", fake_index_note, raising=False)
    monkeypatch.setattr(agent, "load_vocab", lambda db: {}, raising=False)
    monkeypatch.setattr(agent, "get_db_path", lambda root: tmp_path / "captures.db", raising=False)

    enrich_fn = _build_enrich_fn(_Cfg(), str(tmp_path))
    enriched, failed = enrich_fn(vault_notes, str(tmp_path))

    assert (enriched, failed) == (1, 0)
    assert seen["input_type"] == "note"
    assert set(seen["cats"]) == {"research", "personal"}          # live enum, not hardcoded
    assert embeds == [(str(tmp_path / "n1.md"), "http://localhost:11434", "nomic-embed-text")]


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
        n.enriched = True; n.enrich_source = "desktop-llm"; n.category = "research"
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


def test_build_reminders_fn_reconciles_db(tmp_path):
    from mobile_sync_agent import _build_reminders_fn
    from reminders import list_reminders
    from index_writer import get_db_path

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
        sync=types.SimpleNamespace(mirror_captures=False),
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

"""Tests for delete_detect.py — the desktop delete detection (ISS-005 B/C).

Covers the pure classifiers (scoping) and process_deletes' NON-DESTRUCTIVE defaults + the two-pass
confirm before an irreversible out-of-band FS delete, all without a real Drive client.
"""
from pathlib import Path

from delete_detect import (
    classify_fs_deleted,
    classify_inbound_deletes,
    classify_outbound_soft_deletes,
    hub_trashed_ids,
    load_delete_prompts,
    local_trashed_files,
    local_trashed_ids,
    process_deletes,
)


def _state():
    return {
        "live": {"drive_file_id": "F1", "base_rev": "r1"},
        "gone": {"drive_file_id": "F3", "base_rev": "r3"},
        "inbound": {"drive_file_id": "F4", "base_rev": "r4"},
        "unsynced": {"drive_file_id": None},
        "hub_names_migrated": True,  # the flat flag lives in state too — must be ignored
    }


# --- pure classifiers ---------------------------------------------------------

def test_classify_fs_deleted_scopes_to_once_synced_absent_from_vault_and_trash():
    st = _state()
    # "gone" is absent from vault + not in local _trash/ → the ONLY permanent-delete candidate.
    fs = classify_fs_deleted(st, vault_ids={"live", "inbound"}, local_trashed_ids=set())
    assert fs == {"gone"}


def test_soft_deleted_in_local_trash_is_never_a_permanent_delete():
    st = _state()
    fs = classify_fs_deleted(st, vault_ids={"live", "inbound"}, local_trashed_ids={"gone"})
    assert fs == set()  # sitting in local _trash/ → soft delete, never permanent


def test_never_synced_note_is_never_a_delete_signal():
    st = {"unsynced": {"drive_file_id": None}}
    assert classify_fs_deleted(st, vault_ids=set(), local_trashed_ids=set()) == set()


def test_classify_inbound_trash_vs_remove():
    st = _state()
    trash = classify_inbound_deletes(st, {"live", "inbound"}, hub_ids={"live"}, hub_trashed_ids={"inbound"})
    assert trash == {"inbound": "trash"}
    remove = classify_inbound_deletes(st, {"live", "inbound"}, hub_ids={"live"}, hub_trashed_ids=set())
    assert remove == {"inbound": "remove"}


def test_inbound_requires_the_note_present_locally():
    # "gone" is absent locally → it is fs-delete's job, never an inbound prompt.
    st = _state()
    assert "gone" not in classify_inbound_deletes(st, {"live", "inbound"}, hub_ids={"live"}, hub_trashed_ids=set())


def test_classify_outbound_soft_delete_scopes_to_live_hub_copy():
    # "soft" is in local _trash/ and its hub copy is still live in a category folder → propagate.
    st = _state()
    st["soft"] = {"drive_file_id": "F2", "base_rev": "r2"}
    out = classify_outbound_soft_deletes(st, local_trashed={"soft"}, hub_ids={"live", "soft"})
    assert out == {"soft"}
    # Hub copy already gone from categories (peer trashed/removed it) → idempotent no-op.
    assert classify_outbound_soft_deletes(st, local_trashed={"soft"}, hub_ids={"live"}) == set()
    # Never-synced note in local _trash/ → nothing on the hub to move.
    assert classify_outbound_soft_deletes(st, local_trashed={"unsynced"}, hub_ids={"unsynced"}) == set()


# --- scans --------------------------------------------------------------------

def test_local_trashed_ids_reads_frontmatter(tmp_path):
    trash = tmp_path / "_trash"
    trash.mkdir()
    (trash / "a.md").write_text("---\nid: 01A\ntitle: A\n---\nbody\n", encoding="utf-8")
    (trash / "b.md").write_text("---\ntitle: no id here\n---\nbody\n", encoding="utf-8")
    assert local_trashed_ids(str(tmp_path)) == {"01A"}


def test_hub_trashed_ids_keys_by_noteid_then_stem():
    children = [
        {"name": "Foo.md", "appProperties": {"noteId": "01X"}},
        {"name": "01Y.md"},
        {"name": "picture.png"},  # non-.md ignored
    ]
    assert hub_trashed_ids(lambda _fid: children, "trash-folder") == {"01X", "01Y"}


# --- process_deletes: non-destructive defaults + two-pass confirm -------------

def _run(tmp_path, state, vault_notes, hub_files, hub_trash_children, deleted, trash_id="TRASH"):
    """Drive one process_deletes pass. `deleted` collects file ids the hub delete was asked to remove."""
    return process_deletes(
        str(tmp_path),
        str(tmp_path / ".omni_capture" / "mobile_sync_state.json"),
        state,
        vault_notes,
        hub_files,
        trash_id,
        "2026-07-22T00:00:00Z",
        list_children=lambda _fid: hub_trash_children,
        delete_file=lambda fid: deleted.append(fid),
    )


def test_inbound_delete_records_a_prompt_and_deletes_nothing(tmp_path):
    (tmp_path / ".omni_capture").mkdir()
    state = {"inbound": {"drive_file_id": "F4", "base_rev": "r4"}}
    deleted = []
    # note present locally, hub file absent from categories but sitting in hub _trash/ → soft delete.
    new_state, fs_del, prompts = _run(
        tmp_path, state,
        vault_notes={"inbound": {"id": "inbound"}},
        hub_files={},
        hub_trash_children=[{"name": "inbound.md", "appProperties": {"noteId": "inbound"}}],
        deleted=deleted,
    )
    assert fs_del == 0 and deleted == []          # NON-DESTRUCTIVE — nothing deleted
    assert prompts == 1
    assert new_state == state                     # local note kept intact
    held = load_delete_prompts(str(tmp_path / ".omni_capture" / "mobile_sync_state.json"))["prompts"]
    assert held["inbound"]["kind"] == "trash"


def test_keep_here_resolution_suppresses_the_reraise(tmp_path):
    """gap 2: a prompt the user resolved keep_here (recorded in store["keep_here"]) must NOT be
    re-raised on the next pass even though the note is still local + the hub file still absent."""
    (tmp_path / ".omni_capture").mkdir()
    state_path = str(tmp_path / ".omni_capture" / "mobile_sync_state.json")
    # Pre-seed the durable keep-here decision (what the resolve endpoint writes).
    from delete_detect import save_delete_prompts
    save_delete_prompts(state_path, {"prompts": {}, "pending_fs": {}, "keep_here": {"inbound": {"resolved_at": "x"}}})

    state = {"inbound": {"drive_file_id": "F4", "base_rev": "r4"}}
    _new, fs_del, prompts = _run(
        tmp_path, state,
        vault_notes={"inbound": {"id": "inbound"}},
        hub_files={},
        hub_trash_children=[{"name": "inbound.md", "appProperties": {"noteId": "inbound"}}],
        deleted=[],
    )
    assert (fs_del, prompts) == (0, 0)                       # never re-prompted
    held = load_delete_prompts(state_path)
    assert held["prompts"] == {}
    assert "inbound" in held["keep_here"]                    # decision still remembered


def test_out_of_band_fs_delete_needs_two_passes_before_it_removes_the_hub_file(tmp_path):
    (tmp_path / ".omni_capture").mkdir()
    state = {"gone": {"drive_file_id": "F3", "base_rev": "r3"}}
    deleted = []
    # Pass 1: "gone" absent from vault + local _trash/. First sighting → recorded, NOT deleted.
    s1, fs1, _ = _run(tmp_path, state, vault_notes={}, hub_files={}, hub_trash_children=[], deleted=deleted)
    assert fs1 == 0 and deleted == []             # two-pass guard: no irreversible delete yet
    assert "gone" in s1                            # state row still present
    pending = load_delete_prompts(str(tmp_path / ".omni_capture" / "mobile_sync_state.json"))["pending_fs"]
    assert "gone" in pending

    # Pass 2: still absent → confirmed permanent delete propagates to the hub, state row dropped.
    s2, fs2, _ = _run(tmp_path, s1, vault_notes={}, hub_files={}, hub_trash_children=[], deleted=deleted)
    assert fs2 == 1 and deleted == ["F3"]
    assert "gone" not in s2


def test_a_transient_absence_that_reappears_is_never_deleted(tmp_path):
    (tmp_path / ".omni_capture").mkdir()
    state = {"gone": {"drive_file_id": "F3", "base_rev": "r3"}}
    deleted = []
    # Pass 1: absent (e.g. the file was momentarily locked/unreadable) → recorded pending.
    s1, _, _ = _run(tmp_path, state, vault_notes={}, hub_files={}, hub_trash_children=[], deleted=deleted)
    # Pass 2: the note is readable again (back in the vault) → pending cleared, NOTHING deleted.
    s2, fs2, _ = _run(tmp_path, s1, vault_notes={"gone": {"id": "gone"}}, hub_files={"gone": {"id": "gone"}},
                      hub_trash_children=[], deleted=deleted)
    assert fs2 == 0 and deleted == []
    assert "gone" in s2
    pending = load_delete_prompts(str(tmp_path / ".omni_capture" / "mobile_sync_state.json"))["pending_fs"]
    assert "gone" not in pending


_CRLF_NOTE = (
    b"---\nid: soft\ntitle: Soft\ncategory: Personal\norigin: note\n---\n"
    b"# Soft\r\n\r\nSacred body with CRLF and trailing spaces.   \n"
)


def _seed_local_trash(tmp_path, raw=_CRLF_NOTE, name="Soft.md"):
    (tmp_path / ".omni_capture").mkdir(exist_ok=True)
    trash = tmp_path / "_trash"
    trash.mkdir(exist_ok=True)
    (trash / name).write_bytes(raw)
    return trash / name


def _outbound_run(tmp_path, state, hub_files, moved, remote_rev_ok=True):
    """Run process_deletes with the outbound seams wired. `moved` collects (file_id, dest)."""
    return process_deletes(
        str(tmp_path),
        str(tmp_path / ".omni_capture" / "mobile_sync_state.json"),
        state,
        vault_notes={},          # the soft-deleted note left the vault for _trash/
        hub_files=hub_files,
        trash_folder_id="TRASH",
        now_iso="2026-07-22T00:00:00Z",
        list_children=lambda _fid: [],
        delete_file=lambda fid: (_ for _ in ()).throw(AssertionError("permanent delete must NOT run")),
        move_file=lambda fid, dest: moved.append((fid, dest)),
        ensure_hub_trash=lambda: "HUBTRASH",
        vault_root=str(tmp_path),
    )


def test_desktop_soft_delete_propagates_the_hub_file_into_hub_trash(tmp_path):
    """ISS-005 A follow-up gap 1: a note in local _trash/ whose hub copy is live + fresh base_rev →
    the hub file is re-parented into hub _trash/ (soft, recoverable), NOT permanently deleted."""
    trashed = _seed_local_trash(tmp_path)
    state = {"soft": {"drive_file_id": "F2", "base_rev": "r2"}}
    hub_files = {"soft": {"id": "F2", "headRevisionId": "r2", "category": "Personal"}}
    moved = []
    new_state, fs_del, prompts = _outbound_run(tmp_path, state, hub_files, moved)
    assert moved == [("F2", "HUBTRASH")]           # re-parented into hub _trash/ (a MOVE, not delete)
    assert (fs_del, prompts) == (0, 0)
    assert "soft" not in new_state                 # sync row dropped — trashed on both peers now
    # BODY-SACRED: process_deletes never opened/rewrote the local trashed file (CRLF + trailing space).
    assert trashed.read_bytes() == _CRLF_NOTE


def test_stale_base_soft_delete_downgrades_to_conflict_not_a_blind_hub_trash(tmp_path):
    """gap 1 delete-vs-edit (§6 case 1): the hub head advanced past the delete's base_rev → the hub is
    NOT trashed; the note is restored out of local _trash/ so the next reconcile pass owns the merge."""
    trashed = _seed_local_trash(tmp_path)
    state = {"soft": {"drive_file_id": "F2", "base_rev": "r2"}}
    # remote head r9 != base r2 → a peer edited it after the delete was based.
    hub_files = {"soft": {"id": "F2", "headRevisionId": "r9", "category": "Personal"}}
    moved = []
    new_state, fs_del, prompts = _outbound_run(tmp_path, state, hub_files, moved)
    assert moved == []                              # delete NOT executed on the hub
    assert (fs_del, prompts) == (0, 0)
    assert not trashed.exists()                     # restored out of _trash/ …
    restored = tmp_path / "Personal" / "Soft.md"
    assert restored.is_file() and restored.read_bytes() == _CRLF_NOTE  # … body byte-identical
    assert "soft" in new_state                      # sync row kept — reconcile owns it next pass


def test_outbound_soft_delete_is_idempotent_after_the_hub_move(tmp_path):
    """Once the hub copy is in hub _trash/ it leaves get_hub_notes' listing → the next pass sees no
    live hub copy and never re-moves it (no drive calls, no permanent delete)."""
    _seed_local_trash(tmp_path)
    state = {"soft": {"drive_file_id": "F2", "base_rev": "r2"}}
    moved = []
    # hub_files no longer carries "soft" (it now sits in the reserved hub _trash/).
    new_state, fs_del, prompts = _outbound_run(tmp_path, state, hub_files={}, moved=moved)
    assert moved == [] and (fs_del, prompts) == (0, 0)


def test_local_trashed_files_maps_id_to_path(tmp_path):
    p = _seed_local_trash(tmp_path)
    files = local_trashed_files(str(tmp_path))
    assert set(files) == {"soft"} and files["soft"] == p


def test_clean_pass_makes_no_drive_calls_and_no_writes(tmp_path):
    (tmp_path / ".omni_capture").mkdir()
    state = {"live": {"drive_file_id": "F1", "base_rev": "r1"}}
    called = {"listed": 0}

    def _list(_fid):
        called["listed"] += 1
        return []

    new_state, fs_del, prompts = process_deletes(
        str(tmp_path), str(tmp_path / ".omni_capture" / "mobile_sync_state.json"),
        state, vault_notes={"live": {"id": "live"}}, hub_files={"live": {"id": "live"}},
        trash_folder_id="TRASH", now_iso="2026-07-22T00:00:00Z",
        list_children=_list, delete_file=lambda fid: None,
    )
    assert (fs_del, prompts) == (0, 0)
    assert new_state == state
    assert called["listed"] == 0                   # no hub _trash/ listing on a clean pass
    assert not (tmp_path / ".omni_capture" / "delete_prompts.json").exists()  # no write either

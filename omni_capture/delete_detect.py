"""delete_detect.py — desktop delete detection (ISS-005 B/C, data-model §3 lifecycle + §6 reconcile).

The two delete-reconcile decisions the desktop sync pass makes, kept as pure classifiers + a durable
JSON store DELIBERATELY OUTSIDE the tested reconcile/mirror loops (reconcile_changes / mirror_to_hub)
so those correctness-critical functions are untouched. run_once calls process_deletes best-effort.

  1. OUT-OF-BAND FS DELETE = authoritative PERMANENT delete (ISS-005 B, §3 out-of-band clause).
     A note that HAD a sync_state row (was synced) and is now absent from BOTH its synced folder AND
     the local `_trash/` was deleted on the filesystem outside the app → propagate as a real hub
     delete. SCOPING IS LOAD-BEARING: a note still sitting in local `_trash/` is a *soft* delete, not
     a permanent one, and is NEVER fs-deleted; a note that never had a sync_state row is "nothing to
     pull", never a delete. A permanent delete is IRREVERSIBLE, so it is gated by a TWO-PASS CONFIRM
     (the note must be absent on two consecutive passes) — a transient unreadable/locked local file
     (read_vault_notes skips those) can never be mistaken for an intentional delete.

  2. INBOUND DELETE PROMPT (ISS-005 C, §6 case 2). A note the desktop STILL holds locally whose hub
     file a peer soft-deleted (moved to `_trash/`) or removed → a NON-DESTRUCTIVE DELETE-PROMPT: keep
     the local copy, record a durable flag, NEVER silently delete. The default with no user response
     is exactly this hold (the desktop's old behavior was a bare `continue` past the missing hub file
     — non-destructive — which this preserves while adding the flag). Resolution is a later surface.

`state` here is the desktop's mobile_sync_state.json sidecar (the "sync_state row" equivalent):
{note_id: {"drive_file_id", "base_rev", "local_hash", "hub_name"}}. Prompts live in a sibling
`delete_prompts.json`, itself a derived/operational cache (safe to lose — the next pass re-detects).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Tuple

from frontmatter import read_all_fields

_RESERVED_FOLDERS = {"_trash", "_mobile_inbox", "_attachments", "_templates", ".sync"}


# --- pure classifiers ---------------------------------------------------------------------------

def classify_fs_deleted(
    state: Dict[str, Dict],
    vault_ids: Set[str],
    local_trashed_ids: Set[str],
) -> Set[str]:
    """Once-synced notes now absent from BOTH the vault AND local `_trash/` → out-of-band permanent
    delete candidates (ISS-005 B). A note present in the vault, or sitting in local `_trash/` (a soft
    delete), or one that was never synced (no drive_file_id) is NEVER a candidate."""
    out: Set[str] = set()
    for note_id, s in state.items():
        if not isinstance(s, dict) or not s.get("drive_file_id"):
            continue  # never synced (or the flat migration flag) → not a permanent-delete signal
        if note_id in vault_ids or note_id in local_trashed_ids:
            continue
        out.add(note_id)
    return out


def classify_outbound_soft_deletes(
    state: Dict[str, Dict],
    local_trashed: Set[str],
    hub_ids: Set[str],
) -> Set[str]:
    """Notes the DESKTOP soft-deleted locally (now sitting in the vault's local `_trash/`) whose
    once-synced hub copy is STILL LIVE in a hub category folder → the soft-move must propagate to the
    hub `_trash/` so the peer sees the delete (ISS-005 A follow-up, §3 "delete is symmetric").

    Scoping (all load-bearing): a note with no `drive_file_id` was never synced — there is nothing on
    the hub to move. A note NOT in `hub_ids` has no LIVE hub copy: its hub file was already re-parented
    into `_trash/` (get_hub_notes skips reserved folders, so a trashed file leaves hub_ids) or removed
    by a peer — so this is IDEMPOTENT (fires once, never re-fires after the move) and stays DISTINCT
    from the out-of-band permanent-delete path (a note in local `_trash/` is a SOFT delete → hub
    `_trash/`, recoverable; classify_fs_deleted only ever fires for a note absent from local `_trash/`)."""
    out: Set[str] = set()
    for note_id in local_trashed:
        s = state.get(note_id)
        if not isinstance(s, dict) or not s.get("drive_file_id"):
            continue
        if note_id in hub_ids:
            out.add(note_id)
    return out


def classify_inbound_deletes(
    state: Dict[str, Dict],
    vault_ids: Set[str],
    hub_ids: Set[str],
    hub_trashed_ids: Set[str],
) -> Dict[str, str]:
    """Notes the desktop STILL holds (present in the vault) whose once-synced hub file is now absent
    from the hub's category folders → inbound delete (ISS-005 C). `"trash"` when the hub file sits in
    the hub `_trash/` (a peer soft-delete → prompt), else `"remove"` (a peer permanent delete)."""
    out: Dict[str, str] = {}
    for note_id, s in state.items():
        if not isinstance(s, dict) or not s.get("drive_file_id") or not s.get("base_rev"):
            continue  # only a note we have actually synced (has a base_rev) can be an inbound delete
        if note_id not in vault_ids or note_id in hub_ids:
            continue  # gone locally (that's fs-delete's job) OR still on the hub → not inbound-deleted
        out[note_id] = "trash" if note_id in hub_trashed_ids else "remove"
    return out


# --- filesystem / hub id scans (small, no reconcile coupling) ------------------------------------

def local_trashed_files(vault_path: str) -> Dict[str, Path]:
    """Frontmatter id -> Path for every note currently sitting in the vault's local `_trash/` folder.
    Superset of local_trashed_ids (whose result is just this dict's key set); the Path lets the
    outbound soft-delete path restore a stale-base note out of `_trash/` without a second scan."""
    out: Dict[str, Path] = {}
    trash_dir = Path(vault_path).resolve() / "_trash"
    if not trash_dir.is_dir():
        return out
    for f in trash_dir.glob("*.md"):
        try:
            fields = read_all_fields(f.read_text(encoding="utf-8", errors="ignore", newline=""))
        except OSError:
            continue
        nid = fields.get("id")
        if nid:
            out.setdefault(nid, f)
    return out


def local_trashed_ids(vault_path: str) -> Set[str]:
    """Frontmatter ids of the notes currently sitting in the vault's local `_trash/` folder. Used to
    keep a soft-deleted note from being mistaken for an out-of-band permanent delete."""
    return set(local_trashed_files(vault_path))


def hub_trashed_ids(list_children: Callable[[str], list], trash_folder_id: str) -> Set[str]:
    """Note ids currently under the hub `_trash/` folder. `list_children` is injected (bound to
    mobile_sync_agent._list_children) so this stays unit-testable without a real Drive client."""
    out: Set[str] = set()
    for f in list_children(trash_folder_id):
        name = f.get("name", "")
        if not name.endswith(".md"):
            continue
        props = f.get("appProperties") or {}
        out.add(props.get("noteId") or Path(name).stem)
    return out


# --- durable prompt / pending store -------------------------------------------------------------

def _prompts_path(state_path: str) -> str:
    return str(Path(state_path).with_name("delete_prompts.json"))


def load_delete_prompts(state_path: str) -> Dict[str, Dict]:
    """Load the sibling `delete_prompts.json`. Shape:
    {"prompts": {id: {...}}, "pending_fs": {id:{}}, "keep_here": {id:{}}}.
    `keep_here` records inbound DELETE-PROMPTs the user resolved as "keep here / just remove there" so
    process_deletes never re-raises them (the local note stays, the remote stays removed). Absent/
    corrupt → an empty shell (derived cache; safe to rebuild — the next pass re-detects)."""
    path = _prompts_path(state_path)
    if not os.path.exists(path):
        return {"prompts": {}, "pending_fs": {}, "keep_here": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {"prompts": {}, "pending_fs": {}, "keep_here": {}}
    data.setdefault("prompts", {})
    data.setdefault("pending_fs", {})
    data.setdefault("keep_here", {})
    return data


def save_delete_prompts(state_path: str, data: Dict[str, Dict]) -> None:
    """Atomic write (temp sibling + os.replace), mirroring save_state's crash-safe idiom."""
    path = _prompts_path(state_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


# --- the orchestration run_once calls -----------------------------------------------------------

def process_deletes(
    vault_path: str,
    state_path: str,
    state: Dict[str, Dict],
    vault_notes: Dict[str, Dict],
    hub_files: Dict[str, Dict],
    trash_folder_id: Optional[str],
    now_iso: str,
    list_children: Callable[[str], list],
    delete_file: Callable[[str], None],
    move_file: Optional[Callable[[str, str], None]] = None,
    ensure_hub_trash: Optional[Callable[[], str]] = None,
    vault_root: Optional[str] = None,
) -> Tuple[Dict[str, Dict], int, int]:
    """Detect + act on the delete signals for one pass. NON-DESTRUCTIVE by default:
      - OUTBOUND desktop soft-delete → re-parent the LIVE hub file into hub `_trash/` (body-sacred:
        metadata-only move, bytes never rewritten); a stale base_rev (hub advanced) downgrades to the
        §6 delete-vs-edit conflict — the note is restored out of local `_trash/` for reconcile, the hub
        is NOT trashed. Only runs when move_file + ensure_hub_trash are wired (run_once supplies them).
      - inbound deletes → record a durable prompt, KEEP the local note (never deleted here); a prompt
        the user resolved "keep here" (store["keep_here"]) is never re-raised.
      - out-of-band fs-deletes → recorded first, and only HARD-deleted from the hub on the SECOND
        consecutive absent pass (two-pass confirm against transient local read faults).
    Returns (state_after, fs_deleted_count, prompt_count). `state_after` has confirmed fs-deleted AND
    propagated soft-deleted notes dropped; the prompt/pending store is persisted here. Guaranteed no
    I/O when nothing is pending and there are no candidates (so a clean pass makes zero Drive calls)."""
    vault_ids = set(vault_notes)
    hub_ids = set(hub_files)
    trashed_files = local_trashed_files(vault_path)
    trashed_local = set(trashed_files)
    fs_candidates = classify_fs_deleted(state, vault_ids, trashed_local)
    outbound = (
        classify_outbound_soft_deletes(state, trashed_local, hub_ids)
        if move_file is not None and ensure_hub_trash is not None else set()
    )
    # Cheap pre-check for the inbound side: any once-synced note present locally but absent from the
    # hub category folders. Only if that set is non-empty do we pay for a hub `_trash/` listing.
    maybe_inbound = {
        nid for nid, s in state.items()
        if isinstance(s, dict) and s.get("drive_file_id") and s.get("base_rev")
        and nid in vault_ids and nid not in hub_ids
    }

    store = load_delete_prompts(state_path)
    pending_fs: Dict[str, Dict] = store["pending_fs"]
    prompts: Dict[str, Dict] = store["prompts"]
    keep_here: Dict[str, Dict] = store["keep_here"]

    if not fs_candidates and not outbound and not maybe_inbound and not pending_fs and not prompts:
        return state, 0, 0  # clean pass — no candidates, nothing held → no Drive calls, no writes

    new_state = dict(state)

    # --- OUTBOUND desktop soft-delete → hub _trash/ (ISS-005 A follow-up, §3 symmetric delete) ---
    # SCOPED here, OUTSIDE reconcile_changes/mirror_to_hub so those loops' byte-behavior for
    # non-deleted notes is untouched. A note the desktop moved to its LOCAL `_trash/` whose hub copy
    # is still live in a category folder is propagated as the SAME soft move to the hub `_trash/`.
    for note_id in outbound:
        hf = hub_files.get(note_id)
        if not hf or not hf.get("id"):
            continue
        base_rev = (state.get(note_id) or {}).get("base_rev")
        remote_rev = hf.get("headRevisionId")
        if base_rev and remote_rev and remote_rev != base_rev:
            # §6 case 1 delete-vs-edit: the hub head advanced past the base_rev this delete carries —
            # a peer edited the note after the delete was based. The delete is NOT executed. Restore
            # the note out of local `_trash/` so the next reconcile pass pulls/merges the peer's newer
            # body (remote edit restored locally → conflict for the resolver). Never a blind hub trash.
            path = trashed_files.get(note_id)
            if path is not None:
                try:
                    from trash import restore_from_trash
                    restore_from_trash(Path(vault_root or vault_path), path.name)
                    print(f"[delete_detect] stale-base delete of {note_id}: hub advanced "
                          f"({remote_rev} != {base_rev}); restored locally for reconcile, delete NOT executed")
                except Exception as e:  # noqa: BLE001 — a failed restore must not abort the pass
                    print(f"[delete_detect] stale-base delete restore of {note_id} failed: {e}")
            continue
        # §6 case 3 uncontested: re-parent the live hub file into hub `_trash/`. Metadata-only move —
        # body bytes NEVER rewritten (body-sacred: delete = move). Drop the sync row (trashed on both
        # peers now; a later restore re-adopts the hub file via reconcile_changes' adopt path).
        try:
            trash_id = ensure_hub_trash()
            move_file(hf["id"], trash_id)
            new_state.pop(note_id, None)
            print(f"[delete_detect] propagated desktop soft-delete of {note_id} to hub _trash/")
        except Exception as e:  # noqa: BLE001 — a failed hub move must not abort the pass
            print(f"[delete_detect] hub soft-delete of {note_id} failed: {e}")

    # --- inbound-delete prompts (part 5, non-destructive) ---
    inbound: Dict[str, str] = {}
    if maybe_inbound:
        hub_trashed = hub_trashed_ids(list_children, trash_folder_id) if trash_folder_id else set()
        inbound = classify_inbound_deletes(state, vault_ids, hub_ids, hub_trashed)
    for nid, kind in inbound.items():
        if nid in keep_here:
            continue  # user resolved this as keep-here — never re-prompt (remote stays removed)
        rec = prompts.get(nid)
        if rec and rec.get("kind") == kind:
            continue  # already held — leave the first_seen stamp intact
        prompts[nid] = {"kind": kind, "first_seen": rec.get("first_seen", now_iso) if rec else now_iso}
    # A held prompt whose note is back on the hub, gone locally, or now agrees is stale → drop it.
    for nid in [n for n in prompts if n not in inbound]:
        del prompts[nid]
    # A keep-here decision whose note is back on the hub (re-synced) is spent → forget it.
    for nid in [n for n in keep_here if n in hub_ids]:
        del keep_here[nid]

    # --- out-of-band fs-delete (part 4, two-pass confirm before an IRREVERSIBLE hub delete) ---
    fs_deleted = 0
    for nid in fs_candidates:
        if nid in pending_fs:
            # Seen absent on a prior pass AND still absent now → confirmed permanent delete.
            s = state.get(nid) or {}
            file_id = s.get("drive_file_id")
            if file_id:
                try:
                    delete_file(file_id)
                except Exception as e:  # noqa: BLE001 — a failed hub delete must not abort the pass
                    print(f"[delete_detect] hub delete of {nid} failed: {e}")
                    continue  # keep the pending record; retry next pass
            new_state.pop(nid, None)
            pending_fs.pop(nid, None)
            fs_deleted += 1
        else:
            pending_fs[nid] = {"first_seen": now_iso}  # first sighting — confirm next pass
    # A pending fs-delete that reappeared (readable again, or restored) is not a delete → forget it.
    for nid in [n for n in pending_fs if n not in fs_candidates]:
        del pending_fs[nid]

    store["prompts"] = prompts
    store["pending_fs"] = pending_fs
    store["keep_here"] = keep_here
    save_delete_prompts(state_path, store)
    return new_state, fs_deleted, len(prompts)


if __name__ == "__main__":
    # Smoke test: the pure classifiers + two-pass fs-delete confirm, no Drive/FS needed for the core.
    st = {
        "live": {"drive_file_id": "F1", "base_rev": "r1"},      # present locally + on hub
        "soft": {"drive_file_id": "F2", "base_rev": "r2"},      # gone locally, in local _trash/
        "gone": {"drive_file_id": "F3", "base_rev": "r3"},      # gone locally + not in _trash/ → fs-delete
        "inbound": {"drive_file_id": "F4", "base_rev": "r4"},   # present locally, hub file trashed
        "unsynced": {"drive_file_id": None},                     # never synced → never a signal
    }
    vault = {"live", "soft_placeholder", "inbound"}  # note: "soft"/"gone" absent from vault
    fs = classify_fs_deleted(st, {"live", "inbound"}, local_trashed_ids=set())
    assert fs == {"soft", "gone"}, fs
    fs2 = classify_fs_deleted(st, {"live", "inbound"}, local_trashed_ids={"soft"})
    assert fs2 == {"gone"}, fs2  # soft-deleted (in _trash/) is NOT a permanent delete
    inb = classify_inbound_deletes(st, {"live", "inbound"}, hub_ids={"live"}, hub_trashed_ids={"inbound"})
    assert inb == {"inbound": "trash"}, inb
    inb2 = classify_inbound_deletes(st, {"live", "inbound"}, hub_ids={"live"}, hub_trashed_ids=set())
    assert inb2 == {"inbound": "remove"}, inb2  # hub file gone entirely → permanent inbound
    # Outbound soft-delete: "soft" sits in local _trash/ AND its hub copy is still live → propagate.
    outb = classify_outbound_soft_deletes(st, local_trashed={"soft"}, hub_ids={"live", "soft"})
    assert outb == {"soft"}, outb
    # Hub copy already gone from category folders (trashed/removed) → nothing to propagate (idempotent).
    assert classify_outbound_soft_deletes(st, local_trashed={"soft"}, hub_ids={"live"}) == set()
    # Never-synced note in local _trash/ → nothing on the hub to move.
    assert classify_outbound_soft_deletes(st, local_trashed={"unsynced"}, hub_ids={"unsynced"}) == set()
    print("delete_detect.py smoke check OK")

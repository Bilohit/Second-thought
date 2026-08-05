"""
sync_pending.py — Phase-1 Task 1.3: what the SYNC panel may honestly say is
outstanding, without lying about it.

READ-ONLY. This module never writes the sync sidecar, never runs a sync pass,
never enriches, and never re-defines "what a note is": the vault walk is
`mobile_sync_agent.read_vault_notes` (lan_sync.py:95 states that rule in-source)
and the pending predicate is the exact NEGATION of the skip at
`mobile_sync_agent.py:1135`.

TWO POSTURES (user decision s143 — HYBRID; not open for redesign)
-----------------------------------------------------------------
* **At rest** (`local_pending`) — filesystem only, ZERO Drive calls, so it is
  safe to call at the `/sync/status` poll cadence. Its label is
  **"Changed since last sync"**. The word *queue* is banned from this surface:
  a local-only source cannot honour drain semantics, because two hub-side
  filters (`mobile_sync_agent.py:1144` F-1 skip, `:1151` advanced-head guard)
  and the entire inbound set are only knowable from a live hub listing.
* **On explicit user action** (`pending_with_hub`, `?hub=true`) — ONE Drive
  listing upgrades the answer to exact `will_upload · blocked · to_pull`, using
  the three-state posture `note_history.py:29-31` already established
  (`ok` / `offline` / `not_synced`).

THE REFUSAL STATE NEVER SHOWS A COUNT (user decision s143)
----------------------------------------------------------
`sync_ignore.filter_ignored_notes` returns `{}` when the ignore sidecar does not
parse (`sync_ignore.py:114`) — refusing to sync anything is the only safe
failure for a confidentiality control. But a panel that ran the count through
that filter would render **zero pending at the exact moment `run_pass` refuses
the entire sync** (`mobile_sync_agent.py:1941-1942` raises before Drive is
touched). Empty-reads-as-all-synced is the most dangerous failure mode on this
surface, so `local_pending` calls
`sync_ignore.assert_ignore_set_readable` FIRST — the same precondition, in the
same order, as `run_pass` — and returns `status: "blocked"` carrying the
underlying error, with **no counts and no items at all**.

WHAT THIS SURFACE CANNOT SEE (each is a real ceiling, none are papered over)
---------------------------------------------------------------------------
* Captures (`origin: capture`) — see `scope.captures_counted` and the ponytail
  in `local_pending`.
* Attachments — see `scope.attachments_counted` and its ponytail.
* Whether a "changed" note changed because the USER edited it or because
  `enrich_notes` (`mobile_sync_agent.py:1780-1781`) rewrote its frontmatter —
  see the ponytail on `_classify`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Set

# Items are capped so a first-run vault cannot ship thousands of rows through
# the localhost API; the COUNTS above them stay exact.
MAX_ITEMS = 200

LABEL_RESTING = "Changed since last sync"
LABEL_BLOCKED = "Sync blocked — ignore list unreadable"

# Reasons a note is outstanding. `changed` is the only one the local read can
# state positively; `no_sync_record` is deliberately a SEPARATE bucket (see
# `unknown` in the payload) because it is not evidence of a local edit.
REASON_CHANGED = "content_changed"
REASON_NO_RECORD = "no_sync_record"

# Hub-resolved outcomes (only ever populated by pending_with_hub).
OUT_UPLOAD = "will_upload"
OUT_BLOCKED = "blocked"
OUT_PULL = "to_pull"

STATUS_OK = "ok"
STATUS_OFFLINE = "offline"
STATUS_NOT_SYNCED = "not_synced"
STATUS_BLOCKED = "blocked"


def _state_path(vault_root: Path) -> Path:
    # Mirrors mobile_sync_agent.run_pass()'s own default (:1933) and
    # note_history._sync_state_path: vault-anchored, never CWD-relative.
    return vault_root / ".omni_capture" / "mobile_sync_state.json"


def _classify(note: Dict, prior: Optional[Dict]) -> Optional[str]:
    """The negation of `mobile_sync_agent.py:1135`.

    That skip is `prior and prior["local_hash"] == note["hash"] and
    prior["drive_file_id"]`; anything else is outstanding. `note["hash"]` is the
    sha256 `read_vault_notes` already computed over the file's verbatim bytes —
    this module never hashes a file itself, so there is exactly one definition
    of a note's content hash.

    ponytail: the sidecar stores ONE whole-content hash, so a note whose
    frontmatter was rewritten by `enrich_notes` (mobile_sync_agent.py:1780-1781)
    is indistinguishable here from a note the user edited — both read as
    `content_changed`. That is why the resting label is "Changed since last
    sync" and never "you edited". Upgrade path: record a body-only hash
    alongside `local_hash` in the sidecar, which is a sync-state schema change
    and needs its own user-approved pass — not something a read-only panel may
    introduce.
    """
    if prior is None or not prior.get("drive_file_id"):
        return REASON_NO_RECORD
    if prior.get("local_hash") != note["hash"]:
        return REASON_CHANGED
    return None


def _blocked_payload(error: str) -> dict:
    """The refusal state. Carries the error, NEVER a number — a count here would
    read as 'all synced' at the exact moment the whole pass is refused."""
    return {
        "status": STATUS_BLOCKED,
        "reason": "ignore_set_unreadable",
        "error": error,
        "label": LABEL_BLOCKED,
    }


def local_pending(vault_root: Path) -> dict:
    """Resting answer: local hash-vs-sidecar diff + held delete prompts.

    Filesystem only — no Drive client is constructed and no network call is
    issued, so this is safe at `/sync/status` poll cadence."""
    from mobile_sync_agent import load_state, read_vault_notes
    from sync_ignore import (
        IgnoreSetUnreadable,
        assert_ignore_set_readable,
        filter_ignored_notes,
    )

    vault_root = Path(vault_root)

    # FIRST, before anything can produce a number: the same precondition
    # run_pass asserts at :1942. A corrupt ignore set refuses the whole pass, so
    # the panel must refuse to count rather than render 0.
    try:
        assert_ignore_set_readable(vault_root)
    except IgnoreSetUnreadable as exc:
        return _blocked_payload(str(exc))

    from config import get_config
    mirror_captures = bool(get_config().sync.mirror_captures)

    # ponytail: always read with mirror_captures=False, even when the setting is
    # ON. read_vault_notes MINTS an id and rewrites the file for a capture that
    # has none (mobile_sync_agent.py:257-273) — a read-only panel may not write
    # to the vault to answer a question. So captures are never counted here and
    # `scope.captures_counted` says so out loud, rather than the count silently
    # jumping by +hundreds the moment [sync] mirror_captures flips. Upgrade
    # path: a keyword-only `mint_ids=False` read mode on read_vault_notes that
    # returns id-less captures under a separate key.
    notes = read_vault_notes(str(vault_root), False)
    visible = filter_ignored_notes(notes, vault_root)

    state_path = _state_path(vault_root)
    state = load_state(str(state_path))

    items = []
    changed = 0
    unknown = 0
    for note_id, note in visible.items():
        reason = _classify(note, state.get(note_id))
        if reason is None:
            continue
        if reason == REASON_CHANGED:
            changed += 1
        else:
            unknown += 1
        if len(items) < MAX_ITEMS:
            items.append({"id": note_id, "path": note["path"], "reason": reason})

    from delete_detect import load_delete_prompts
    prompts = load_delete_prompts(str(state_path)).get("prompts", {})

    return {
        "status": STATUS_OK,
        "label": LABEL_RESTING,
        # Two buckets on purpose. `changed` is the only number backed by
        # evidence of a local edit. `unknown` holds notes with no usable sidecar
        # row: a fresh note, OR a lost/rebuilt sidecar — and a lost sidecar is
        # NOT mass-pending, because reconcile_changes quietly adopts the hub
        # file and skips it when the bytes already match
        # (mobile_sync_agent.py:959-974). Keeping them apart is what stops a
        # sidecar loss from rendering as "N notes will upload".
        "changed": changed,
        "unknown": unknown,
        "deletes_pending": len(prompts),
        "items": items,
        "truncated": (changed + unknown) > len(items),
        "sidecar_present": state_path.is_file(),
        "sidecar_rows": len(state),
        "scope": {
            "notes_scanned": len(visible),
            "captures_counted": False,
            "mirror_captures_enabled": mirror_captures,
            # ponytail: attachments are presence-is-state — _sync_note_attachments
            # keeps no sidecar row per attachment, so there is no local record to
            # diff against and a pending attachment is structurally invisible
            # here. Upgrade path: a per-attachment ledger written by
            # _sync_note_attachments, which is a sync-state change, not a panel
            # change.
            "attachments_counted": False,
        },
        "hub": None,
    }


def _find_hub_folder(drive, name: Optional[str] = None) -> Optional[str]:
    """Hub root id, or None — the LIST half of
    `mobile_sync_agent.ensure_hub_folder` (:321) with the CREATE half removed.
    A read-only panel must never bring the hub folder into existence. The folder
    name and mime constant are imported, never restated."""
    from mobile_sync_agent import HUB_FOLDER_NAME, _FOLDER_MIME
    name = name or HUB_FOLDER_NAME
    q = f"name='{name}' and mimeType='{_FOLDER_MIME}' and trashed=false"
    found = drive.files().list(q=q, fields="files(id,name)").execute().get("files", [])
    return found[0]["id"] if found else None


def _resolve_against_hub(
    visible: Dict[str, Dict],
    state: Dict[str, Dict],
    hub_files: Dict[str, Dict],
    trashed_ids: Set[str],
) -> dict:
    """Turn the resting diff into exact directions, replaying mirror_to_hub's own
    two hub-side filters and pull_new_hub_notes' own "new" test. Pure — no I/O,
    so it is unit-testable without a Drive client.

    This walks EVERY visible note, not just the resting-pending ones: a note the
    peer edited has an unchanged local hash, so the resting diff cannot see it
    at all. Inbound work only becomes visible once the hub head is in hand —
    which is the whole reason the resting label may never say "will upload"."""
    will_upload = []
    blocked = []
    to_pull = []

    for note_id, note in visible.items():
        prior = state.get(note_id)
        hub_file = hub_files.get(note_id)
        if prior is None or not prior.get("drive_file_id"):
            # mobile_sync_agent.py:1144 — no observed sync for this note. If the
            # hub already holds it, mirror_to_hub SKIPS it and reconcile_changes
            # owns it; it is not an upload and it is not stuck.
            if hub_file is not None:
                blocked.append({"id": note_id, "path": note["path"],
                                "reason": "reconcile_owns_no_base_rev"})
            else:
                will_upload.append({"id": note_id, "path": note["path"]})
            continue
        head_advanced = bool(
            prior.get("base_rev")
            and hub_file
            and hub_file.get("headRevisionId") != prior.get("base_rev")
        )
        local_changed = prior.get("local_hash") != note["hash"]
        if head_advanced:
            # mobile_sync_agent.py:1151 — the guard mirror_to_hub applies. With
            # a local change too this is a reconcile/conflict, NOT an upload;
            # with no local change the direction is INBOUND. Reporting either as
            # "will upload" is the inverted-direction lie.
            if local_changed:
                blocked.append({"id": note_id, "path": note["path"],
                                "reason": "hub_head_advanced"})
            else:
                to_pull.append({"id": note_id, "path": note["path"],
                                "reason": "hub_head_advanced"})
            continue
        if local_changed:
            will_upload.append({"id": note_id, "path": note["path"]})

    # pull_new_hub_notes' own definition of "new": id in neither the local vault
    # nor the state sidecar, minus ids sitting in the local `_trash/` (ISS-046).
    for note_id in hub_files:
        if note_id in visible or note_id in state or note_id in trashed_ids:
            continue
        to_pull.append({"id": note_id, "reason": "hub_only"})

    return {
        "status": STATUS_OK,
        "will_upload": will_upload[:MAX_ITEMS],
        "blocked": blocked[:MAX_ITEMS],
        "to_pull": to_pull[:MAX_ITEMS],
        "counts": {
            OUT_UPLOAD: len(will_upload),
            OUT_BLOCKED: len(blocked),
            OUT_PULL: len(to_pull),
        },
    }


def pending_with_hub(vault_root: Path) -> dict:
    """The explicit-action answer: the resting payload plus ONE Drive listing.

    Only ever called from a user gesture (expand / Sync now) — never on a poll.
    The `hub` block carries `note_history.py`'s three states: `ok` when the
    listing succeeded, `offline` when Drive has no cached credentials or the
    call failed, `not_synced` when the hub folder does not exist yet. A non-`ok`
    state carries NO buckets — absent, not zeroed."""
    vault_root = Path(vault_root)
    base = local_pending(vault_root)
    if base["status"] != STATUS_OK:
        return base  # refusal outranks everything; still no counts, still no network

    from drive_auth import has_cached_credentials
    if not has_cached_credentials():
        base["hub"] = {"status": STATUS_OFFLINE}
        return base

    try:
        from drive_auth import get_drive_service
        from mobile_sync_agent import get_hub_notes, load_state, read_vault_notes
        from sync_ignore import filter_ignored_notes

        drive = get_drive_service()
        hub_id = _find_hub_folder(drive)
        if hub_id is None:
            base["hub"] = {"status": STATUS_NOT_SYNCED}
            return base
        hub_files = get_hub_notes(drive, hub_id)
    except Exception as exc:  # token revoked mid-session, quota, network
        # Same posture as note_history.get_note_history: "offline", not a 5xx.
        base["hub"] = {"status": STATUS_OFFLINE, "error": str(exc)}
        return base

    visible = filter_ignored_notes(read_vault_notes(str(vault_root), False), vault_root)
    state = load_state(str(_state_path(vault_root)))
    from delete_detect import local_trashed_ids
    base["hub"] = _resolve_against_hub(
        visible, state, hub_files, local_trashed_ids(str(vault_root))
    )
    return base


# ---------------------------------------------------------------------------
# Smoke test  (python sync_pending.py) — the pure predicate + the hub resolver,
# no vault and no Drive needed. The endpoint-level cases (refusal state, zero
# network at rest) live in test_sync_pending.py.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    n = {"id": "n1", "path": "/v/P/a.md", "hash": "H1"}

    assert _classify(n, None) == REASON_NO_RECORD
    assert _classify(n, {"local_hash": "H1"}) == REASON_NO_RECORD          # no drive_file_id
    assert _classify(n, {"local_hash": "H0", "drive_file_id": "f"}) == REASON_CHANGED
    assert _classify(n, {"local_hash": "H1", "drive_file_id": "f"}) is None
    print("[T1] _classify negates mobile_sync_agent.py:1135  PASS")

    visible = {
        "up":      {"id": "up",      "path": "/v/P/up.md",   "hash": "H2"},
        "f1":      {"id": "f1",      "path": "/v/P/f1.md",   "hash": "H3"},
        "adv":     {"id": "adv",     "path": "/v/P/adv.md",  "hash": "H4"},
        "inbound": {"id": "inbound", "path": "/v/P/in.md",   "hash": "H5"},
    }
    state = {
        "up":      {"drive_file_id": "d1", "base_rev": "r1", "local_hash": "OLD"},
        "adv":     {"drive_file_id": "d3", "base_rev": "r3", "local_hash": "OLD"},
        "inbound": {"drive_file_id": "d4", "base_rev": "r4", "local_hash": "H5"},
    }
    hub = {
        "up":      {"headRevisionId": "r1"},
        "f1":      {"headRevisionId": "rX"},
        "adv":     {"headRevisionId": "rZ"},
        "inbound": {"headRevisionId": "rNEW"},
        "hubonly": {"headRevisionId": "rH"},
        "gone":    {"headRevisionId": "rG"},
    }
    res = _resolve_against_hub(visible, state, hub, {"gone"})
    ids = lambda k: sorted(x["id"] for x in res[k])
    assert ids("will_upload") == ["up"], ids("will_upload")
    assert ids("blocked") == ["adv", "f1"], ids("blocked")
    assert ids("to_pull") == ["hubonly", "inbound"], ids("to_pull")
    assert res["counts"] == {OUT_UPLOAD: 1, OUT_BLOCKED: 2, OUT_PULL: 2}
    print("[T2] hub resolver: F-1 skip, advanced head, inbound, trash  PASS")

    b = _blocked_payload("boom")
    assert b["status"] == STATUS_BLOCKED and "changed" not in b and "unknown" not in b
    print("[T3] refusal state carries no count  PASS")

    print("\nAll sync_pending.py smoke tests passed.")

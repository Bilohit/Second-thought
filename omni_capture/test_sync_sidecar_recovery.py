"""test_sync_sidecar_recovery.py — F-1: losing the derived sync sidecar must never cost a byte.

Plain pytest (NOT fuzz-gated). These pin, deterministically, the minimal sequence the §3.1 race
fuzz shrank to at its full 2000-example budget:

    sync a note · the peer edits it on the hub · the state sidecar is lost · run_once

`mobile_sync_agent.mirror_to_hub` used to answer a missing sidecar entry by adopting the hub
listing as `prior` with `base_rev` = the CURRENT head — a revision it had never synced at. That
defeated both safety nets at once (`local_hash: None` missed the already-synced skip, and the
advanced-head guard compared the head against itself), so the desktop uploaded its stale body over
the peer's edit: the hub head REVERTED, the remote edit was gone from both sides, and no conflicted
copy was written. Unconditional silent data loss on ANY sidecar loss with an un-pulled remote edit.

The fake hub (a real revision-history-carrying in-memory Drive) is imported rather than re-authored
— `test_fuzz_races` builds it on top of `test_mobile_sync_agent`'s fake, and a third competing fake
is exactly what that file's docstring warns against. Only the FUZZ-gated *tests* in that module are
skipped without FUZZ=1; its helpers import fine.
"""
from __future__ import annotations

import os
from pathlib import Path

from frontmatter import strip_frontmatter
from mobile_sync_agent import run_once
from note_model import parse_note, serialize_note
from test_fuzz_races import SCRATCHPAD, _bodies_on_disk, _fresh, _sync_note


def _hub_bodies(hub) -> set[str]:
    return {strip_frontmatter(hub.text(r["id"])) for r in hub.all_note_recs()}


def test_sidecar_loss_with_a_remote_edit_never_reverts_the_hub_head(tmp_path):
    """The headline. NO local edit is involved — the desktop never touches its copy. Sidecar
    loss alone used to be enough to roll the canonical head back to the desktop's stale body."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)
    body_before = strip_frontmatter(Path(local_path).read_text(encoding="utf-8", newline=""))

    remote = parse_note(hub.text(fid))
    remote.body = "phone edit — never pulled to this desktop\n"
    hub.overwrite(fid, serialize_note(remote))

    os.remove(state_path)                      # crash: derived sidecar lost
    run_once(str(vault), state_path, hub, vault_root=str(vault), scratchpad_folder=SCRATCHPAD)

    # Body-sacred: recovery may merge machine-owned frontmatter into the local file, never a body.
    assert strip_frontmatter(
        Path(local_path).read_text(encoding="utf-8", newline="")) == body_before
    surviving = _bodies_on_disk(vault) | _hub_bodies(hub)
    assert "phone edit — never pulled to this desktop\n" in surviving, (
        "remote edit REVERTED by a sidecar loss alone — hub head rolled back to the desktop's "
        "stale body with no conflicted copy; non-destructive lock violated"
    )
    assert "orig body\n" in surviving, "the desktop's own body was dropped instead"


def test_sidecar_loss_with_edits_on_both_sides_keeps_both_bodies(tmp_path):
    """Sidecar lost AND both peers edited: no common ancestor exists, so the divergence routes to
    the non-destructive conflicted-copy rule — never a blind upload over the advanced head."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)

    remote = parse_note(hub.text(fid))
    remote.body = "remote body — typed on the phone\n"
    hub.overwrite(fid, serialize_note(remote))
    local = parse_note(Path(local_path).read_text(encoding="utf-8", newline=""))
    local.body = "local body — typed on the desktop\n"
    Path(local_path).write_text(serialize_note(local), encoding="utf-8", newline="")

    os.remove(state_path)                      # crash: derived sidecar lost
    run_once(str(vault), state_path, hub, vault_root=str(vault), scratchpad_folder=SCRATCHPAD)

    surviving = _bodies_on_disk(vault) | _hub_bodies(hub)
    assert "local body — typed on the desktop\n" in surviving
    assert "remote body — typed on the phone\n" in surviving, (
        "remote body destroyed: mirror blind-uploaded over an advanced head after sidecar loss"
    )


def test_sidecar_loss_on_an_unchanged_note_is_a_no_op(tmp_path):
    """The LOW from the same root cause: `local_hash: None` made the next mirror re-upload
    BYTE-IDENTICAL content and burn a headRevisionId — a Drive write per note per sidecar loss,
    and a bumped head makes every peer re-pull an unchanged note. A content compare must make the
    rebuild a no-op, and must repopulate the sidecar so the pass after it skips outright."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, _ = _sync_note(hub, vault, state_path)
    rev_before, content_before = hub.recs[fid]["headRevisionId"], hub.recs[fid]["content"]

    os.remove(state_path)                      # crash: derived sidecar lost
    run_once(str(vault), state_path, hub, vault_root=str(vault), scratchpad_folder=SCRATCHPAD)

    assert hub.recs[fid]["content"] == content_before
    assert hub.recs[fid]["headRevisionId"] == rev_before, (
        "sidecar rebuild re-uploaded identical bytes and bumped headRevisionId — not idempotent"
    )
    assert Path(state_path).exists(), "sidecar not rebuilt from the files it is derived from"


def test_sidecar_loss_reuses_the_hub_file_instead_of_duplicating(tmp_path):
    """The hub-adopt fallback's legitimate goal, preserved: the note's existing hub file is
    UPDATED, never re-created as a duplicate orphan. Guards against 'fix the clobber by dropping
    the adopt' — the local edit must still land, on the one file the note already has.

    The known cost of having no ancestor: the hub body ("orig body") cannot be told apart from a
    peer's un-pulled edit, so it is kept as a conflicted copy rather than assumed stale. That is
    the non-destructive rule doing its job — noise on a lost sidecar, never a lost byte.
    """
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)

    local = parse_note(Path(local_path).read_text(encoding="utf-8", newline=""))
    local.body = "desktop edit while the sidecar was gone\n"
    Path(local_path).write_text(serialize_note(local), encoding="utf-8", newline="")

    os.remove(state_path)                      # crash: derived sidecar lost
    run_once(str(vault), state_path, hub, vault_root=str(vault), scratchpad_folder=SCRATCHPAD)

    own = [r["id"] for r in hub.all_note_recs()
           if (r.get("appProperties") or {}).get("noteId") == "s01"]
    assert own == [fid], f"note s01 must keep its one hub file, got {own}"
    assert strip_frontmatter(hub.text(fid)) == "desktop edit while the sidecar was gone\n", (
        "the local-only edit never reached the hub — adopt must still upload onto the hub file"
    )
    assert "orig body\n" in _bodies_on_disk(vault), "the hub's body was discarded, not kept"

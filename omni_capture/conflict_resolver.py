"""
conflict_resolver.py — F-1 desktop half: surfaces + resolves a body-vs-body
conflicted copy that reconcile.py (mobile_sync_agent.py) spun off next to the
original note.

Detection: reconcile.py never renames the ORIGINAL note file, and writes the
conflicted copy at `<original's directory>/<fresh_conflict_id>.md` with
`title = "<original title> (conflicted copy <device> <modified>)"` (see
reconcile.py `_merge_two`/`reconcile`, suffix construction). The random id
means the copy's FILENAME carries no relation to the original -- the title
prefix is the only reliable link, so that's what this module matches on.

All three resolution actions are ordinary file operations through paths this
codebase already has (body-sacred safe, per workspace CLAUDE.md):
  - "both"   : no file op at all -- the conflicted copy already stands as its
               own independent note; there is nothing to change.
  - "mine"   : the conflicted copy moves to the vault's _trash folder.
  - "theirs" : the conflicted copy's body becomes the original note's body
               (via note_editor.write_note_body -- a normal user file-write,
               frontmatter carried through byte-for-byte), then the copy
               moves to _trash.

ponytail: no "undismiss" / per-user dismissal state is persisted for "both" --
the banner reappears if the note is reopened, because the conflicted-copy
file still legitimately exists on disk. Add a dismissal flag (frontmatter or
a small sidecar) only if that reappearance proves annoying in practice.
"""
from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from frontmatter import read_all_fields, strip_frontmatter
from note_editor import resolve_note_path, write_note_body

_CONFLICT_MARK = " (conflicted copy "


def _vault_trash_dir(vault_root: Path) -> Path:
    d = vault_root.resolve() / "_trash"
    d.mkdir(exist_ok=True)
    return d


def _trash_file(vault_root: Path, path: Path) -> Path:
    trash_dir = _vault_trash_dir(vault_root)
    dest = trash_dir / path.name
    if dest.exists():
        # SYNC-17: `int(time.time())` is second-granular, so two resolves inside the same second
        # produced the SAME trash name and shutil.move overwrote the first file outright. A uuid4
        # suffix cannot collide. The timestamp is kept for human readability.
        dest = trash_dir / f"{path.stem}.{int(time.time())}.{uuid.uuid4().hex[:8]}{path.suffix}"
    shutil.move(str(path), str(dest))
    # F-2: bump mtime to the actual trash time (shutil.move preserves the
    # original mtime otherwise) so trash.py's Library view can show an
    # accurate "deleted N days ago" / purge countdown.
    now = time.time()
    os.utime(dest, (now, now))
    return dest


def find_conflict_sibling(vault_root: Path, path_str: str) -> Optional[Path]:
    """Return the conflicted-copy Path sitting beside *path_str*'s note, or
    None if there isn't one."""
    path = resolve_note_path(vault_root, path_str)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    local_fields = read_all_fields(path.read_text(encoding="utf-8", errors="ignore"))
    local_title = local_fields.get("title") or path.stem
    prefix = f"{local_title}{_CONFLICT_MARK}"
    for sib in path.parent.glob("*.md"):
        if sib == path:
            continue
        try:
            sib_text = sib.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        sib_fields = read_all_fields(sib_text)
        if (sib_fields.get("title") or "").startswith(prefix):
            return sib
    return None


def get_conflict(vault_root: Path, path_str: str) -> Optional[dict]:
    """Return the two-sided diff payload for the GUI, or None if this note
    has no conflicted copy right now."""
    path = resolve_note_path(vault_root, path_str)
    sib = find_conflict_sibling(vault_root, path_str)
    if sib is None:
        return None
    local_text = path.read_text(encoding="utf-8", errors="ignore")
    remote_text = sib.read_text(encoding="utf-8", errors="ignore")
    remote_fields = read_all_fields(remote_text)
    return {
        "conflict_path": str(sib),
        "local_body": strip_frontmatter(local_text),
        "remote_body": strip_frontmatter(remote_text),
        "remote_device": remote_fields.get("device"),
        "remote_modified": remote_fields.get("modified"),
        # Optimistic-concurrency token: the GUI must echo this back on a
        # "theirs" resolve so write_note_body raises NoteConflictError if the
        # original note was edited on disk between opening the diff and
        # resolving it (otherwise "theirs" would silently clobber that edit).
        "local_mtime": path.stat().st_mtime,
    }


def resolve_conflict(
    vault_root: Path,
    path_str: str,
    conflict_path_str: str,
    action: str,
    expected_mtime: Optional[float] = None,
) -> dict:
    """Apply one of "both" | "mine" | "theirs". Raises FileNotFoundError if
    either file is gone (already resolved elsewhere), ValueError for an
    unknown action.

    "theirs" overwrites the original note's body, so it REQUIRES
    *expected_mtime* -- the `local_mtime` the GUI got from get_conflict. It is
    passed straight to write_note_body, which raises NoteConflictError if the
    note was edited on disk since the diff was loaded (never a silent clobber).
    """
    path = resolve_note_path(vault_root, path_str)
    conflict_path = resolve_note_path(vault_root, conflict_path_str)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if not conflict_path.is_file():
        raise FileNotFoundError(str(conflict_path))

    if action == "both":
        return {"ok": True, "action": "both"}

    if action == "mine":
        _trash_file(vault_root, conflict_path)
        return {"ok": True, "action": "mine"}

    if action == "theirs":
        if expected_mtime is None:
            raise ValueError("expected_mtime is required to resolve 'theirs'")
        remote_text = conflict_path.read_text(encoding="utf-8", errors="ignore")
        remote_body = strip_frontmatter(remote_text)
        # Guard first (may raise NoteConflictError); only trash the copy once
        # the original note actually took the remote body.
        write_note_body(vault_root, path_str, remote_body, expected_mtime)
        # SYNC-17: the body write above already succeeded and IS the user's intent. A raise from
        # _trash_file here used to propagate, so the caller saw a failed resolve while the note
        # had in fact taken the remote body — leaving the original holding the remote body AND
        # the conflicted copy still on disk, i.e. an apparently-unresolved conflict that re-resolves
        # into a second copy. Log instead; the copy stays and can be dismissed again.
        try:
            _trash_file(vault_root, conflict_path)
        except OSError as exc:
            print(f"[conflict_resolver] body written but trashing {conflict_path} failed: {exc}")
        return {"ok": True, "action": "theirs"}

    raise ValueError(f"unknown resolve action: {action!r}")


def list_vault_conflicts(vault_root: Path) -> list[dict]:
    """Cheap vault-wide scan (title-prefix match only, no per-note round
    trip) so the GUI can badge rows in bulk (VaultManager/Library) without
    one /note/conflict request per file. Skips reserved folders."""
    root = vault_root.resolve()
    if not root.is_dir():
        return []
    reserved = {"_trash", "_mobile_inbox", "_attachments", "_templates", ".sync", ".omni_capture"}

    by_title: dict[str, list[Path]] = {}
    for md_file in root.rglob("*.md"):
        if any(part in reserved for part in md_file.relative_to(root).parts[:-1]):
            continue
        try:
            fields = read_all_fields(md_file.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        title = fields.get("title")
        if title:
            by_title.setdefault(title, []).append(md_file)

    out: list[dict] = []
    for title, copy_path in ((t, p) for t, ps in by_title.items() if _CONFLICT_MARK in t for p in ps):
        original_title = title.split(_CONFLICT_MARK, 1)[0]
        for original_path in by_title.get(original_title, []):
            if original_path.parent == copy_path.parent and original_path != copy_path:
                out.append({
                    "path": str(original_path),
                    "conflict_path": str(copy_path),
                    "title": original_title,
                })
                break
    return out


# ---------------------------------------------------------------------------
# Smoke test  (python conflict_resolver.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        cat = vault / "Tech_Notes"
        cat.mkdir()
        original = cat / "example.md"
        original.write_text(
            "---\nid: 01ORIG\ntitle: Example note\ncategory: Tech_Notes\n---\n"
            "# Example note\n\nMy local body.\n",
            encoding="utf-8",
        )
        copy_ = cat / "01COPYFRESH.md"
        copy_.write_text(
            "---\nid: 01COPYFRESH\ntitle: Example note (conflicted copy phone-9f3e 2026-07-11T19:27:00Z)\n"
            "category: Tech_Notes\ndevice: phone-9f3e\nmodified: 2026-07-11T19:27:00Z\n---\n"
            "# Example note\n\nTheir remote body.\n",
            encoding="utf-8",
        )

        # T1: sibling detected by title prefix.
        sib = find_conflict_sibling(vault, str(original))
        assert sib == copy_
        print("[T1] find_conflict_sibling  PASS")

        # T2: get_conflict returns both bodies + remote metadata.
        conflict = get_conflict(vault, str(original))
        assert conflict is not None
        assert "My local body." in conflict["local_body"]
        assert "Their remote body." in conflict["remote_body"]
        assert conflict["remote_device"] == "phone-9f3e"
        print("[T2] get_conflict  PASS")

        # T3: list_vault_conflicts finds the same pair vault-wide.
        found = list_vault_conflicts(vault)
        assert len(found) == 1 and found[0]["path"] == str(original)
        print("[T3] list_vault_conflicts  PASS")

        # T4: "mine" trashes the copy, leaves the original body untouched.
        resolve_conflict(vault, str(original), str(copy_), "mine")
        assert not copy_.exists()
        assert (vault / "_trash" / copy_.name).exists()
        assert "My local body." in original.read_text(encoding="utf-8")
        print("[T4] resolve_conflict mine  PASS")

        # T5: "theirs" swaps the body then trashes the copy (fresh pair),
        # using the local_mtime the GUI would have read from get_conflict.
        copy2 = cat / "01COPYFRESH2.md"
        copy2.write_text(
            "---\nid: 01COPYFRESH2\ntitle: Example note (conflicted copy desk-a1b2 2026-07-12T14:02:00Z)\n"
            "category: Tech_Notes\n---\n# Example note\n\nSecond remote body.\n",
            encoding="utf-8",
        )
        conflict2 = get_conflict(vault, str(original))
        resolve_conflict(vault, str(original), str(copy2), "theirs", conflict2["local_mtime"])
        assert "Second remote body." in original.read_text(encoding="utf-8")
        assert not copy2.exists()
        print("[T5] resolve_conflict theirs  PASS")

        # T6: a STALE expected_mtime (original edited after the diff loaded)
        # must refuse "theirs" and leave both files intact -- no silent clobber.
        from note_editor import NoteConflictError
        copy3 = cat / "01COPYFRESH3.md"
        copy3.write_text(
            "---\nid: 01COPYFRESH3\ntitle: Example note (conflicted copy desk-c3d4 2026-07-13T10:00:00Z)\n"
            "category: Tech_Notes\n---\n# Example note\n\nThird remote body.\n",
            encoding="utf-8",
        )
        conflict3 = get_conflict(vault, str(original))
        stale_mtime = conflict3["local_mtime"] - 5.0  # pretend an edit happened since
        raised = False
        try:
            resolve_conflict(vault, str(original), str(copy3), "theirs", stale_mtime)
        except NoteConflictError:
            raised = True
        assert raised, "stale mtime must raise NoteConflictError"
        assert copy3.exists(), "copy must survive a refused 'theirs'"
        assert "Second remote body." in original.read_text(encoding="utf-8"), "original body must be untouched"
        print("[T6] resolve_conflict theirs stale-mtime guard  PASS")

    print("\nAll conflict_resolver.py smoke tests passed.")

"""
trash.py — F-2: Library "Trash" surface. Lists notes sitting in the vault's
`_trash/` folder and restores them back to their original category.

Files land in `_trash/` today via conflict_resolver.py's `_trash_file` (a
plain `shutil.move`) — this module is the read/restore counterpart, reusing
the same folder convention rather than inventing a second trash mechanism.
No new "delete a note" affordance is added here (out of scope) — this is
purely the restore surface the mock calls out as missing.

Files are the source of truth: "deleted_at" is the trashed file's own mtime
(conflict_resolver._trash_file bumps it to the move time via os.utime), and
"original category" is read straight out of the note's own frontmatter —
nothing is tracked in a side database.

OF-16: `purge_expired` hard-deletes `_trash/*.md` past the 30-day window (the
LOCAL-vault half of the purge); the desktop sync agent sweeps the hub `_trash/`
separately (mobile_sync_agent.purge_expired_hub_trash — the Drive-side purge
authority, note-features §6 "purge runs only on the online device"). The
"Purge policy: 30 days" caption is now enforced, not display-only.
"""
from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path

from frontmatter import read_all_fields
from path_safety import safe_subdir

_PURGE_AFTER_SECONDS = 30 * 24 * 3600


def _trash_dir(vault_root: Path) -> Path:
    return vault_root.resolve() / "_trash"


def move_to_trash(vault_root: Path, path: Path) -> dict:
    """ISS-005 A: user-originated soft-delete. Move a live note `.md` into `_trash/`.

    This is the DESKTOP half of the symmetric soft-move (data-model §3 "Delete is symmetric"):
    the phone already queues a `delete` op that re-parents the hub file into `_trash/`; this gives
    the desktop the identical local effect so both peers delete the same way. It mirrors
    conflict_resolver._trash_file (a plain byte-verbatim `shutil.move` + an mtime bump so the
    Trash view's "deleted N days ago" / 30-day purge countdown is accurate) but is a USER delete
    rather than a conflict artifact.

    BODY-SACRED: a filesystem move never opens or rewrites the file, so the frontmatter and the
    sacred body are byte-identical afterwards (asserted in the sibling test). `category` stays in
    the note's own frontmatter, which is exactly what restore_from_trash reads to put it back.

    *path* is the caller-resolved, in-vault note path (route handlers resolve+guard it first).
    Returns {ok, filename, trashed_path}. Raises FileNotFoundError if the note is absent."""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))

    trash_dir = _trash_dir(vault_root)
    trash_dir.mkdir(exist_ok=True)
    dest = trash_dir / path.name
    if dest.exists():
        # SYNC-17 idiom: second-granular int(time) can collide within one second, and a uuid4
        # suffix cannot — never overwrite an existing trashed note.
        dest = trash_dir / f"{path.stem}.{int(time.time())}.{uuid.uuid4().hex[:8]}{path.suffix}"
    shutil.move(str(path), str(dest))
    # Bump mtime to the trash time (shutil.move preserves the original otherwise) so list_trash's
    # "deleted N days ago" + purge countdown is accurate — same as conflict_resolver._trash_file.
    now = time.time()
    os.utime(dest, (now, now))
    return {"ok": True, "filename": dest.name, "trashed_path": str(dest)}


def list_trash(vault_root: Path) -> list[dict]:
    """Return every `.md` file currently in `_trash/`, newest-deleted first."""
    trash_dir = _trash_dir(vault_root)
    if not trash_dir.is_dir():
        return []
    out: list[dict] = []
    for f in trash_dir.glob("*.md"):
        try:
            fields = read_all_fields(f.read_text(encoding="utf-8", errors="ignore"))
            stat = f.stat()
        except OSError:
            continue
        deleted_at = stat.st_mtime
        out.append({
            "filename": f.name,
            "title": fields.get("title") or f.stem,
            "category": fields.get("category") or "Uncategorized",
            "deleted_at": deleted_at,
            "purge_at": deleted_at + _PURGE_AFTER_SECONDS,
        })
    out.sort(key=lambda r: r["deleted_at"], reverse=True)
    return out


def purge_expired(vault_root: Path, now: float | None = None) -> list[str]:
    """OF-16: permanently delete `_trash/*.md` whose 30-day recovery window has elapsed.

    `deleted_at` is the trashed file's own mtime (see list_trash). Restore always wins: a file restored
    before its window elapses has already left `_trash/`, so it is never seen here. This is the LOCAL
    half of the purge; the hub `_trash/` is swept by the sync agent. Returns the filenames purged."""
    now = time.time() if now is None else now
    trash_dir = _trash_dir(vault_root)
    if not trash_dir.is_dir():
        return []
    purged: list[str] = []
    for f in trash_dir.glob("*.md"):
        try:
            if now - f.stat().st_mtime >= _PURGE_AFTER_SECONDS:
                f.unlink()
                purged.append(f.name)
        except OSError:
            continue
    return purged


def restore_from_trash(vault_root: Path, filename: str) -> dict:
    """Move `_trash/<filename>` back to its original category folder (read
    from the note's own `category` frontmatter field). A normal file move —
    it syncs like any other vault edit on the next pass, no special-casing
    needed on the sync side."""
    trash_dir = _trash_dir(vault_root)
    src = trash_dir / filename
    if not src.is_file():
        raise FileNotFoundError(str(src))

    fields = read_all_fields(src.read_text(encoding="utf-8", errors="ignore"))
    # SRV-04: `category` is raw frontmatter text, and frontmatter arrives from the
    # Drive hub / phone sync -- it is untrusted. Joining it directly let a restore
    # write outside the vault. Fall back to Uncategorized rather than raising: one
    # hostile note must not make the restore surface unusable.
    # (The FILENAME half of this path is already guarded by the caller -- do not
    # add a second check for it here.)
    try:
        dest_dir = safe_subdir(vault_root, fields.get("category") or "Uncategorized")
    except ValueError:
        dest_dir = safe_subdir(vault_root, "Uncategorized")
    category = dest_dir.name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if dest.exists():
        dest = dest_dir / f"{src.stem}.{int(time.time())}{src.suffix}"
    shutil.move(str(src), str(dest))
    return {"ok": True, "category": category, "path": str(dest)}


# ---------------------------------------------------------------------------
# Smoke test  (python trash.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        trash_dir = vault / "_trash"
        trash_dir.mkdir()
        note = trash_dir / "old.md"
        note.write_text(
            "---\ntitle: Old note\ncategory: Personal\n---\n# Old note\n\nbody.\n",
            encoding="utf-8",
        )

        # T1: list_trash reports title/category/timestamps.
        items = list_trash(vault)
        assert len(items) == 1
        assert items[0]["title"] == "Old note"
        assert items[0]["category"] == "Personal"
        assert items[0]["purge_at"] > items[0]["deleted_at"]
        print("[T1] list_trash  PASS")

        # T2: restore moves the file back to its original category folder.
        result = restore_from_trash(vault, "old.md")
        assert result["category"] == "Personal"
        assert not note.exists()
        assert (vault / "Personal" / "old.md").exists()
        assert list_trash(vault) == []
        print("[T2] restore_from_trash  PASS")

        # T3: restoring a missing file raises.
        try:
            restore_from_trash(vault, "nope.md")
            raise AssertionError("expected FileNotFoundError")
        except FileNotFoundError:
            pass
        print("[T3] restore_from_trash missing  PASS")

        # T4: purge_expired removes only files past the 30-day window (OF-16).
        import os as _os
        fresh = trash_dir / "fresh.md"
        fresh.write_text("---\ntitle: Fresh\n---\nbody\n", encoding="utf-8")
        old = trash_dir / "expired.md"
        old.write_text("---\ntitle: Expired\n---\nbody\n", encoding="utf-8")
        old_mtime = time.time() - (_PURGE_AFTER_SECONDS + 3600)
        _os.utime(old, (old_mtime, old_mtime))
        purged = purge_expired(vault)
        assert purged == ["expired.md"], purged
        assert not old.exists()
        assert fresh.exists()
        print("[T4] purge_expired  PASS")

        # T5: move_to_trash soft-moves a live note into _trash/, body byte-identical (ISS-005 A).
        cat = vault / "Personal"
        cat.mkdir(exist_ok=True)
        live = cat / "keep-me.md"
        original_bytes = (
            "---\ntitle: Keep me\ncategory: Personal\norigin: note\n---\n"
            "# Keep me\r\n\r\nSacred body with CRLF and trailing spaces.   \n"
        )
        live.write_bytes(original_bytes.encode("utf-8"))
        result = move_to_trash(vault, live)
        assert not live.exists(), "note left its category folder"
        trashed = trash_dir / result["filename"]
        assert trashed.is_file()
        # BODY-SACRED: the whole file (frontmatter + body) is byte-identical after the move.
        assert trashed.read_bytes() == original_bytes.encode("utf-8"), "move rewrote bytes"
        # And it now shows up in the Trash listing with its original category intact for restore.
        listed = [r for r in list_trash(vault) if r["filename"] == result["filename"]]
        assert listed and listed[0]["category"] == "Personal"
        print("[T5] move_to_trash body-sacred  PASS")

    print("\nAll trash.py smoke tests passed.")

"""hand_made_folders.py -- FR-34 (s146 ruling): the user-made folder census.

Contract: `Second Thought - Android App/data-model-and-contracts.md` §2.1. Desktop-only,
read-only enumeration of every folder the user made by hand inside the vault, written to
`<vault>/.sync/hand_made_folders.json` and mirrored to the hub `.sync/` folder so the phone
can render these folders read-only in BROWSE.

READ-ONLY IS THE WHOLE POINT (s146, ★★★): this module writes NOTHING into any listed
folder -- no tag, no body edit, no frontmatter, no registry entry, no move. Its only
filesystem side effect is the one census file `write_census` produces. A directory is
hand-made unless it is one of the contract's four exclusions:

  1. a registry project folder at depth 1 (`.projects.toml`, contract §13),
  2. a reserved system folder (`_loose` `_scratchpad` `_trash` `_attachments`
     `_mobile_inbox` `_templates`),
  3. any descendant of `_attachments/`,
  4. dot-prefixed.

Missing/malformed input is always zero rows, never an error -- this file must never become
a sync dependency (contract §2.1's "failure is silent, never loud").
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Tuple

import project_registry
from projects import LOOSE_DIR, note_dir_for

SCHEMA_VERSION = 1
_SYNC_DIR = ".sync"
CENSUS_FILENAME = "hand_made_folders.json"

# Contract §2.1 exclusion (2). LOOSE_DIR is imported rather than re-typed so this set can
# never drift from projects.py's own reserved-name list.
_RESERVED_FOLDERS = {LOOSE_DIR, "_scratchpad", "_trash", "_attachments", "_mobile_inbox", "_templates"}


def _registry_dirs(vault_root: Path) -> set:
    """Every depth-1 directory name the project registry claims (exclusion 1).

    Reuses `project_registry.load` (the existing reader -- no second TOML parser) and
    `projects.note_dir_for`, the SAME dir-resolution the filing path uses, so a project
    with a custom `dir` (contract §13.1) is excluded by its actual directory, not by its
    project name."""
    reg = project_registry.load(vault_root)
    return {note_dir_for(name, reg) for name in reg.get("projects", {})}


def _walk_hand_made(vault_root: Path, registry_dirs: set) -> Iterator[Tuple[str, int, int]]:
    """Yield (path, depth, note_count) for every hand-made directory, recursively, no depth
    cap. Dot-prefixed dirs and `_attachments/` are pruned from `dirnames` before `os.walk`
    descends into them, so a deep `_attachments/<id>/...` subtree costs one skip, not one
    skip per descendant."""
    for dirpath, dirnames, filenames in os.walk(vault_root):
        rel = Path(dirpath).relative_to(vault_root)
        depth = 0 if rel == Path(".") else len(rel.parts)

        # Exclusions 2+3+4 PRUNE descent, they do not merely skip a row: a reserved folder
        # that only skipped its own yield would still have `os.walk` descend and report
        # `_trash/Foo` or `_loose/Foo` at depth 2, and `_loose` may never be rendered.
        # Pruning `_attachments` here IS exclusion 3 -- no descendant survives to be yielded.
        dirnames[:] = [
            d for d in sorted(dirnames)
            if not d.startswith(".") and not (depth == 0 and d in _RESERVED_FOLDERS)
        ]

        if depth == 0:
            continue  # the vault root itself is never a folder row
        if depth == 1 and rel.parts[0] in registry_dirs:
            continue  # exclusion 1. NOT pruned: a registry project folder is not itself a row,
            # but a hand-made folder INSIDE one (`Work/Clients`) is the contract's own §2.1
            # example and is exactly what this census exists to find.

        note_count = sum(1 for f in filenames if f.endswith(".md"))
        yield "/".join(rel.parts), depth, note_count


def build_census(vault_root: Path, device_id: str) -> dict:
    """The full `hand_made_folders.json` payload (contract §2.1). Pure read -- never writes,
    never raises: a missing/non-directory `vault_root` just yields zero folders."""
    vault_root = Path(vault_root)
    folders = []
    if vault_root.is_dir():
        registry_dirs = _registry_dirs(vault_root)
        for path, depth, note_count in _walk_hand_made(vault_root, registry_dirs):
            folders.append({"path": path, "depth": depth, "note_count": note_count})
    folders.sort(key=lambda f: f["path"])
    return {
        "version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "device": device_id,
        "folders": folders,
    }


def write_census(vault_root: Path, device_id: str) -> Tuple[str, bool]:
    """Write `<vault>/.sync/hand_made_folders.json`, atomically. Returns `(path, changed)`.

    `changed` is False when the newly built `folders` array is identical to the array
    already on disk -- since `generated_at` is informational-only (contract §2.1) and would
    otherwise differ on every call, the file is left untouched (byte-identical to what was
    previously uploaded) so the sync-pass caller can skip a no-op upload."""
    vault_root = Path(vault_root)
    sync_dir = vault_root / _SYNC_DIR
    sync_dir.mkdir(parents=True, exist_ok=True)
    path = sync_dir / CENSUS_FILENAME

    census = build_census(vault_root, device_id)

    old_folders = None
    try:
        old_folders = json.loads(path.read_text(encoding="utf-8")).get("folders")
    except (OSError, ValueError, AttributeError):
        old_folders = None

    if old_folders == census["folders"]:
        return str(path), False

    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(census, f, indent=2)
    os.replace(tmp, path)
    return str(path), True


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Work" / "Clients").mkdir(parents=True)
        (vault / "Work" / "Clients" / "a.md").write_text("x", encoding="utf-8")
        (vault / "Reading").mkdir()
        (vault / "_attachments" / "note1").mkdir(parents=True)
        (vault / "_attachments" / "note1" / "img.png").write_text("x", encoding="utf-8")
        (vault / "_trash").mkdir()
        (vault / ".sync").mkdir()

        census = build_census(vault, "desktop-test")
        paths = {f["path"] for f in census["folders"]}
        assert paths == {"Work", "Work/Clients", "Reading"}, paths
        print("[T1] exclusions (reserved / _attachments / dot-prefixed) PASS")

        by_path = {f["path"]: f for f in census["folders"]}
        assert by_path["Work/Clients"]["depth"] == 2
        assert by_path["Work/Clients"]["note_count"] == 1
        assert by_path["Work"]["note_count"] == 0
        print("[T2] depth + direct-only note_count PASS")

        p1, changed1 = write_census(vault, "desktop-test")
        p2, changed2 = write_census(vault, "desktop-test")
        assert changed1 is True and changed2 is False
        print("[T3] no-op skip on unchanged census PASS")

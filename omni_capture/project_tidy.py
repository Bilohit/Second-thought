"""Derived housekeeping: move each note into the directory its tag implies.

DESKTOP ALONE RE-PATHS A FILE. The phone never moves a file and never creates a directory — that is
the load-bearing safety property of the rework, because a path change is the one operation Drive
reconcile cannot merge field-wise (contract §1.3).

Worst case with the desktop off for a week: the vault on disk is untidy while both apps read
correctly, because both read the tag. Self-healing, never wrong.

This module is the PURE planner. The applier that touches the filesystem is `apply_tidy` (Task 6).
"""
import uuid
from pathlib import Path
from typing import Dict, List, NamedTuple

from project_registry import Registry, resolve_project
from projects import note_dir_for


class NoteLoc(NamedTuple):
    path: Path
    body: str


class Move(NamedTuple):
    src: Path
    dst: Path


def plan_tidy(entries: List[NoteLoc], vault_root: Path, reg: Registry) -> List[Move]:
    """Every note's target is `vault_root / note_dir_for(resolve_project(body, reg))` — a project
    directory, or `_loose/`. Notes already in place are not moved."""
    vault_root = Path(vault_root)
    taken: Dict[Path, int] = {}
    for entry in entries:
        taken[entry.path] = taken.get(entry.path, 0) + 1

    moves: List[Move] = []
    for entry in entries:
        target_dir = vault_root / note_dir_for(resolve_project(entry.body, reg))
        dst = target_dir / entry.path.name
        if dst == entry.path:
            continue
        if dst in taken:
            # Never clobber. Mirrors _unique_file_path's 6-char suffix convention
            # (storage_engine.py:525).
            dst = dst.with_name(f"{dst.stem}-{uuid.uuid4().hex[:6]}{dst.suffix}")
        taken[dst] = taken.get(dst, 0) + 1
        moves.append(Move(entry.path, dst))
    return moves

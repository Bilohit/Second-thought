"""Derived housekeeping: move each note into the directory its tag implies.

DESKTOP ALONE RE-PATHS A FILE. The phone never moves a file and never creates a directory — that is
the load-bearing safety property of the rework, because a path change is the one operation Drive
reconcile cannot merge field-wise (contract §1.3).

Worst case with the desktop off for a week: the vault on disk is untidy while both apps read
correctly, because both read the tag. Self-healing, never wrong.

This module is the PURE planner. The applier that touches the filesystem is `apply_tidy` (Task 6).
"""
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, List, NamedTuple

from dedup import _vault_lock
from project_registry import Registry, resolve_project
from projects import LOOSE_DIR, note_dir_for


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


class TidyResult(NamedTuple):
    moved: int
    skipped: int
    removed_dirs: int


def _tidy_lock_path(vault_root: Path) -> Path:
    # Vault-root sidecar, same convention as merge.py's _merge_lock_path (dedup.py itself keeps
    # its own lock inside .omni_capture/, colocated with dedup_index.json). `dedup._vault_lock` is
    # a generic FileLock factory keyed to whatever lock path its caller supplies (dedup.py:52) —
    # it is not vault-root-specific despite the name, so each module defining a lock path for its
    # own read-modify-write cycle is the existing pattern, not a new one.
    return vault_root / ".tidy.lock"


def apply_tidy(vault_root: Path, moves: List[Move]) -> TidyResult:
    """Apply planned moves. Serialized under the shared vault write lock (contract §13.2 as
    corrected in v3.1 — v3.0 named `_LEDGER_FILES`, which is a category->filename map with no lock).

    NEVER edits file content: this moves files and nothing else. `os.replace` is atomic on the same
    volume; a destination that already exists is SKIPPED, never clobbered, mirroring
    `mobile_sync_agent._maybe_refile_local` (mobile_sync_agent.py:686).
    """
    vault_root = Path(vault_root)
    moved = skipped = 0
    source_dirs: set = set()
    applied: List[Move] = []

    with _vault_lock(_tidy_lock_path(vault_root)):
        for move in moves:
            if not move.src.exists() or move.dst.exists():
                skipped += 1
                continue
            move.dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(move.src, move.dst)
            except OSError:
                # ponytail: one move held open by another writer (e.g. mid-append) aborts only
                # itself, not the whole pass -- tidy is idempotent housekeeping, and the worst
                # case is already contract-accepted: "the vault on disk is untidy while both
                # apps read correctly, self-healing, never wrong" (data-model §1.3). The next
                # tidy pass retries this move. Upgrade path if that's ever not good enough:
                # take `.merge.lock` too, so tidy wins the race instead of retrying.
                skipped += 1
                continue
            source_dirs.add(move.src.parent)
            moved += 1
            applied.append(move)

        removed_dirs = 0
        for directory in source_dirs:
            if directory.name == LOOSE_DIR or directory == vault_root:
                continue
            try:
                directory.rmdir()          # only succeeds when empty
                removed_dirs += 1
            except OSError:
                pass

    # FR-26: captures.db / vectors.db each still hold a row keyed on the OLD path for every
    # note that just moved -- a pure filesystem move re-syncs neither on its own. Same defect
    # class as trash.move_to_trash (trash.py:121), same idiom: best-effort, non-fatal, and run
    # only after the file is already safely on disk so an index failure can never roll back or
    # block the move. Unlike trash (one file per call), a tidy pass moves a whole plan at once,
    # so this is one batched reconcile pass over every note that actually moved -- done here,
    # outside `_vault_lock`, rather than interleaved into the move loop above, so a slow or
    # failing index write never extends the lock hold or gets confused with a move failure.
    if applied:
        _sync_index_after_moves(vault_root, applied)

    return TidyResult(moved, skipped, removed_dirs)


def _sync_index_after_moves(vault_root: Path, applied: List[Move]) -> None:
    """Best-effort captures.db/vectors.db cleanup for a batch of already-applied moves.

    Mirrors trash.move_to_trash's index cleanup (trash.py:128-134): the vault file has already
    moved (the source of truth), so nothing here may raise past this function -- every DB op is
    caught individually and just logged, exactly like trash.py's own `except Exception`.
    """
    try:
        from index_writer import remove_capture_by_path, upsert_capture_from_file
        from vector_store import remove_from_index
    except Exception as exc:
        print(f"[ProjectTidy] index modules unavailable: {exc}", file=sys.stderr)
        return

    for move in applied:
        try:
            remove_capture_by_path(vault_root, move.src)
            upsert_capture_from_file(vault_root, move.dst)
            # ponytail: vectors.db is dropped, not re-embedded here -- re-embedding needs the
            # Ollama base_url/model config, which project_tidy.py has no business importing
            # (same division of labor trash.py's restore_from_trash draws for the identical
            # reason, trash.py:234-237). A stale vector row would keep semantic search
            # pointing at a dead path; dropping it now is strictly safer than that, and the
            # note is re-embedded on the next full vault reindex.
            remove_from_index(vault_root, move.src)
        except Exception as exc:
            print(f"[ProjectTidy] index cleanup for {move.dst} error: {exc}", file=sys.stderr)

"""
vault_sync.py — Vault index diff-sync.

Public API
----------
sync_vault_indexes(vault_root, base_url, embed_model) -> SyncResult
    Walk vault .md files; remove orphan index rows; add/update changed files.

purge_orphan_index_entries(vault_root) -> int
    Exists-check only (no Ollama). Safe to call on every startup.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, TypedDict

from index_writer import (
    init_db, _file_hash, heal_corrupt_db, remove_capture_by_path, upsert_capture_from_file,
)
from vector_store import _connect, index_note, remove_from_index

_SKIP_DIRS = {".omni_capture", ".git", ".obsidian"}


def _iter_vault_md(vault_root: Path):
    for p in vault_root.rglob("*.md"):
        if any(part.startswith(".") or part in _SKIP_DIRS for part in p.parts[len(vault_root.parts):]):
            continue
        yield p


class SyncResult(TypedDict):
    added: int
    removed: int
    updated: int
    skipped: int
    healed: bool          # a corrupt captures.db was discarded and rebuilt from files
    dedup_rebuilt: bool   # a missing/empty dedup ledger was rebuilt from the vault files (R-1)
    error: Optional[str]  # the pass did NOT complete; counts below are partial


def purge_orphan_index_entries(vault_root: Path) -> int:
    """Delete captures/embedding rows whose file no longer exists on disk. No Ollama.

    # ponytail: provisional=1 rows (LAN overlay, contract §11) use a synthetic
    # path/id that never resolves to a real vault file by design -- their
    # lifecycle is owned by clear_provisional/supersede + the TTL sweep, not
    # this file-existence orphan sweep. Excluded here so this sweep never
    # deletes a still-valid provisional row out from under the overlay.
    """
    removed = 0
    try:
        conn = init_db(vault_root)
        rows = conn.execute("SELECT path FROM captures WHERE provisional = 0").fetchall()
        conn.close()
        for row in rows:
            p = Path(row["path"])
            if not p.exists():
                remove_capture_by_path(vault_root, p)
                remove_from_index(vault_root, p)
                removed += 1
        # Embedding rows can outlive their captures row (interrupted purge,
        # out-of-band DB edit). Same parent-aware exists-check as
        # sync_vault_indexes: chunk ids "<parent>::c<i>" resolve to the
        # parent file. Fetched AFTER the captures pass so rows it already
        # removed are not double-counted. Still no Ollama involved.
        with _connect(vault_root) as conn:
            emb_ids = {
                r[0] for r in conn.execute(
                    "SELECT id FROM embeddings WHERE provisional = 0"
                ).fetchall()
            }
        for parent_rel in {i.split("::c")[0] for i in emb_ids}:
            if not (vault_root / parent_rel).exists():
                remove_from_index(vault_root, vault_root / parent_rel)
                removed += 1
    except Exception as exc:
        print(f"[VaultSync] purge_orphan_index_entries error: {exc}", file=sys.stderr)
    return removed


def sync_vault_indexes(vault_root: Path, base_url: str, embed_model: str) -> SyncResult:
    """Full diff-sync: heal a corrupt index, remove orphans, add/update changed files."""
    result: SyncResult = {"added": 0, "removed": 0, "updated": 0, "skipped": 0,
                          "healed": False, "dedup_rebuilt": False, "error": None}
    try:
        # --- heal a corrupt captures.db BEFORE anything reads it ---
        # It is a derived cache; an unreadable one is discarded here so the
        # add/update pass below re-creates it from the vault files. Without this
        # the DatabaseError fell into the blanket `except` at the bottom and this
        # function returned {"added": 0} -- indistinguishable from "nothing to do"
        # -- while the index stayed dead until a human deleted the file.
        result["healed"] = heal_corrupt_db(vault_root)

        # --- rebuild a missing/empty dedup ledger (R-1 finisher) ---
        # The ledger is a derived cache like the two DBs around it, but it was the only one with
        # no automatic recovery: rebuild_dedup_index() existed and nothing called it. A user who
        # reindexes to fix their stores reasonably expects ALL derived stores healed, not two of
        # three. Missing/empty only -- the policy (and why it must never run over a live ledger)
        # lives in dedup.rebuild_dedup_index_if_missing. Best-effort: a failed ledger rebuild must
        # never abort the captures/vectors sync below.
        try:
            from dedup import rebuild_dedup_index_if_missing
            if rebuild_dedup_index_if_missing(vault_root) is not None:
                result["dedup_rebuilt"] = True
        except Exception as exc:
            print(f"[VaultSync] dedup ledger rebuild skipped: {exc}", file=sys.stderr)

        # --- purge orphans (captures table) ---
        # ponytail: provisional=1 rows are excluded — their synthetic path never
        # appears on disk by design (LAN overlay, contract §11); they are
        # cleared by clear_provisional/supersede + the TTL sweep, not this diff.
        conn = init_db(vault_root)
        indexed_paths = {
            row["path"] for row in
            conn.execute("SELECT path FROM captures WHERE provisional = 0").fetchall()
        }
        conn.close()

        disk_paths = {str(p) for p in _iter_vault_md(vault_root)}

        for ap in indexed_paths - disk_paths:
            remove_capture_by_path(vault_root, Path(ap))
            remove_from_index(vault_root, Path(ap))
            result["removed"] += 1

        # --- purge orphans (embeddings only, not in captures) ---
        try:
            with _connect(vault_root) as conn:
                emb_ids = {
                    row[0] for row in
                    conn.execute("SELECT id FROM embeddings WHERE provisional = 0").fetchall()
                }
            # Chunk rows are keyed "<parent>::c<i>". Existence must be checked
            # against the PARENT file -- checking the raw chunk id never
            # matches a real path, which wrongly purged every chunked note's
            # embeddings on each sync (and they were never re-added, because
            # the unchanged captures.hash routed the file to "skipped").
            for parent_rel in {i.split("::c")[0] for i in emb_ids}:
                abs_p = vault_root / parent_rel
                if not abs_p.exists():
                    remove_from_index(vault_root, abs_p)
                    result["removed"] += 1
        except Exception as exc:
            print(f"[VaultSync] embedding orphan purge error: {exc}", file=sys.stderr)

        # --- add / update ---
        conn = init_db(vault_root)
        hash_map = {
            row["path"]: row["hash"]
            for row in conn.execute("SELECT path, hash FROM captures").fetchall()
        }
        conn.close()

        for p in _iter_vault_md(vault_root):
            ap = str(p)
            current_hash = _file_hash(ap)
            stored_hash  = hash_map.get(ap)

            if ap not in hash_map:
                # new file — upsert into captures + embed
                upsert_capture_from_file(vault_root, p)
                _embed_file(vault_root, p, base_url, embed_model)
                result["added"] += 1
            elif current_hash != stored_hash:
                # changed — re-upsert + re-embed
                upsert_capture_from_file(vault_root, p)
                _embed_file(vault_root, p, base_url, embed_model)
                result["updated"] += 1
            else:
                result["skipped"] += 1

    except Exception as exc:
        # Still fail-soft (a broken index must never break capture), but the caller
        # is told the pass aborted instead of reading the zeroed counts as success.
        print(f"[VaultSync] sync_vault_indexes error: {exc}", file=sys.stderr)
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def _embed_file(vault_root: Path, p: Path, base_url: str, embed_model: str) -> None:
    try:
        content = p.read_text(encoding="utf-8", errors="ignore")
        if content.strip():
            index_note(vault_root, p, content, base_url, embed_model)
    except Exception as exc:
        print(f"[VaultSync] embed error {p}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    print("vault_sync: module import OK")

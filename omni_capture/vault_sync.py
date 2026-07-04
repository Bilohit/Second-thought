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
from typing import TypedDict

from index_writer import (
    init_db, _file_hash, remove_capture_by_path, upsert_capture_from_file,
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


def purge_orphan_index_entries(vault_root: Path) -> int:
    """Delete captures/embedding rows whose file no longer exists on disk. No Ollama."""
    removed = 0
    try:
        conn = init_db(vault_root)
        rows = conn.execute("SELECT path FROM captures").fetchall()
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
            emb_ids = {r[0] for r in conn.execute("SELECT id FROM embeddings").fetchall()}
        for parent_rel in {i.split("::c")[0] for i in emb_ids}:
            if not (vault_root / parent_rel).exists():
                remove_from_index(vault_root, vault_root / parent_rel)
                removed += 1
    except Exception as exc:
        print(f"[VaultSync] purge_orphan_index_entries error: {exc}", file=sys.stderr)
    return removed


def sync_vault_indexes(vault_root: Path, base_url: str, embed_model: str) -> SyncResult:
    """Full diff-sync: remove orphans, add/update changed files."""
    result: SyncResult = {"added": 0, "removed": 0, "updated": 0, "skipped": 0}
    try:
        # --- purge orphans (captures table) ---
        conn = init_db(vault_root)
        indexed_paths = {row["path"] for row in conn.execute("SELECT path FROM captures").fetchall()}
        conn.close()

        disk_paths = {str(p) for p in _iter_vault_md(vault_root)}

        for ap in indexed_paths - disk_paths:
            remove_capture_by_path(vault_root, Path(ap))
            remove_from_index(vault_root, Path(ap))
            result["removed"] += 1

        # --- purge orphans (embeddings only, not in captures) ---
        try:
            with _connect(vault_root) as conn:
                emb_ids = {row[0] for row in conn.execute("SELECT id FROM embeddings").fetchall()}
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
        print(f"[VaultSync] sync_vault_indexes error: {exc}", file=sys.stderr)

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

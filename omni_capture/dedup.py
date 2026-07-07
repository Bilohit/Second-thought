"""
dedup.py -- content-hash deduplication index for the vault.

Extracted from storage_engine.py (see docs/ROADMAP.md "Split storage_engine.py
into dedup.py / merge.py / scratchpad.py"). Owns the on-disk dedup index
(.omni_capture/dedup_index.json) and the content-hashing rules used to decide
whether a capture is a duplicate of something already in the vault.

Files are the source of truth (see CLAUDE.md hard rules) -- this index is a
derived cache in front of the vault's .md files, never authoritative over
them. storage_engine.write_to_vault() already re-validates a dedup hit against
the file's actual current category before trusting it.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Optional

from filelock import FileLock

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# JSON index for deduplication (relative to vault root)
_DEDUP_INDEX_NAME = ".omni_capture/dedup_index.json"


# ---------------------------------------------------------------------------
# File locking helper (shared by the dedup-index and merge-append RMW cycles
# -- two concurrent captures landing close together must not silently clobber
# each other's read-modify-write). merge.py imports this rather than
# duplicating it, since both cycles need the exact same semantics.
# ---------------------------------------------------------------------------

def _vault_lock(lock_path: Path, timeout: float = 10.0) -> FileLock:
    """Return a FileLock keyed to lock_path, creating its parent dir if needed.

    Callers must hold this lock for the *entire* read-modify-write cycle they
    are protecting (acquire before the read, release after the write) -- a
    lock around just the load or just the save call does not close the race.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(lock_path), timeout=timeout)


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def _dedup_index_path(vault_root: Path) -> Path:
    return vault_root / _DEDUP_INDEX_NAME


def _dedup_lock_path(vault_root: Path) -> Path:
    # Sidecar next to dedup_index.json (inside .omni_capture/), not the vault root.
    return _dedup_index_path(vault_root).parent / ".dedup.lock"


def _load_dedup_index(vault_root: Path) -> dict:
    p = _dedup_index_path(vault_root)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_dedup_index(vault_root: Path, index: dict) -> None:
    p = _dedup_index_path(vault_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_url(url: str) -> str:
    import urllib.parse as _up
    try:
        p = _up.urlparse(url.strip())
        netloc = p.netloc.lower()
        path = p.path.rstrip("/")
        params = "&".join(sorted(p.query.split("&"))) if p.query else ""
        return _up.urlunparse((p.scheme.lower(), netloc, path, p.params, params, ""))
    except Exception:
        return url.strip().lower()


def _normalize_content(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _content_hash(text: str, source_url: Optional[str] = None) -> str:
    norm_text = _normalize_content(text)[:2000]
    # Blank/whitespace-only content (and no URL) would otherwise hash to a single
    # constant key, causing every empty capture to be treated as a duplicate of
    # the first one ever stored. Give such captures a unique, never-matching key.
    if not norm_text and not source_url:
        return "blank-" + uuid.uuid4().hex[:26]
    if source_url:
        raw = _normalize_url(source_url) + "::" + norm_text
    else:
        raw = norm_text
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]


def check_duplicate(
    text: str,
    source_url: Optional[str],
    vault_root: Path,
) -> Optional[str]:
    """Return vault-relative path of existing note if content is a duplicate."""
    h = _content_hash(text, source_url)
    idx = _load_dedup_index(vault_root)
    return idx.get(h)


def register_in_dedup_index(
    text: str,
    source_url: Optional[str],
    vault_root: Path,
    note_path: Path,
) -> None:
    h = _content_hash(text, source_url)
    try:
        rel = str(note_path.relative_to(vault_root))
    except ValueError:
        rel = str(note_path)
    # Whole read-modify-write cycle held under one lock -- two captures
    # registering close together must not last-write-wins each other's entry.
    with _vault_lock(_dedup_lock_path(vault_root)):
        idx = _load_dedup_index(vault_root)
        idx[h] = rel
        _save_dedup_index(vault_root, idx)


# ---------------------------------------------------------------------------
# Smoke test  (python dedup.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)

        # T1: blank content never collides with another blank capture.
        h1 = _content_hash("   ", None)
        h2 = _content_hash("", None)
        assert h1 != h2
        assert h1.startswith("blank-") and h2.startswith("blank-")
        print("[T1] _content_hash blank-content uniqueness  PASS")

        # T2: same text + same URL (modulo whitespace/query-order) hashes identically.
        h3 = _content_hash("Hello   world", "https://example.com/a?b=2&a=1")
        h4 = _content_hash("hello world", "https://example.com/a?a=1&b=2")
        assert h3 == h4
        print("[T2] _content_hash normalization  PASS")

        # T3: check_duplicate is None until registered, then resolves after.
        note_dir = vault / "Journal"
        note_dir.mkdir(parents=True)
        note = note_dir / "a.md"
        note.write_text("hello", encoding="utf-8")
        assert check_duplicate("some unique text", None, vault) is None
        register_in_dedup_index("some unique text", None, vault, note)
        assert check_duplicate("some unique text", None, vault) == str(note.relative_to(vault))
        print("[T3] check_duplicate / register_in_dedup_index round-trip  PASS")

        # T4: _dedup_lock_path lives alongside the index file, not at vault root.
        assert _dedup_lock_path(vault).parent == _dedup_index_path(vault).parent
        print("[T4] _dedup_lock_path colocated with index  PASS")

    print("\nAll dedup.py smoke tests passed.")

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

Derived AND rebuildable (finding R-1, data-model-and-contracts.md §1.1): the
key is hashed over the pipeline's PRE-write text, which no vault scan can
recompute -- disk bytes have been through wikilink injection, post-processing
and frontmatter by then, and _LEDGER_FILES/smart-merge collapse N captures into
1 file. So the key is PERSISTED into each note's `capture_keys` frontmatter at
register time, and rebuild_dedup_index() reconstructs the whole index from the
vault alone. capture_keys is always a LIST -- a merged ledger file carries all
N of its captures' keys. Captures predating §1.1 carry none and are skipped by
a rebuild (partial, refills by use); backfill_capture_keys() closes that gap
from the existing index.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Optional

from atomic_io import atomic_write_text, atomic_write_verbatim
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
        except Exception as e:
            # SYNC-18: the swallow STAYS -- dedup_index.json is a documented rebuildable
            # cache and a capture must not fail because it is unreadable. But it is now
            # LOUD: silently returning {} made a torn or corrupt index look like a fresh
            # one, so the resulting partial rebuild was invisible.
            print(f"[dedup] WARNING: dedup index unreadable ({type(e).__name__}), "
                  f"treating as EMPTY -- duplicates may be re-filed until "
                  f"rebuild_dedup_index() runs: {p}")
            return {}
    return {}


def _save_dedup_index(vault_root: Path, index: dict) -> None:
    # SYNC-18: atomic (temp sibling + os.replace). A bare write_text truncates and
    # streams, so a crash mid-write left a torn JSON file that _load_dedup_index then
    # read as an empty index.
    p = _dedup_index_path(vault_root)
    atomic_write_text(p, json.dumps(index, indent=2, ensure_ascii=False))


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


def content_hash(text: str, source_url: Optional[str] = None) -> str:
    """The dedup identity of a capture.

    Public because storage_engine must compute this ONCE at write time and
    persist it into the note's `capture_keys` frontmatter (data-model §1.1) --
    the hash is taken over the pipeline's PRE-write text, which disk never
    sees, so a vault scan cannot recompute it. Persisting it is what makes the
    ledger rebuildable (finding R-1).
    """
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


# Back-compat alias: this was module-private before R-1 made it a written contract.
_content_hash = content_hash


# ---------------------------------------------------------------------------
# capture_keys frontmatter -- the ledger's source of truth (data-model §1.1)
#
# The index maps key -> note path. Both halves of the key's input are lost by
# the time content reaches disk (the text is rewritten by wikilink injection +
# post-processing), and _LEDGER_FILES/smart-merge collapse N captures into 1
# file -- so the key is persisted into the file rather than recomputed from it.
# ALWAYS a list: one merged ledger file legitimately carries N keys.
# ---------------------------------------------------------------------------

# Frontmatter block at the very start of the file. Group 1 is the interior; the
# body is everything past the match, and every edit here splices ONLY group 1
# back, so body bytes are returned untouched (body-sacred lock).
_FM_BLOCK_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_CAPTURE_KEYS_RE = re.compile(r"^capture_keys:[ \t]*\[(.*?)\][ \t]*$", re.MULTILINE)


def parse_capture_keys(raw_note: str) -> list:
    """Keys carried by a note's frontmatter; [] when absent or malformed."""
    m = _FM_BLOCK_RE.match(raw_note)
    if not m:
        return []
    line = _CAPTURE_KEYS_RE.search(m.group(1))
    if not line:
        return []
    return [k.strip().strip("\"'") for k in line.group(1).split(",") if k.strip()]


def inject_capture_keys(raw_note: str, keys) -> Optional[str]:
    """Return raw_note with capture_keys set to union(existing, keys).

    Frontmatter-only: the body below the closing `---` is spliced back byte-for-
    byte, never reformatted. Returns None when there is no frontmatter block to
    inject into, or when the union changes nothing (so callers never rewrite a
    file for a no-op).
    """
    m = _FM_BLOCK_RE.match(raw_note)
    if not m:
        return None
    fm = m.group(1)
    existing = parse_capture_keys(raw_note)
    merged = list(dict.fromkeys(existing + list(keys)))  # union, order-stable
    if merged == existing:
        return None
    new_line = "capture_keys: [" + ", ".join(merged) + "]"
    found = _CAPTURE_KEYS_RE.search(fm)
    new_fm = (fm[: found.start()] + new_line + fm[found.end():]) if found else (fm + "\n" + new_line)
    return raw_note[: m.start(1)] + new_fm + raw_note[m.end(1):]


def _is_vault_note(p: Path) -> bool:
    # Skip machine dirs (.omni_capture/, .sync/) and soft-deleted notes.
    return not any(part.startswith(".") or part == "_trash" for part in p.parts)


def rebuild_dedup_index(vault_root: Path) -> int:
    """Rebuild dedup_index.json from the vault's .md files. Returns key count.

    This is what makes the workspace lock ("every ... dedup ledger is a derived,
    rebuildable cache") literally true. Captures written before §1.1 carry no
    capture_keys and are skipped -- the result is a PARTIAL index that refills
    by use, never a wrong one. An unreadable file is skipped, never fatal: a
    rebuild must always terminate with a usable index.
    """
    idx: dict = {}
    for p in sorted(vault_root.rglob("*.md")):
        rel_parts = p.relative_to(vault_root)
        if not _is_vault_note(rel_parts):
            continue
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for k in parse_capture_keys(raw):
            idx[k] = str(rel_parts)
    with _vault_lock(_dedup_lock_path(vault_root)):
        _save_dedup_index(vault_root, idx)
    return len(idx)


def rebuild_dedup_index_if_missing(vault_root: Path) -> Optional[int]:
    """Rebuild the ledger ONLY when it is missing or empty. Returns the key count, or None if an
    intact ledger was left alone.

    R-1's remaining half: rebuild_dedup_index() existed and worked, but nothing ever called it, so
    the ledger was rebuildable in theory and lost in practice. This is the policy in one place --
    both callers (the boot task and the diff-sync reindex) share it rather than each re-deciding.

    Missing/empty only, for two independent reasons:
      * cost -- the rebuild is a full vault rglob; paying it on every boot to re-derive a ledger
        that is almost always intact is waste.
      * correctness -- a populated ledger is AUTHORITATIVE over the scan. Captures written before
        contract §1.1 carry no capture_keys, so a rebuild is partial by construction (see
        rebuild_dedup_index) and would silently DROP their keys. Never rebuild over live data.

    An empty dict is indistinguishable from a lost ledger, and rebuilding it is idempotent, so both
    take the same branch.
    """
    if _load_dedup_index(vault_root):
        return None
    return rebuild_dedup_index(vault_root)


def backfill_capture_keys(vault_root: Path, dry_run: bool = True) -> dict:
    """One-time migration: push today's dedup_index.json mapping INTO the files.

    The live index already holds key -> path for every capture written before
    §1.1; writing those keys into the notes' frontmatter closes R-1 for legacy
    data instead of only going forward. Idempotent (union), frontmatter-only,
    body byte-identical.

    dry_run defaults to True ON PURPOSE: this touches real user notes, so the
    caller must ask for the write explicitly after reading the plan.
    """
    idx = _load_dedup_index(vault_root)
    by_file: dict = {}
    for h, rel in idx.items():
        by_file.setdefault(rel, []).append(h)

    changed, skipped = [], []
    for rel, keys in sorted(by_file.items()):
        p = vault_root / rel
        if not p.exists():
            skipped.append((rel, "missing from vault"))
            continue
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception as e:
            skipped.append((rel, f"unreadable: {e}"))
            continue
        out = inject_capture_keys(raw, sorted(keys))
        if out is None:
            skipped.append((rel, "no frontmatter, or already current"))
            continue
        changed.append((rel, sorted(keys)))
        if not dry_run:
            p.write_text(out, encoding="utf-8")
    return {"changed": changed, "skipped": skipped, "dry_run": dry_run}


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
    """Record this capture's dedup key -- in the note AND in the index.

    Every caller in storage_engine writes the note first and registers after, so
    note_path exists here. Persisting the key into the file is what demotes
    dedup_index.json to a genuinely rebuildable cache (data-model §1.1, R-1);
    doing it here rather than in _build_frontmatter covers all three write paths
    (scratchpad / voice / normal+merge) at the single point they route through.
    """
    h = content_hash(text, source_url)
    try:
        rel = str(note_path.relative_to(vault_root))
    except ValueError:
        rel = str(note_path)
    # Whole read-modify-write cycle held under one lock -- two captures
    # registering close together must not last-write-wins each other's entry.
    # The note's capture_keys RMW rides the same lock: a ledger file (N captures
    # -> 1 file) is appended to by concurrent captures, and a union computed
    # outside the lock would drop keys the same way.
    with _vault_lock(_dedup_lock_path(vault_root)):
        idx = _load_dedup_index(vault_root)
        idx[h] = rel
        _save_dedup_index(vault_root, idx)
        # Frontmatter-only: inject_capture_keys splices the body back byte-for-
        # byte. Non-fatal but LOUD -- a capture must not fail because its note
        # could not be re-read, yet a silent miss here would quietly cost this
        # note its rebuildability, which is exactly the R-1 defect returning.
        try:
            # SYNC-07: newline="" on BOTH ends. inject_capture_keys splices the body back
            # byte-for-byte, but the default universal-newline mode translated CRLF->LF on
            # read and LF->os.linesep on write, so every dedup registration silently
            # rewrote the whole body's line endings on Windows. Atomic for the same reason
            # as every other note write: a torn body must be impossible.
            out = inject_capture_keys(note_path.read_text(encoding="utf-8", newline=""), [h])
            if out is not None:
                atomic_write_verbatim(note_path, out)
        except Exception as e:
            print(f"[dedup] WARNING: capture_keys not persisted to {rel}: {e!r} "
                  f"-- index entry is intact, but this note will be skipped by "
                  f"rebuild_dedup_index() until backfill_capture_keys() runs.")


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

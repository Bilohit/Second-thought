"""
merge.py -- smart-merge/topic-collision logic for the vault.

Extracted from storage_engine.py (see docs/ROADMAP.md "Split storage_engine.py
into dedup.py / merge.py / scratchpad.py"). Owns the decision of whether a new
capture should be appended into an existing same-topic note (find_merge_target,
_is_same_topic) and the mechanics of that append (_append_general).

`_category_str` / `_signals_to_tags` are shared low-level helpers that also
back storage_engine._build_frontmatter; they stay defined in storage_engine.py
and are imported here lazily (inside each function) to avoid a circular
import, since storage_engine.py imports find_merge_target/_is_same_topic/
_append_general from this module at top level.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dedup import _vault_lock

# ---------------------------------------------------------------------------
# Merge thresholds (unchanged from original storage_engine.py)
# ---------------------------------------------------------------------------
MERGE_MIN_SHARED_TAGS: int = 2
MERGE_MIN_TAG_JACCARD: float = 0.5
MERGE_SEMANTIC_THRESHOLD: float = 0.85


def _merge_lock_path(vault_root: Path) -> Path:
    return vault_root / ".merge.lock"


def _append_general(path: Path, new_content: str, vault_root: Path) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    sep = f"\n\n---\n*Captured: {ts}*\n\n"
    # ponytail: one vault-wide merge lock (not per-target-file) held only for
    # this short read-then-write -- keeps lock granularity narrow (an append
    # is fast, so unrelated captures still barely serialize) without the
    # bookkeeping of a lock-file-per-target. Revisit with per-file locks only
    # if a vault sees enough concurrent merge-append traffic to contend here.
    with _vault_lock(_merge_lock_path(vault_root)):
        existing = path.read_text(encoding="utf-8")
        path.write_text(existing.rstrip() + sep + new_content + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Topic-collision guard
# ---------------------------------------------------------------------------

def _read_note_tags(path: Path) -> set:
    """Extract frontmatter tags from a note (lower-cased)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()

    tags: set = set()

    # Inline form
    import re
    inline = re.search(r"^tags:[ \t]*(.+)$", text, re.MULTILINE)
    if inline:
        raw = inline.group(1).strip().strip("[]")
        tags.update(
            t.strip().strip("'\"").lower()
            for t in raw.split(",") if t.strip()
        )

    # Block form
    for t in re.findall(r"^[ \t]*-[ \t]+(.+)$", text[:1000], re.MULTILINE):
        tags.add(t.strip().strip("'\"").lower())

    return {t for t in tags if t and not t.startswith("-")}


def _is_synced_note(path: Path) -> bool:
    """
    True if `path` is a synced NOTE (origin: note, or carries an `id:` — a phone/desktop note whose
    body is sacred), as opposed to a pipeline capture. B-1: such a file must NEVER be a smart-merge
    append target. A phone note filed under a category folder shares tags with same-topic captures;
    appending a capture below its frontmatter is a body-sacred violation, and the next sync pass reads
    the appended bytes as a local body edit. Only the leading frontmatter block is inspected.
    """
    import re
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    fm = m.group(1) if m else text[:500]
    if re.search(r"^origin:[ \t]*note[ \t]*$", fm, re.MULTILINE):
        return True
    if re.search(r"^id:[ \t]*\S", fm, re.MULTILINE):
        return True
    return False


def _is_same_topic(existing_path: Path, new_signals: List[str], min_shared_tags: int = 1) -> bool:
    """
    min_shared_tags raises the bar above the default single-shared-tag match.
    Used for image captures: a vision description sharing exactly one tag
    with an unrelated note (e.g. both happen to mention "ollama") is too
    weak a signal to silently append a photo into that note.
    """
    if not existing_path.exists() or not new_signals:
        return True
    # B-1: never append a capture into a synced note's body (body-sacred). Not "same topic" for merge.
    if _is_synced_note(existing_path):
        return False
    existing_tags = _read_note_tags(existing_path)
    if not existing_tags:
        return True
    from storage_engine import _signals_to_tags
    normalised_new = set(_signals_to_tags(new_signals))
    return len(existing_tags & normalised_new) >= min_shared_tags


# ---------------------------------------------------------------------------
# Smart context-aware merge-target finder
# ---------------------------------------------------------------------------

def find_merge_target(
    output,
    vault_root: Path,
    enable_semantic_merge: bool = False,
    embed_base_url: Optional[str] = None,
    embed_model: str = "nomic-embed-text",
) -> Optional[Path]:
    """
    Locate an existing note in the capture's category that this content
    should be merged into, even when the LLM proposes a different filename.
    Returns None to create a new file.
    """
    from storage_engine import _category_str, _signals_to_tags

    cat = _category_str(output)
    new_tags = set(_signals_to_tags(output.key_signals))
    if not new_tags:
        return None

    cat_dir = vault_root / cat
    if not cat_dir.exists():
        return None

    candidates = [
        f for f in cat_dir.iterdir()
        # B-1: exclude synced notes (origin: note / id:) — a capture must never merge into a note body.
        if f.is_file() and f.suffix == ".md" and not _is_synced_note(f)
    ]
    if not candidates:
        return None

    semantic: dict = {}
    if enable_semantic_merge and embed_base_url:
        try:
            from vector_store import best_match
            match = best_match(
                vault_root, output.markdown_content,
                embed_base_url, embed_model, category=cat,
            )
            if match:
                rel, sim = match
                semantic[Path(rel).name] = sim
        except Exception as exc:
            print(f"[StorageEngine] semantic merge skipped: {exc}", flush=True)

    best_path: Optional[Path] = None
    best_score = 0.0

    for cand in candidates:
        cand_tags = _read_note_tags(cand)
        if not cand_tags:
            continue
        shared = new_tags & cand_tags
        if not shared:
            continue
        union = new_tags | cand_tags
        jaccard = len(shared) / len(union) if union else 0.0
        sim = semantic.get(cand.name, 0.0)

        strong_tag_match = (
            len(shared) >= MERGE_MIN_SHARED_TAGS and jaccard >= MERGE_MIN_TAG_JACCARD
        )
        semantic_confirmed = (
            len(shared) >= 1 and sim >= MERGE_SEMANTIC_THRESHOLD
        )
        if not (strong_tag_match or semantic_confirmed):
            continue

        score = jaccard + sim
        if score > best_score:
            best_score = score
            best_path = cand

    if best_path is not None:
        print(
            f"[StorageEngine] smart-merge target found: {best_path.name} "
            f"(score={round(best_score, 3)})",
            flush=True,
        )
    return best_path


# ---------------------------------------------------------------------------
# Smoke test  (python merge.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile
    from models import CaptureOutput

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)

        # T1: find_merge_target returns None when the category dir doesn't exist.
        out = CaptureOutput(
            category="Tech_Notes", suggested_filename="asyncio-notes",
            markdown_content="notes", key_signals=["python"], confidence=0.9,
            requires_new_category=False,
        )
        assert find_merge_target(out, vault) is None
        print("[T1] find_merge_target (no category dir)  PASS")

        # T2: find_merge_target returns None when no candidate shares a tag.
        cat_dir = vault / "Tech_Notes"
        cat_dir.mkdir()
        unrelated = cat_dir / "unrelated.md"
        unrelated.write_text("---\ntags:\n  - cooking\n---\n\nBody.\n", encoding="utf-8")
        assert find_merge_target(out, vault) is None
        print("[T2] find_merge_target (no shared tags)  PASS")

        # T3: find_merge_target matches on strong tag overlap (Jaccard + shared count).
        match_note = cat_dir / "python-notes.md"
        match_note.write_text("---\ntags:\n  - python\n  - async\n---\n\nBody.\n", encoding="utf-8")
        out2 = CaptureOutput(
            category="Tech_Notes", suggested_filename="more-notes",
            markdown_content="notes", key_signals=["python", "async"], confidence=0.9,
            requires_new_category=False,
        )
        target = find_merge_target(out2, vault)
        assert target == match_note, target
        print("[T3] find_merge_target (strong tag match)  PASS")

        # T4: _is_same_topic requires a higher bar (min_shared_tags=2) for image captures.
        assert _is_same_topic(match_note, ["python"], min_shared_tags=2) is False
        assert _is_same_topic(match_note, ["python", "async"], min_shared_tags=2) is True
        print("[T4] _is_same_topic min_shared_tags threshold  PASS")

        # T5: _append_general appends with a timestamped separator, preserving original body.
        target_file = vault / "note.md"
        target_file.write_text("original body", encoding="utf-8")
        _append_general(target_file, "new content", vault)
        text = target_file.read_text(encoding="utf-8")
        assert "original body" in text and "new content" in text
        assert "*Captured:" in text
        print("[T5] _append_general  PASS")

        # T6 (B-1): a synced NOTE (origin: note / id:) filed in a category is NEVER a merge target,
        # even with a strong tag overlap — body-sacred. It must be skipped as a candidate AND rejected
        # by _is_same_topic, so a same-topic capture creates its own file instead of appending.
        synced = cat_dir / "phone-note.md"
        synced.write_text(
            "---\nid: 01ABC\norigin: note\ntags:\n  - python\n  - async\n---\n\nUser's sacred body.\n",
            encoding="utf-8",
        )
        assert find_merge_target(out2, vault) == match_note  # picks the capture note, not the synced note
        # even if the synced note were the only same-topic candidate, it's excluded:
        match_note.unlink()
        assert find_merge_target(out2, vault) is None
        assert _is_same_topic(synced, ["python", "async"], min_shared_tags=1) is False
        print("[T6] B-1 synced note never a merge target  PASS")

    print("\nAll merge.py smoke tests passed.")

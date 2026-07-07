"""
scratchpad.py -- scratchpad (needs-review inbox) routing for the vault.

Extracted from storage_engine.py (see docs/ROADMAP.md "Split storage_engine.py
into dedup.py / merge.py / scratchpad.py"). Owns writing low-confidence /
unrecognised / failed-enrichment captures to the vault's scratchpad folder,
and the list/approve/discard lifecycle for items sitting there.

`init_vault`, `_safe_stem`, `_write_new_file`, and `_unique_file_path` are
vault-write mechanics that stay defined in storage_engine.py; they are
imported here lazily (inside each function) to avoid a circular import,
since storage_engine.py imports route_to_scratchpad/route_failed_vision/
route_failed_llm/list_scratchpad/approve_scratchpad_item/
get_scratchpad_item_text/discard_scratchpad_item from this module at top
level (partly to re-export them for main.py/server.py's existing
`from storage_engine import route_failed_vision` / `route_failed_llm` calls).
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from models import CaptureOutput
from frontmatter import strip_frontmatter


def _scratchpad_path(vault_root: Path, scratchpad_folder: str) -> Path:
    return vault_root / scratchpad_folder


def route_to_scratchpad(
    output: CaptureOutput,
    source_url: Optional[str],
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
    body_content: Optional[str] = None,
) -> Path:
    """
    Write a note to the scratchpad folder with status: needs_review and a
    unique note_id so it can be located and approved/discarded later.
    """
    from storage_engine import init_vault, _safe_stem, _write_new_file

    init_vault(vault_root, scratchpad_folder)
    note_id = uuid.uuid4().hex[:12]
    filename = _safe_stem(output.suggested_filename)
    path = _scratchpad_path(vault_root, scratchpad_folder) / (filename + "-" + note_id + ".md")
    _write_new_file(path, output, source_url,
                    body_content=body_content, scratchpad=True, note_id=note_id,
                    vault_root=vault_root)
    print(f"[StorageEngine] routed to scratchpad (note_id={note_id}): {path}")
    return path


def route_failed_vision(
    source_metadata: dict,
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
) -> Path:
    """
    Route an image capture whose vision step failed straight to the
    scratchpad, flagged needs_vision_retry: true.

    Deliberately bypasses the classifier and semantic retrieval entirely --
    those must never run on the degraded-vision placeholder (see
    _degraded_image_payload), since the placeholder's diagnostic keywords
    were observed to deterministically anchor the classifier on an unrelated
    existing note (e.g. "ollama"/"llava" matching coding/ollama-native.md).
    """
    from storage_engine import init_vault, _safe_stem, _write_new_file

    init_vault(vault_root, scratchpad_folder)

    reason = source_metadata.get("vision_failure_reason", "vision model unavailable")
    image_embed = source_metadata.get("image_embed")

    body_lines = [f"> [!warning] Vision recognition failed\n> {reason}"]
    if image_embed:
        body_lines.append(image_embed)
    body = "\n\n".join(body_lines) + "\n"

    placeholder = CaptureOutput(
        category="Unprocessed_Images",
        suggested_filename="unprocessed-image",
        markdown_content=body,
        rationale=reason,
        key_signals=["vision-failed"],
        confidence=0.0,
        requires_new_category=False,
    )

    note_id = uuid.uuid4().hex[:12]
    filename = _safe_stem(placeholder.suggested_filename)
    path = _scratchpad_path(vault_root, scratchpad_folder) / (filename + "-" + note_id + ".md")
    _write_new_file(
        path, placeholder, source_url=None, body_content=body,
        scratchpad=True, note_id=note_id,
        extra_frontmatter={"needs_vision_retry": "true"},
        vault_root=vault_root,
    )
    print(f"[StorageEngine] WARN vision failed (note_id={note_id}): {reason} -> {path}", flush=True)
    return path


def route_failed_llm(
    enriched_text: str,
    reason: str,
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
    source_url: Optional[str] = None,
) -> Path:
    """
    Route a capture whose LLM enrichment stage failed (Ollama down, model
    error, or a parse failure surviving the two-pass retry) straight to the
    scratchpad, flagged needs_llm_retry: true.

    Deliberately bypasses the classifier and semantic retrieval entirely --
    same rationale as route_failed_vision: the failure must never be
    laundered into a confident (and wrong) category, and the raw captured
    text must not be lost.
    """
    from storage_engine import init_vault, _safe_stem, _write_new_file

    init_vault(vault_root, scratchpad_folder)

    body = f"> [!warning] LLM enrichment failed\n> {reason}\n\n{enriched_text}\n"

    placeholder = CaptureOutput(
        category="Unprocessed_Captures",
        suggested_filename="unprocessed-capture",
        markdown_content=body,
        rationale=reason,
        key_signals=["llm-failed"],
        confidence=0.0,
        requires_new_category=False,
    )

    note_id = uuid.uuid4().hex[:12]
    filename = _safe_stem(placeholder.suggested_filename)
    path = _scratchpad_path(vault_root, scratchpad_folder) / (filename + "-" + note_id + ".md")
    _write_new_file(
        path, placeholder, source_url=source_url, body_content=body,
        scratchpad=True, note_id=note_id,
        extra_frontmatter={"needs_llm_retry": "true"},
        vault_root=vault_root,
    )
    print(f"[StorageEngine] WARN LLM enrichment failed (note_id={note_id}): {reason} -> {path}", flush=True)
    return path


def list_scratchpad(vault_root: Path, scratchpad_folder: str = "_scratchpad") -> list:
    """Return metadata for all notes in the scratchpad folder."""
    sp = _scratchpad_path(vault_root, scratchpad_folder)
    if not sp.exists():
        return []
    items = []
    for f in sorted(sp.iterdir()):
        if f.is_file() and f.suffix == ".md":
            text = f.read_text(encoding="utf-8", errors="ignore")
            note_id = _extract_frontmatter_field(text, "note_id") or f.stem
            category = _extract_frontmatter_field(text, "category") or "unknown"
            items.append({
                "note_id":  note_id,
                "filename": f.name,
                "path":     str(f),
                "category": category,
                "size":     f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    return items


def approve_scratchpad_item(
    note_id: str,
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
    target_category: Optional[str] = None,
) -> Path:
    """
    Move a scratchpad note to its final category directory.
    Strips status: needs_review and note_id fields.
    """
    from storage_engine import init_vault, _unique_file_path

    item = _find_scratchpad_item(note_id, vault_root, scratchpad_folder)
    if item is None:
        raise FileNotFoundError(f"Scratchpad item {note_id!r} not found.")

    text = item.read_text(encoding="utf-8", errors="ignore")
    category = target_category or _extract_frontmatter_field(text, "category") or "Uncategorised"

    init_vault(vault_root, scratchpad_folder)
    dest_dir = vault_root / category
    dest_dir.mkdir(parents=True, exist_ok=True)

    base_filename = re.sub(r"-" + note_id + r"$", "", item.stem) + ".md"
    dest_path = dest_dir / base_filename
    if dest_path.exists():
        dest_path = _unique_file_path(dest_path)

    updated = _rewrite_frontmatter_for_approval(text, category)
    dest_path.write_text(updated, encoding="utf-8")
    item.unlink()
    print(f"[StorageEngine] scratchpad approved {note_id} -> {dest_path}")

    # Remove old scratchpad index entries; caller re-indexes the dest path.
    try:
        from vector_store import remove_from_index
        from index_writer import remove_capture_by_path
        remove_from_index(vault_root, item)
        remove_capture_by_path(vault_root, item)
    except Exception as exc:
        print(f"[StorageEngine] index cleanup on approve error: {exc}", file=sys.stderr)

    return dest_path


def get_scratchpad_item_text(
    note_id: str,
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
) -> Optional[str]:
    """Return a scratchpad note's body text (frontmatter stripped), or None if not found."""
    item = _find_scratchpad_item(note_id, vault_root, scratchpad_folder)
    if item is None:
        return None
    text = item.read_text(encoding="utf-8", errors="ignore")
    return strip_frontmatter(text).strip()


def discard_scratchpad_item(
    note_id: str,
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
) -> None:
    """Permanently delete a scratchpad note."""
    item = _find_scratchpad_item(note_id, vault_root, scratchpad_folder)
    if item is None:
        raise FileNotFoundError(f"Scratchpad item {note_id!r} not found.")
    item.unlink()
    print(f"[StorageEngine] scratchpad discarded {note_id}")

    try:
        from vector_store import remove_from_index
        from index_writer import remove_capture_by_path
        remove_from_index(vault_root, item)
        remove_capture_by_path(vault_root, item)
    except Exception as exc:
        print(f"[StorageEngine] index cleanup on discard error: {exc}", file=sys.stderr)


def _find_scratchpad_item(
    note_id: str,
    vault_root: Path,
    scratchpad_folder: str,
) -> Optional[Path]:
    sp = _scratchpad_path(vault_root, scratchpad_folder)
    if not sp.exists():
        return None
    for f in sp.iterdir():
        if not (f.is_file() and f.suffix == ".md"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        if _extract_frontmatter_field(text, "note_id") == note_id:
            return f
        if note_id in f.stem:
            return f
    return None


def _extract_frontmatter_field(text: str, field: str) -> Optional[str]:
    fm_match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    block = fm_match.group(1) if fm_match else ""
    m = re.search(r"^" + re.escape(field) + r":\s*(.+)$", block, re.MULTILINE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return None


# Per-category status a note should carry once approved out of the
# scratchpad, in place of the needs_review flag it had while pending.
# Watch_Later items track read/unread state rather than review state.
_CATEGORY_DEFAULT_STATUS: Dict[str, str] = {"Watch_Later": "unread"}


def _rewrite_frontmatter_for_approval(text: str, category: str) -> str:
    """
    Remove status: needs_review and note_id from frontmatter.
    If the target category defines a default post-approval status (see
    _CATEGORY_DEFAULT_STATUS), insert it in place of the dropped status line.
    """
    default_status = _CATEGORY_DEFAULT_STATUS.get(category)
    out = []
    inserted = False
    for line in text.split("\n"):
        if re.match(r"^status:\s*needs_review", line):
            continue  # drop
        if re.match(r"^note_id:\s*", line):
            continue  # drop
        out.append(line)
        if default_status and not inserted and re.match(r"^category:\s*", line):
            out.append(f"status: {default_status}")
            inserted = True
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Smoke test  (python scratchpad.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        SP = "_scratchpad"

        # T1: route_to_scratchpad writes status: needs_review + a unique note_id.
        t1 = CaptureOutput(
            category="Tech_Notes", suggested_filename="mystery-thing",
            markdown_content="I have no idea what this is.",
            key_signals=["unknown"], confidence=0.4,
            requires_new_category=False,
        )
        p1 = route_to_scratchpad(t1, None, vault, scratchpad_folder=SP, body_content=t1.markdown_content)
        assert SP in str(p1)
        assert "status: needs_review" in p1.read_text(encoding="utf-8")
        print(f"[T1] route_to_scratchpad  PASS  -> {p1.name}")

        # T2: route_failed_vision flags needs_vision_retry and preserves the reason + embed.
        p2 = route_failed_vision(
            {
                "vision_failure_reason": "vision model 'llava' could not describe the image",
                "image_embed": "![[img-abcd1234.png]]",
            },
            vault_root=vault,
            scratchpad_folder=SP,
        )
        text2 = p2.read_text(encoding="utf-8")
        assert "needs_vision_retry: true" in text2
        assert "![[img-abcd1234.png]]" in text2
        assert "vision model 'llava' could not describe the image" in text2
        print(f"[T2] route_failed_vision  PASS  -> {p2.name}")

        # T3: route_failed_llm flags needs_llm_retry and preserves the raw text + reason.
        p3 = route_failed_llm(
            "the raw captured text that must not be lost",
            "Ollama connection refused",
            vault_root=vault,
            scratchpad_folder=SP,
        )
        text3 = p3.read_text(encoding="utf-8")
        assert "needs_llm_retry: true" in text3
        assert "Ollama connection refused" in text3
        assert "the raw captured text that must not be lost" in text3
        print(f"[T3] route_failed_llm  PASS  -> {p3.name}")

        # T4: list_scratchpad / approve_scratchpad_item / discard_scratchpad_item lifecycle.
        items = list_scratchpad(vault, SP)
        assert len(items) == 3
        note_id_1 = _extract_frontmatter_field(p1.read_text(encoding="utf-8"), "note_id")
        approved = approve_scratchpad_item(note_id_1, vault, SP, target_category="Tech_Notes")
        assert approved.exists()
        assert SP not in str(approved)
        assert "needs_review" not in approved.read_text(encoding="utf-8")
        print(f"[T4] approve_scratchpad_item  PASS  -> {approved.name}")

        note_id_2 = _extract_frontmatter_field(p2.read_text(encoding="utf-8"), "note_id")
        discard_scratchpad_item(note_id_2, vault, SP)
        assert all(i["note_id"] != note_id_2 for i in list_scratchpad(vault, SP))
        print("[T5] discard_scratchpad_item  PASS")

    print("\nAll scratchpad.py smoke tests passed.")

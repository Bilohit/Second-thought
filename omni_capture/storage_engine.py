"""
storage_engine.py  -- Step 4: Storage Engine

Dynamic category edition
------------------------
Categories are no longer hardcoded.  Any top-level directory in the vault
root (except system folders that start with '_' and the configured scratchpad
folder) is treated as a valid category.  Each category folder may contain an
optional '.category.toml' file with a 'description' field used to build the
LLM system prompt.

Flat frontmatter schema
-----------------------
All notes share the same base frontmatter fields regardless of category.
Per-category YAML schema fields have been removed in favour of a single
consistent structure that Dataview can query uniformly.

Scratchpad routing
------------------
Low-confidence (<SCRATCHPAD_CONFIDENCE_THRESHOLD) or unrecognised captures
(requires_new_category=True) are written to the configured scratchpad folder
with status: needs_review and a unique note_id for later manual review.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from models import CaptureOutput
from config import DEFAULT_VAULT_ROOT

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Captures below this confidence threshold go to the scratchpad for review.
SCRATCHPAD_CONFIDENCE_THRESHOLD: float = 0.6

# Merge thresholds (unchanged from original)
MERGE_MIN_SHARED_TAGS: int = 2
MERGE_MIN_TAG_JACCARD: float = 0.5
MERGE_SEMANTIC_THRESHOLD: float = 0.85

# JSON index for deduplication (relative to vault root)
_DEDUP_INDEX_NAME = ".omni_capture/dedup_index.json"

# Folders that are ALWAYS excluded from the category list, regardless of name.
# (The configured scratchpad folder is also excluded at runtime.)
_SYSTEM_FOLDER_PREFIXES = ("_", ".")

# Filler/stop words dropped when shortening LLM-suggested filenames.
_FILENAME_STOPWORDS: frozenset = frozenset({
    "a", "an", "the", "of", "to", "for", "with", "and", "or", "but", "in",
    "on", "at", "by", "from", "how", "guide", "notes", "note", "this",
    "that", "is", "are", "into", "about", "your", "my",
})


# ---------------------------------------------------------------------------
# Category discovery
# ---------------------------------------------------------------------------

def discover_categories(
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
) -> List[str]:
    """
    Return the names of all valid category folders in vault_root.

    A folder is a valid category when:
      * It is a direct child of vault_root.
      * Its name does NOT start with '_' (system folders).
      * Its name is NOT the configured scratchpad folder.

    Returns a sorted list so that category order is deterministic.
    """
    if not vault_root.exists():
        return []
    return sorted(
        d.name
        for d in vault_root.iterdir()
        if d.is_dir()
        and not any(d.name.startswith(p) for p in _SYSTEM_FOLDER_PREFIXES)
        and d.name != scratchpad_folder
    )


def read_category_config(cat_dir: Path) -> dict:
    """
    Read the optional '.category.toml' from a category folder.

    Supported keys
    --------------
    description : str
        Plain-English description of what this category stores.
        Used verbatim in the LLM system prompt.
    format : str   (optional, future use)
        Hint for content formatting, e.g. 'finance_table', 'crm_interaction'.

    Returns an empty dict if the file is absent or unreadable.
    """
    config_file = cat_dir / ".category.toml"
    if not config_file.exists():
        return {}
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError:
                return {}
        with open(config_file, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def build_category_descriptions(
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
) -> Dict[str, str]:
    """
    Return a mapping of {category_name: description} for every discovered
    category folder.

    If a folder has no '.category.toml' (or no 'description' key inside it),
    a sensible default description is generated from the folder name.
    """
    categories = discover_categories(vault_root, scratchpad_folder)
    result: Dict[str, str] = {}
    for cat in categories:
        cat_dir = vault_root / cat
        cfg = read_category_config(cat_dir)
        desc = cfg.get(
            "description",
            f"Content related to {cat.replace('_', ' ')}.",
        )
        result[cat] = desc
    return result


# ---------------------------------------------------------------------------
# Vault initialisation
# ---------------------------------------------------------------------------

def init_vault(
    vault_root: Path = DEFAULT_VAULT_ROOT,
    scratchpad_folder: str = "_scratchpad",
) -> None:
    """
    Ensure the vault root and the scratchpad folder exist.

    Unlike the previous version, this no longer creates any category folders —
    categories are defined by whatever top-level folders the user creates.
    The only system folder created automatically is the scratchpad.
    """
    vault_root.mkdir(parents=True, exist_ok=True)
    (vault_root / scratchpad_folder).mkdir(exist_ok=True)
    # Hidden metadata dir (dedup index, vector index, etc.)
    (vault_root / ".omni_capture").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def _dedup_index_path(vault_root: Path) -> Path:
    return vault_root / _DEDUP_INDEX_NAME


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
    idx = _load_dedup_index(vault_root)
    try:
        rel = str(note_path.relative_to(vault_root))
    except ValueError:
        rel = str(note_path)
    idx[h] = rel
    _save_dedup_index(vault_root, idx)


# ---------------------------------------------------------------------------
# File path helpers
# ---------------------------------------------------------------------------

def _category_str(output: CaptureOutput) -> str:
    """Return category as a plain string (handles str-Enum members safely)."""
    cat = output.category
    # Enum members created with type=str have .value; plain str passes through.
    return cat.value if hasattr(cat, 'value') else str(cat)


def _truncate_slug(slug: str, max_chars: int) -> str:
    """Cut a kebab-case slug down to max_chars, preferring a '-' boundary so
    words are never sliced mid-token. Hard-slices only if a single token
    already exceeds max_chars on its own."""
    if len(slug) <= max_chars:
        return slug
    cut = slug[:max_chars]
    boundary = cut.rfind("-")
    if boundary > 0:
        return cut[:boundary]
    return cut


def _shorten_filename(raw: str, max_words: int = 2, max_chars: int = 40) -> str:
    """
    Deterministically enforce the filename word-count/char-count limits,
    treating the LLM's suggested_filename as untrusted input (the
    prompt-side rule in llm_engine.py is advisory only).
    """
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", raw.lower()) if t]
    survivors = [t for t in tokens if t not in _FILENAME_STOPWORDS]
    chosen = survivors if survivors else tokens
    slug = "-".join(chosen[:max_words])
    return _truncate_slug(slug, max_chars)


def _safe_stem(raw_filename: str) -> str:
    """Shorten-then-sanitise: the single chokepoint for turning an LLM-suggested
    filename into a filesystem-safe stem."""
    from config import get_config
    cfg = get_config()
    shortened = _shorten_filename(
        raw_filename,
        max_words=cfg.capture.filename_max_words,
        max_chars=cfg.capture.filename_max_chars,
    )
    return re.sub(r"[^\w\-]", "-", shortened).strip("-")


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _youtube_title_stem(title: Optional[str], max_chars: int = 80) -> str:
    """Turn a full YouTube title into a filesystem-safe stem that PRESERVES
    the whole title (unlike _safe_stem, which is for terse LLM filenames).
    Collapses non-word runs to '-', truncates on a '-' boundary at max_chars,
    and falls back to 'youtube-video' for empty/reserved input."""
    raw = (title or "").strip()
    slug = re.sub(r"[^\w]+", "-", raw, flags=re.UNICODE).strip("-")
    if not slug or slug.upper() in _WINDOWS_RESERVED_NAMES:
        return "youtube-video"
    return _truncate_slug(slug, max_chars)


_PADDING_LEAD_RE = re.compile(
    r"^(here('| i)s|in this (note|article|summary)|the following|below (is|are))\b.*$",
    re.IGNORECASE,
)


def _strip_padding(text: str) -> str:
    """
    Remove common LLM preamble padding (e.g. "Here is a summary:") when it
    appears as the very first non-blank line, outside fenced code blocks.
    Conservative by design: only strips the leading line, never touches an
    identical phrase appearing mid-document, and never alters fenced code.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fence_re = re.compile(r"^\s*(```|~~~)")

    first_content_idx = None
    in_fence = False
    for i, line in enumerate(lines):
        if fence_re.match(line):
            in_fence = not in_fence
            break  # fenced content can't be the leading text line
        if line.strip() == "":
            continue
        first_content_idx = i
        break

    if first_content_idx is None or in_fence:
        return text

    if _PADDING_LEAD_RE.match(lines[first_content_idx].strip()):
        stripped_line = lines[first_content_idx].strip()
        del lines[first_content_idx]
        # Drop the now-leading blank line, if any, so we don't reintroduce
        # the blank-line stripping that _trim_content already does anyway.
        while first_content_idx < len(lines) and lines[first_content_idx].strip() == "":
            del lines[first_content_idx]
        print(f"[StorageEngine] stripped LLM preamble line: {stripped_line[:80]!r}", flush=True)

    return "\n".join(lines)


def _soft_cap_content(text: str, max_chars: int) -> str:
    """Truncate on a paragraph boundary and mark truncation. No-op when
    max_chars <= 0 (the default, preserving existing behaviour)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    boundary = cut.rfind("\n\n")
    if boundary > 0:
        cut = cut[:boundary]
    print(f"[StorageEngine] note truncated to {max_chars} chars (was {len(text)})", flush=True)
    return cut.rstrip() + "\n\n*(truncated)*"


def _trim_content(text: str) -> str:
    """
    Markdown-aware content trim: strip trailing whitespace per line, collapse
    3+ blank lines to 1, strip leading/trailing blank lines, normalise CRLF,
    and ensure exactly one trailing newline. Lines inside fenced code blocks
    (``` or ~~~) pass through unchanged since some languages are
    whitespace-significant.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    out: List[str] = []
    in_fence = False
    blank_run = 0
    fence_re = re.compile(r"^\s*(```|~~~)")

    for line in lines:
        if fence_re.match(line):
            in_fence = not in_fence
            out.append(line)
            blank_run = 0
            continue

        if in_fence:
            out.append(line)
            continue

        stripped = line.rstrip()
        if stripped == "":
            blank_run += 1
            if blank_run <= 1:
                out.append(stripped)
        else:
            blank_run = 0
            out.append(stripped)

    # Strip leading/trailing blank lines.
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()

    return "\n".join(out) + "\n"


# Categories that are a single running ledger rather than one-note-per-topic.
# pre_resolver.py documents Finance as always targeting Finance/Expenses.md;
# this mirrors that here so write_to_vault honours it even when called
# without going through pre_resolve first (e.g. the LLM's suggested_filename
# is irrelevant for a ledger -- every entry is a row in the same file).
_LEDGER_FILES: Dict[str, str] = {"Finance": "Expenses.md"}


def _resolve_file_path(output: CaptureOutput, vault_root: Path) -> Path:
    cat = _category_str(output)
    ledger_file = _LEDGER_FILES.get(cat)
    filename = ledger_file if ledger_file else _safe_stem(output.suggested_filename) + ".md"
    return vault_root / cat / filename


def _unique_file_path(base_path: Path) -> Path:
    """Append a 6-char hex ID to the stem to avoid clobbering an existing file."""
    if not base_path.exists():
        return base_path
    short = uuid.uuid4().hex[:6]
    return base_path.with_name(base_path.stem + "-" + short + base_path.suffix)


# ---------------------------------------------------------------------------
# Frontmatter builder  (flat schema — same fields for every category)
# ---------------------------------------------------------------------------

def _signals_to_tags(key_signals: List[str]) -> List[str]:
    tags: List[str] = []
    for signal in key_signals:
        tag = signal.strip().lower()
        tag = re.sub(r"[^\w\s/\-]", "", tag)
        tag = re.sub(r"\s+", "-", tag).strip("-/")
        if tag:
            tags.append(tag)
    return tags


def _build_frontmatter(
    output: CaptureOutput,
    source_url: Optional[str],
    scratchpad: bool = False,
    note_id: Optional[str] = None,
    extra_frontmatter: Optional[Dict[str, str]] = None,
) -> str:
    """
    Build YAML frontmatter with a flat schema shared across all categories.

    Fields
    ------
    created     ISO-8601 timestamp
    category    folder name
    status      'needs_review' (scratchpad only) | absent otherwise
    note_id     scratchpad review ID (scratchpad only)
    source      source URL (when available)
    confidence  LLM self-reported confidence
    rationale   LLM reasoning
    tags        list derived from key_signals
    extra_frontmatter  caller-supplied flat string fields (e.g. needs_vision_retry)
    """
    now = datetime.now().isoformat(timespec="seconds")
    tags = _signals_to_tags(output.key_signals)
    cat = _category_str(output)

    lines = ["---", f"created: {now}", f"category: {cat}"]

    if scratchpad:
        lines.append("status: needs_review")
        if note_id:
            lines.append(f"note_id: {note_id}")

    if source_url:
        lines.append(f"source: {source_url}")

    lines.append(f"confidence: {round(output.confidence, 3)}")

    if output.rationale:
        safe = output.rationale.replace('"', "'").replace("\n", " ")
        lines.append(f'rationale: "{safe}"')

    if extra_frontmatter:
        for key, value in extra_frontmatter.items():
            lines.append(f"{key}: {value}")

    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append(f"  - {tag}")
    else:
        lines.append("tags: []")

    lines.append("---\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Note writers
# ---------------------------------------------------------------------------

def _write_new_file(
    path: Path,
    output: CaptureOutput,
    source_url: Optional[str],
    body_content: Optional[str] = None,
    scratchpad: bool = False,
    note_id: Optional[str] = None,
    extra_frontmatter: Optional[Dict[str, str]] = None,
) -> None:
    content = body_content if body_content is not None else output.markdown_content
    front = _build_frontmatter(output, source_url, scratchpad=scratchpad, note_id=note_id,
                                extra_frontmatter=extra_frontmatter)
    path.write_text(front + content, encoding="utf-8")


def _append_general(path: Path, new_content: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    sep = f"\n\n---\n*Captured: {ts}*\n\n"
    existing = path.read_text(encoding="utf-8")
    path.write_text(existing.rstrip() + sep + new_content + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Scratchpad helpers  (replaces the old _inbox)
# ---------------------------------------------------------------------------

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
    init_vault(vault_root, scratchpad_folder)
    note_id = uuid.uuid4().hex[:12]
    filename = _safe_stem(output.suggested_filename)
    path = _scratchpad_path(vault_root, scratchpad_folder) / (filename + "-" + note_id + ".md")
    _write_new_file(path, output, source_url,
                    body_content=body_content, scratchpad=True, note_id=note_id)
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
    )
    print(f"[StorageEngine] WARN vision failed (note_id={note_id}): {reason} -> {path}", flush=True)
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
    return dest_path


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
    pattern = r"^" + re.escape(field) + r":\s*(.+)$"
    m = re.search(pattern, text, re.MULTILINE)
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
# Existing-context reader  (for read-before-write LLM pass)
# ---------------------------------------------------------------------------

def read_existing_context(
    output: CaptureOutput,
    vault_root: Path = DEFAULT_VAULT_ROOT,
) -> Optional[str]:
    target = _resolve_file_path(output, vault_root)
    if not target.exists():
        return None
    return target.read_text(encoding="utf-8")[:2000]


# ---------------------------------------------------------------------------
# Wikilink injection helper
# ---------------------------------------------------------------------------

def _postprocess_content(raw_content: str) -> str:
    """Strip LLM padding, apply the optional soft length cap, then run the
    existing whitespace/fence-aware trim. Single chokepoint so both the
    scratchpad and normal-write paths stay in lockstep."""
    from config import get_config
    cfg = get_config()
    text = _strip_padding(raw_content)
    text = _soft_cap_content(text, cfg.capture.note_max_chars)
    return _trim_content(text)


def _build_deterministic_append(source_metadata: Optional[dict]) -> str:
    """
    Render the deterministic, non-LLM artifacts (image embed, verbatim OCR
    transcription) that enrichment_router carries in EnrichedPayload.source_metadata.

    These are appended to the note verbatim, after the LLM-generated
    markdown_content, so the model can't paraphrase, reorder, or drop them.
    """
    if not source_metadata:
        return ""
    parts = []
    embed = source_metadata.get("image_embed")
    if embed:
        parts.append(embed)
    transcribed = source_metadata.get("transcribed_text")
    if transcribed:
        heading = "Extracted Text" if source_metadata.get("source_type") == "image_ocr" else "Transcribed Text"
        parts.append(f"## {heading}\n{transcribed}")
    return "\n\n".join(parts)


def _try_inject_wikilinks(
    output: CaptureOutput,
    path: Optional[Path],
    vault_root: Path,
) -> str:
    try:
        from link_resolver import build_link_index, inject_wikilinks
        link_index = build_link_index(vault_root)
        if path:
            try:
                rel_stem = str(path.relative_to(vault_root).with_suffix("")).replace("\\", "/")
            except ValueError:
                rel_stem = path.stem
        else:
            rel_stem = output.suggested_filename
        return inject_wikilinks(output.markdown_content, link_index, exclude_stems={rel_stem})
    except Exception as err:
        print(f"[StorageEngine] link resolver skipped: {err}", flush=True)
        return output.markdown_content


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


def _is_same_topic(existing_path: Path, new_signals: List[str], min_shared_tags: int = 1) -> bool:
    """
    min_shared_tags raises the bar above the default single-shared-tag match.
    Used for image captures: a vision description sharing exactly one tag
    with an unrelated note (e.g. both happen to mention "ollama") is too
    weak a signal to silently append a photo into that note.
    """
    if not existing_path.exists() or not new_signals:
        return True
    existing_tags = _read_note_tags(existing_path)
    if not existing_tags:
        return True
    normalised_new = set(_signals_to_tags(new_signals))
    return len(existing_tags & normalised_new) >= min_shared_tags


# ---------------------------------------------------------------------------
# Smart context-aware merge-target finder
# ---------------------------------------------------------------------------

def find_merge_target(
    output: CaptureOutput,
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
    cat = _category_str(output)
    new_tags = set(_signals_to_tags(output.key_signals))
    if not new_tags:
        return None

    cat_dir = vault_root / cat
    if not cat_dir.exists():
        return None

    candidates = [
        f for f in cat_dir.iterdir()
        if f.is_file() and f.suffix == ".md"
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
# Forced-category routing  (used by background jobs, e.g. YouTube)
# ---------------------------------------------------------------------------

def ensure_category(vault_root: Path, name: str, description: str) -> Path:
    """
    Create vault_root/name if absent and write a '.category.toml' with the
    given description if no config file already exists. Never overwrites a
    user-edited '.category.toml'.
    """
    cat_dir = vault_root / name
    cat_dir.mkdir(parents=True, exist_ok=True)

    config_file = cat_dir / ".category.toml"
    if not config_file.exists():
        import tomlkit
        doc = tomlkit.document()
        doc.add("description", description)
        config_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    return cat_dir


# Stable sentinel marking the summary region of a YouTube note for in-place
# replacement in finalize_youtube_note. Match on this comment, never on the
# human-readable placeholder text, since postprocessing could alter the latter.
_YOUTUBE_SUMMARY_SENTINEL = "<!-- ST:SUMMARY -->"


def create_youtube_note(
    title: Optional[str],
    url: str,
    transcript_md: str,
    vault_root: Path,
    youtube_cfg,
    scratchpad_folder: str = "_scratchpad",
) -> Path:
    """
    Phase 1 of the async YouTube worker: write the full, untruncated
    transcript to a real note immediately, before any LLM call, with a
    placeholder summary region marked by _YOUTUBE_SUMMARY_SENTINEL.

    This guarantees the raw transcript is never lost even if summarization
    later fails or times out.
    """
    ensure_category(vault_root, youtube_cfg.folder_name, youtube_cfg.description)
    init_vault(vault_root, scratchpad_folder)

    from config import get_config
    stem = _youtube_title_stem(title, max_chars=get_config().capture.youtube_filename_max_chars)
    base_path = vault_root / youtube_cfg.folder_name / (stem + ".md")
    path = _unique_file_path(base_path)

    now = datetime.now().isoformat(timespec="seconds")
    heading = title or "YouTube Video"
    content = (
        "---\n"
        f"created: {now}\n"
        f"category: {youtube_cfg.folder_name}\n"
        f"source: {url}\n"
        "status: summarizing\n"
        "tags: []\n"
        "---\n\n"
        f"# {heading}\n\n"
        "> [!info] Source\n"
        f"> {url}\n\n"
        "## Summary\n"
        f"{_YOUTUBE_SUMMARY_SENTINEL}\n"
        "⏳ Summarizing transcript…\n\n"
        "## Transcript\n"
        f"{transcript_md}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def finalize_youtube_note(
    path: Path,
    summary_md: str,
    vault_root: Path,
    *,
    tags: Optional[List[str]] = None,
) -> None:
    """
    Phase 4: replace the placeholder summary region (marked by
    _YOUTUBE_SUMMARY_SENTINEL) with the final summary, and flip
    status: summarizing -> status: done in frontmatter.

    Always locates the summary region by the sentinel comment, never by
    matching the placeholder text. If the sentinel is somehow missing
    (corrupted note), appends the summary under a fresh heading instead of
    failing.
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    processed_summary = _postprocess_content(summary_md)

    sentinel_idx = text.find(_YOUTUBE_SUMMARY_SENTINEL)
    if sentinel_idx == -1:
        new_text = text.rstrip() + "\n\n## Summary\n" + processed_summary + "\n"
    else:
        transcript_idx = text.find("\n## Transcript", sentinel_idx)
        before = text[:sentinel_idx]
        after = text[transcript_idx:] if transcript_idx != -1 else ""
        new_text = before + processed_summary + "\n" + after

    new_text = re.sub(
        r"^status:\s*summarizing\s*$", "status: done", new_text, count=1, flags=re.MULTILINE,
    )

    if tags:
        tag_block = "tags:\n" + "\n".join(f"  - {t}" for t in tags)
        new_text = re.sub(r"^tags:\s*\[\]\s*$", tag_block, new_text, count=1, flags=re.MULTILINE)

    path.write_text(new_text, encoding="utf-8")


def write_to_named_category(
    output: CaptureOutput,
    category: str,
    vault_root: Path,
    source_url: Optional[str] = None,
    description: str = "",
    scratchpad_folder: str = "_scratchpad",
    enable_semantic_merge: bool = False,
    embed_base_url: Optional[str] = None,
    embed_model: str = "nomic-embed-text",
) -> Path:
    """
    Force-route a capture into a named category, bypassing scratchpad
    diversion. Intended for content whose destination is already known from
    user intent (e.g. a YouTube URL), where low model confidence should not
    divert it to manual review.
    """
    ensure_category(vault_root, category, description)

    output.category = category
    output.requires_new_category = False
    if output.confidence < SCRATCHPAD_CONFIDENCE_THRESHOLD:
        output.confidence = max(output.confidence, SCRATCHPAD_CONFIDENCE_THRESHOLD)

    return write_to_vault(
        output,
        source_url=source_url,
        vault_root=vault_root,
        scratchpad_folder=scratchpad_folder,
        enable_semantic_merge=enable_semantic_merge,
        embed_base_url=embed_base_url,
        embed_model=embed_model,
    )


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------

def write_to_vault(
    output: CaptureOutput,
    source_url: Optional[str] = None,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    scratchpad_folder: str = "_scratchpad",
    enable_semantic_merge: bool = False,
    embed_base_url: Optional[str] = None,
    embed_model: str = "nomic-embed-text",
    source_metadata: Optional[dict] = None,
) -> Path:
    """
    Write/append a CaptureOutput to the vault.

    Routing
    -------
    1. Dedup check        — skip only when an exact duplicate already exists in
                            the *same* category the engine just decided.
    2. Scratchpad routing — low confidence or requires_new_category → scratchpad.
    3. Smart merge        — append into an existing same-topic note when tags match.
    4. Normal write       — per-category append or new file with collision-safe name.

    source_metadata, when passed (e.g. an image capture's EnrichedPayload.source_metadata),
    may carry deterministic artifacts (image_embed, transcribed_text) that are
    appended verbatim after the LLM-generated content -- see _build_deterministic_append.
    """
    init_vault(vault_root, scratchpad_folder)
    deterministic_append = _build_deterministic_append(source_metadata)
    extra_fm = None
    if source_metadata and source_metadata.get("source_type"):
        extra_fm = {"source_type": source_metadata["source_type"]}

    decided_category = _category_str(output)

    # 1. Deduplication
    #
    # The dedup index is keyed purely on content, so a re-captured note whose
    # decision has changed category (e.g. the engine now says CRM but an older
    # copy was filed under Tech_Notes) used to be silently short-circuited back
    # to the stale location — the GUI showed one category while the file landed
    # in another. Only honour a dedup hit when the indexed note still lives in
    # the category the engine just decided; otherwise fall through and write to
    # the correct place, refreshing the index pointer afterwards.
    dup_path = check_duplicate(output.markdown_content, source_url, vault_root)
    if dup_path:
        existing = vault_root / dup_path
        existing_category = Path(dup_path).parts[0] if Path(dup_path).parts else ""
        if existing.exists() and existing_category == decided_category:
            print(f"[StorageEngine] DUPLICATE -- already at {dup_path}. Skipping.")
            return existing
        if existing.exists():
            print(
                f"[StorageEngine] dedup hit at {dup_path} is in category "
                f"'{existing_category}', but this capture was decided as "
                f"'{decided_category}'. Re-filing to the decided category."
            )
        else:
            print(
                f"[StorageEngine] stale dedup entry for {dup_path} "
                "(file missing) -- ignoring and writing fresh."
            )

    # 2. Scratchpad routing
    if output.confidence < SCRATCHPAD_CONFIDENCE_THRESHOLD or output.requires_new_category:
        reason = (
            f"confidence={round(output.confidence, 2)} < {SCRATCHPAD_CONFIDENCE_THRESHOLD}"
            if output.confidence < SCRATCHPAD_CONFIDENCE_THRESHOLD
            else "requires_new_category=True"
        )
        print(f"[StorageEngine] -> scratchpad ({reason})")
        linked_content = _postprocess_content(_try_inject_wikilinks(output, None, vault_root))
        if deterministic_append:
            linked_content = linked_content + "\n\n" + deterministic_append
        path = route_to_scratchpad(
            output, source_url, vault_root,
            scratchpad_folder=scratchpad_folder,
            body_content=linked_content,
        )
        register_in_dedup_index(output.markdown_content, source_url, vault_root, path)
        return path

    # Ensure the category folder exists (user may have created it after startup)
    cat = _category_str(output)
    (vault_root / cat).mkdir(parents=True, exist_ok=True)

    # 3. Normal write
    base_path = _resolve_file_path(output, vault_root)
    path = base_path

    linked_content = _postprocess_content(_try_inject_wikilinks(output, path, vault_root))
    if deterministic_append:
        linked_content = linked_content + "\n\n" + deterministic_append
    is_ledger = cat in _LEDGER_FILES

    if not path.exists():
        # Smart merge: look for a different existing note in the same category
        # that is confidently about the same topic. Ledger categories skip this
        # — there's only ever one file, created below.
        merge_target = None if is_ledger else find_merge_target(
            output, vault_root,
            enable_semantic_merge=enable_semantic_merge,
            embed_base_url=embed_base_url,
            embed_model=embed_model,
        )
        if merge_target is not None:
            path = merge_target
            _append_general(path, linked_content)
            action = "appended (smart-merge)"
        else:
            _write_new_file(path, output, source_url, body_content=linked_content,
                            extra_frontmatter=extra_fm)
            action = "created"
    else:
        # File already exists — append when it's the same topic, or
        # unconditionally for ledger categories (every entry is a new row
        # in the same running file, regardless of topic). Image captures
        # require 2+ shared tags, not just 1: a vision description sharing a
        # single incidental tag with an unrelated note is too weak a signal
        # to silently merge a photo into it.
        is_image = bool(source_metadata and (source_metadata.get("image_embed") or source_metadata.get("vision_model")))
        min_shared = 2 if is_image else 1
        if is_ledger or _is_same_topic(base_path, output.key_signals, min_shared_tags=min_shared):
            _append_general(path, linked_content)
            action = "appended (general)"
        else:
            path = _unique_file_path(base_path)
            _write_new_file(path, output, source_url, body_content=linked_content,
                            extra_frontmatter=extra_fm)
            action = "created (topic-collision avoided)"
            print(
                f"[StorageEngine] WARNING: suggested_filename collision on different topic. "
                f"Created new file: {path}"
            )

    print(f"[StorageEngine] {action}: {path}")
    register_in_dedup_index(output.markdown_content, source_url, vault_root, path)
    return path


# ---------------------------------------------------------------------------
# Smoke test  (python storage_engine.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        vault = pathlib.Path(tmp)
        SP = "_scratchpad"

        # Create some user-defined category folders
        (vault / "Tech_Notes").mkdir()
        (vault / "Journal").mkdir()
        (vault / "Recipes").mkdir()

        # T1: discover_categories ignores system folders
        cats = discover_categories(vault, scratchpad_folder=SP)
        assert "Tech_Notes" in cats
        assert "Journal" in cats
        assert SP not in cats
        print(f"[T1] discover_categories: {cats}  PASS")

        # T2: read_category_config returns empty dict when no file
        cfg_empty = read_category_config(vault / "Tech_Notes")
        assert cfg_empty == {}
        print("[T2] read_category_config (no file)  PASS")

        # T3: read_category_config reads description
        (vault / "Tech_Notes" / ".category.toml").write_text(
            'description = "Code, tools, and engineering notes."\n',
            encoding="utf-8",
        )
        cfg_loaded = read_category_config(vault / "Tech_Notes")
        assert cfg_loaded["description"] == "Code, tools, and engineering notes."
        print("[T3] read_category_config (with file)  PASS")

        # T4: build_category_descriptions uses file description + auto-generates fallback
        descs = build_category_descriptions(vault, scratchpad_folder=SP)
        assert descs["Tech_Notes"] == "Code, tools, and engineering notes."
        assert "Journal" in descs
        assert "related to Journal" in descs["Journal"]
        print(f"[T4] build_category_descriptions: {descs}  PASS")

        # T5: build_capture_model from models
        from models import build_capture_model, CaptureOutput as BaseCaptureOutput
        Model = build_capture_model(list(descs.keys()))
        assert hasattr(Model, "model_fields")
        print(f"[T5] build_capture_model  PASS  (fields: {list(Model.model_fields)})")

        # T6: write note to a discovered category
        t6 = BaseCaptureOutput(
            category="Tech_Notes", suggested_filename="asyncio-notes",
            markdown_content="async def main(): ...",
            key_signals=["python", "async"], confidence=0.92,
            requires_new_category=False,
        )
        p6 = write_to_vault(t6, vault_root=vault, scratchpad_folder=SP)
        assert p6.exists()
        assert "Tech_Notes" in str(p6)
        txt6 = p6.read_text()
        assert "category: Tech_Notes" in txt6
        assert "CATEGORY_SCHEMA" not in txt6  # flat schema check
        print(f"[T6] write_to_vault (new note)  PASS  -> {p6.name}")

        # T7: deduplication
        p6b = write_to_vault(t6, vault_root=vault, scratchpad_folder=SP)
        assert str(p6) == str(p6b)
        print("[T7] deduplication  PASS")

        # T8: low confidence -> scratchpad
        t8 = BaseCaptureOutput(
            category="Tech_Notes", suggested_filename="mystery-thing",
            markdown_content="I have no idea what this is unique abc.",
            key_signals=["unknown"], confidence=0.4,
            requires_new_category=False,
        )
        p8 = write_to_vault(t8, vault_root=vault, scratchpad_folder=SP)
        assert SP in str(p8)
        assert "status: needs_review" in p8.read_text()
        print(f"[T8] scratchpad routing (low confidence)  PASS  -> {p8.name}")

        # T9: requires_new_category -> scratchpad
        t9 = BaseCaptureOutput(
            category="Tech_Notes", suggested_filename="new-thing-unique",
            markdown_content="This is a new category entirely unique xyz.",
            key_signals=[], confidence=0.8,
            requires_new_category=True,
        )
        p9 = write_to_vault(t9, vault_root=vault, scratchpad_folder=SP)
        assert SP in str(p9)
        print("[T9] scratchpad routing (requires_new_category)  PASS")

        # T10: list_scratchpad and approve
        items = list_scratchpad(vault, SP)
        assert len(items) >= 2
        note_id_8 = items[0]["note_id"]
        approved = approve_scratchpad_item(note_id_8, vault, SP, target_category="Tech_Notes")
        assert approved.exists()
        assert SP not in str(approved)
        assert "needs_review" not in approved.read_text()
        print(f"[T10] approve_scratchpad_item  PASS  -> {approved.name}")

        # T11: discard
        items_after = list_scratchpad(vault, SP)
        note_id_9 = items_after[0]["note_id"]
        discard_scratchpad_item(note_id_9, vault, SP)
        assert all(i["note_id"] != note_id_9 for i in list_scratchpad(vault, SP))
        print("[T11] discard_scratchpad_item  PASS")

        # T12: adding a new folder at runtime is immediately discovered
        (vault / "Fitness_Log").mkdir()
        cats2 = discover_categories(vault, scratchpad_folder=SP)
        assert "Fitness_Log" in cats2
        print(f"[T12] runtime folder discovery  PASS  (cats: {cats2})")

        # T13: _shorten_filename drops stop words and caps at max_words (now 2)
        assert _shorten_filename("how-to-set-up-docker-compose-networking-guide") == "set-up"
        assert _shorten_filename("asyncio-event-loop") == "asyncio-event"
        # All-stopword input falls back to the original tokens instead of "".
        assert _shorten_filename("the-of-and") == "the-of"
        print("[T13] _shorten_filename  PASS")

        # T13b: a >40-char single-topic slug truncates on a '-' boundary, never mid-word
        long_slug = _shorten_filename("supercalifragilisticexpialidocious-extra", max_words=2, max_chars=40)
        assert len(long_slug) <= 40
        assert not long_slug.endswith("-")
        assert "supercalifragilisticexpialidocious" in long_slug
        # A single token that alone exceeds max_chars is hard-sliced.
        hard_sliced = _truncate_slug("a" * 60, 40)
        assert hard_sliced == "a" * 40
        print(f"[T13b] _shorten_filename char cap  PASS  ({long_slug!r})")

        # T13c: _youtube_title_stem preserves the full title (unlike _safe_stem),
        # only sanitising it for the filesystem.
        full_title = "How Transformers Really Work — A Visual Intro"
        stem_full = _youtube_title_stem(full_title)
        assert stem_full == "How-Transformers-Really-Work-A-Visual-Intro", stem_full

        # Unicode/CJK characters are preserved, not stripped to ASCII
        # (trailing full-width punctuation is non-word and gets dropped).
        cjk_title = "深層学習とは何か？"
        stem_cjk = _youtube_title_stem(cjk_title)
        assert stem_cjk == "深層学習とは何か", stem_cjk

        # Emoji/symbols collapse to single hyphens, no doubled/leading/trailing hyphens.
        emoji_title = "🔥 Best Recipe!! // Ever??"
        stem_emoji = _youtube_title_stem(emoji_title)
        assert "--" not in stem_emoji
        assert not stem_emoji.startswith("-") and not stem_emoji.endswith("-")
        assert "Best-Recipe-Ever" in stem_emoji, stem_emoji

        # Over-long titles truncate within max_chars, backing off to a '-' boundary.
        long_title = "word " * 30  # 150 chars, well over the 80-char default cap
        stem_long = _youtube_title_stem(long_title.strip())
        assert len(stem_long) <= 80, len(stem_long)
        assert not stem_long.endswith("-")

        # Empty / None input falls back to "youtube-video".
        assert _youtube_title_stem(None) == "youtube-video"
        assert _youtube_title_stem("") == "youtube-video"
        assert _youtube_title_stem("   ") == "youtube-video"

        # Windows-reserved device names fall back too (case-insensitive).
        assert _youtube_title_stem("CON") == "youtube-video"
        assert _youtube_title_stem("con") == "youtube-video"
        print("[T13c] _youtube_title_stem  PASS")

        # T14: _trim_content collapses blank lines but preserves fenced code blocks
        messy = (
            "\n\nIntro line.   \n\n\n\n"
            "More text.\n"
            "```python\n"
            "def f():\n"
            "    x = 1\n\n\n"
            "    return x\n"
            "```\n\n\n"
            "Outro.\n\n\n"
        )
        trimmed = _trim_content(messy)
        assert trimmed.startswith("Intro line.\n")
        assert "Intro line.\n\nMore text." in trimmed  # 3+ blanks collapsed to 1
        assert "    x = 1\n\n\n    return x" in trimmed  # fence content untouched
        assert "```\n\nOutro." in trimmed  # blanks after fence still collapsed
        assert trimmed.endswith("Outro.\n")
        print("[T14] _trim_content  PASS")

        # T14b: _strip_padding removes a leading preamble line but leaves an
        # identical phrase mid-body untouched, and leaves fenced code byte-identical.
        padded = (
            "Here is a summary:\n\n"
            "Actual content starts here.\n"
            "Here is a summary: this phrase mid-body stays.\n"
            "```python\n"
            "# Here is a summary: should stay inside the fence\n"
            "```\n"
        )
        stripped = _strip_padding(padded)
        assert not stripped.startswith("Here is a summary:")
        assert "Actual content starts here." in stripped
        assert "Here is a summary: this phrase mid-body stays." in stripped
        assert "# Here is a summary: should stay inside the fence" in stripped
        print("[T14b] _strip_padding  PASS")

        # T15: ensure_category creates folder + .category.toml, never overwrites
        yt_dir = ensure_category(vault, "YouTube", "Summaries from YouTube videos.")
        assert yt_dir.exists()
        assert (yt_dir / ".category.toml").exists()
        assert "YouTube" in discover_categories(vault, scratchpad_folder=SP)
        ensure_category(vault, "YouTube", "DIFFERENT — should not overwrite")
        assert "Summaries from YouTube videos." in (yt_dir / ".category.toml").read_text()
        print("[T15] ensure_category  PASS")

        # T16: write_to_named_category forces category + floors low confidence
        t16 = BaseCaptureOutput(
            category="Tech_Notes",  # LLM's original guess -- should be overridden
            suggested_filename="rust-async-talk",
            markdown_content="Notes from a conference talk on async Rust.",
            key_signals=["rust", "async"], confidence=0.3,
            requires_new_category=False,
        )
        p16 = write_to_named_category(
            t16, category="YouTube", vault_root=vault,
            description="Summaries from YouTube videos.",
            scratchpad_folder=SP,
        )
        assert "YouTube" in str(p16)
        assert SP not in str(p16)
        print(f"[T16] write_to_named_category  PASS  -> {p16}")

        # T17: create_youtube_note writes sentinel + full transcript, status: summarizing
        from config import YouTubeConfig
        yt_cfg = YouTubeConfig(folder_name="YouTube", description="Summaries from YouTube videos.")
        p17 = create_youtube_note(
            "My Video Title", "https://youtu.be/abc123",
            "full untruncated transcript text here", vault, yt_cfg, scratchpad_folder=SP,
        )
        assert p17.exists()
        text17 = p17.read_text(encoding="utf-8")
        assert "status: summarizing" in text17
        assert "<!-- ST:SUMMARY -->" in text17
        assert "full untruncated transcript text here" in text17
        assert "## Transcript" in text17
        print(f"[T17] create_youtube_note  PASS  -> {p17.name}")

        # T17b: create_youtube_note uses the full sanitized title as the filename
        # stem (via _youtube_title_stem), not the 2-word LLM-filename slug that
        # _safe_stem would produce for the same string.
        long_title_17b = "How Transformers Really Work — A Visual Intro"
        p17b = create_youtube_note(
            long_title_17b, "https://youtu.be/longtitle",
            "transcript text", vault, yt_cfg, scratchpad_folder=SP,
        )
        assert p17b.stem == "How-Transformers-Really-Work-A-Visual-Intro", p17b.stem
        print(f"[T17b] create_youtube_note full-title filename  PASS  -> {p17b.name}")

        # T18: finalize_youtube_note replaces sentinel region and flips status
        finalize_youtube_note(p17, "**Final summary content.**", vault, tags=["python", "async"])
        text18 = p17.read_text(encoding="utf-8")
        assert "status: done" in text18
        assert "status: summarizing" not in text18
        assert "Final summary content." in text18
        assert "Summarizing transcript" not in text18
        assert "full untruncated transcript text here" in text18  # transcript preserved
        assert "  - python" in text18 and "  - async" in text18
        print("[T18] finalize_youtube_note  PASS")

        # T19: finalize_youtube_note degrades gracefully when sentinel is missing
        p19 = vault / "YouTube" / "no-sentinel.md"
        p19.write_text("---\ncategory: YouTube\nstatus: summarizing\ntags: []\n---\n\n# Title\n\nNo sentinel here.\n", encoding="utf-8")
        finalize_youtube_note(p19, "Recovered summary.", vault)
        text19 = p19.read_text(encoding="utf-8")
        assert "## Summary" in text19
        assert "Recovered summary." in text19
        print("[T19] finalize_youtube_note (missing sentinel)  PASS")

        # T20: write_to_vault appends deterministic image_embed/transcribed_text
        # verbatim after the LLM-generated markdown_content (H3/A1 seam).
        t20 = BaseCaptureOutput(
            category="Tech_Notes", suggested_filename="screenshot-note",
            markdown_content="The LLM's paraphrased description of the screenshot.",
            key_signals=["screenshot"], confidence=0.9,
            requires_new_category=False,
        )
        p20 = write_to_vault(
            t20, vault_root=vault, scratchpad_folder=SP,
            source_metadata={
                "image_embed": "![[img-20260619-abcd1234.png]]",
                "transcribed_text": "verbatim OCR text from the screenshot",
            },
        )
        text20 = p20.read_text(encoding="utf-8")
        assert "![[img-20260619-abcd1234.png]]" in text20
        assert "## Transcribed Text" in text20
        assert "verbatim OCR text from the screenshot" in text20
        print(f"[T20] write_to_vault deterministic-append seam  PASS  -> {p20.name}")

        # T20b: image captures require >=2 shared tags to auto-append into an
        # existing note -- one incidental shared tag (e.g. "ollama") must
        # create a new file instead of merging an unrelated photo into it.
        existing = BaseCaptureOutput(
            category="Tech_Notes", suggested_filename="ollama-native",
            markdown_content="Notes about Ollama's native tokenize endpoint.",
            key_signals=["ollama", "tokenize"], confidence=0.9,
            requires_new_category=False,
        )
        p_existing = write_to_vault(existing, vault_root=vault, scratchpad_folder=SP)

        image_capture = BaseCaptureOutput(
            category="Tech_Notes", suggested_filename="ollama-native",
            markdown_content="A golden retriever puppy standing on grass.",
            key_signals=["ollama"], confidence=0.9,
            requires_new_category=False,
        )
        p_image = write_to_vault(
            image_capture, vault_root=vault, scratchpad_folder=SP,
            source_metadata={"image_embed": "![[img-dog.png]]", "vision_model": "llava"},
        )
        assert p_image != p_existing, "single shared tag must not merge an image capture"
        assert "golden retriever" in p_image.read_text(encoding="utf-8")
        assert "golden retriever" not in p_existing.read_text(encoding="utf-8")
        print(f"[T20b] image capture 2-tag merge threshold  PASS  -> {p_image.name}")

        # T21: route_failed_vision writes a flagged scratchpad note without
        # ever touching the classifier, and never leaks the raw image bytes
        # path into the body -- only the embed and the human-readable reason.
        p21 = route_failed_vision(
            {
                "vision_failure_reason": "vision model 'llava' could not describe the image",
                "image_embed": "![[img-20260619-e940f820.png]]",
            },
            vault_root=vault,
            scratchpad_folder=SP,
        )
        assert p21.exists()
        assert SP in str(p21)
        text21 = p21.read_text(encoding="utf-8")
        assert "needs_vision_retry: true" in text21
        assert "status: needs_review" in text21
        assert "![[img-20260619-e940f820.png]]" in text21
        assert "vision model 'llava' could not describe the image" in text21
        print(f"[T21] route_failed_vision  PASS  -> {p21.name}")

        # T22: route_failed_vision emits a WARN log line containing the
        # actual failure reason, so the real cause is visible in the
        # process log instead of being buried only in the scratchpad note.
        import contextlib
        import io as _io

        captured = _io.StringIO()
        with contextlib.redirect_stdout(captured):
            route_failed_vision(
                {
                    "vision_failure_reason": "Could not reach Ollama at http://localhost:11434 (HTTP Error 404: Not Found).",
                },
                vault_root=vault,
                scratchpad_folder=SP,
            )
        log_output = captured.getvalue()
        assert "WARN" in log_output, log_output
        assert "Could not reach Ollama at http://localhost:11434 (HTTP Error 404: Not Found)." in log_output, log_output
        print("[T22] route_failed_vision WARN log includes failure reason  PASS")

    print("\nAll storage_engine.py smoke tests passed.")

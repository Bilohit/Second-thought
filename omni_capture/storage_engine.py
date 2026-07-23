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

import logging
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from models import CaptureOutput
from config import DEFAULT_VAULT_ROOT, get_config

# dedup.py / merge.py / scratchpad.py extraction (see docs/ROADMAP.md "Split
# storage_engine.py into dedup.py / merge.py / scratchpad.py"). storage_engine.py
# stays the orchestration entry point (write_to_vault) and re-exports these names
# so existing `from storage_engine import route_failed_vision` etc. call sites
# (main.py, server.py, tests) keep working unchanged.
from dedup import (  # noqa: F401  (re-exported for backward-compatible imports)
    _content_hash,
    _dedup_index_path,
    _dedup_lock_path,
    _load_dedup_index,
    _normalize_content,
    _normalize_url,
    _save_dedup_index,
    _vault_lock,
    check_duplicate,
    register_in_dedup_index,
)
from merge import (  # noqa: F401  (re-exported for backward-compatible imports)
    MERGE_MIN_SHARED_TAGS,
    MERGE_MIN_TAG_JACCARD,
    MERGE_SEMANTIC_THRESHOLD,
    _append_general,
    _is_same_topic,
    _merge_lock_path,
    _read_note_tags,
    find_merge_target,
)
from scratchpad import (  # noqa: F401  (re-exported for backward-compatible imports)
    _CATEGORY_DEFAULT_STATUS,
    _extract_frontmatter_field,
    _find_scratchpad_item,
    _rewrite_frontmatter_for_approval,
    _scratchpad_path,
    approve_scratchpad_item,
    discard_scratchpad_item,
    get_scratchpad_item_text,
    list_scratchpad,
    route_failed_llm,
    route_failed_vision,
    route_to_scratchpad,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Captures below this confidence threshold go to the scratchpad for review.
# Kept as the fallback default; the live value is read from config at call time.
SCRATCHPAD_CONFIDENCE_THRESHOLD: float = 0.6


def _confidence_threshold() -> float:
    """Live confidence floor from config, falling back to the module default."""
    try:
        from config import get_config
        return float(get_config().capture.confidence_threshold)
    except Exception:
        return SCRATCHPAD_CONFIDENCE_THRESHOLD

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
# Category description generation (LLM-backed, fail-soft)
# ---------------------------------------------------------------------------

_CATEGORY_DESC_MAX_CHARS = 500


def write_category_description(cat_dir: Path, description: Optional[str]) -> Optional[str]:
    """
    Merge a 'description' value into <cat_dir>/.category.toml, preserving any
    other keys already in that file. Pass None or "" to clear the key.

    Shared by the manual description-edit endpoint and the auto-describe
    path so both write through the same toml read/merge/write logic.
    Returns the value actually stored (None if cleared).
    """
    import tomlkit

    desc = description.strip()[:_CATEGORY_DESC_MAX_CHARS] if description else None

    config_file = cat_dir / ".category.toml"
    existing: dict = read_category_config(cat_dir) if config_file.exists() else {}

    if not desc:
        existing.pop("description", None)
    else:
        existing["description"] = desc

    if existing:
        doc = tomlkit.document()
        for k, v in existing.items():
            doc.add(k, v)  # type: ignore[arg-type]
        config_file.write_text(tomlkit.dumps(doc), encoding="utf-8")
    elif config_file.exists():
        config_file.unlink()

    return desc


def generate_category_description(name: str, sample_text: Optional[str] = None) -> Optional[str]:
    """
    Ask the local LLM for a single concise (<=120 char) routing description
    for a folder called `name`, optionally grounded in `sample_text`.

    Fail-soft: any error (Ollama down, timeout, bad output) returns None
    rather than raising, so callers can just skip writing a description.
    """
    try:
        from config import get_config
        from llm_engine import summarize

        cfg = get_config()
        instruction = (
            "You are naming the routing rule for a folder in a personal note vault. "
            f"Write ONE concise sentence (under 120 characters) describing what kind of "
            f"content belongs in a folder called '{name}'. "
            "No preamble, no quotes, just the sentence."
        )
        text = sample_text.strip()[:1500] if sample_text else f"Folder name: {name}"

        result = summarize(
            text,
            instruction=instruction,
            base_url=cfg.ollama.base_url,
            model=cfg.ollama.model,
            temperature=0.2,
            max_retries=1,
        )
        result = result.strip().strip('"').strip("'")
        return result[:_CATEGORY_DESC_MAX_CHARS] if result else None
    except Exception:
        logger.warning("generate_category_description('%s') failed", name, exc_info=True)
        return None


def suggest_category_names(sample_text: str, existing_names: List[str]) -> List[str]:
    """
    Ask the local LLM for 2-3 generalized, reusable folder names suited to
    `sample_text`, excluding anything already in `existing_names`.

    Fail-soft: any error returns [].
    """
    try:
        from config import get_config
        from llm_engine import summarize

        cfg = get_config()
        existing_str = ", ".join(existing_names) if existing_names else "(none yet)"
        instruction = (
            "Suggest 2-3 short, general, reusable folder names for organizing notes "
            "in a personal knowledge vault, based on the content below. "
            f"Do NOT reuse any of these existing folder names: {existing_str}. "
            "Respond with ONLY the folder names, one per line, no numbering, "
            "no punctuation, no explanation."
        )
        text = sample_text.strip()[:1500]
        if not text:
            return []

        result = summarize(
            text,
            instruction=instruction,
            base_url=cfg.ollama.base_url,
            model=cfg.ollama.model,
            temperature=0.3,
            max_retries=1,
        )

        existing_lower = {n.strip().lower() for n in existing_names}
        seen: set = set()
        suggestions: List[str] = []
        for line in result.splitlines():
            cand = line.strip().strip("-*•").strip().strip('"').strip("'").strip()
            if not cand or len(cand) > 40:
                continue
            key = cand.lower()
            if key in existing_lower or key in seen:
                continue
            seen.add(key)
            suggestions.append(cand)
            if len(suggestions) >= 3:
                break
        return suggestions
    except Exception:
        return []


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
    vault_root: Optional[Path] = None,
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
    if vault_root is not None:
        try:
            from tag_vocab import load_vocab, normalize_tags
            from index_writer import get_db_path
            tags = normalize_tags(tags, load_vocab(get_db_path(vault_root)))
        except Exception:
            pass  # vocab normalization is best-effort; raw tags are still valid
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
    vault_root: Optional[Path] = None,
) -> None:
    content = body_content if body_content is not None else output.markdown_content
    front = _build_frontmatter(output, source_url, scratchpad=scratchpad, note_id=note_id,
                                extra_frontmatter=extra_frontmatter, vault_root=vault_root)
    path.write_text(front + content, encoding="utf-8")


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

# SYNC-03: the transcript region needs its own stable sentinel for the same reason the summary
# does. finalize_youtube_note used to locate the transcript by the literal heading "\n## Transcript";
# rename or postprocess that heading and the lookup returned -1, `after` became "", and the ENTIRE
# transcript was replaced by the summary. New notes carry this marker; the heading lookup stays as a
# legacy fallback for notes written before it, and when NEITHER is found the summary is APPENDED
# rather than truncating anything.
_YOUTUBE_TRANSCRIPT_SENTINEL = "<!-- ST:TRANSCRIPT -->"


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
        f"{_YOUTUBE_TRANSCRIPT_SENTINEL}\n"
        "## Transcript\n"
        f"{transcript_md}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def create_voice_note(
    title: Optional[str],
    transcript_md: str,
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
) -> Path:
    """
    Sibling of create_youtube_note for long voice recordings: write the full,
    untranscribed-loss transcript to a real note immediately, before any LLM
    call, with a placeholder summary region marked by
    _YOUTUBE_SUMMARY_SENTINEL so finalize_youtube_note can be reused as-is.

    Voice notes have no dedicated category config (unlike YouTube's
    youtube_cfg.folder_name), so they land in the scratchpad like other
    fail-soft placeholder routes (see route_failed_vision).
    """
    init_vault(vault_root, scratchpad_folder)

    heading = title or f"Voice note {datetime.now():%Y-%m-%d %H:%M}"
    stem = _youtube_title_stem(heading, max_chars=80)
    base_path = _scratchpad_path(vault_root, scratchpad_folder) / (stem + ".md")
    path = _unique_file_path(base_path)

    now = datetime.now().isoformat(timespec="seconds")
    content = (
        "---\n"
        f"created: {now}\n"
        f"category: {scratchpad_folder}\n"
        "status: summarizing\n"
        "tags: []\n"
        "---\n\n"
        f"# {heading}\n\n"
        "## Summary\n"
        f"{_YOUTUBE_SUMMARY_SENTINEL}\n"
        "⏳ Summarizing transcript…\n\n"
        f"{_YOUTUBE_TRANSCRIPT_SENTINEL}\n"
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
        # SYNC-03: anchor on the transcript sentinel first, fall back to the literal heading for
        # notes written before it existed. If NEITHER is found the tail is unknown, so keep the
        # whole remainder and append the summary — never silently truncate a transcript.
        transcript_idx = text.find(_YOUTUBE_TRANSCRIPT_SENTINEL, sentinel_idx)
        if transcript_idx == -1:
            transcript_idx = text.find("\n## Transcript", sentinel_idx)
        if transcript_idx == -1:
            new_text = text.rstrip() + "\n\n## Summary\n" + processed_summary + "\n"
        else:
            before = text[:sentinel_idx]
            after = text[transcript_idx:]
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
    floor = _confidence_threshold()
    if output.confidence < floor:
        output.confidence = max(output.confidence, floor)

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
    threshold = _confidence_threshold()
    if output.confidence < threshold or output.requires_new_category:
        reason = (
            f"confidence={round(output.confidence, 2)} < {threshold}"
            if output.confidence < threshold
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

    # Voice notes: every recording is its own note. The LLM reuses slugs for
    # similar recordings (observed: tomorrow-reminder.md created twice then
    # appended), and smart-merge/append silently folded new recordings into
    # old ones. Timestamped filename guarantees uniqueness; skip merge/append.
    if source_metadata and source_metadata.get("audio_path"):
        from datetime import datetime as _dt
        stem = _safe_stem(output.suggested_filename)
        path = vault_root / cat / f"{stem}-{_dt.now():%Y%m%d-%H%M%S-%f}.md"
        _write_new_file(path, output, source_url, body_content=linked_content,
                        extra_frontmatter=extra_fm, vault_root=vault_root)
        print(f"[StorageEngine] created (voice, unique): {path.relative_to(vault_root)}")
        register_in_dedup_index(output.markdown_content, source_url, vault_root, path)
        return path

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
            _append_general(path, linked_content, vault_root)
            action = "appended (smart-merge)"
        else:
            _write_new_file(path, output, source_url, body_content=linked_content,
                            extra_frontmatter=extra_fm, vault_root=vault_root)
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
            _append_general(path, linked_content, vault_root)
            action = "appended (general)"
        else:
            path = _unique_file_path(base_path)
            _write_new_file(path, output, source_url, body_content=linked_content,
                            extra_frontmatter=extra_fm, vault_root=vault_root)
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

"""
storage_engine.py  -- Step 4: Storage Engine

Projects edition (Projects S1, 2026-08-01, s125)
------------------------------------------------
The folder-name `category` concept is retired.  A note's grouping is the
`#project@<name>` BODY tag (data-model-and-contracts.md v3.1 §1.3), resolved
once through `project_registry.resolve_project`.  The directory a capture
lands in is `projects.note_dir_for(resolved)` -- the project's own folder when
the tag resolves, `_loose/` when it does not.  Landing in `_loose/` is a
SUCCESS, not a failure: a dangling, invalid, absent or not-yet-synced project
name all read as loose, and the note is still written, still at depth 1.

Flat frontmatter schema
-----------------------
All notes share the same base frontmatter fields.  Per-project YAML schema
fields do not exist -- one consistent structure that Dataview can query
uniformly.

Scratchpad routing
------------------
Low-confidence (<SCRATCHPAD_CONFIDENCE_THRESHOLD) or unrecognised captures
(requires_new_category=True) are written to the configured scratchpad folder
with status: needs_review and a unique note_id for later manual review.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from models import CaptureOutput
from config import DEFAULT_VAULT_ROOT, get_config
from machine_tags import apply_trailing_tags_line
from projects import note_dir_for, parse_project_tag
from project_registry import load as _load_registry, resolve_project

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

# Filler/stop words dropped when shortening LLM-suggested filenames.
_FILENAME_STOPWORDS: frozenset = frozenset({
    "a", "an", "the", "of", "to", "for", "with", "and", "or", "but", "in",
    "on", "at", "by", "from", "how", "guide", "notes", "note", "this",
    "that", "is", "are", "into", "about", "your", "my",
})


# ---------------------------------------------------------------------------
# Project resolution  (the single grouping rule)
# ---------------------------------------------------------------------------

def _project_str(output: CaptureOutput) -> Optional[str]:
    """The engine's project choice as a plain string, or None. build_capture_model
    constrains `project` to a str-Enum of the registry's current names, so unwrap
    .value the same way the retired _category_str did."""
    project = getattr(output, "project", None)
    if project is None:
        return None
    name = project.value if hasattr(project, "value") else str(project)
    return name or None


def _stamp_project_tag(body: str, project: Optional[str]) -> str:
    """Materialise the engine's project choice as the note's `#project@<name>` BODY tag --
    the ONE truth every derived cache (the `project:` frontmatter line, the index column,
    the directory) is computed from (contract v3.1 §1.3).

    Written as ISS-051's machine trailing `tags:` line, which is the only body region a
    machine may write and only on content this device authored -- every caller here is a
    desktop-originated capture the pipeline just produced. A body that already carries a
    project tag is returned byte-identical, so this is idempotent and never overrides a
    tag the user typed.
    """
    if not project or parse_project_tag(body):
        return body
    return apply_trailing_tags_line(body, ["project@" + project])


def _note_dir(output: CaptureOutput, vault_root: Path) -> str:
    """The vault-relative directory a capture files into: its resolved project, else
    `_loose`. Single chokepoint -- merge.find_merge_target resolves through this too, so
    the merge search and the write can never disagree about where a capture belongs.

    An unresolvable project (no tag, invalid name, unregistered, registry not synced yet)
    is LOOSE and is a SUCCESS: the note is still written, still at depth 1.
    """
    body = _stamp_project_tag(output.markdown_content, _project_str(output))
    reg = _load_registry(vault_root)
    return note_dir_for(resolve_project(body, reg), reg)


# The registry's `description` field is the ONE thing that exists nowhere else
# (contract §13); this caps what an LLM-generated one may write into it.
PROJECT_DESC_MAX_CHARS = 500


def generate_project_description(name: str, sample_text: Optional[str] = None) -> Optional[str]:
    """
    Ask the local LLM for a single concise (<=120 char) routing description
    for a project called `name`, optionally grounded in `sample_text`.

    Fail-soft: any error (Ollama down, timeout, bad output) returns None
    rather than raising, so callers can just skip writing a description.
    """
    try:
        from config import get_config
        from llm_engine import summarize

        cfg = get_config()
        instruction = (
            "You are naming the routing rule for a project in a personal note vault. "
            f"Write ONE concise sentence (under 120 characters) describing what kind of "
            f"content belongs in a project called '{name}'. "
            "No preamble, no quotes, just the sentence."
        )
        text = sample_text.strip()[:1500] if sample_text else f"Project name: {name}"

        result = summarize(
            text,
            instruction=instruction,
            base_url=cfg.ollama.base_url,
            model=cfg.ollama.model,
            temperature=0.2,
            max_retries=1,
        )
        result = result.strip().strip('"').strip("'")
        return result[:PROJECT_DESC_MAX_CHARS] if result else None
    except Exception:
        logger.warning("generate_project_description('%s') failed", name, exc_info=True)
        return None


def suggest_project_names(sample_text: str, existing_names: List[str]) -> List[str]:
    """
    Ask the local LLM for 2-3 generalized, reusable project names suited to
    `sample_text`, excluding anything already in `existing_names`.

    A suggestion the registry could not hold is dropped rather than offered: the name
    is simultaneously a tag, a TOML key and a directory name (contract §1.3), so an
    ineligible one would be dangling -- i.e. loose -- the moment the user accepted it.

    Fail-soft: any error returns [].
    """
    try:
        from config import get_config
        from llm_engine import summarize
        from projects import is_valid_project_name

        cfg = get_config()
        existing_str = ", ".join(existing_names) if existing_names else "(none yet)"
        instruction = (
            "Suggest 2-3 short, general, reusable project names for organizing notes "
            "in a personal knowledge vault, based on the content below. "
            "Each name must be letters, digits, '-' or '_' only, starting with a "
            "letter or digit, with NO spaces. "
            f"Do NOT reuse any of these existing project names: {existing_str}. "
            "Respond with ONLY the project names, one per line, no numbering, "
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
            if not cand or len(cand) > 40 or not is_valid_project_name(cand):
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


def _resolve_file_path(output: CaptureOutput, vault_root: Path) -> Path:
    """`<resolved project>/<slug>.md`, or `_loose/<slug>.md`. Always depth 1, so a body's
    `![alt](../_attachments/<id>/<file>)` ref stays valid wherever the note is filed."""
    return vault_root / _note_dir(output, vault_root) / (_safe_stem(output.suggested_filename) + ".md")


def _unique_file_path(base_path: Path) -> Path:
    """Append a 6-char hex ID to the stem to avoid clobbering an existing file."""
    if not base_path.exists():
        return base_path
    short = uuid.uuid4().hex[:6]
    return base_path.with_name(base_path.stem + "-" + short + base_path.suffix)


# ---------------------------------------------------------------------------
# Frontmatter builder  (flat schema — same fields for every category)
# ---------------------------------------------------------------------------

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
    status      'needs_review' (scratchpad only) | absent otherwise
    note_id     scratchpad review ID (scratchpad only)
    source      source URL (when available)
    confidence  LLM self-reported confidence
    rationale   LLM reasoning
    tags        sys/*-prefixed entries of key_signals ONLY -- auto enrichment
                writes a project assignment and nothing else (Projects S1,
                2026-08-01, s125 item 5), so LLM-classification key_signals no
                longer become arbitrary user-facing tags. The sys/ namespace
                is a distinct, pre-existing mechanism (ISS-019): route_failed_
                vision/route_failed_llm (scratchpad.py) still need their
                machine-written sys/vision-failed / sys/llm-failed marker to
                reach frontmatter for retry_engine to find it, and the Tags
                browser already filters the whole sys/ namespace out.
    extra_frontmatter  caller-supplied flat string fields (e.g. needs_vision_retry)
    """
    now = datetime.now().isoformat(timespec="seconds")
    tags = [s for s in output.key_signals if s.startswith("sys/")]

    # v2.2 (2026-07-24, DESKTOP-FIRST): category is NOT written to frontmatter — the folder a
    # capture is filed into IS its category (data-model §1.2). output.category still selects that
    # folder (the filing mechanism, upstream of this builder), it is just no longer duplicated here.
    lines = ["---", f"created: {now}"]

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

    `youtube_cfg.folder_name` is now a PROJECT NAME, not a folder to create: the note is
    stamped with `#project@<folder_name>` and filed wherever that resolves. If the user
    has no such project registered the note is loose -- correct, and still written.
    """
    init_vault(vault_root, scratchpad_folder)

    from config import get_config
    stem = _youtube_title_stem(title, max_chars=get_config().capture.youtube_filename_max_chars)

    now = datetime.now().isoformat(timespec="seconds")
    heading = title or "YouTube Video"
    body = (
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
    body = _stamp_project_tag(body, youtube_cfg.folder_name)
    reg = _load_registry(vault_root)
    note_dir = note_dir_for(resolve_project(body, reg), reg)
    (vault_root / note_dir).mkdir(parents=True, exist_ok=True)
    path = _unique_file_path(vault_root / note_dir / (stem + ".md"))

    content = (
        "---\n"
        f"created: {now}\n"
        f"source: {url}\n"
        "status: summarizing\n"
        "tags: []\n"
        "---\n\n"
        f"{body}"
    )
    path.write_text(content, encoding="utf-8")
    return path


def _attach_staged_audio(vault_root: Path, note_path: Path, audio_staged_path: Optional[Path]) -> None:
    """
    Claim a Whisper temp-audio file as a real vault attachment on *note_path*
    (which must already have a frontmatter `id`, just written to disk) via
    note_editor.add_attachment, then unlink the temp file. Shared by both
    note-write paths that can own a staged voice recording (create_voice_note
    for long recordings, write_to_vault's voice branch for short ones) -- see
    O-9 comment in server.py._run_pipeline_blocking for why the temp file
    must survive until the owning note exists.
    """
    if audio_staged_path is None or not audio_staged_path.exists():
        return
    from note_editor import add_attachment

    add_attachment(
        vault_root,
        str(note_path),
        f"voice{audio_staged_path.suffix}",
        audio_staged_path.read_bytes(),
        expected_mtime=note_path.stat().st_mtime,
    )
    audio_staged_path.unlink(missing_ok=True)


def create_voice_note(
    title: Optional[str],
    transcript_md: str,
    vault_root: Path,
    scratchpad_folder: str = "_scratchpad",
    audio_staged_path: Optional[Path] = None,
) -> Path:
    """
    Sibling of create_youtube_note for long voice recordings: write the full,
    untranscribed-loss transcript to a real note immediately, before any LLM
    call, with a placeholder summary region marked by
    _YOUTUBE_SUMMARY_SENTINEL so finalize_youtube_note can be reused as-is.

    Voice notes have no project of their own (unlike YouTube's
    youtube_cfg.folder_name), so they land in the scratchpad like other
    fail-soft placeholder routes (see route_failed_vision).
    """
    init_vault(vault_root, scratchpad_folder)

    heading = title or f"Voice note {datetime.now():%Y-%m-%d %H:%M}"
    stem = _youtube_title_stem(heading, max_chars=80)
    base_path = _scratchpad_path(vault_root, scratchpad_folder) / (stem + ".md")
    path = _unique_file_path(base_path)

    now = datetime.now().isoformat(timespec="seconds")
    note_id = uuid.uuid4().hex[:26]
    content = (
        "---\n"
        f"id: {note_id}\n"
        f"created: {now}\n"
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

    _attach_staged_audio(vault_root, path, audio_staged_path)

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
    merge_info: Optional[dict] = None,
) -> Path:
    """
    Write/append a CaptureOutput to the vault.

    Routing
    -------
    1. Dedup check        — skip only when an exact duplicate already exists in
                            the *same* project directory this capture resolves to.
    2. Scratchpad routing — low confidence or requires_new_category → scratchpad.
    3. Smart merge        — append into an existing same-topic note when tags match.
    4. Normal write       — append or new file with collision-safe name, in the
                            resolved project's folder or `_loose/`.

    source_metadata, when passed (e.g. an image capture's EnrichedPayload.source_metadata),
    may carry deterministic artifacts (image_embed, transcribed_text) that are
    appended verbatim after the LLM-generated content -- see _build_deterministic_append.
    """
    init_vault(vault_root, scratchpad_folder)
    deterministic_append = _build_deterministic_append(source_metadata)
    extra_fm = None
    if source_metadata and source_metadata.get("source_type"):
        extra_fm = {"source_type": source_metadata["source_type"]}

    project = _project_str(output)
    decided_dir = _note_dir(output, vault_root)

    # 1. Deduplication
    #
    # The dedup index is keyed purely on content, so a re-captured note whose
    # decision has changed project (e.g. the engine now says `research` but an
    # older copy was filed under `_loose`) used to be silently short-circuited
    # back to the stale location — the GUI showed one destination while the file
    # lived in another. Only honour a dedup hit when the indexed note still lives
    # in the directory this capture resolves to; otherwise fall through and write
    # to the correct place, refreshing the index pointer afterwards.
    dup_path = check_duplicate(output.markdown_content, source_url, vault_root)
    if dup_path:
        existing = vault_root / dup_path
        existing_dir = Path(dup_path).parts[0] if Path(dup_path).parts else ""
        if existing.exists() and existing_dir == decided_dir:
            print(f"[StorageEngine] DUPLICATE -- already at {dup_path}. Skipping.")
            return existing
        if existing.exists():
            print(
                f"[StorageEngine] dedup hit at {dup_path} is in "
                f"'{existing_dir}', but this capture resolves to "
                f"'{decided_dir}'. Re-filing to the resolved destination."
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

    # The project folder (or `_loose/`) may not exist yet — a project's directory is
    # created the first time a note is filed into it, never by registering it.
    cat = decided_dir
    (vault_root / cat).mkdir(parents=True, exist_ok=True)

    # 3. Normal write
    base_path = vault_root / cat / (_safe_stem(output.suggested_filename) + ".md")
    path = base_path

    linked_content = _postprocess_content(_try_inject_wikilinks(output, path, vault_root))
    if deterministic_append:
        linked_content = linked_content + "\n\n" + deterministic_append
    # The `#project@` body tag is stamped LAST, after every other body transform, so the
    # machine trailing line stays the final line of the note (ISS-051 §3).
    linked_content = _stamp_project_tag(linked_content, project)

    # Voice notes: every recording is its own note. The LLM reuses slugs for
    # similar recordings (observed: tomorrow-reminder.md created twice then
    # appended), and smart-merge/append silently folded new recordings into
    # old ones. Timestamped filename guarantees uniqueness; skip merge/append.
    if source_metadata and source_metadata.get("audio_path"):
        from datetime import datetime as _dt
        stem = _safe_stem(output.suggested_filename)
        path = vault_root / cat / f"{stem}-{_dt.now():%Y%m%d-%H%M%S-%f}.md"
        voice_extra_fm = dict(extra_fm or {})
        voice_extra_fm["id"] = uuid.uuid4().hex[:26]
        _write_new_file(path, output, source_url, body_content=linked_content,
                        extra_frontmatter=voice_extra_fm, vault_root=vault_root)
        _staged = source_metadata.get("audio_staged_path")
        _attach_staged_audio(vault_root, path, Path(_staged) if _staged else None)
        print(f"[StorageEngine] created (voice, unique): {path.relative_to(vault_root)}")
        register_in_dedup_index(output.markdown_content, source_url, vault_root, path)
        return path

    if not path.exists():
        # Smart merge: look for a different existing note in the same directory
        # that is confidently about the same topic. Image captures require
        # 2+ shared tags on the semantic-match branch too (d05) — matches the
        # existing-file path's own guard below.
        is_image = bool(source_metadata and (source_metadata.get("image_embed") or source_metadata.get("vision_model")))
        merge_target = find_merge_target(
            output, vault_root,
            enable_semantic_merge=enable_semantic_merge,
            embed_base_url=embed_base_url,
            embed_model=embed_model,
            min_shared_tags=2 if is_image else 1,
        )
        if merge_target is not None:
            path = merge_target
            _append_general(path, linked_content, vault_root)
            action = "appended (smart-merge)"
            # s114/d05: a smart merge folds this capture into a DIFFERENT note than the one its own
            # filename would have produced -- the user asked for a capture and got an edit to
            # something else. That happened silently, and a clipboard image ended up inside an
            # unrelated text capture with no signal anywhere. Report it so the caller's toast can
            # say "Merged into X" instead of the usual "Saved". Only this branch is surprising:
            # "appended (general)" below is the same note the filename already named.
            if merge_info is not None:
                merge_info["merged_into"] = path.name
        else:
            _write_new_file(path, output, source_url, body_content=linked_content,
                            extra_frontmatter=extra_fm, vault_root=vault_root)
            action = "created"
    else:
        # File already exists — append when it's the same topic. Image captures
        # require 2+ shared tags, not just 1: a vision description sharing a
        # single incidental tag with an unrelated note is too weak a signal
        # to silently merge a photo into it.
        is_image = bool(source_metadata and (source_metadata.get("image_embed") or source_metadata.get("vision_model")))
        min_shared = 2 if is_image else 1
        if _is_same_topic(base_path, output.key_signals, min_shared_tags=min_shared):
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

        # A registry with one real project. The project's DIRECTORY is not created here:
        # it appears the first time a note is filed into it.
        import project_registry as _reg
        _reg.save(vault, {"schema": 1, "projects": {
            "Tech": {"description": "Code, tools, and engineering notes."},
        }})

        from models import build_capture_model, CaptureOutput as BaseCaptureOutput

        def _cap(project=None, **kw):
            kw.setdefault("key_signals", [])
            kw.setdefault("confidence", 0.9)
            kw.setdefault("requires_new_category", False)
            out = BaseCaptureOutput(**kw)
            out.project = project
            return out

        # T1: _note_dir -- a registered project resolves to its own folder
        assert _note_dir(_cap("Tech", suggested_filename="x", markdown_content="body"), vault) == "Tech"

        # T2: an UNREGISTERED project name is dangling -> loose, never an error
        assert _note_dir(_cap("Nope", suggested_filename="x", markdown_content="body"), vault) == "_loose"

        # T3: no project at all -> loose
        assert _note_dir(_cap(None, suggested_filename="x", markdown_content="body"), vault) == "_loose"

        # T4: a project tag ALREADY in the body wins, and stamping is idempotent
        already = "notes\n\ntags: #project@Tech\n"
        assert _stamp_project_tag(already, "Other") == already
        print("[T1-T4] project resolution + tag stamping  PASS")

        # T5: build_capture_model from models
        Model = build_capture_model(["Tech"])
        assert hasattr(Model, "model_fields")
        print(f"[T5] build_capture_model  PASS  (fields: {list(Model.model_fields)})")

        # T6: write a note into a resolved project; the body carries the tag
        t6 = _cap("Tech", suggested_filename="asyncio-notes",
                  markdown_content="async def main(): ...",
                  key_signals=["python", "async"], confidence=0.92)
        p6 = write_to_vault(t6, vault_root=vault, scratchpad_folder=SP)
        assert p6.exists()
        assert p6.parent.name == "Tech", p6
        txt6 = p6.read_text(encoding="utf-8")
        assert "tags: #project@Tech" in txt6
        assert "CATEGORY_SCHEMA" not in txt6  # flat schema check
        print(f"[T6] write_to_vault (new note)  PASS  -> {p6.name}")

        # T6b: a capture whose project does not resolve lands in _loose/ and that is a
        # SUCCESS -- the whole point of the projects rework (OF-6's failure class is gone).
        t6b = _cap("Unregistered", suggested_filename="drifting-note",
                   markdown_content="Content for a project nobody registered.",
                   confidence=0.92)
        p6b = write_to_vault(t6b, vault_root=vault, scratchpad_folder=SP)
        assert p6b.exists() and p6b.parent.name == "_loose", p6b
        print(f"[T6b] unresolved project -> _loose  PASS  -> {p6b.name}")

        # T7: deduplication
        p6c = write_to_vault(t6, vault_root=vault, scratchpad_folder=SP)
        assert str(p6) == str(p6c)
        print("[T7] deduplication  PASS")

        # T8: low confidence -> scratchpad
        t8 = _cap("Tech", suggested_filename="mystery-thing",
                  markdown_content="I have no idea what this is unique abc.",
                  key_signals=["unknown"], confidence=0.4)
        p8 = write_to_vault(t8, vault_root=vault, scratchpad_folder=SP)
        assert SP in str(p8)
        assert "status: needs_review" in p8.read_text(encoding="utf-8")
        print(f"[T8] scratchpad routing (low confidence)  PASS  -> {p8.name}")

        # T9: requires_new_category -> scratchpad
        t9 = _cap("Tech", suggested_filename="new-thing-unique",
                  markdown_content="This is a brand new topic entirely unique xyz.",
                  confidence=0.8)
        t9.requires_new_category = True
        p9 = write_to_vault(t9, vault_root=vault, scratchpad_folder=SP)
        assert SP in str(p9)
        print("[T9] scratchpad routing (requires_new_category)  PASS")

        # T10: list_scratchpad and approve into a project
        items = list_scratchpad(vault, SP)
        assert len(items) >= 2
        note_id_8 = items[0]["note_id"]
        approved = approve_scratchpad_item(note_id_8, vault, SP, target_project="Tech")
        assert approved.exists()
        assert approved.parent.name == "Tech", approved
        assert "needs_review" not in approved.read_text(encoding="utf-8")
        assert "tags: #project@Tech" in approved.read_text(encoding="utf-8")
        print(f"[T10] approve_scratchpad_item  PASS  -> {approved.name}")

        # T11: discard
        items_after = list_scratchpad(vault, SP)
        note_id_9 = items_after[0]["note_id"]
        discard_scratchpad_item(note_id_9, vault, SP)
        assert all(i["note_id"] != note_id_9 for i in list_scratchpad(vault, SP))
        print("[T11] discard_scratchpad_item  PASS")

        # T12: approving with no target lands the note in _loose/, never at the vault root
        items12 = list_scratchpad(vault, SP)
        if items12:
            approved12 = approve_scratchpad_item(items12[0]["note_id"], vault, SP)
            assert approved12.parent.name == "_loose", approved12
            print("[T12] approve with no project -> _loose  PASS")

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
        p19 = p17.parent / "no-sentinel.md"
        p19.write_text("---\nstatus: summarizing\ntags: []\n---\n\n# Title\n\nNo sentinel here.\n", encoding="utf-8")
        finalize_youtube_note(p19, "Recovered summary.", vault)
        text19 = p19.read_text(encoding="utf-8")
        assert "## Summary" in text19
        assert "Recovered summary." in text19
        print("[T19] finalize_youtube_note (missing sentinel)  PASS")

        # T20: write_to_vault appends deterministic image_embed/transcribed_text
        # verbatim after the LLM-generated markdown_content (H3/A1 seam).
        t20 = _cap("Tech", suggested_filename="screenshot-note",
                   markdown_content="The LLM's paraphrased description of the screenshot.",
                   key_signals=["screenshot"])
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
        # The target is hand-written WITH its tags: since s125 item 5, a pipeline
        # capture no longer persists key_signals as frontmatter tags, so a note the
        # write path produced has none for a later capture to be judged against
        # (and an untagged target is deliberately permissive -- _is_same_topic).
        p_existing = vault / "Tech" / "ollama-native.md"
        p_existing.parent.mkdir(parents=True, exist_ok=True)
        p_existing.write_text(
            "---\ncreated: 2026-08-01T10:00:00\ntags:\n  - ollama\n  - tokenize\n---\n"
            "Notes about Ollama's native tokenize endpoint.\n",
            encoding="utf-8",
        )

        image_capture = _cap("Tech", suggested_filename="ollama-native",
                             markdown_content="A golden retriever puppy standing on grass.",
                             key_signals=["ollama"])
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

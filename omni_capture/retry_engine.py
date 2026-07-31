"""
retry_engine.py -- enrichment retry engine for needs_llm_retry scratchpad placeholders.

route_failed_llm() has always flagged a failed capture `needs_llm_retry: true` and
preserved the raw text -- but nothing has ever consumed that flag. retry_pending()
is the consumer: it re-runs the LLM decision stage over each flagged placeholder
still in _scratchpad and re-files it into a real category, like a fresh capture.

SAFETY GATE (this module's whole safety argument): a placeholder is repaired ONLY
when is_retryable() AND placeholder_matches() both hold. The flag alone is not proof
the body is untouched -- repair deletes the placeholder and lets the LLM re-author
the content, so a body the user has started editing must never enter that path.

The banner prefix alone CANNOT prove that: it is a prefix, and an appended edit
leaves it intact. Two signals close the hole:

  * `retry_sig` -- route_failed_llm stamps sha1(body) into the placeholder's
    (machine-owned) frontmatter. Authoritative, no clock or mtime involved.
  * legacy fallback -- placeholders written before retry_sig existed carry no sig,
    so they fall back to "banner intact AND the file has not been written since it
    was created" (mtime vs the `created` stamp, LEGACY_EDIT_SLACK_S of slack). The
    failure modes are asymmetric on purpose: a copy/restore/sync that rewrites mtime
    reads as EDITED and is skipped; reading UNTOUCHED on a genuinely edited file
    would take an edit inside the same two minutes as the capture failing.

A body that fails either check is skipped and left byte-identical, forever.
ponytail: skipped placeholders are resolvable only by hand (Inbox Approve, which
moves + embeds without rewriting the body). If that ever proves too blunt, the
upgrade is a conservative repair mode -- strip the verified banner, keep every
remaining byte verbatim, use the LLM for category/title/tags only.
"""
from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from frontmatter import strip_frontmatter
from scratchpad import _extract_frontmatter_field, _scratchpad_path

# Mirrors route_failed_llm()'s exact body shape (scratchpad.py:135):
#   f"> [!warning] LLM enrichment failed\n> {reason}\n\n{enriched_text}\n"
# ponytail: `.` does not match \n, so a multi-line failure reason fails the match
# and its capture is skipped rather than repaired. That is the safe direction --
# widen to a multi-line reason block only if a real reason ever wraps.
_PLACEHOLDER_RE = re.compile(r"\A> \[!warning\] LLM enrichment failed\n> .*\n\n")

DEFAULT_MAX_ITEMS = 5

# How far a legacy (pre-retry_sig) placeholder's mtime may sit past its `created`
# stamp and still count as untouched. `created` has second resolution and the file
# is written immediately after it is computed, so this is pure slack.
LEGACY_EDIT_SLACK_S = 120.0


def body_signature(body: str) -> str:
    """Tamper evidence for a scratchpad placeholder body. Written into frontmatter
    by route_failed_llm, re-checked here before any repair."""
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]


def is_retryable(text: str) -> bool:
    """True when a scratchpad note's frontmatter still carries needs_llm_retry: true."""
    return _extract_frontmatter_field(text, "needs_llm_retry") == "true"


def placeholder_matches(text: str, path: Optional[Path] = None) -> bool:
    """True when the body is still provably route_failed_llm's untouched placeholder.

    Requires the banner prefix AND a matching `retry_sig`. Placeholders written
    before retry_sig existed have no sig: they pass only when `path` is supplied and
    the file has not been written since its `created` stamp (see module docstring).
    Without `path`, a legacy placeholder cannot be proven untouched and returns False.
    """
    body = strip_frontmatter(text)
    if not _PLACEHOLDER_RE.match(body):
        return False

    sig = _extract_frontmatter_field(text, "retry_sig")
    if sig:
        return sig == body_signature(body)

    return _legacy_untouched(text, path)


def _legacy_untouched(text: str, path: Optional[Path]) -> bool:
    """Fallback for pre-retry_sig placeholders: the file must not have been written
    since it was created. Any unreadable/absent stamp counts as EDITED (skip)."""
    if path is None:
        return False
    created = _extract_frontmatter_field(text, "created")
    if not created:
        return False
    try:
        created_ts = datetime.fromisoformat(created).timestamp()
        return (path.stat().st_mtime - created_ts) <= LEGACY_EDIT_SLACK_S
    except (ValueError, OSError):
        return False


def _extract_original_text(body: str) -> str:
    """Strip route_failed_llm()'s warning-banner prefix off an already-verified
    placeholder body, returning the raw enriched_text it wrapped."""
    m = _PLACEHOLDER_RE.match(body)
    if not m:
        raise ValueError("body is not a route_failed_llm placeholder")
    raw = body[m.end():]
    return raw[:-1] if raw.endswith("\n") else raw


def _default_ollama_reachable() -> bool:
    """Reuses server.py's own probe instead of a second health check."""
    from server import _ollama_reachable
    from llm_engine import _ollama_setting
    base_url = _ollama_setting("OLLAMA_BASE_URL", "base_url", "http://localhost:11434").rstrip("/")
    return _ollama_reachable(base_url)


def retry_pending(
    vault: Path,
    deps: Optional[dict] = None,
    scratchpad_folder: str = "_scratchpad",
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict:
    """Re-run the LLM decision stage for every needs_llm_retry placeholder still in
    the scratchpad, BOUNDED to `max_items` repairs per call (s104 precedent: an
    unbounded retry loop produced repeated failures with no ceiling).

    Preconditions, checked once before touching any file:
      * >=1 real category folder exists -- run_llm_engine() hard-refuses an empty
        category_descriptions dict (llm_engine.py:322-326), and a retry must never
        CREATE a category folder to satisfy it.
      * Ollama is reachable.

    Failures are contained PER NOTE: one bad placeholder is logged and left exactly
    as it was (still needs_llm_retry: true) for the next call -- never aborts the pass.
    """
    deps = deps or {}
    is_ollama_reachable = deps.get("is_ollama_reachable", _default_ollama_reachable)

    summary = {"attempted": 0, "recovered": 0, "skipped": 0, "failed": 0}

    sp = _scratchpad_path(vault, scratchpad_folder)
    if not sp.exists():
        return summary

    from storage_engine import discover_categories
    if not discover_categories(vault, scratchpad_folder):
        print("[RetryEngine] no category folders yet -- skipping retry pass.", flush=True)
        return summary

    if not is_ollama_reachable():
        print("[RetryEngine] Ollama unreachable -- skipping retry pass.", flush=True)
        return summary

    from storage_engine import build_category_descriptions, write_to_vault as _default_write_to_vault
    from llm_engine import run_llm_engine as _default_run_llm_engine
    from vector_store import index_note as _default_index_note, remove_from_index
    from index_writer import remove_capture_by_path
    from capture_log import log_capture as _default_log_capture
    from config import get_config
    from models import EnrichedPayload

    run_llm_engine = deps.get("run_llm_engine", _default_run_llm_engine)
    write_to_vault = deps.get("write_to_vault", _default_write_to_vault)
    index_note = deps.get("index_note", _default_index_note)
    log_capture = deps.get("log_capture", _default_log_capture)

    cfg = get_config()
    category_descriptions = build_category_descriptions(vault, scratchpad_folder)

    for f in sorted(sp.iterdir()):
        if summary["attempted"] >= max_items:
            break
        if not (f.is_file() and f.suffix == ".md"):
            continue

        text = f.read_text(encoding="utf-8", errors="ignore")
        if not is_retryable(text):
            continue
        if not placeholder_matches(text, f):
            # Flag is set but the body has been hand-edited -- never touch it again.
            summary["skipped"] += 1
            continue

        summary["attempted"] += 1
        try:
            body = strip_frontmatter(text)
            source_url = _extract_frontmatter_field(text, "source")
            raw_text = _extract_original_text(body)

            enriched = EnrichedPayload(
                raw_input=raw_text,
                input_type="url" if source_url else "text",
                enriched_text=raw_text,
                source_url=source_url,
            )

            output = run_llm_engine(
                enriched,
                category_descriptions=category_descriptions,
                max_retries=cfg.capture.llm_max_retries,
                temperature=cfg.capture.llm_temperature,
                scrutiny=cfg.capture.llm_scrutiny,
            )

            written_path = write_to_vault(
                output,
                source_url=source_url,
                vault_root=vault,
                scratchpad_folder=scratchpad_folder,
                enable_semantic_merge=cfg.vector.enabled,
                embed_base_url=cfg.ollama.base_url,
                embed_model=cfg.vector.embed_model,
            )

            if cfg.vector.enabled:
                try:
                    note_text = Path(written_path).read_text(encoding="utf-8", errors="ignore")
                    index_note(vault, Path(written_path), note_text, cfg.ollama.base_url, cfg.vector.embed_model)
                except Exception as index_exc:
                    print(f"[RetryEngine] index write failed (note still saved): {index_exc}", file=sys.stderr)

            # write_to_vault picked a fresh path in the real category -- the OLD
            # placeholder is a different file and needs its own cleanup, mirroring
            # discard_scratchpad_item's cleanup (scratchpad.py).
            try:
                remove_from_index(vault, f)
                remove_capture_by_path(vault, f)
            except Exception as cleanup_exc:
                print(f"[RetryEngine] index cleanup on retry error: {cleanup_exc}", file=sys.stderr)
            f.unlink()

            log_capture(output, enriched, str(written_path), cfg.ollama.model)
            print(f"[RetryEngine] recovered {f.name} -> {written_path}", flush=True)
            summary["recovered"] += 1
        except Exception as exc:
            print(f"[RetryEngine] retry failed for {f.name}: {exc}", file=sys.stderr)
            summary["failed"] += 1

    return summary


if __name__ == "__main__":
    _body = "> [!warning] LLM enrichment failed\n> Ollama connection refused\n\nraw body\n"
    _ph = f"---\nneeds_llm_retry: true\nretry_sig: {body_signature(_body)}\ntags: []\n---\n{_body}"
    assert is_retryable(_ph) is True
    assert placeholder_matches(_ph) is True
    assert _extract_original_text(strip_frontmatter(_ph)) == "raw body"
    # The hole this module exists to close: an appended edit keeps the banner prefix
    # intact, so only the signature catches it.
    assert placeholder_matches(_ph + "hand edit\n") is False
    assert is_retryable(_ph + "hand edit\n") is True
    print("retry_engine self-check OK")

"""
enrichment_router.py
--------------------
Step 2 — Enrichment Router (Preprocessing)

Receives an InputPayload from the Interceptor, identifies the data shape
via regex, fetches/extracts the richest possible text, and returns an
EnrichedPayload ready for the LLM Decision Engine.

Supported routes
  url_web       → readability-lxml article extraction + tracking-param strip
  url_github    → GitHub public API (name, description, language, topics)
  url_youtube   → youtube-transcript-api captions (raw + code-block filtered)
  image         → placeholder → local LLaVA vision model
  audio         → placeholder → local Whisper model
  text          → pass-through (no enrichment needed)
"""

from __future__ import annotations

import html
import json
import re
import threading
import urllib.parse
import urllib.request
from typing import Optional

from models import EnrichedPayload
from interceptor import InputPayload


# ── URL classifier patterns ───────────────────────────────────────────────────
_GITHUB_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/?#]+)",
    re.IGNORECASE,
)
_YOUTUBE_RE = re.compile(
    r"^https?://(?:www\.)?(?:"
    r"youtube\.com/watch\?.*v=(?P<vid1>[^&]+)"
    r"|youtu\.be/(?P<vid2>[^?]+)"
    r")",
    re.IGNORECASE,
)

# Tracking parameters commonly appended to URLs
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "mc_cid", "mc_eid",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_tracking_params(url: str) -> str:
    """Remove known tracking query parameters from a URL."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    clean_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
    new_query = urllib.parse.urlencode(clean_qs, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def _extract_youtube_video_id(url: str) -> Optional[str]:
    m = _YOUTUBE_RE.match(url)
    if not m:
        return None
    return m.group("vid1") or m.group("vid2")


def _extract_code_blocks_from_transcript(transcript: str) -> str:
    """
    Anti-Tutorial Hell filter.

    The LLM will handle semantic extraction, but we pre-filter the raw
    transcript here by keeping only lines that look like:
      • Shell commands  (start with $, #, %, or common CLI tools)
      • Code-like lines (indented 4+ spaces, or contain =, (, ), {, })
      • Already-fenced blocks (``` ... ```)

    Returns a condensed string so the LLM context stays small.
    """
    CODE_HEURISTIC = re.compile(
        r"^(?:\$\s|#\s|%\s)"                    # shell prompts
        r"|^\s{4,}"                               # 4-space indent
        r"|(?:import |def |class |return |if |for |while )"  # Python keywords
        r"|(?:npm |pip |git |docker |kubectl |brew |apt )"   # CLI tools
        r"|(?:[A-Za-z_]\w*\s*=\s*)"              # assignments
        r"|(?:```)",                              # fenced blocks
        re.MULTILINE,
    )
    lines = transcript.splitlines()
    kept = [ln for ln in lines if CODE_HEURISTIC.search(ln)]
    return "\n".join(kept) if kept else transcript  # fallback: full transcript


# ── Route handlers ────────────────────────────────────────────────────────────

def _enrich_web_url(url: str) -> EnrichedPayload:
    """Use readability-lxml to extract the main article text."""
    try:
        from readability import Document

        clean_url = _strip_tracking_params(url)
        req = urllib.request.Request(
            clean_url,
            headers={"User-Agent": "Mozilla/5.0 (SecondThought/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_html = resp.read()
            content_type = resp.headers.get_content_charset()

        from config import get_config
        max_chars = get_config().capture.web_max_chars

        # readability-lxml's bytes path (get_encoding) uses str regexes against
        # the raw bytes and raises TypeError on this Python version; decoding
        # to str ourselves first bypasses that path entirely (build_doc skips
        # get_encoding when given a str).
        decoded_html = raw_html.decode(content_type or "utf-8", "replace")

        doc = Document(decoded_html)
        # readability returns HTML summary; strip tags then unescape HTML entities
        summary_html = doc.summary()
        plain = re.sub(r"<[^>]+>", " ", summary_html)
        plain = html.unescape(plain)           # &amp; → &, &lt; → <, &#8217; → ', …
        plain = re.sub(r"\s{2,}", " ", plain).strip()[:max_chars]
        title = doc.title()

        return EnrichedPayload(
            raw_input=url,
            input_type="url_web",
            enriched_text=f"# {title}\n\n{plain}",
            source_url=clean_url,
            source_metadata={"title": title, "original_url": url},
        )

    except Exception as exc:
        # Graceful degradation: pass raw URL as text if extraction fails
        return EnrichedPayload(
            raw_input=url,
            input_type="url_web",
            enriched_text=f"[Web extraction failed: {exc}]\n\nURL: {url}",
            source_url=url,
        )


def _enrich_github_url(url: str, match: re.Match) -> EnrichedPayload:
    """Query GitHub public API for repo metadata."""
    owner = match.group("owner")
    repo = match.group("repo").rstrip("/")
    api_url = f"https://api.github.com/repos/{owner}/{repo}"

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "SecondThought/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        enriched = (
            f"# {data.get('full_name', repo)}\n\n"
            f"**Description:** {data.get('description') or 'N/A'}\n"
            f"**Language:** {data.get('language') or 'N/A'}\n"
            f"**Stars:** {data.get('stargazers_count', 0):,}\n"
            f"**Topics:** {', '.join(data.get('topics', [])) or 'N/A'}\n"
            f"**License:** {(data.get('license') or {}).get('name', 'N/A')}\n"
            f"**URL:** {url}\n"
        )
        return EnrichedPayload(
            raw_input=url,
            input_type="url_github",
            enriched_text=enriched,
            source_url=url,
            source_metadata={
                "owner": owner,
                "repo": repo,
                "language": data.get("language"),
                "stars": data.get("stargazers_count"),
            },
        )

    except Exception as exc:
        return EnrichedPayload(
            raw_input=url,
            input_type="url_github",
            enriched_text=f"[GitHub API failed: {exc}]\n\nURL: {url}",
            source_url=url,
        )


_YOUTUBE_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_YOUTUBE_TITLE_SUFFIX_RE = re.compile(r"\s*-\s*YouTube\s*$")


def _fetch_youtube_watch_page_title(url: str) -> Optional[str]:
    """Fallback when oEmbed fails (private/age-restricted/region-locked
    videos, transient errors, etc.): parse <title> from the watch page HTML.
    Dependency-free (urllib only). Never raises."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SecondThought/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body = resp.read().decode(charset, errors="replace")
        match = _YOUTUBE_TITLE_TAG_RE.search(body)
        if not match:
            return None
        title = html.unescape(match.group(1)).strip()
        title = _YOUTUBE_TITLE_SUFFIX_RE.sub("", title).strip()
        return title or None
    except Exception as exc:
        print(f"[EnrichmentRouter] watch-page title fallback failed for {url}: {exc}", flush=True)
        return None


def _fetch_youtube_title(url: str) -> Optional[str]:
    """Best-effort video title via the oEmbed endpoint (no API key required),
    falling back to parsing the watch page <title> when oEmbed fails. Never
    raises -- a title-fetch failure must not abort the capture."""
    try:
        oembed_url = (
            "https://www.youtube.com/oembed?url="
            + urllib.parse.quote(url, safe="")
            + "&format=json"
        )
        req = urllib.request.Request(
            oembed_url, headers={"User-Agent": "SecondThought/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        title = data.get("title")
        if title:
            return title.strip()
    except Exception as exc:
        print(f"[EnrichmentRouter] title fetch failed for {url}: {exc}", flush=True)
    return _fetch_youtube_watch_page_title(url)


def fetch_youtube_transcript(url: str) -> dict:
    """
    Fetch the full, untruncated transcript for a YouTube URL.

    Unlike _enrich_youtube_url (which truncates to youtube_max_chars and
    bundles a heading + code-filter into one blob for the normal LLM-routing
    pipeline), this returns the raw segments and full text so the caller can
    write the complete transcript to a note before any LLM call, and decide
    on chunking/summarization itself.

    Never raises -- on any failure (captions disabled/missing, no en track,
    network error) returns transcript_available=False with an error string.
    """
    video_id = _extract_youtube_video_id(url)
    if not video_id:
        return {
            "video_id": None,
            "title": None,
            "segments": [],
            "full_text": "",
            "transcript_available": False,
            "error": f"Could not extract video ID from URL: {url}",
        }

    title = _fetch_youtube_title(url)

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        fetched = YouTubeTranscriptApi().fetch(
            video_id, languages=["en", "en-US", "en-GB"]
        )
        segments = fetched.to_raw_data()  # -> list[{"text","start","duration"}]
        full_text = " ".join(seg["text"] for seg in segments)

        return {
            "video_id": video_id,
            "title": title,
            "segments": segments,
            "full_text": full_text,
            "transcript_available": True,
            "error": None,
        }

    except Exception as exc:
        print(f"[EnrichmentRouter] transcript fetch failed for {url} (video_id={video_id}): {exc}", flush=True)
        return {
            "video_id": video_id,
            "title": title,
            "segments": [],
            "full_text": "",
            "transcript_available": False,
            "error": str(exc),
        }


def _enrich_youtube_url(url: str) -> EnrichedPayload:
    """Pull full captions and apply the Anti-Tutorial Hell filter."""
    video_id = _extract_youtube_video_id(url)
    if not video_id:
        return EnrichedPayload(
            raw_input=url,
            input_type="url_youtube",
            enriched_text=f"[Could not extract video ID from URL: {url}]",
            source_url=url,
            source_metadata={"transcript_available": False},
        )

    title = _fetch_youtube_title(url)

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        fetched = YouTubeTranscriptApi().fetch(
            video_id, languages=["en", "en-US", "en-GB"]
        )
        transcript_list = fetched.to_raw_data()  # -> list[{"text","start","duration"}]
        from config import get_config
        max_chars = get_config().capture.youtube_max_chars

        full_text = " ".join(seg["text"] for seg in transcript_list)
        code_filtered = _extract_code_blocks_from_transcript(full_text)

        heading = f"# {title}" if title else f"# YouTube Transcript — {url}"
        enriched = (
            f"{heading}\n\n"
            f"## Full Transcript\n{full_text[:max_chars]}\n\n"
            f"## Code / Command Lines (pre-filtered)\n{code_filtered}"
        )
        return EnrichedPayload(
            raw_input=url,
            input_type="url_youtube",
            enriched_text=enriched,
            source_url=url,
            source_metadata={
                "video_id": video_id,
                "segments": len(transcript_list),
                "transcript_available": True,
                "title": title,
            },
        )

    except Exception as exc:
        # Captions disabled/missing (or no en/en-US/en-GB track) -- flag this
        # so the caller (e.g. _run_youtube_job) can fail the job cleanly
        # instead of writing a junk note built from the error string.
        print(f"[EnrichmentRouter] transcript fetch failed for {url} (video_id={video_id}): {exc}", flush=True)
        return EnrichedPayload(
            raw_input=url,
            input_type="url_youtube",
            enriched_text=f"[YouTube transcript failed: {exc}]\n\nURL: {url}",
            source_url=url,
            source_metadata={
                "video_id": video_id,
                "transcript_available": False,
                "title": title,
                "error": str(exc),
            },
        )


def _check_vision_model_available(base_url: str, vision_model: str, timeout: float = 5.0) -> Optional[str]:
    """
    Query GET {base_url}/api/tags and verify `vision_model` is present and
    advertises the "vision" capability.

    Returns None if available, otherwise a human-readable reason string
    (the caller decides whether to raise or degrade based on that reason).
    Never raises -- any failure to even reach /api/tags is itself a reason.
    """
    import json as _json
    import urllib.request as _req
    import urllib.error as _err

    bare_name = vision_model.split(":")[0]
    tags_url = base_url.rstrip("/") + "/api/tags"

    try:
        with _req.urlopen(tags_url, timeout=timeout) as resp:
            data = _json.loads(resp.read())
    except _err.URLError as exc:
        return f"Could not reach Ollama at {base_url} ({exc})."
    except Exception as exc:
        return f"Could not reach Ollama at {base_url} ({exc})."

    models = data.get("models", [])
    match = next(
        (m for m in models if m.get("name", "").split(":")[0] == bare_name),
        None,
    )
    if match is None:
        return (
            f"Vision model '{vision_model}' is not pulled. Run: ollama pull {vision_model}"
        )

    capabilities = match.get("capabilities") or []
    if capabilities and "vision" not in capabilities:
        return (
            f"Model '{vision_model}' is pulled but does not advertise vision "
            f"capability (capabilities: {capabilities}). Point [ollama] vision_model "
            f"at a vision-capable model (e.g. llava, bakllava)."
        )

    return None


def _downscale_image(image_bytes: bytes, max_dimension: int = 1344) -> bytes:
    """Downscale image so neither dimension exceeds max_dimension, always
    re-encoded as PNG (even the pass-through branch) so the bytes always
    match the .png extension _save_image_attachment gives them.

    Returns the original bytes unchanged only if Pillow is unavailable or
    re-encoding itself fails -- this is a size/latency optimization, never a
    hard requirement.
    """
    try:
        import io
        from PIL import Image
    except ImportError:
        return image_bytes

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.width > max_dimension or img.height > max_dimension:
                scale = max_dimension / max(img.width, img.height)
                new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
                img = img.resize(new_size, Image.LANCZOS)

            # Preserve transparency where it exists; flatten everything else
            # to RGB (PNG also supports L/RGBA/RGB directly, so only palette
            # and CMYK images need an explicit conversion).
            if img.mode == "P" and "transparency" in img.info:
                target_mode = "RGBA"
            elif img.mode in ("RGB", "RGBA", "L"):
                target_mode = img.mode
            else:
                target_mode = "RGB"

            buf = io.BytesIO()
            img.convert(target_mode).save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return image_bytes


def _save_image_attachment(image_bytes: bytes, vault_root) -> "Path":
    """Persist the captured image under {vault_root}/_attachments and return its path.

    Underscore-prefixed (not dot-prefixed) so the folder is both visible to
    Obsidian's vault index (dot-prefixed folders are invisible, breaking the
    ![[...]] embed) and excluded from discover_categories (which excludes
    '_'/'.'-prefixed folders).
    """
    import hashlib
    import time
    from pathlib import Path

    attachments_dir = Path(vault_root) / "_attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    shorthash = hashlib.sha1(image_bytes).hexdigest()[:8]
    filename = f"img-{timestamp}-{shorthash}.png"
    dest = attachments_dir / filename
    dest.write_bytes(image_bytes)
    return dest


_OCR_ENGINE = None  # lazily constructed singleton; RapidOCR model load is expensive
_OCR_ENGINE_LOCK = threading.Lock()


def _run_ocr(image_bytes: bytes) -> Optional[str]:
    """
    Best-effort OCR transcription via rapidocr-onnxruntime.

    Returns None if OCR is unavailable/fails or finds no text -- this is an
    optional enhancement layered on top of the vision model, never a hard
    requirement, so it must never raise.
    """
    global _OCR_ENGINE
    try:
        import io
        import numpy as np
        from PIL import Image

        if _OCR_ENGINE is None:
            with _OCR_ENGINE_LOCK:
                if _OCR_ENGINE is None:
                    from rapidocr_onnxruntime import RapidOCR
                    _OCR_ENGINE = RapidOCR()

        with Image.open(io.BytesIO(image_bytes)) as img:
            arr = np.array(img.convert("RGB"))

        result, _elapse = _OCR_ENGINE(arr)
        if not result:
            return None
        lines = [line[1] for line in result]
        return "\n".join(lines).strip() or None
    except Exception as exc:
        print(f"[EnrichmentRouter] OCR pass failed: {exc}", flush=True)
        return None


def _degraded_image_payload(
    image_bytes: bytes,
    vision_model: str,
    reason: str,
    image_path: Optional["Path"] = None,
    image_embed: Optional[str] = None,
) -> EnrichedPayload:
    # enriched_text deliberately carries no diagnostic/model-name keywords
    # (e.g. "llava", "ollama pull ...") -- a vision failure must never look
    # like real captured content to the classifier or the embedding/semantic
    # retrieval step. The human-readable reason lives in source_metadata only,
    # for the scratchpad note and any UI that wants to show it.
    enriched_text = ""

    source_metadata = {
        "image_size_bytes": len(image_bytes),
        "vision_model": vision_model,
        "vision_available": False,
        "vision_failure_reason": reason,
    }
    if image_path is not None:
        source_metadata["image_path"] = str(image_path)
    if image_embed:
        source_metadata["image_embed"] = image_embed

    return EnrichedPayload(
        raw_input="<image>",
        input_type="image",
        enriched_text=enriched_text,
        source_metadata=source_metadata,
    )


def _enrich_image(image_bytes: bytes) -> EnrichedPayload:
    """
    Send clipboard image to a locally running LLaVA instance via Ollama.

    Requires: `ollama pull llava`
    The vision model, base URL, and prompt are read from config.toml → [ollama].

    Degrades gracefully (returns a placeholder EnrichedPayload) when the vision
    model is missing/unreachable, matching _enrich_audio/_enrich_web_url, unless
    [ollama] image_required = true, in which case it raises instead.
    """
    import base64
    import json as _json
    import urllib.error as _uerr
    import urllib.request as _req

    from config import get_config
    cfg = get_config()
    vision_model = cfg.ollama.vision_model

    # Persist-first: save the clipboard image before any enrichment attempt,
    # so a missing/unreachable vision model can never lose the user's
    # capture. Both the degraded and success paths reference this same path.
    upload_bytes = _downscale_image(image_bytes)
    image_path = None
    try:
        image_path = _save_image_attachment(upload_bytes, cfg.vault.root)
    except Exception as exc:
        print(f"[EnrichmentRouter] failed to persist image attachment: {exc}", flush=True)
    image_embed = f"![[{image_path.name}]]" if image_path is not None else None

    # ── OCR-first fast path ────────────────────────────────────────────────
    # For text-heavy screenshots, RapidOCR is both faster and more accurate
    # than the vision LLM. If it yields enough text, skip the (slow) LLaVA
    # call entirely and hand the OCR text to the LLM as a plain-text capture.
    if cfg.capture.ocr_fast_path_enabled:
        try:
            fast_ocr = _run_ocr(upload_bytes)  # never raises; returns None on failure
        except Exception as exc:               # belt-and-braces
            print(f"[EnrichmentRouter] OCR fast-path probe failed (non-fatal): {exc}", flush=True)
            fast_ocr = None
        if fast_ocr and len(fast_ocr) >= cfg.capture.ocr_text_min_chars:
            print(
                f"[EnrichmentRouter] OCR fast path taken "
                f"({len(fast_ocr)} chars >= {cfg.capture.ocr_text_min_chars}); "
                f"skipping vision model.", flush=True,
            )
            source_metadata = {
                "image_size_bytes": len(image_bytes),
                "source_type": "image_ocr",
                "ocr_fast_path": True,
                "transcribed_text": fast_ocr,
            }
            if image_path is not None:
                source_metadata["image_path"] = str(image_path)
            if image_embed:
                source_metadata["image_embed"] = image_embed
            return EnrichedPayload(
                raw_input="<image>",
                input_type="image_ocr",
                enriched_text=fast_ocr,
                source_metadata=source_metadata,
            )

    preflight_reason = _check_vision_model_available(cfg.ollama.base_url, vision_model)
    if preflight_reason is not None:
        if cfg.ollama.image_required:
            raise RuntimeError(preflight_reason)
        return _degraded_image_payload(image_bytes, vision_model, preflight_reason, image_path, image_embed)

    api_url = cfg.ollama.base_url.rstrip("/") + "/api/generate"

    # Cold-load warmup: a vision model pulled only minutes/hours earlier can
    # return an empty response on its very first request while Ollama is
    # still loading the multimodal projector into memory (observed: ~11s
    # round trip on a "fresh" model -- 3 retries burned on empty responses,
    # never a real describe). A throwaway, generously-timed warmup call
    # forces that load to finish up front, so the real attempts below get a
    # warm model instead of spending their retry budget on the cold start.
    try:
        warmup_body = _json.dumps({
            "model": vision_model,
            "prompt": "ready",
            "stream": False,
            "keep_alive": cfg.ollama.keep_alive,
        }).encode()
        warmup_request = _req.Request(
            api_url, data=warmup_body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with _req.urlopen(warmup_request, timeout=120):
            pass
    except Exception as exc:
        print(f"[EnrichmentRouter] vision warmup call failed (non-fatal): {exc}", flush=True)

    b64 = base64.b64encode(upload_bytes).decode()

    payload_data = {
        "model": vision_model,
        "prompt": cfg.ollama.vision_prompt,
        "images": [b64],
        "stream": False,
        "keep_alive": cfg.ollama.keep_alive,
    }
    body = _json.dumps(payload_data).encode()

    max_attempts = 3
    last_exc: Optional[BaseException] = None
    description = ""
    for attempt in range(max_attempts):
        try:
            request = _req.Request(
                api_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # First attempt gets extra patience in case the warmup call above
            # didn't fully finish loading the model.
            attempt_timeout = 90 if attempt == 0 else 60
            with _req.urlopen(request, timeout=attempt_timeout) as resp:
                result = _json.loads(resp.read())

            description = result.get("response", "").strip()
            if not description:
                raise RuntimeError("LLaVA returned an empty response.")
            last_exc = None
            break

        except _uerr.HTTPError as exc:
            # Clean 404/4xx = model missing/misconfigured -- not transient, don't retry.
            last_exc = exc
            break
        except Exception as exc:
            # Connection reset / timeout / transient network errors -- retry.
            last_exc = exc
            if attempt < max_attempts - 1:
                import time as _time
                _time.sleep(min(2 ** (attempt + 1), 15))
                continue

    if last_exc is not None:
        if isinstance(last_exc, _uerr.HTTPError) and last_exc.code == 404:
            hint = f"Make sure Ollama is running and the model is available: ollama pull {vision_model}"
        elif isinstance(last_exc, _uerr.HTTPError):
            hint = (
                f"Ollama returned HTTP {last_exc.code} -- check the Ollama server logs "
                "(this is not a missing-model issue, so `ollama pull` will not help)."
            )
        else:
            hint = f"Make sure Ollama is running and the model is available: ollama pull {vision_model}"
        reason = (
            f"vision model '{vision_model}' could not describe the image "
            f"(after {max_attempts} attempt(s)): {last_exc}. {hint}"
        )
        if cfg.ollama.image_required:
            raise RuntimeError(reason) from last_exc
        return _degraded_image_payload(image_bytes, vision_model, reason, image_path, image_embed)

    ocr_text = _run_ocr(upload_bytes) if cfg.ocr.enabled else None

    # Routing context for the LLM: description (+ OCR as optional context).
    # The verbatim image embed and transcribed text are deliberately NOT put
    # here -- they're deterministic artifacts carried in source_metadata so
    # the storage layer can append them after the LLM step, verbatim,
    # instead of letting the LLM paraphrase/drop them.
    routing_parts = [description]
    if ocr_text:
        routing_parts.append(f"OCR text: {ocr_text}")
    enriched_text = "\n\n".join(routing_parts)

    source_metadata = {
        "image_size_bytes": len(image_bytes),
        "vision_model": vision_model,
        "vision_available": True,
        "ocr_used": ocr_text is not None,
    }
    if image_path is not None:
        source_metadata["image_path"] = str(image_path)
    if image_embed:
        source_metadata["image_embed"] = image_embed
    if ocr_text:
        source_metadata["transcribed_text"] = ocr_text

    return EnrichedPayload(
        raw_input="<image>",
        input_type="image",
        enriched_text=enriched_text,
        source_metadata=source_metadata,
    )


def _enrich_audio(audio_path: str) -> EnrichedPayload:
    """
    Transcribe an audio file using a locally running Whisper model.

    Requires: `pip install openai-whisper`
    Model size and device are read from config.toml → [whisper].
    """
    from config import get_config
    cfg = get_config()

    whisper_model = cfg.whisper.model
    device_pref   = cfg.whisper.device

    try:
        import whisper  # type: ignore

        if device_pref == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        else:
            device = device_pref

        model = whisper.load_model(whisper_model, device=device)
        result = model.transcribe(audio_path, fp16=(device == "cuda"))
        transcript = result["text"].strip()

    except ImportError:
        transcript = (
            "[Whisper not installed. Run: pip install openai-whisper]\n"
            f"File: {audio_path}"
        )
    except Exception as exc:
        transcript = f"[Whisper transcription failed: {exc}]\nFile: {audio_path}"

    return EnrichedPayload(
        raw_input=audio_path,
        input_type="audio",
        enriched_text=transcript,
        source_metadata={
            "audio_path": audio_path,
            "whisper_model": whisper_model,
        },
    )


# ── Main router ───────────────────────────────────────────────────────────────

def route_and_enrich(payload: InputPayload) -> EnrichedPayload:
    """
    Inspect the InputPayload, dispatch to the correct enrichment handler,
    and return a fully populated EnrichedPayload.
    """
    if payload.is_image():
        return _enrich_image(payload.image_bytes)  # type: ignore[arg-type]

    if not payload.is_url():
        return EnrichedPayload(
            raw_input=payload.raw,
            input_type="text",
            enriched_text=payload.raw,
        )

    url = payload.raw

    if _YOUTUBE_RE.match(url):
        return _enrich_youtube_url(url)

    gh_match = _GITHUB_RE.match(url)
    if gh_match:
        return _enrich_github_url(url, gh_match)

    return _enrich_web_url(url)


# ── Smoke tests ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import unittest.mock as mock

    # ── T1: html.unescape applied in _enrich_web_url ──────────────────────
    html_with_entities = (
        b"<html><body><p>AT&amp;T &lt;rocks&gt; &#8217;quotes&#8217;</p></body></html>"
    )
    fake_resp = mock.MagicMock()
    fake_resp.read.return_value = html_with_entities
    fake_resp.headers.get_content_charset.return_value = None
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = mock.MagicMock(return_value=False)

    with mock.patch("urllib.request.urlopen", return_value=fake_resp):
        ep = _enrich_web_url("http://example.com/test")

    assert "&amp;" not in ep.enriched_text, "HTML entities should be unescaped"
    assert "failed" not in ep.enriched_text.lower(), f"extraction should succeed: {ep.enriched_text!r}"
    print(f"[T1] html.unescape works — snippet: {ep.enriched_text[:80]!r}  PASS")

    # ── T2: NoTranscriptFound is not in module scope ───────────────────────
    try:
        _ = NoTranscriptFound  # type: ignore[name-defined]  # noqa: F821
        assert False, "NoTranscriptFound should NOT be in module scope"
    except NameError:
        print("[T2] NoTranscriptFound not in module scope  PASS")

    # ── T3: tracking param stripping ──────────────────────────────────────
    stripped = _strip_tracking_params(
        "https://example.com/page?utm_source=newsletter&id=42"
    )
    assert "utm_source" not in stripped
    assert "id=42" in stripped
    print(f"[T3] Tracking params stripped: {stripped}  PASS")

    # ── T4: fetch_youtube_transcript success ───────────────────────────────
    fake_api = mock.MagicMock()
    fake_fetched = mock.MagicMock()
    fake_fetched.to_raw_data.return_value = [
        {"text": "hello", "start": 0.0, "duration": 1.0},
        {"text": "world", "start": 1.0, "duration": 1.0},
    ]
    fake_api.fetch.return_value = fake_fetched
    with mock.patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=fake_api), \
         mock.patch(f"{__name__}._fetch_youtube_title", return_value="Test Video"):
        result = fetch_youtube_transcript("https://youtu.be/abc123")
    assert result["transcript_available"] is True
    assert result["full_text"] == "hello world"
    assert result["video_id"] == "abc123"
    assert result["title"] == "Test Video"
    print(f"[T4] fetch_youtube_transcript success  PASS  -> {result['full_text']!r}")

    # ── T5: fetch_youtube_transcript -- no captions ────────────────────────
    fake_api_fail = mock.MagicMock()
    fake_api_fail.fetch.side_effect = RuntimeError("No transcripts available")
    with mock.patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=fake_api_fail), \
         mock.patch(f"{__name__}._fetch_youtube_title", return_value=None):
        result5 = fetch_youtube_transcript("https://youtu.be/xyz789")
    assert result5["transcript_available"] is False
    assert result5["error"] is not None
    assert result5["full_text"] == ""
    print("[T5] fetch_youtube_transcript no-captions  PASS")

    # ── Shared fake config for image-enrichment tests ──────────────────────
    import tempfile
    import types
    import urllib.error as _uerr
    from pathlib import Path

    def _make_fake_cfg(tmp_root, image_required=False):
        cfg = types.SimpleNamespace()
        cfg.ollama = types.SimpleNamespace(
            base_url="http://localhost:11434",
            vision_model="llava",
            vision_prompt="Describe this image.",
            keep_alive="30m",
            image_required=image_required,
        )
        cfg.vault = types.SimpleNamespace(root=tmp_root)
        cfg.ocr = types.SimpleNamespace(enabled=False)
        cfg.capture = types.SimpleNamespace(
            ocr_fast_path_enabled=False,  # keep legacy vision tests on the vision path
            ocr_text_min_chars=10,
        )
        return cfg

    def _tags_response(models):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps({"models": models}).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)
        return resp

    # ── T6: /api/generate 404 -> degrades, never an unhandled traceback ────
    with tempfile.TemporaryDirectory() as tmp:
        fake_cfg = _make_fake_cfg(tmp)
        tags_ok = _tags_response([{"name": "llava:latest", "capabilities": ["vision"]}])

        def _urlopen_404(request, timeout=None):
            url = request if isinstance(request, str) else request.full_url
            if "/api/tags" in url:
                return tags_ok
            raise _uerr.HTTPError(url, 404, "Not Found", {}, None)

        with mock.patch("config.get_config", return_value=fake_cfg), \
             mock.patch("urllib.request.urlopen", side_effect=_urlopen_404):
            ep_img = _enrich_image(b"fake-bytes")

        assert ep_img.source_metadata["vision_available"] is False
        # The diagnostic lives in source_metadata, never in enriched_text --
        # a vision failure must not look like real content to the classifier
        # or the embedding/semantic retrieval step (see _degraded_image_payload).
        assert "ollama pull" in ep_img.source_metadata["vision_failure_reason"]
        assert ep_img.enriched_text == ""
        # H1: the image must be persisted even on the degraded path.
        assert "image_path" in ep_img.source_metadata
        assert (Path(tmp) / "_attachments").exists()
        assert any((Path(tmp) / "_attachments").iterdir())
        print("[T6] _enrich_image degrades cleanly on /api/generate 404 (image still persisted)  PASS")

    # ── T7: /api/tags missing the vision model -> actionable preflight msg ─
    with tempfile.TemporaryDirectory() as tmp:
        fake_cfg = _make_fake_cfg(tmp)
        tags_missing = _tags_response([{"name": "llama3.2:latest", "capabilities": ["completion"]}])

        with mock.patch("config.get_config", return_value=fake_cfg), \
             mock.patch("urllib.request.urlopen", return_value=tags_missing):
            ep_img2 = _enrich_image(b"fake-bytes")

        assert ep_img2.source_metadata["vision_available"] is False
        assert "ollama pull llava" in ep_img2.source_metadata["vision_failure_reason"]
        assert ep_img2.enriched_text == ""
        print("[T7] preflight catches missing vision model  PASS")

    # ── T8: successful /api/generate -> description used, image persisted ──
    with tempfile.TemporaryDirectory() as tmp:
        fake_cfg = _make_fake_cfg(tmp)
        tags_ok2 = _tags_response([{"name": "llava:latest", "capabilities": ["vision"]}])
        gen_ok = mock.MagicMock()
        gen_ok.read.return_value = json.dumps({"response": "a cat"}).encode()
        gen_ok.__enter__ = lambda s: s
        gen_ok.__exit__ = mock.MagicMock(return_value=False)

        def _urlopen_ok(request, timeout=None):
            url = request if isinstance(request, str) else request.full_url
            if "/api/tags" in url:
                return tags_ok2
            return gen_ok

        with mock.patch("config.get_config", return_value=fake_cfg), \
             mock.patch("urllib.request.urlopen", side_effect=_urlopen_ok), \
             mock.patch(f"{__name__}._downscale_image", side_effect=lambda b, **k: b):
            ep_img3 = _enrich_image(b"fake-bytes")

        assert "a cat" in ep_img3.enriched_text
        assert ep_img3.source_metadata["vision_available"] is True
        # H2/A2: image persisted under _attachments (not .attachments).
        assert (Path(tmp) / "_attachments").exists()
        # H3/A1: the embed is a deterministic artifact in source_metadata,
        # NOT mixed into the LLM-routing enriched_text.
        assert "image_embed" in ep_img3.source_metadata
        assert ep_img3.source_metadata["image_embed"] not in ep_img3.enriched_text
        print(f"[T8] _enrich_image success path  PASS  -> {ep_img3.enriched_text!r}")

    # ── T9: OCR pass enabled -> both sections present, ocr_used flagged ────
    with tempfile.TemporaryDirectory() as tmp:
        fake_cfg = _make_fake_cfg(tmp)
        fake_cfg.ocr.enabled = True
        tags_ok3 = _tags_response([{"name": "llava:latest", "capabilities": ["vision"]}])
        gen_ok3 = mock.MagicMock()
        gen_ok3.read.return_value = json.dumps({"response": "a screenshot"}).encode()
        gen_ok3.__enter__ = lambda s: s
        gen_ok3.__exit__ = mock.MagicMock(return_value=False)

        def _urlopen_ok3(request, timeout=None):
            url = request if isinstance(request, str) else request.full_url
            if "/api/tags" in url:
                return tags_ok3
            return gen_ok3

        with mock.patch("config.get_config", return_value=fake_cfg), \
             mock.patch("urllib.request.urlopen", side_effect=_urlopen_ok3), \
             mock.patch(f"{__name__}._downscale_image", side_effect=lambda b, **k: b), \
             mock.patch(f"{__name__}._run_ocr", return_value="raw transcribed text"):
            ep_img4 = _enrich_image(b"fake-bytes")

        # OCR text is allowed as LLM routing context...
        assert "raw transcribed text" in ep_img4.enriched_text
        assert "a screenshot" in ep_img4.enriched_text
        assert ep_img4.source_metadata["ocr_used"] is True
        # ...but the verbatim transcript for the note body lives in
        # source_metadata, for the storage layer to append deterministically.
        assert ep_img4.source_metadata["transcribed_text"] == "raw transcribed text"
        assert "## Transcribed Text" not in ep_img4.enriched_text
        print("[T9] OCR pass wired in when [ocr] enabled=true  PASS")

    # ── T10: native vision endpoints never receive a `/v1`-suffixed base ───
    # Regression for the bug where server.py/main.py wrote `/v1` into
    # OLLAMA_BASE_URL for the OpenAI-compatible text client, and that
    # polluted value then leaked into cfg.ollama.base_url (config.py reads
    # OLLAMA_BASE_URL back in) and from there into these native Ollama
    # calls, producing http://localhost:11434/v1/api/tags -> 404 on every
    # image capture.
    #
    # This test asserts the contract at the URL-construction boundary
    # directly: with a BARE cfg.ollama.base_url (the only value the fixed
    # startup code should ever produce), the requested URLs must contain
    # "/api/" and must NOT contain "/v1/". (The separate env-pollution
    # chain itself -- server.py/_run_pipeline_blocking and
    # main.py/run_pipeline no longer appending "/v1" -- is covered by
    # tests/test_e2e.py's env-pollution regression tests.)
    with tempfile.TemporaryDirectory() as tmp:
        fake_cfg = _make_fake_cfg(tmp)  # base_url is bare: "http://localhost:11434"
        tags_ok4 = _tags_response([{"name": "llava:latest", "capabilities": ["vision"]}])
        gen_ok4 = mock.MagicMock()
        gen_ok4.read.return_value = json.dumps({"response": "a dog"}).encode()
        gen_ok4.__enter__ = lambda s: s
        gen_ok4.__exit__ = mock.MagicMock(return_value=False)

        requested_urls = []

        def _urlopen_capture(request, timeout=None):
            url = request if isinstance(request, str) else request.full_url
            requested_urls.append(url)
            if "/api/tags" in url:
                return tags_ok4
            return gen_ok4

        with mock.patch("config.get_config", return_value=fake_cfg), \
             mock.patch("urllib.request.urlopen", side_effect=_urlopen_capture), \
             mock.patch(f"{__name__}._downscale_image", side_effect=lambda b, **k: b):
            ep_img5 = _enrich_image(b"fake-bytes")

        assert ep_img5.source_metadata["vision_available"] is True
        assert requested_urls, "expected at least one HTTP call"
        for url in requested_urls:
            assert "/api/" in url, f"expected native /api/ endpoint, got {url}"
            assert "/v1/" not in url, f"native vision call must not use /v1, got {url}"
        assert requested_urls[0] == "http://localhost:11434/api/tags", requested_urls[0]
        assert any(u == "http://localhost:11434/api/generate" for u in requested_urls), requested_urls
        print("[T10] native vision endpoints (/api/tags, /api/generate) never carry /v1  PASS")

    # ── T10b: native vision endpoints 404 when base_url IS /v1-polluted ────
    # This is the actual symptom reproduction: if cfg.ollama.base_url were
    # ever "http://localhost:11434/v1" (the pre-fix polluted value),
    # _enrich_image must degrade (never raise) and the failure reason must
    # show the broken /v1/api/... URL -- proving this is exactly the bug
    # described in current-issues.md. This stays true regardless of the
    # Part A fix (it documents *why* the fix matters) and protects against
    # ever reintroducing a code path that passes a /v1-suffixed base_url
    # into the native vision helpers.
    with tempfile.TemporaryDirectory() as tmp:
        fake_cfg_polluted = _make_fake_cfg(tmp)
        fake_cfg_polluted.ollama.base_url = "http://localhost:11434/v1"  # simulates the bug

        def _urlopen_404_polluted(request, timeout=None):
            url = request if isinstance(request, str) else request.full_url
            raise _uerr.HTTPError(url, 404, "Not Found", {}, None)

        with mock.patch("config.get_config", return_value=fake_cfg_polluted), \
             mock.patch("urllib.request.urlopen", side_effect=_urlopen_404_polluted):
            ep_img6 = _enrich_image(b"fake-bytes")

        assert ep_img6.source_metadata["vision_available"] is False
        reason = ep_img6.source_metadata["vision_failure_reason"]
        assert "/v1" in reason, (
            f"expected the polluted /v1 base_url to surface in the failure "
            f"reason (documenting the bug), got: {reason!r}"
        )
        print("[T10b] /v1-polluted base_url reproduces the documented 404 symptom (degrades, never raises)  PASS")

    # ── T11: _fetch_youtube_title falls back to the watch-page <title> when
    # oEmbed fails (private/age-restricted/region-locked videos, etc.) ─────
    def _urlopen_oembed_fails_watch_ok(request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        if "oembed" in url:
            raise _uerr.HTTPError(url, 404, "Not Found", {}, None)
        watch_resp = mock.MagicMock()
        watch_resp.read.return_value = (
            b"<html><head><title>Real Video Title &amp; More - YouTube</title></head><body></body></html>"
        )
        watch_resp.headers.get_content_charset.return_value = None
        watch_resp.__enter__ = lambda s: s
        watch_resp.__exit__ = mock.MagicMock(return_value=False)
        return watch_resp

    with mock.patch("urllib.request.urlopen", side_effect=_urlopen_oembed_fails_watch_ok):
        title11 = _fetch_youtube_title("https://youtu.be/fallback123")
    assert title11 == "Real Video Title & More", title11
    print(f"[T11] _fetch_youtube_title watch-page fallback  PASS  -> {title11!r}")

    # ── T12: watch-page fallback also fails -> None, never raises ──────────
    def _urlopen_both_fail(request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        raise _uerr.HTTPError(url, 404, "Not Found", {}, None)

    with mock.patch("urllib.request.urlopen", side_effect=_urlopen_both_fail):
        title12 = _fetch_youtube_title("https://youtu.be/bothfail")
    assert title12 is None
    print("[T12] _fetch_youtube_title both fetches fail -> None (no raise)  PASS")

    print("\nAll enrichment_router.py smoke tests passed.")

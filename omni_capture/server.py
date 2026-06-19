"""
server.py - FastAPI bridge between the Tauri GUI and the Second Thought pipeline.

Endpoints
  GET  /health
  POST /capture                        SSE stream of pipeline events
  POST /share                          Browser-extension / OS share-target (no clipboard)
  GET  /config
  PATCH /config
  GET  /vault/categories
  POST /vault/categories
  PATCH /vault/categories/{name}
  DELETE /vault/categories/{name}
  GET  /vault/categories/{name}/files
  GET  /search?q=&category=&since=&limit=   FTS search (SQLite)
  GET  /stats                               category + time statistics (SQLite)
  GET  /inbox
  POST /inbox/{note_id}/approve
  DELETE /inbox/{note_id}
  GET  /jobs/{job_id}                       background job status (e.g. YouTube)

SSE events emitted by /capture and /share:
  step     {"step": "intercept|enrich|decide|write", "status": "active|done|error"}
  thinking {"rationale": "...", "key_signals": [...], "confidence": 0.95, "category": "CRM"}
  done     {"path": "/vault/Category/file.md", "category": "Tech_Notes"}
  error    {"message": "..."}
  job      {"job_id": "...", "kind": "youtube", "status": "queued"} -- hand-off to a
           background job; the stream closes after this event and the GUI polls
           GET /jobs/{job_id} for completion instead of waiting on this stream.

content_type values accepted by /capture:
  text        plain text or Markdown snippet
  url         HTTP/HTTPS URL string
  image_b64   base64-encoded PNG/JPEG image -> routed to LLaVA (_enrich_image)
  audio_b64   base64-encoded audio file  -> routed to Whisper (_enrich_audio)
              (CLI/HTTP only -- the GUI's ContentType union does not expose
              an audio capture path; see gui/src/lib/api.ts)

Security
  CORS       restricted to OMNI_TAURI_ORIGIN (default: http://tauri.localhost).
  Secret     every request must carry X-Omni-Secret matching OMNI_GUI_SECRET.
             If OMNI_GUI_SECRET is unset the check is skipped with a startup warning.
"""
from __future__ import annotations
import asyncio, base64, hashlib, json, os, shutil, sys, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

try:
    import tomlkit
except ImportError:
    raise ImportError("pip install tomlkit")

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# -- CORS & shared-secret configuration ---------------------------------------
# The webview origin differs between dev and the packaged build:
#   - Vite dev server      -> http://localhost:1420
#   - Windows WebView2 prod -> http://tauri.localhost
#   - macOS/Linux WKWebView -> tauri://localhost
# All three must be allowed or the built GUI's fetch() is blocked by CORS,
# which surfaces in the UI as "Python server not running".
_DEFAULT_ORIGINS = [
    "http://localhost:1420",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
]
_env_origin = os.getenv("OMNI_TAURI_ORIGIN", "").strip()
_ALLOWED_ORIGINS = ([_env_origin] if _env_origin else []) + _DEFAULT_ORIGINS
_GUI_SECRET   = os.getenv("OMNI_GUI_SECRET", "")

app = FastAPI(title="Second Thought GUI Server", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(_ALLOWED_ORIGINS)),  # dedupe, preserve order
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

if not _GUI_SECRET:
    print(
        "[server] WARNING: OMNI_GUI_SECRET is not set -- "
        "X-Omni-Secret header validation is DISABLED.",
        flush=True,
    )

_executor = ThreadPoolExecutor(max_workers=2)
# Separate pool for long-running background jobs (e.g. YouTube transcript
# fetch + summarisation) so they cannot starve normal /capture requests.
_bg_executor = ThreadPoolExecutor(max_workers=2)
CONFIG_PATH = Path(__file__).parent / "config.toml"


@app.on_event("startup")
def _warm_model() -> None:
    """Fire a tiny throwaway generation in the background so the first real
    capture doesn't pay Ollama's cold model-load (~40s observed in logs)."""
    def _warm():
        try:
            from config import reload_config
            cfg = reload_config()
            base = cfg.ollama.base_url.rstrip("/")
            if not base.endswith("/v1"):
                base += "/v1"
            from openai import OpenAI
            client = OpenAI(base_url=base, api_key="ollama")
            client.chat.completions.create(
                model=cfg.ollama.model,
                messages=[{"role": "user", "content": "ok"}],
                max_tokens=1,
                extra_body={"keep_alive": cfg.ollama.keep_alive},
            )
            print("[Warmup] model preloaded", flush=True)
        except Exception as exc:
            print(f"[Warmup] skipped: {exc}", flush=True)
    _bg_executor.submit(_warm)

# ---------------------------------------------------------------------------
# Background job registry (in-process; the server is a single long-lived
# process spawned by Rust, so a dict is sufficient -- no DB needed).
# ---------------------------------------------------------------------------
_jobs: dict[str, dict] = {}   # job_id -> {status, kind, category, path, error, created, updated}
_jobs_lock = threading.Lock()


def _set_job(job_id: str, ttl_seconds: int = 3600, **fields) -> None:
    now = time.time()
    with _jobs_lock:
        entry = _jobs.setdefault(job_id, {"created": now})
        entry.update(fields)
        entry["updated"] = now

        stale = [k for k, v in _jobs.items() if now - v.get("updated", now) > ttl_seconds]
        for k in stale:
            del _jobs[k]


def _get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        entry = _jobs.get(job_id)
        return dict(entry) if entry is not None else None

# ---------------------------------------------------------------------------
# Request-level dedup gate
# ---------------------------------------------------------------------------
# The hotkey binding (AutoHotkey / Hammerspoon) often fires 2-3 times per
# keypress, sending identical POST /capture payloads within milliseconds.
# Without this gate the full pipeline (enrichment + LLM + storage) runs
# once per duplicate, wasting ~10-30 s of GPU time each time.
#
# We keep a dict of {content_hash: accepted_at_timestamp} and reject any
# request whose hash was already accepted within _DEDUP_WINDOW_S seconds.
# The dict is pruned on every new request so it never grows unboundedly.

_DEDUP_WINDOW_S: float = 0.5
_recent_request_hashes: dict[str, float] = {}  # hash -> epoch seconds


def _request_hash(content_type: str, content: str) -> str:
    raw = f"{content_type}:{content[:2000]}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _is_duplicate_request(content_type: str, content: str) -> bool:
    """Return True and log if this request was already accepted recently."""
    now = time.monotonic()
    h   = _request_hash(content_type, content)

    # Prune stale entries
    stale = [k for k, ts in _recent_request_hashes.items() if now - ts > _DEDUP_WINDOW_S]
    for k in stale:
        del _recent_request_hashes[k]

    if h in _recent_request_hashes:
        age = round(now - _recent_request_hashes[h], 2)
        print(
            f"[server] Duplicate /capture dropped (same content seen {age}s ago). "
            "Check hotkey binding for repeat-fire.",
            flush=True,
        )
        return True

    _recent_request_hashes[h] = now
    return False


# -- Shared-secret dependency -------------------------------------------------

def _require_secret(x_omni_secret: Optional[str] = Header(default=None)) -> None:
    """
    FastAPI dependency injected on every route.

    Validates the X-Omni-Secret header sent by the Tauri GUI.
    Skipped entirely when OMNI_GUI_SECRET env var is not configured
    (development convenience -- warning logged at startup).
    """
    if not _GUI_SECRET:
        return
    if x_omni_secret != _GUI_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Omni-Secret.")


# -- Pydantic models ----------------------------------------------------------

class CaptureRequest(BaseModel):
    content_type: str   # text | url | image_b64 | audio_b64
    content: str

class ShareRequest(BaseModel):
    """Sent by the browser extension or OS share-target without touching the clipboard."""
    url: str
    title: Optional[str] = None
    selection: Optional[str] = None   # highlighted text on the page, if any

class ConfigPatch(BaseModel):
    vault_root: Optional[str] = None
    ollama_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    hotkey: Optional[str] = None

class CategoryCreate(BaseModel):
    name: str

class CategoryRename(BaseModel):
    new_name: str

class CategoryDescriptionPatch(BaseModel):
    description: Optional[str] = None  # None = clear description; str = set/update (max 500 chars)

class InboxApprove(BaseModel):
    target_category: Optional[str] = None


# -- Vault helpers -------------------------------------------------------------

def _get_vault_root() -> Path:
    """Return the vault root from the live config (single source of truth)."""
    from config import get_config
    return get_config().vault.root

def _safe_name(name: str) -> str:
    import re
    return re.sub(r"[^\w\-. ]", "_", name).strip()


def _safe_category_dir(root: Path, name: str) -> Path:
    """
    Resolve a category directory and guarantee it stays directly inside the
    vault root. Rejects path-traversal, path separators, and any name
    that would escape or nest below the vault.

    Raises HTTPException(400) on any invalid / unsafe name.
    """
    cleaned = _safe_name(name)
    if not cleaned or cleaned in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid category name.")

    root_resolved = root.resolve()
    target = (root_resolved / cleaned).resolve()
    if target.parent != root_resolved:
        raise HTTPException(
            status_code=400,
            detail="Category name must not contain path separators or traversal.",
        )
    return target


# -- SSE helper ---------------------------------------------------------------

def _sse(event: str, **data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# -- Pipeline runner ----------------------------------------------------------

def _run_pipeline_blocking(content_type, content, q, loop, run_id=None):
    tag = f"[run:{run_id}] " if run_id else ""

    def emit(event, **kwargs):
        loop.call_soon_threadsafe(q.put_nowait, {"event": event, **kwargs})

    try:
        from config import reload_config
        cfg = reload_config()
        os.environ["OMNI_VAULT_ROOT"] = str(cfg.vault.root)
        os.environ["OLLAMA_MODEL"] = cfg.ollama.model
        # Keep OLLAMA_BASE_URL bare (canonical host). "/v1" is appended only
        # at the moment an OpenAI-compatible client is constructed (see
        # llm_engine._normalize_base_url) -- never written back here, or it
        # leaks into cfg.ollama.base_url on the next reload_config() and
        # poisons the native Ollama vision/embeddings endpoints (/api/...).
        os.environ["OLLAMA_BASE_URL"] = cfg.ollama.base_url.rstrip("/")
        os.environ["OLLAMA_KEEP_ALIVE"] = cfg.ollama.keep_alive

        from interceptor import InputPayload
        from enrichment_router import route_and_enrich, _YOUTUBE_RE
        from llm_engine import run_llm_engine
        from storage_engine import write_to_vault, read_existing_context, build_category_descriptions
        from pre_resolver import pre_resolve
        from vector_store import retrieve_related, index_note

        emit("step", step="intercept", status="active")

        if content_type == "url" and _YOUTUBE_RE.match(content):
            # Long-running (network + model) -- hand off to a background job
            # instead of blocking this SSE stream.
            emit("step", step="intercept", status="done")
            job_id = uuid.uuid4().hex[:12]
            _set_job(job_id, ttl_seconds=cfg.youtube.job_ttl_seconds,
                     status="queued", kind="youtube", category=None, path=None, error=None)
            _bg_executor.submit(_run_youtube_job, job_id, content, cfg)
            emit("job", job_id=job_id, kind="youtube", status="queued")
            return

        if content_type == "image_b64":
            # Decoded bytes -> InputPayload with image_bytes;
            # route_and_enrich dispatches to _enrich_image (LLaVA).
            payload = InputPayload(raw="<image_data>", input_type="image_bytes",
                                   image_bytes=base64.b64decode(content))
        elif content_type == "url":
            payload = InputPayload(raw=content, input_type="url")
        else:
            payload = InputPayload(raw=content, input_type="text")
        emit("step", step="intercept", status="done")

        emit("step", step="enrich", status="active")

        if content_type == "audio_b64":
            # Audio: write temp file, run Whisper, delete temp file.
            import tempfile, pathlib as _pathlib
            from enrichment_router import _enrich_audio
            audio_bytes = base64.b64decode(content)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tf.write(audio_bytes)
                tmp_audio_path = tf.name
            try:
                enriched = _enrich_audio(tmp_audio_path)
            finally:
                _pathlib.Path(tmp_audio_path).unlink(missing_ok=True)
        else:
            # text, url, image_b64 -- route_and_enrich handles all three.
            # image_b64 is dispatched internally to _enrich_image (LLaVA).
            enriched = route_and_enrich(payload)

        emit("step", step="enrich", status="done")

        if enriched.source_metadata.get("vision_available") is False:
            # Vision failed at capture time. The placeholder enriched_text
            # carries no real content -- classifying or semantically
            # retrieving against it would only launder the failure into a
            # confident (and wrong) category. Route straight to scratchpad
            # instead, flagged for a vision retry.
            from storage_engine import route_failed_vision
            emit("step", step="decide", status="done")
            emit("step", step="write", status="active")
            written_path = route_failed_vision(
                enriched.source_metadata,
                vault_root=cfg.vault.root,
                scratchpad_folder=cfg.vault.scratchpad_folder,
            )
            emit("step", step="write", status="done")
            emit("done", path=str(written_path), category="Unprocessed_Images")
            try:
                from notifier import notify_capture_error
                if cfg.notifications.enabled:
                    notify_capture_error(
                        "Vision recognition failed -- image saved for retry.",
                        title_prefix=cfg.notifications.title_prefix,
                    )
            except Exception:
                pass
            return

        emit("step", step="decide", status="active")
        resolved = pre_resolve(enriched, cfg.vault.root)

        semantic_snippets: list[str] = []
        if cfg.vector.enabled:
            semantic_snippets = retrieve_related(
                cfg.vault.root,
                enriched.enriched_text,
                cfg.ollama.base_url,
                cfg.vector.embed_model,
                cfg.vector.top_k,
                min_similarity=cfg.vector.min_similarity,
            )

        ctx_parts: list[str] = []
        if resolved.existing_context:
            ctx_parts.append(resolved.existing_context)
        if semantic_snippets:
            ctx_parts.append(
                "## Semantically Related Notes\n\n" + "\n\n".join(semantic_snippets)
            )
        existing_context = "\n\n---\n\n".join(ctx_parts) if ctx_parts else None

        category_descriptions = build_category_descriptions(cfg.vault.root, cfg.vault.scratchpad_folder)
        output = run_llm_engine(
            enriched,
            category_descriptions=category_descriptions,
            existing_context=existing_context,
            max_retries=cfg.capture.llm_max_retries,
            temperature=cfg.capture.llm_temperature,
        )

        # Two-pass fallback: the pre-resolver was uncertain, but now that the
        # LLM has picked a category we can check for an existing CRM/Finance
        # file and re-run with that context loaded.
        if resolved.certainty == "low" and output.category in ("CRM", "Finance"):
            fallback_context = read_existing_context(output, vault_root=cfg.vault.root)
            if fallback_context:
                output = run_llm_engine(
                    enriched,
                    category_descriptions=category_descriptions,
                    existing_context=fallback_context,
                    max_retries=cfg.capture.llm_max_retries,
                    temperature=cfg.capture.llm_temperature,
                )

        emit("thinking",
             rationale=output.rationale or "",
             key_signals=output.key_signals or [],
             confidence=round(output.confidence, 2),
             category=output.category)
        emit("step", step="decide", status="done")

        emit("step", step="write", status="active")
        written_path = write_to_vault(
            output, source_url=enriched.source_url,
            vault_root=cfg.vault.root,
            scratchpad_folder=cfg.vault.scratchpad_folder,
            enable_semantic_merge=cfg.vector.enabled,
            embed_base_url=cfg.ollama.base_url,
            embed_model=cfg.vector.embed_model,
            source_metadata=enriched.source_metadata,
        )
        if cfg.vector.enabled:
            from pathlib import Path as _Path
            note_text = _Path(written_path).read_text(encoding="utf-8", errors="ignore")
            index_note(
                cfg.vault.root, _Path(written_path), note_text,
                cfg.ollama.base_url, cfg.vector.embed_model,
            )
        emit("step", step="write", status="done")
        emit("done", path=str(written_path), category=output.category)

        try:
            from notifier import notify_capture_success
            from capture_log import log_capture
            if cfg.notifications.enabled:
                notify_capture_success(category=output.category,
                                       filepath=str(written_path),
                                       title_prefix=cfg.notifications.title_prefix)
            log_capture(output, enriched, str(written_path), cfg.ollama.model)
        except Exception:
            pass

    except Exception as exc:
        print(f"[server] {tag}pipeline failed: {exc}", flush=True)
        emit("error", message=str(exc))
    finally:
        loop.call_soon_threadsafe(q.put_nowait, None)


def _run_youtube_job(job_id: str, url: str, cfg) -> None:
    """
    Background worker driving the four-phase async YouTube pipeline:

      fetching -> writing_transcript -> summarizing -> [combining] ->
      finalizing -> done | error

    The note is written to the vault with the full raw transcript BEFORE any
    LLM call (end of writing_transcript), so the source text is never lost
    even if summarization later fails or the process crashes mid-job.
    """
    ttl = cfg.youtube.job_ttl_seconds

    def set_status(status: str, **extra) -> None:
        _set_job(job_id, ttl_seconds=ttl, status=status, **extra)

    try:
        import asyncio
        from datetime import datetime
        from functools import partial

        from enrichment_router import fetch_youtube_transcript
        from storage_engine import create_youtube_note, finalize_youtube_note, register_in_dedup_index
        from summarizer import count_tokens, chunk_transcript, _map_phase, reduce_summaries
        from llm_engine import summarize_async, DETAILED_SUMMARY_PROMPT, OLLAMA_API_KEY, _normalize_base_url
        from openai import AsyncOpenAI

        set_status("fetching")
        transcript = fetch_youtube_transcript(url)

        if not transcript.get("transcript_available"):
            print(f"[server] youtube job {job_id} failed: no captions available "
                  f"(url={url}, detail={transcript.get('error', 'n/a')})", flush=True)
            set_status("error", error="No captions available for this video")
            return

        full_text = transcript["full_text"]
        title = transcript.get("title")
        segments = transcript["segments"]

        # Canonical bare host (matches the project-wide invariant: base_url is
        # always bare; /v1 is added only at OpenAI-compatible client construction
        # via _normalize_base_url). count_tokens below hits Ollama's native
        # /api/tokenize and needs the bare host; the AsyncOpenAI client gets /v1.
        base_url = cfg.ollama.base_url.rstrip("/")
        model = cfg.ollama.model

        fetched_note = f"*{len(segments)} segments • fetched {datetime.now().isoformat(timespec='seconds')}*"
        transcript_md = f"{fetched_note}\n\n{full_text}"
        path = create_youtube_note(
            title, url, transcript_md, cfg.vault.root, cfg.youtube, cfg.vault.scratchpad_folder,
        )
        set_status("writing_transcript", path=str(path))

        count = partial(count_tokens, base_url=base_url, model=model)
        max_chunk_tokens = (
            cfg.capture.summary_model_context_tokens
            - cfg.capture.summary_safety_buffer_tokens
            - cfg.capture.summary_reserved_output_tokens
        )

        async def run_summarization() -> str:
            client = AsyncOpenAI(base_url=_normalize_base_url(base_url), api_key=OLLAMA_API_KEY)
            try:
                if count(full_text) <= max_chunk_tokens:
                    set_status("summarizing", chunk_index=1, chunk_total=1,
                               detail="Summarizing transcript")
                    return await summarize_async(
                        full_text, instruction=DETAILED_SUMMARY_PROMPT, base_url=base_url,
                        model=model, temperature=cfg.capture.llm_temperature,
                        max_retries=cfg.capture.llm_max_retries, timeout=None, client=client,
                    )

                chunks = chunk_transcript(
                    segments, count=count, max_tokens=max_chunk_tokens,
                    overlap_tokens=cfg.capture.summary_chunk_overlap_tokens,
                    max_chunks=cfg.capture.summary_max_chunks,
                )
                total = len(chunks)
                set_status("summarizing", chunk_index=0, chunk_total=total,
                           detail=f"Summarizing 0 of {total} sections")

                def on_progress(done: int, total_: int) -> None:
                    set_status("summarizing", chunk_index=done, chunk_total=total_,
                               detail=f"Summarized {done} of {total_} sections")

                partials = await _map_phase(
                    chunks, client=client, model=model, temperature=cfg.capture.llm_temperature,
                    max_retries=cfg.capture.llm_max_retries, timeout=None,
                    max_concurrency=cfg.capture.summary_max_concurrency,
                    on_progress=on_progress, base_url=base_url,
                )

                set_status("combining", chunk_total=total, detail="Combining section summaries")
                return await reduce_summaries(
                    partials, count=count, client=client, model=model,
                    temperature=cfg.capture.llm_temperature, max_retries=cfg.capture.llm_max_retries,
                    timeout=None, max_chunk_tokens=max_chunk_tokens,
                    overlap_tokens=cfg.capture.summary_chunk_overlap_tokens,
                    max_chunks=cfg.capture.summary_max_chunks,
                    max_concurrency=cfg.capture.summary_max_concurrency,
                    reduce_max_depth=cfg.capture.reduce_max_depth, base_url=base_url,
                )
            finally:
                await client.close()

        summary = asyncio.run(run_summarization())

        set_status("finalizing", detail="Finalizing note")
        finalize_youtube_note(path, summary, cfg.vault.root)

        if cfg.vector.enabled:
            try:
                from vector_store import index_note
                note_text = path.read_text(encoding="utf-8", errors="ignore")
                index_note(cfg.vault.root, path, note_text, cfg.ollama.base_url, cfg.vector.embed_model)
            except Exception as exc:
                print(f"[server] youtube job {job_id} vector index skipped: {exc}", flush=True)

        try:
            register_in_dedup_index(summary, url, cfg.vault.root, path)
        except Exception:
            pass

        set_status("done", category=cfg.youtube.folder_name, path=str(path))

        try:
            from notifier import notify_capture_success
            from capture_log import log_capture
            from models import CaptureOutput, EnrichedPayload
            if cfg.notifications.enabled:
                notify_capture_success(category=cfg.youtube.folder_name,
                                       filepath=str(path),
                                       title_prefix=cfg.notifications.title_prefix)
            minimal_output = CaptureOutput(
                category=cfg.youtube.folder_name,
                suggested_filename=path.stem,
                markdown_content=summary,
                confidence=1.0,
            )
            minimal_enriched = EnrichedPayload(
                raw_input=url, input_type="url_youtube", enriched_text=full_text, source_url=url,
            )
            log_capture(minimal_output, minimal_enriched, str(path), cfg.ollama.model)
        except Exception:
            pass

    except Exception as exc:
        print(f"[server] youtube job {job_id} failed: {exc}", flush=True)
        set_status("error", error=str(exc))


async def _stream_capture(content_type: str, content: str, run_id: Optional[str] = None) -> AsyncIterator[str]:
    if _is_duplicate_request(content_type, content):
        yield _sse("duplicate")
        return

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[Optional[dict]] = asyncio.Queue()
    loop.run_in_executor(_executor, _run_pipeline_blocking, content_type, content, q, loop, run_id)
    while True:
        item = await q.get()
        if item is None:
            break
        event = item.pop("event")
        yield _sse(event, **item)


# -- Core endpoints -----------------------------------------------------------

@app.get("/health")
async def health():
    # Unauthenticated liveness probe: used by launch.ps1 to detect readiness.
    # Returns only a boolean, so it leaks nothing sensitive even with a secret set.
    return {"ok": True}

@app.post("/capture")
async def capture(
    req: CaptureRequest,
    _: None = Depends(_require_secret),
    x_capture_run_id: Optional[str] = Header(default=None, alias="X-Capture-Run-Id"),
):
    return StreamingResponse(
        _stream_capture(req.content_type, req.content, run_id=x_capture_run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/share")
async def share(req: ShareRequest, _: None = Depends(_require_secret)):
    """
    Browser-extension / OS share-target endpoint.

    Accepts a URL + optional selected text directly from the browser -- no
    clipboard involved.  If a text selection is provided it is prepended to
    the URL so the enrichment router receives both the context and the link.

    Returns a streaming SSE response identical to /capture.
    """
    if req.selection and req.selection.strip():
        combined = f"{req.selection.strip()}\n\nSource: {req.url}"
        content_type = "text"
        content = combined
    else:
        content_type = "url"
        content = req.url

    return StreamingResponse(
        _stream_capture(content_type, content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, _: None = Depends(_require_secret)):
    """Status of a background job (e.g. a YouTube capture). Cheap; polled by the GUI."""
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "kind": job.get("kind"),
        "category": job.get("category"),
        "path": job.get("path"),
        "error": job.get("error"),
        "chunk_index": job.get("chunk_index"),
        "chunk_total": job.get("chunk_total"),
        "detail": job.get("detail"),
    }


@app.get("/config")
async def get_config_endpoint(_: None = Depends(_require_secret)):
    if CONFIG_PATH.exists():
        return tomlkit.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}

@app.patch("/config")
async def patch_config(patch: ConfigPatch, _: None = Depends(_require_secret)):
    """
    Patch individual config keys without disturbing the rest of the file.

    Uses tomlkit so that comments and key ordering are preserved.
    """
    if CONFIG_PATH.exists():
        doc = tomlkit.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()

    def _set(section: str, key: str, value: str) -> None:
        if section not in doc:
            doc.add(tomlkit.comment(f"  [{section}] added by GUI"))
            doc.add(section, tomlkit.table())
        doc[section][key] = value

    if patch.vault_root is not None:
        _set("vault", "root", patch.vault_root)
    if patch.ollama_model is not None:
        _set("ollama", "model", patch.ollama_model)
    if patch.ollama_base_url is not None:
        _set("ollama", "base_url", patch.ollama_base_url)
    if patch.hotkey is not None:
        _set("gui", "hotkey", patch.hotkey)

    CONFIG_PATH.write_text(tomlkit.dumps(doc), encoding="utf-8")

    from config import reload_config
    reload_config()

    return {"ok": True}


# -- Vault management endpoints -----------------------------------------------

@app.get("/vault/categories")
async def list_categories(_: None = Depends(_require_secret)):
    root = _get_vault_root()
    if not root.exists():
        return {"categories": [], "vault_root": str(root)}
    from storage_engine import read_category_config
    result = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            md_files = [f for f in entry.iterdir() if f.suffix == ".md"]
            cfg = read_category_config(entry)
            result.append({
                "name": entry.name,
                "file_count": len(md_files),
                "path": str(entry),
                "description": cfg.get("description", None),
            })
    return {"categories": result, "vault_root": str(root)}

@app.post("/vault/categories")
async def create_category(body: CategoryCreate, _: None = Depends(_require_secret)):
    root = _get_vault_root()
    new_dir = _safe_category_dir(root, body.name)
    name = new_dir.name
    if new_dir.exists():
        raise HTTPException(status_code=409, detail=f"'{name}' already exists.")
    new_dir.mkdir(parents=True, exist_ok=False)
    return {"ok": True, "name": name, "path": str(new_dir)}

@app.patch("/vault/categories/{name}")
async def rename_category(name: str, body: CategoryRename, _: None = Depends(_require_secret)):
    root = _get_vault_root()
    src = _safe_category_dir(root, name)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")
    dst = _safe_category_dir(root, body.new_name)
    new_name = dst.name
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"'{new_name}' already exists.")
    src.rename(dst)
    return {"ok": True, "old_name": name, "new_name": new_name}

@app.patch("/vault/categories/{name}/description")
async def update_category_description(
    name: str,
    body: CategoryDescriptionPatch,
    _: None = Depends(_require_secret),
):
    """
    Set or clear the LLM routing description for a category folder.

    The description is persisted in <vault>/<category>/.category.toml under
    the 'description' key.  This file is read by build_category_descriptions()
    and injected verbatim into the LLM system prompt on every capture so the
    model can route files more precisely.

    Pass description=null (JSON null) or an empty string to clear it.
    Maximum length: 500 characters.
    """
    root = _get_vault_root()
    target = _safe_category_dir(root, name)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")

    desc = body.description
    if desc is not None:
        desc = desc.strip()[:500]  # enforce max length

    config_file = target / ".category.toml"

    # Load existing .category.toml (if any) so we don't clobber other keys.
    existing: dict = {}
    if config_file.exists():
        try:
            if sys.version_info >= (3, 11):
                import tomllib
            else:
                import tomli as tomllib  # type: ignore[no-redef]
            with open(config_file, "rb") as f:
                existing = tomllib.load(f)
        except Exception:
            existing = {}

    if not desc:
        # Clear: remove the description key entirely.
        existing.pop("description", None)
    else:
        existing["description"] = desc

    # Write back using tomlkit so the file stays human-readable.
    import tomlkit as _tomlkit
    doc = _tomlkit.document()
    for k, v in existing.items():
        doc.add(k, v)  # type: ignore[arg-type]

    if existing:
        config_file.write_text(_tomlkit.dumps(doc), encoding="utf-8")
    elif config_file.exists():
        # No keys remain — remove the file rather than leaving it empty.
        config_file.unlink()

    return {"ok": True, "name": name, "description": desc or None}


@app.delete("/vault/categories/{name}")
async def delete_category(name: str, force: bool = False, _: None = Depends(_require_secret)):
    root = _get_vault_root()
    target = _safe_category_dir(root, name)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")
    files = [f for f in target.iterdir() if f.is_file()]
    if files and not force:
        raise HTTPException(status_code=409,
            detail=f"'{name}' contains {len(files)} file(s). Pass force=true to delete anyway.")
    shutil.rmtree(target)
    return {"ok": True, "deleted": name}

@app.get("/vault/categories/{name}/files")
async def list_category_files(name: str, _: None = Depends(_require_secret)):
    root = _get_vault_root()
    target = _safe_category_dir(root, name)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")
    files = []
    for f in sorted(target.iterdir()):
        if f.is_file() and f.suffix == ".md":
            stat = f.stat()
            files.append({"name": f.stem, "filename": f.name, "path": str(f),
                          "size_bytes": stat.st_size, "modified": stat.st_mtime})
    return {"category": name, "files": files}


# -- Search & stats endpoints -------------------------------------------------

@app.get("/search")
async def search_captures(
    q: str = "",
    category: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 25,
    _: None = Depends(_require_secret),
):
    """Full-text search over captured notes via the SQLite FTS5 index."""
    from index_writer import search as idx_search
    limit = min(max(1, limit), 200)
    results = idx_search(q, _get_vault_root(), category=category, since=since, limit=limit)
    return {"results": results, "count": len(results), "query": q}


@app.get("/stats")
async def capture_stats(_: None = Depends(_require_secret)):
    """Aggregated capture statistics backed by SQLite."""
    from index_writer import stats as idx_stats
    return idx_stats(_get_vault_root())


# -- Inbox endpoints ----------------------------------------------------------

@app.get("/inbox")
async def list_inbox_items(_: None = Depends(_require_secret)):
    """List all notes pending review in the scratchpad folder."""
    from config import get_config
    from storage_engine import list_scratchpad
    root  = _get_vault_root()
    items = list_scratchpad(root, get_config().vault.scratchpad_folder)
    return {"inbox": items, "count": len(items)}


@app.post("/inbox/{note_id}/approve")
async def approve_inbox(
    note_id: str,
    body: InboxApprove = InboxApprove(),
    _: None = Depends(_require_secret),
):
    """Move a scratchpad note to its final category."""
    from config import get_config
    from storage_engine import approve_scratchpad_item
    root = _get_vault_root()
    try:
        dest = approve_scratchpad_item(note_id, root, get_config().vault.scratchpad_folder, target_category=body.target_category)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "note_id": note_id, "path": str(dest)}


@app.delete("/inbox/{note_id}")
async def discard_inbox(note_id: str, _: None = Depends(_require_secret)):
    """Permanently delete a scratchpad note."""
    from config import get_config
    from storage_engine import discard_scratchpad_item
    root = _get_vault_root()
    try:
        discard_scratchpad_item(note_id, root, get_config().vault.scratchpad_folder)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "discarded": note_id}

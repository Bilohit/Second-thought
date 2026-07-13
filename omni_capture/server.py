"""
server.py - FastAPI bridge between the Tauri GUI and the Second Thought pipeline.

Owns: FastAPI app wiring, the capture SSE endpoint, and `_run_pipeline_blocking`
(kept here per CLAUDE.md hard rule -- hand-duplicated alongside
main.py:run_pipeline(), never moved into a shared module). Background-job
machinery (registry, workers, `/jobs/{id}` polling) lives in `jobs.py`;
vault-admin-only endpoints (category CRUD, search, stats) live in
`vault_admin.py` -- both are mounted below via `app.include_router(...)` so
the route table is unchanged.

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
  GET  /reminders
  POST /reminders
  DELETE /reminders/{reminder_id}
  GET  /jobs/{job_id}                       background job status (e.g. YouTube)
  POST /look/chat                           streaming RAG chat (SSE)
  POST /vault/sync-index                    vault diff-sync (add/remove/update index rows)

SSE events emitted by /look/chat:
  meta     {"confidence": 0.34, "tier": "high"|"talk"|"none", "answerable": true}
  sources  {"sources": [...]}
  token    {"text": "..."}  (repeated)
  done     {}
  error    {"message": "..."}
  Default vault chat is strict RAG; tier "talk" = /talk prefix (general knowledge).

SSE events emitted by /capture and /share:
  step     {"step": "intercept|enrich|decide|write", "status": "active|done|error"}
  thinking {"rationale": "...", "key_signals": [...], "confidence": 0.95, "category": "CRM"}
  reminder_offer {"events": [{"when_iso": "...", "label": "..."}], "note_path": "..."} -- emitted
           after write, before done, only when the capture contains concrete future
           dates/times; GUI offers to create reminders via POST /reminders.
  done     {"path": "/vault/Category/file.md", "category": "Tech_Notes"}
  error    {"message": "..."}
  job      {"job_id": "...", "kind": "youtube"|"voice", "status": "queued"} -- hand-off to a
           background job; the stream closes after this event and the GUI polls
           GET /jobs/{job_id} for completion instead of waiting on this stream.

content_type values accepted by /capture:
  text        plain text or Markdown snippet
  url         HTTP/HTTPS URL string
  image_b64   base64-encoded PNG/JPEG image -> routed to LLaVA (_enrich_image)
  audio_b64   base64-encoded audio file  -> routed to Whisper (_enrich_audio)
              GUI voice path: pill right-click -> MediaRecorder -> audio_b64

Security
  CORS       restricted to OMNI_TAURI_ORIGIN (default: http://tauri.localhost).
  Secret     every request must carry X-Omni-Secret matching OMNI_GUI_SECRET.
             If OMNI_GUI_SECRET is unset the check is skipped with a startup warning.
"""
from __future__ import annotations
import asyncio, base64, hashlib, hmac, json, os, sys, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

try:
    import tomlkit
except ImportError:
    raise ImportError("pip install tomlkit")

import anyio
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import reload_config
import index_health

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
# Long-running background jobs (YouTube/voice transcript+summarize) and this
# file's own startup warmup/DB-maintenance tasks share `jobs._bg_executor` --
# a single small pool, not duplicated -- so neither starves normal /capture
# requests handled by `_executor` above.

# Max base64-encoded payload size (64 MB encoded ≈ 48 MB decoded).
# A 4K PNG screenshot is ~20-30 MB; this cap blocks accidental or deliberate
# memory/disk exhaustion without affecting any real capture.
_MAX_B64_LEN = 64 * 1024 * 1024
CONFIG_PATH = Path(__file__).parent / "config.toml"

# Set True once warmup finishes (success or skip) — a skipped warmup
# shouldn't pin /health at "never ready" forever, it just means the first
# real capture pays the cold-model cost instead of a synthetic one.
_MODEL_READY = False
# None = still warming, True = warmup succeeded, False = warmup failed
_MODEL_OK: bool | None = None


@app.on_event("startup")
def _warm_model() -> None:
    """Fire a tiny throwaway generation in the background so the first real
    capture doesn't pay Ollama's cold model-load (~40s observed in logs)."""
    def _warm():
        global _MODEL_READY, _MODEL_OK
        try:
            from config import reload_config
            cfg = reload_config()
            from llm_engine import _normalize_base_url, OLLAMA_API_KEY
            from openai import OpenAI
            client = OpenAI(base_url=_normalize_base_url(cfg.ollama.base_url), api_key=OLLAMA_API_KEY)
            client.chat.completions.create(
                model=cfg.ollama.model,
                messages=[{"role": "user", "content": "ok"}],
                max_tokens=1,
                extra_body={"keep_alive": cfg.ollama.keep_alive},
            )
            print("[Warmup] model preloaded", flush=True)
            _MODEL_OK = True
        except Exception as exc:
            print(f"[Warmup] skipped: {exc}", flush=True)
            _MODEL_OK = False
        finally:
            _MODEL_READY = True
    jobs._bg_executor.submit(_warm)


@app.on_event("startup")
def _startup_db_tasks() -> None:
    """Best-effort startup DB maintenance: orphan purge then body-excerpt backfill.
    Run sequentially in one task so they share one DB open and don't race."""
    def _run():
        root = _get_vault_root()
        try:
            from vault_sync import purge_orphan_index_entries
            n = purge_orphan_index_entries(root)
            if n:
                print(f"[VaultSync] startup purge removed {n} orphan rows", flush=True)
        except Exception as exc:
            print(f"[VaultSync] startup purge skipped: {exc}", flush=True)
        try:
            from index_writer import reindex_bodies
            n = reindex_bodies(root)
            if n:
                print(f"[Reindex] body_excerpt backfilled for {n} rows", flush=True)
        except Exception as exc:
            print(f"[Reindex] skipped: {exc}", flush=True)
    jobs._bg_executor.submit(_run)


def _fire_due(db_path, notify_fn) -> None:
    """Notify and mark-fired every reminder whose fire_at has passed.
    A single bad row/notification must never kill the loop for the rest."""
    from datetime import datetime
    from reminders import due_reminders, mark_fired

    for r in due_reminders(db_path, datetime.now().isoformat(timespec="seconds")):
        try:
            notify_fn(f"⏰ {r['label']}", Path(r["note_path"]).name)
            mark_fired(db_path, r["id"])
        except Exception as exc:
            print(f"[Reminders] fire failed for id={r.get('id')}: {exc}", flush=True)
            continue


@app.on_event("startup")
def _startup_load_jobs() -> None:
    """Reload persisted background-job rows so GET /jobs/{id} survives a
    server restart (see docs/ROADMAP.md: "Persist the background-job
    registry"). Best-effort -- a failure here never blocks startup."""
    try:
        n = jobs.load_jobs()
        if n:
            print(f"[jobs] reloaded {n} persisted job(s)", flush=True)
    except Exception as exc:
        print(f"[jobs] startup reload failed: {exc}", flush=True)


@app.on_event("startup")
def _startup_reminders_thread() -> None:
    """Background due-checker: polls reminders.due_reminders() on a fixed
    interval and fires desktop notifications for anything past its fire_at.
    Config is captured once at startup (matches this file's other startup
    hooks -- none of them re-read config per iteration; only the request-time
    pipeline calls reload_config())."""
    from config import get_config
    from index_writer import get_db_path
    from notifier import send_notification

    cfg = get_config()
    interval = cfg.reminders.check_interval_seconds
    db_path = get_db_path(cfg.vault.root)

    def _loop():
        while True:
            time.sleep(interval)
            try:
                _fire_due(db_path, notify_fn=lambda t, m: send_notification(t, m))
            except Exception as exc:
                print(f"[Reminders] due-check pass failed: {exc}", flush=True)
    threading.Thread(target=_loop, daemon=True).start()


@app.on_event("startup")
def _startup_lan_listener() -> None:
    """Optional same-WiFi LAN sync accelerator (contract §11). Off by default --
    only starts when [lan] enabled = true and a host is configured. This is a
    SEPARATE listener/app (lan_server.build_lan_app()) exposing ONLY /lan/*; it
    never touches this loopback GUI app or its routes.
    # ponytail: LAN listener lifecycle rides the main process; a restart re-reads
    # [lan] config -- no hot-reload of host/port."""
    try:
        import lan_server
        enabled, host, port = lan_server.lan_config()
        if enabled and host:
            # Bind 0.0.0.0, not the single configured host: a multi-homed desktop can't know which
            # NIC the phone shares, so listen on all of them (auth is unchanged — the NaCl key +
            # in-envelope secret double-gate every /lan/push). `host` stays the advertised/QR IP only.
            # ponytail: all-interfaces bind; the double-gate is the security boundary, not the bind addr.
            lan_server.start_lan_listener("0.0.0.0", port)
            print(f"[LAN] listener on 0.0.0.0:{port} (advertised {host})", flush=True)
    except Exception as exc:
        print(f"[LAN] listener startup skipped: {exc}", flush=True)

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


# ---------------------------------------------------------------------------
# Capture retry idempotency (run_id -> terminal event replay)
# ---------------------------------------------------------------------------
# useCapture.ts generates one `runId` per logical capture attempt BEFORE its
# retry loop (gui/src/hooks/useCapture.ts:379, loop starts at :399) and reuses
# it across every retry of that SAME capture -- it is NOT regenerated per
# retry -- so it's a safe idempotency key: unique across different captures,
# stable across retries of one capture. It already arrives here as
# X-Capture-Run-Id (see the `capture` route below).
#
# Problem: a connection drop can lose the SSE response even though the
# pipeline already finished (vault write succeeded). Without this map, the
# GUI's retry re-POSTs the same content and the pipeline runs -- and writes
# to the vault -- a second time.
#
# We record the terminal event ("done", or "job" for YouTube/voice hand-off,
# which also eventually writes to the vault) keyed by run_id the moment it's
# observed leaving the pipeline queue in `_stream_capture`, and on any later
# request carrying the same run_id we replay that exact event instead of
# invoking `_run_pipeline_blocking` again. This only wraps the SSE endpoint --
# `_run_pipeline_blocking` itself is untouched (CLAUDE.md: main.py/server.py
# pipeline bodies stay hand-duplicated and are not to be restructured here).
#
# ponytail: plain in-memory dict, lost on server restart -- acceptable, a
# restart mid-retry-window already breaks the SSE stream itself. TTL is a
# few minutes, well past the GUI's realistic retry-backoff window (a handful
# of attempts, seconds), swept lazily on insert like `jobs._jobs`.
_CAPTURE_DEDUP_TTL_S: float = 300.0  # 5 min
_capture_results: dict[str, dict] = {}  # run_id -> {"event", "payload", "ts"}
_capture_results_lock = threading.Lock()


def _record_capture_terminal(run_id: str, event: str, payload: dict) -> None:
    now = time.time()
    with _capture_results_lock:
        _capture_results[run_id] = {"event": event, "payload": payload, "ts": now}
        stale = [k for k, v in _capture_results.items() if now - v["ts"] > _CAPTURE_DEDUP_TTL_S]
        for k in stale:
            del _capture_results[k]


def _get_capture_terminal(run_id: str) -> Optional[dict]:
    with _capture_results_lock:
        entry = _capture_results.get(run_id)
        return dict(entry) if entry is not None else None


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
    if not hmac.compare_digest(x_omni_secret or "", _GUI_SECRET):
        raise HTTPException(status_code=403, detail="Invalid or missing X-Omni-Secret.")


# -- Split-out routers (jobs.py, vault_admin.py) ------------------------------
# See docs/ROADMAP.md "Split server.py into jobs.py + vault_admin.py". Both are
# mounted with the same X-Omni-Secret dependency every other route in this file
# enforces, applied once here at include-time rather than per-route, so auth
# coverage is identical to before the split.
import jobs
import vault_admin

app.include_router(jobs.router, dependencies=[Depends(_require_secret)])
app.include_router(vault_admin.router, dependencies=[Depends(_require_secret)])


# -- Pydantic models ----------------------------------------------------------

class LookChatRequest(BaseModel):
    question: str
    history: Optional[list[dict]] = None   # [{"role":"user"|"assistant","content":str}], last turns only
    ignore_history: bool = False           # when true, treat question as standalone (no prior turns)

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
    confidence_threshold: Optional[float] = None
    llm_scrutiny: Optional[str] = None
    ocr_fast_path_enabled: Optional[bool] = None
    ocr_text_min_chars: Optional[int] = None
    auto_describe_new_folders: Optional[bool] = None
    chat_system_prompt: Optional[str] = None
    reminders_delivery: Optional[str] = None

class InboxApprove(BaseModel):
    target_category: Optional[str] = None

class ReminderCreate(BaseModel):
    note_path: str
    label: str
    when_iso: str
    delivery: Optional[str] = None
    notify: bool = False


# -- Vault helpers -------------------------------------------------------------

def _get_vault_root() -> Path:
    """Return the vault root from the live config (single source of truth)."""
    from config import get_config
    return get_config().vault.root


# -- SSE helper ---------------------------------------------------------------

def _sse(event: str, **data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# -- Pipeline runner ----------------------------------------------------------

def _run_pipeline_blocking(content_type, content, q, loop, run_id=None):
    tag = f"[run:{run_id}] " if run_id else ""

    from timing import StageTimer
    timer = StageTimer(run_id=run_id)

    def emit(event, **kwargs):
        # Record the idempotency terminal event HERE, at emit time, not in
        # _stream_capture's consumer loop -- a client disconnect before that
        # loop reaches this event must not lose the record (see B-2 / the
        # "Capture retry idempotency" comment block above _record_capture_terminal).
        if run_id and event in ("done", "job"):
            _record_capture_terminal(run_id, event, dict(kwargs))
        loop.call_soon_threadsafe(q.put_nowait, {"event": event, **kwargs})

    enriched = None  # set once Stage 2 (enrich) succeeds; checked in the except below
                     # so an LLM/decide/write failure can still save the raw captured text.
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
            jobs._set_job(job_id, ttl_seconds=cfg.youtube.job_ttl_seconds,
                     status="queued", kind="youtube", category=None, path=None, error=None)
            jobs._bg_executor.submit(jobs._run_youtube_job, job_id, content, cfg)
            emit("job", job_id=job_id, kind="youtube", status="queued")
            return

        if content_type in ("image_b64", "audio_b64") and len(content) > _MAX_B64_LEN:
            raise ValueError(
                f"Payload too large ({len(content):,} bytes encoded, max {_MAX_B64_LEN:,}). "
                "Reduce image/audio size before capturing."
            )

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

        with timer.stage("enrich"):
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

        if content_type == "audio_b64":
            # Long recordings: transcript summarization is expensive enough
            # (map-reduce over many chunks) to block this SSE stream, so hand
            # off to a background job -- same shape as the YouTube hand-off
            # above, minus the fetching phase (transcript already in hand).
            from summarizer import count_tokens
            token_count = count_tokens(
                enriched.enriched_text,
                base_url=cfg.ollama.base_url.rstrip("/"),
                model=cfg.ollama.model,
            )
            if _voice_needs_summarize_job(
                token_count=token_count, threshold=cfg.whisper.summarize_threshold_tokens
            ):
                job_id = uuid.uuid4().hex
                jobs._set_job(job_id, status="queued", kind="voice", category=None, path=None, error=None)
                emit("job", job_id=job_id, kind="voice", status="queued")
                jobs._bg_executor.submit(jobs._run_voice_job, job_id, enriched, cfg)
                return

        # ponytail: synchronous map-reduce; promote to a background job like
        # voice/youtube if pastes ever exceed ~30k tokens.
        _large_text_original: Optional[str] = None
        _large_text_chunk_tags: list[list[str]] = []
        if content_type == "text":
            from summarizer import _char_estimate
            # Cheap local estimate first (propose-then-verify, same pattern as
            # chunk_transcript) -- avoids a network /api/tokenize probe for
            # every ordinary-length text capture; only texts that could
            # plausibly be over threshold pay for the real count.
            if _char_estimate(enriched.enriched_text) > cfg.capture.large_text_token_threshold:
                from summarizer import count_tokens
                text_token_count = count_tokens(
                    enriched.enriched_text,
                    base_url=cfg.ollama.base_url.rstrip("/"),
                    model=cfg.ollama.model,
                )
            else:
                text_token_count = 0
            if text_token_count > cfg.capture.large_text_token_threshold:
                from functools import partial as _partial
                from summarizer import chunk_transcript, digest_chunks

                _large_text_original = enriched.enriched_text
                base_url = cfg.ollama.base_url.rstrip("/")
                count = _partial(count_tokens, base_url=base_url, model=cfg.ollama.model)
                max_chunk_tokens = (
                    cfg.capture.summary_model_context_tokens
                    - cfg.capture.summary_safety_buffer_tokens
                    - cfg.capture.summary_reserved_output_tokens
                )
                segments = [{"text": ln} for ln in _large_text_original.splitlines() if ln.strip()]
                chunks = chunk_transcript(
                    segments, count=count, max_tokens=max_chunk_tokens,
                    overlap_tokens=cfg.capture.summary_chunk_overlap_tokens,
                    max_chunks=cfg.capture.summary_max_chunks,
                )
                digests = digest_chunks(
                    chunks, base_url=base_url, model=cfg.ollama.model,
                    temperature=cfg.capture.llm_temperature,
                    max_retries=cfg.capture.llm_max_retries,
                )
                _large_text_chunk_tags = [tags for tags, _ in digests]
                mini_summaries = [summary for _, summary in digests if summary]
                enriched.enriched_text = (
                    chunks[0]
                    + "\n\n## Section summaries (of the full document)\n\n"
                    + "\n".join(mini_summaries)
                )

        if enriched.source_metadata.get("vision_available") is False:
            # Vision failed at capture time. The placeholder enriched_text
            # carries no real content -- classifying or semantically
            # retrieving against it would only launder the failure into a
            # confident (and wrong) category. Route straight to scratchpad
            # instead, flagged for a vision retry.
            from storage_engine import route_failed_vision
            emit("step", step="decide", status="done")
            emit("step", step="write", status="active")
            with timer.stage("write_scratchpad"):
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
        with timer.stage("retrieve"):
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
        # NARROW scope: only an LLM-stage failure is fail-soft-to-scratchpad
        # (mirrors main.py:run_pipeline). A later write/index failure is a real
        # error, NOT a fail-soft case -- letting the broad outer except catch it
        # here would double-write (the note already on disk + a scratchpad
        # placeholder). Keep this try around the two run_llm_engine calls only.
        try:
            with timer.stage("llm"):
                output = run_llm_engine(
                    enriched,
                    category_descriptions=category_descriptions,
                    existing_context=existing_context,
                    max_retries=cfg.capture.llm_max_retries,
                    temperature=cfg.capture.llm_temperature,
                    scrutiny=cfg.capture.llm_scrutiny,
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
                            scrutiny=cfg.capture.llm_scrutiny,
                        )
        except Exception as llm_exc:
            # LLM enrichment failed even after the two-pass retry (Ollama down,
            # model error, parse failure, or a request timeout) -- fail-soft like
            # every other enrichment path (see CLAUDE.md): route the raw captured
            # text to the scratchpad flagged for retry instead of losing it.
            from storage_engine import route_failed_llm
            print(f"[server] {tag}LLM enrichment failed: {llm_exc}", flush=True)
            # Prefer the ORIGINAL full text for large-text captures -- enriched_text
            # was overwritten above with chunk[0]+section summaries.
            fail_text = _large_text_original if _large_text_original is not None else enriched.enriched_text
            emit("step", step="decide", status="done")
            emit("step", step="write", status="active")
            with timer.stage("write_scratchpad"):
                written_path = route_failed_llm(
                    fail_text,
                    str(llm_exc),
                    vault_root=cfg.vault.root,
                    scratchpad_folder=cfg.vault.scratchpad_folder,
                    source_url=enriched.source_url,
                )
            emit("step", step="write", status="done")
            emit("done", path=str(written_path), category="Unprocessed_Captures")
            try:
                from notifier import notify_capture_error
                if cfg.notifications.enabled:
                    notify_capture_error(
                        "LLM enrichment failed -- capture saved for retry.",
                        title_prefix=cfg.notifications.title_prefix,
                    )
            except Exception:
                pass
            return

        if _large_text_original is not None:
            from index_writer import get_db_path
            from tag_vocab import load_vocab
            try:
                vocab = load_vocab(get_db_path(cfg.vault.root))
            except Exception:
                vocab = {}
            output.key_signals = _merge_large_text_tags(
                output.key_signals or [], _large_text_chunk_tags, vocab,
            )
            # The decide-stage call above only saw chunk[0] + section summaries
            # (a faithful whole-document view for classification) -- keep the
            # ORIGINAL full text in the note body so nothing is lost.
            output.markdown_content = (
                f"{output.markdown_content}\n\n## Full Original Text\n\n{_large_text_original}"
            )

        emit("thinking",
             rationale=output.rationale or "",
             key_signals=output.key_signals or [],
             confidence=round(output.confidence, 2),
             category=output.category)
        emit("step", step="decide", status="done")

        output.markdown_content = _append_transcript(output.markdown_content, enriched)

        emit("step", step="write", status="active")
        with timer.stage("write"):
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
            # Derived-index write is FAIL-SOFT: the vault .md is already written
            # (source of truth), so an embeddings/index failure must never turn a
            # successful capture into a reported error -- swallow + log, per
            # CLAUDE.md "files are the source of truth, DBs are derived indexes".
            with timer.stage("index"):
                from pathlib import Path as _Path
                try:
                    note_text = _Path(written_path).read_text(encoding="utf-8", errors="ignore")
                    index_note(
                        cfg.vault.root, _Path(written_path), note_text,
                        cfg.ollama.base_url, cfg.vector.embed_model,
                    )
                except Exception as index_exc:
                    print(f"[server] {tag}index write failed (note still saved): {index_exc}", flush=True)
        emit("step", step="write", status="done")

        from datetime import datetime as _datetime
        from models import filter_future_events
        future = filter_future_events(output.detected_events, _datetime.now())
        if future:
            emit("reminder_offer",
                 events=[{"when_iso": e.when_iso, "label": e.label} for e in future],
                 note_path=str(written_path))

        emit("done", path=str(written_path), category=output.category)

        with timer.stage("notify"):
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
        # Genuine failure OUTSIDE the fail-soft LLM stage (intercept/enrich, or a
        # write_to_vault failure). LLM-stage failures are already handled by the
        # narrow try above and never reach here. A write failure is a real error,
        # not a fail-soft case -- surface it (mirrors main.py, where non-LLM
        # failures propagate to the top-level catch rather than route-to-scratchpad).
        print(f"[server] {tag}pipeline failed: {exc}", flush=True)
        emit("error", message=str(exc))
    finally:
        try:
            timer.log_summary()
        except Exception:
            pass
        loop.call_soon_threadsafe(q.put_nowait, None)


def _append_transcript(markdown: str, enriched) -> str:
    """Voice notes keep the full transcript below the LLM summary."""
    if enriched.input_type != "audio":
        return markdown
    return f"{markdown}\n\n## Transcript\n\n{enriched.enriched_text}"


def _voice_needs_summarize_job(*, token_count: int, threshold: int) -> bool:
    return token_count > threshold


def _merge_large_text_tags(
    key_signals: list[str], chunk_tags: list[list[str]], vocab: dict[str, str],
) -> list[str]:
    """Merge the classifier's key_signals with every chunk's Map-phase tags,
    then dedupe/normalize against the vault's existing tag vocabulary
    (B1's tag_vocab.normalize_tags) and cap at 10 -- pure, no I/O."""
    from tag_vocab import normalize_tags

    combined = list(key_signals)
    for tags in chunk_tags:
        combined.extend(tags)
    return normalize_tags(combined, vocab)


async def _stream_capture(content_type: str, content: str, run_id: Optional[str] = None) -> AsyncIterator[str]:
    if run_id:
        prior = _get_capture_terminal(run_id)
        if prior is not None:
            print(f"[server] [run:{run_id}] idempotent retry -- replaying prior "
                  f"'{prior['event']}' instead of re-running the pipeline", flush=True)
            yield _sse(prior["event"], **prior["payload"])
            return

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
        # Primary recording point is _run_pipeline_blocking's `emit()` (B-2
        # fix -- covers a client disconnect before this loop ever sees the
        # terminal item). This second write is now just a redundant, harmless
        # overwrite with the same data for the normal (consumer-attached)
        # case, and is the ONLY recording point for callers that replace
        # _run_pipeline_blocking wholesale (e.g. test doubles) instead of
        # going through its real emit().
        if run_id and event in ("done", "job"):
            _record_capture_terminal(run_id, event, dict(item))
        yield _sse(event, **item)


# -- Core endpoints -----------------------------------------------------------

@app.get("/health")
async def health():
    # Unauthenticated liveness probe: used by launch.ps1 to detect readiness.
    # Returns only booleans, so it leaks nothing sensitive even with a secret set.
    # model_ok: null = warming, true = ready, false = disconnected/failed
    # index_health: last captures.db/vectors.db write outcome per index --
    # purely observational, never authoritative (see CLAUDE.md "Files are
    # the source of truth" hard rule).
    return {
        "ok": True,
        "ready": _MODEL_READY,
        "model_ok": _MODEL_OK,
        "index_health": index_health.snapshot(),
    }

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
    if patch.confidence_threshold is not None:
        threshold = float(patch.confidence_threshold)
        if not (0.0 <= threshold <= 1.0):
            raise HTTPException(status_code=400, detail="confidence_threshold must be between 0.0 and 1.0")
        _set("capture", "confidence_threshold", threshold)
    if patch.llm_scrutiny is not None:
        scrutiny = patch.llm_scrutiny.strip().lower()
        if scrutiny not in ("relaxed", "balanced", "strict"):
            raise HTTPException(status_code=400, detail="llm_scrutiny must be relaxed|balanced|strict")
        _set("capture", "llm_scrutiny", scrutiny)
    if patch.ocr_fast_path_enabled is not None:
        _set("capture", "ocr_fast_path_enabled", bool(patch.ocr_fast_path_enabled))
    if patch.ocr_text_min_chars is not None:
        min_chars = int(patch.ocr_text_min_chars)
        if min_chars < 0:
            raise HTTPException(status_code=400, detail="ocr_text_min_chars must be non-negative")
        _set("capture", "ocr_text_min_chars", min_chars)
    if patch.auto_describe_new_folders is not None:
        _set("capture", "auto_describe_new_folders", bool(patch.auto_describe_new_folders))
    if patch.chat_system_prompt is not None:
        _set("look", "chat_system_prompt", patch.chat_system_prompt)
    if patch.reminders_delivery is not None:
        delivery = patch.reminders_delivery.strip().lower()
        if delivery in ("app", "os"):
            _set("reminders", "delivery", delivery)

    CONFIG_PATH.write_text(tomlkit.dumps(doc), encoding="utf-8")

    reload_config()

    return {"ok": True}


# -- Look / RAG chat endpoint -------------------------------------------------

@app.post("/look/chat")
async def look_chat(
    req: LookChatRequest,
    _: None = Depends(_require_secret),
    x_log_level: Optional[str] = Header(None, alias="X-Log-Level"),
):
    from look_log import debug_logging_from_level
    verbose = debug_logging_from_level(x_log_level)
    return StreamingResponse(
        _stream_look_chat(req.question, req.history or [], req.ignore_history, verbose),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


async def _stream_look_chat(question: str, history: list[dict], ignore_history: bool, verbose: bool) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[Optional[dict]] = asyncio.Queue()
    loop.run_in_executor(_executor, _run_look_chat_blocking, question, history, ignore_history, q, loop, verbose)
    while True:
        item = await q.get()
        if item is None:
            break
        event = item.pop("event")
        yield _sse(event, **item)


def _run_look_chat_blocking(question, history, ignore_history, q, loop, verbose=False):
    def emit(event, **kw):
        loop.call_soon_threadsafe(q.put_nowait, {"event": event, **kw})
    from look_log import set_look_verbose, look_debug, look_info, look_error
    set_look_verbose(verbose)
    try:
        from config import reload_config
        from rag_engine import hybrid_retrieve, build_system_prompt, parse_chat_mode, REFUSAL
        effective_history = [] if ignore_history else history
        question, chat_mode = parse_chat_mode(question)
        if not question:
            emit("error", message="Question is empty")
            return
        look_info(
            f"POST /look/chat question={question!r} history_turns={len(effective_history)} "
            f"ignore_history={ignore_history} mode={chat_mode}"
        )
        cfg = reload_config()
        custom_prompt = cfg.look.chat_system_prompt or None

        if chat_mode == "talk":
            sources: list = []
            confidence = 0.0
            tier = "talk"
            answerable = True
            emit("meta", confidence=0.0, tier=tier, answerable=answerable)
            emit("sources", sources=[])
        else:
            sources, confidence, tier = hybrid_retrieve(
                cfg.vault.root, question, cfg.ollama.base_url, cfg.vector.embed_model,
                top_k=cfg.look.chat_top_k,
                min_similarity_floor=cfg.look.chat_min_similarity_floor,
                history=effective_history or None,
            )
            if tier == "none":
                emit("meta", confidence=round(confidence, 4), tier="none", answerable=False)
                emit("sources", sources=[])
                emit("token", text=REFUSAL)
                look_info("POST /look/chat vault refusal — no match")
                emit("done")
                return
            answerable = True
            emit("meta", confidence=round(confidence, 4), tier="high", answerable=answerable)
            emit("sources", sources=sources)

        from openai import OpenAI
        from llm_engine import _normalize_base_url, OLLAMA_API_KEY
        client = OpenAI(base_url=_normalize_base_url(cfg.ollama.base_url), api_key=OLLAMA_API_KEY)
        prompt_mode = "talk" if chat_mode == "talk" else "vault"
        messages = [{"role": "system", "content": build_system_prompt(sources, prompt_mode, custom_prompt)}]
        messages += [m for m in effective_history if m.get("role") in ("user", "assistant")][-6:]
        messages.append({"role": "user", "content": question})
        temperature = (
            cfg.look.chat_general_temperature if chat_mode == "talk"
            else 0.0
        )
        look_debug(
            f"streaming LLM answer model={cfg.ollama.model} mode={chat_mode} tier={tier} "
            f"sources={len(sources)} temp={temperature}"
        )
        stream = client.chat.completions.create(
            model=cfg.ollama.model, messages=messages,
            temperature=temperature, stream=True,
            extra_body={"keep_alive": cfg.ollama.keep_alive},
        )
        token_count = 0
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                token_count += 1
                emit("token", text=delta)
        look_info(f"POST /look/chat done tokens={token_count}")
        emit("done")
    except Exception as exc:
        look_error(f"POST /look/chat failed: {exc}")
        emit("error", message=str(exc))
    finally:
        loop.call_soon_threadsafe(q.put_nowait, None)


# -- Vault index sync endpoint ------------------------------------------------

@app.post("/vault/sync-index")
async def vault_sync_index(_: None = Depends(_require_secret)):
    """Full vault diff-sync: remove orphan rows, add/update changed .md files."""
    from config import reload_config
    from vault_sync import sync_vault_indexes
    cfg = reload_config()
    result = await anyio.to_thread.run_sync(
        lambda: sync_vault_indexes(cfg.vault.root, cfg.ollama.base_url, cfg.vector.embed_model)
    )
    return result


# -- LAN provisional overlay endpoint (contract §11, desktop GUI read side) --

@app.get("/provisional")
async def list_provisional_items(_: None = Depends(_require_secret)):
    """List staged LAN-provisional rows (display/index overlay only -- never
    canonical; see provisional_store.py). Loopback-only, same secret guard
    as every other GUI route -- this is NOT the separate LAN listener."""
    from config import get_config
    import provisional_store as ps
    sync_dir = get_config().vault_sync_dir()
    items = ps.list_provisional(sync_dir)
    return {"provisional": items, "count": len(items)}


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
    from storage_engine import approve_scratchpad_item, get_scratchpad_item_text

    root = _get_vault_root()
    cfg = get_config()

    if body.target_category:
        vault_admin._safe_category_dir(root, body.target_category)  # raises HTTP 400 on traversal

    is_new = bool(body.target_category) and not (root / body.target_category).exists()
    sample_text = get_scratchpad_item_text(note_id, root, cfg.vault.scratchpad_folder) if is_new else None

    try:
        dest = approve_scratchpad_item(note_id, root, cfg.vault.scratchpad_folder, target_category=body.target_category)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        from index_writer import upsert_capture_from_file
        from vector_store import index_note
        upsert_capture_from_file(root, dest)
        if cfg.vector.enabled:
            note_text = dest.read_text(encoding="utf-8", errors="ignore")
            index_note(root, dest, note_text, cfg.ollama.base_url, cfg.vector.embed_model)
    except Exception as _exc:
        print(f"[server] approve re-index failed (non-fatal): {_exc}", flush=True)

    if is_new and cfg.capture.auto_describe_new_folders:
        from storage_engine import generate_category_description, write_category_description
        # Same asyncio.run()-in-a-running-loop hazard as create_category() above --
        # offload to a worker thread. run_sync takes positional args only, hence
        # the partial for the sample_text kwarg.
        from functools import partial
        generated = await anyio.to_thread.run_sync(
            partial(generate_category_description, body.target_category, sample_text=sample_text)
        )
        if generated:
            write_category_description(root / body.target_category, generated)

    return {"ok": True, "note_id": note_id, "path": str(dest)}


@app.get("/inbox/{note_id}/suggest-categories")
async def suggest_inbox_categories(note_id: str, _: None = Depends(_require_secret)):
    """Suggest 2-3 generalized, reusable folder names for a scratchpad item."""
    from config import get_config
    from storage_engine import discover_categories, get_scratchpad_item_text, suggest_category_names

    root = _get_vault_root()
    cfg = get_config()
    text = get_scratchpad_item_text(note_id, root, cfg.vault.scratchpad_folder)
    if text is None:
        raise HTTPException(status_code=404, detail=f"Scratchpad item {note_id!r} not found.")

    existing = discover_categories(root, cfg.vault.scratchpad_folder)
    suggestions = suggest_category_names(text, existing)
    return {"suggestions": suggestions}


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


@app.get("/reminders")
async def get_reminders(_: None = Depends(_require_secret)):
    """List all reminders (pending and fired)."""
    from config import get_config
    from index_writer import get_db_path
    from reminders import list_reminders
    db = get_db_path(get_config().vault.root)
    return {"reminders": list_reminders(db, include_done=True)}


@app.post("/reminders")
async def create_reminder_endpoint(body: ReminderCreate, _: None = Depends(_require_secret)):
    """Create a reminder for a note. Validates when_iso; defaults delivery from config."""
    from datetime import datetime
    from config import get_config
    from index_writer import get_db_path
    from reminders import create_reminder

    try:
        datetime.fromisoformat(body.when_iso)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid when_iso: {body.when_iso!r}")

    cfg = get_config()
    db = get_db_path(cfg.vault.root)
    delivery = body.delivery or cfg.reminders.delivery
    rid = create_reminder(
        db, note_path=body.note_path, label=body.label,
        fire_at_iso=body.when_iso, delivery=delivery,
    )
    if body.notify:
        try:
            from notifier import send_notification
            send_notification("Reminder set", f"{body.label} — {body.when_iso}")
        except Exception:
            pass  # notification is best-effort; the reminder row is already committed
    return {"id": rid}


@app.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder_endpoint(reminder_id: int, _: None = Depends(_require_secret)):
    """Delete a reminder."""
    from config import get_config
    from index_writer import get_db_path
    from reminders import delete_reminder
    db = get_db_path(get_config().vault.root)
    delete_reminder(db, reminder_id)

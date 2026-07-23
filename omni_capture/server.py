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
  GET  /note?path=                          full-window editor: read body + read-only frontmatter (F-7)
  PUT  /note                                 full-window editor: write body only, mtime-guarded (F-7)
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
             SRV-01: if OMNI_GUI_SECRET is unset the server fails CLOSED (403 on
             every route), matching lan_sync._check_secret. It never degrades to
             an unauthenticated localhost API.
"""
from __future__ import annotations
import asyncio, base64, hashlib, hmac, json, os, sys, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator, List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

# SRV-15: the only hosts PATCH /config may point [ollama] base_url at.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

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

from atomic_io import atomic_write_text
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

app = FastAPI(title="Second Thought GUI Server", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(_ALLOWED_ORIGINS)),  # dedupe, preserve order
    # Must cover every verb the app actually routes (incl. the jobs/vault_admin
    # routers) -- a missing verb makes the browser preflight fail with 400
    # "Disallowed CORS method" and the route is unreachable from the GUI. PUT was
    # missing while `PUT /note` was live, which killed note-editor save in the
    # packaged build. Kept an explicit allowlist (not "*") on purpose: this is a
    # secret-guarded localhost surface. test_api_surface.py locks it to the route table.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

if not os.getenv("OMNI_GUI_SECRET", ""):
    print(
        "[server] WARNING: OMNI_GUI_SECRET is not set -- "
        "every route will reject with 403 until it is.",
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

# Single-flight for the Drive OAuth consent (E6). Two Connect clicks would otherwise race two
# local callback servers and two browser windows; the second gets a 409 instead.
_drive_connect_flight = threading.Lock()

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
    """Best-effort startup DB maintenance: corruption heal, then orphan purge, then
    body-excerpt backfill. Run sequentially in one task so they share one DB open and
    don't race."""
    def _run():
        root = _get_vault_root()
        try:
            # FIRST: purge and reindex below both assume a READABLE captures.db. A truncated /
            # half-flushed / bad-sector file raises DatabaseError on their first real read, and
            # each one's own `except` just prints and moves on — so a store corrupt at boot stayed
            # dead until the user happened to POST /vault/sync-index (the only other caller of the
            # heal). captures.db is a derived cache: discarding an unreadable one is the sanctioned
            # recovery, and init_db re-creates it from the DDL.
            from index_writer import heal_corrupt_db
            if heal_corrupt_db(root):
                print("[IndexWriter] startup discarded a corrupt captures.db "
                      "— it rebuilds from the vault files", flush=True)
        except Exception as exc:
            print(f"[IndexWriter] startup heal skipped: {exc}", flush=True)
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
        try:
            # R-1 finisher: the ledger was the one derived store nothing ever rebuilt -- the
            # capability existed, no caller invoked it. Policy (missing/empty only, never over a
            # live ledger) lives in dedup.py so this and the diff-sync reindex cannot drift.
            from dedup import rebuild_dedup_index_if_missing
            n = rebuild_dedup_index_if_missing(root)
            if n is not None:
                print(f"[Dedup] startup rebuilt a missing/empty dedup ledger — {n} keys "
                      "recovered from the vault files", flush=True)
        except Exception as exc:
            print(f"[Dedup] startup ledger rebuild skipped: {exc}", flush=True)
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
def _startup_sync_scheduler() -> None:
    """Drive batched-sync scheduler (phase-5 §1.1). Runs mobile_sync_agent.run_pass() on the
    [sync] interval in a daemon thread with single-flight + backoff + a ring-buffer status feed.
    Always started (cheap); it no-ops each tick while [sync] enabled = false, so flipping that
    flag needs no restart. run_pass raising (e.g. OAuth missing) is recorded as a paused
    status row, never crashes the loop or the server. Drive stays the sole canonical authority.

    NOTE (E6, s25 device day): this used to say "toggling the GUI Sync tab" -- THERE IS NO GUI
    SYNC TAB. `gui/src` has no consumer of /sync/status or /sync/run, so Drive sync is today
    enablable only by hand-editing config.toml [sync] enabled. The no-restart property below is
    real and the endpoints are real; only the GUI surface is missing. This blocked device-day
    items 1 and 2-step-10. Building that tab is frontend-only work -- do not read this comment as
    evidence it exists."""
    try:
        from sync_scheduler import start_scheduler
        from mobile_sync_agent import run_pass
        from config import reload_config
        start_scheduler(pass_fn=run_pass, cfg_fn=lambda: reload_config().sync)
    except Exception as exc:
        print(f"[sync] scheduler start failed: {exc}", flush=True)


@app.on_event("startup")
def _startup_lan_listener() -> None:
    """Optional same-WiFi LAN sync accelerator (contract §11). Off by default --
    only starts when [lan] enabled = true and a host is configured. This is a
    SEPARATE listener/app (lan_server.build_lan_app()) exposing ONLY /lan/*; it
    never touches this loopback GUI app or its routes.
    # ponytail: LAN listener lifecycle rides the main process; a restart re-reads
    # [lan] config -- no hot-reload of the [lan] PORT. The HOST is now self-healing
    # (lan_server's rebind supervisor follows a DHCP/WiFi address change)."""
    try:
        import lan_server
        enabled, host, port = lan_server.lan_config()
        if enabled and host:
            # LAN-05: bind the single configured [lan] host, not 0.0.0.0. The reversal of the
            # previous all-interfaces bind — and the reasoning it replaces — is recorded on the
            # ponytail block in lan_server.py; the rebind supervisor started here keeps the socket
            # on a live address across network changes.
            if lan_server.start_lan_listener(host, port) is None:
                print(f"[LAN] listener not started: [lan] host {host!r} is not bindable", flush=True)
                return
            print(f"[LAN] listener on {host}:{port}", flush=True)
            try:
                # mDNS advertise (contract §11.8-A) — same gate as the listener itself
                # ([lan] enabled + host configured); best-effort, never blocks startup.
                import lan_discovery
                from config import get_config
                vault_path = str(get_config().vault.root)
                device_id = lan_discovery.get_or_create_device_id(vault_path)
                lan_discovery.start_advertising(device_id, port)
            except Exception as exc:
                print(f"[LAN] mDNS advertise startup skipped: {exc}", flush=True)
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


# ---------------------------------------------------------------------------
# In-flight claim (API-2 / OF-2): the terminal map above is check-then-act --
# it is only written when the pipeline REACHES its terminal. A retry issued
# while the first attempt is still running (a lost SSE connection does NOT stop
# the server-side pipeline in _executor) misses the map and would dispatch the
# pipeline a SECOND time -> two notes for one capture. We close that window by
# claiming the run_id BEFORE dispatch: a concurrent/subsequent attempt with the
# same run_id becomes a WAITER on the owner's completion instead of a second run.
#
# The claim's lifetime is the PIPELINE, not the SSE generator: a client
# disconnect cancels the generator while the pipeline keeps running, so release
# lives in _run_pipeline_blocking's finally (disconnect-safe) AND, mirroring the
# dual terminal-record design, in _stream_capture's owner loop after the pipeline
# signals done (covers test doubles that replace _run_pipeline_blocking). pop is
# idempotent, so releasing twice is harmless.
_capture_inflight: dict[str, threading.Event] = {}  # run_id -> done signal, guarded by _capture_results_lock


def _claim_capture_run(run_id: str) -> tuple[str, object]:
    """Atomically resolve this attempt's role for run_id:
      ("terminal", entry) -- pipeline already finished; replay entry (dict).
      ("waiter", event)   -- another attempt is mid-pipeline; wait on the Event.
      ("owner", None)     -- we claimed it; we must run the pipeline AND release.
    """
    with _capture_results_lock:
        entry = _capture_results.get(run_id)
        if entry is not None:
            return "terminal", dict(entry)
        ev = _capture_inflight.get(run_id)
        if ev is not None:
            return "waiter", ev
        _capture_inflight[run_id] = threading.Event()
        return "owner", None


def _release_capture_run(run_id: str) -> None:
    with _capture_results_lock:
        ev = _capture_inflight.pop(run_id, None)
    if ev is not None:
        ev.set()  # wake waiters OUTSIDE the lock (never hold the lock across a wake)


def _request_hash(content_type: str, content: str) -> str:
    # Hash the FULL content: truncating to a prefix made two distinct captures
    # sharing that prefix (licence headers, templated docs, repeated article
    # chrome) collide, and the second was silently dropped as a duplicate inside
    # _DEDUP_WINDOW_S. The content is already in memory; sha256 over it is cheap.
    raw = f"{content_type}:{content}"
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

    SRV-01: fails CLOSED. An unset/empty OMNI_GUI_SECRET is a misconfiguration,
    not a development convenience -- degrading to "no auth" would leave every
    route (incl. DELETE /vault/categories/{name}?force=true, a shutil.rmtree,
    and PUT /note) open to any local process. Same shape as
    lan_sync._check_secret, which has always refused to degrade.

    SRV-21: read via os.getenv on EVERY call, not once at import, so a rotated
    secret takes effect on the running server without a re-import. The Tauri
    shell re-arms the child process on rotation (lib.rs:rotate_secret).
    """
    secret = os.getenv("OMNI_GUI_SECRET", "")
    if not secret:
        raise HTTPException(status_code=403, detail="gui secret not configured")
    if not hmac.compare_digest(x_omni_secret or "", secret):
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

# SRV-12: the pipeline's dispatch is an if/elif chain whose final `else` is the
# text branch, so an unrecognised content_type used to be silently captured AS
# TEXT and answered 200 -- a base64 image sent under a typo'd type landed in the
# vault as a wall of base64. The set is the trust boundary; /capture rejects
# anything outside it with a 400 before the SSE stream opens.
_VALID_CONTENT_TYPES = frozenset({"text", "url", "image_b64", "audio_b64"})


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
    sync_enabled: Optional[bool] = None
    sync_interval_minutes: Optional[int] = None
    sync_on_launch: Optional[bool] = None
    sync_after_capture: Optional[bool] = None
    sync_mirror_captures: Optional[bool] = None

class InboxApprove(BaseModel):
    target_category: Optional[str] = None

class ReminderCreate(BaseModel):
    note_path: str
    label: str
    when_iso: str
    delivery: Optional[str] = None
    notify: bool = False

class NoteBodyUpdate(BaseModel):
    path: str
    body: str
    expected_mtime: float

class NoteAttachmentCreate(BaseModel):
    path: str
    filename: str
    data_b64: str
    expected_mtime: float

class ConflictResolveRequest(BaseModel):
    path: str
    conflict_path: str
    action: str  # "both" | "mine" | "theirs"
    expected_mtime: Optional[float] = None  # required for "theirs" (concurrency guard)


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
        # SRV-16: this used to publish cfg into os.environ (OMNI_VAULT_ROOT,
        # OLLAMA_MODEL/BASE_URL/KEEP_ALIVE) on every capture. os.environ is
        # process-global and _executor runs two captures at once, so two
        # concurrent pipelines raced on it -- and because config.py reads those
        # same vars as OVERRIDES, the first capture permanently pinned them,
        # making a later config.toml edit invisible. The writes are gone; the
        # readers (llm_engine._ollama_setting, used by _make_client /
        # run_llm_engine / summarizer) now resolve env-first-then-config
        # themselves, so an explicit CLI/test env var still wins and nothing
        # mutates shared state per request.
        # Keep cfg.ollama.base_url BARE (canonical host) everywhere -- "/v1" is
        # appended only at the moment an OpenAI-compatible client is constructed
        # (llm_engine._normalize_base_url), never written back, or it poisons the
        # native Ollama vision/embeddings endpoints (/api/...).

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
        # Release the in-flight claim (OF-2). This runs even if the client
        # disconnected mid-stream -- the pipeline finished here regardless -- so a
        # retry that arrived while we were running gets the recorded terminal, not
        # a second dispatch. Terminal for a successful run was already recorded by
        # emit() above, so a woken waiter sees it.
        if run_id:
            _release_capture_run(run_id)
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
    owner = False
    if run_id:
        role, obj = _claim_capture_run(run_id)
        if role == "terminal":
            prior = obj  # already-recorded terminal event
            print(f"[server] [run:{run_id}] idempotent retry -- replaying prior "
                  f"'{prior['event']}' instead of re-running the pipeline", flush=True)
            yield _sse(prior["event"], **prior["payload"])
            return
        if role == "waiter":
            # Another attempt with this run_id is mid-pipeline (a retry after a lost
            # SSE connection -- the server-side pipeline keeps running). Wait for it
            # instead of dispatching a second run that would write the note twice.
            print(f"[server] [run:{run_id}] retry while first attempt still in flight "
                  f"-- waiting for it instead of re-running the pipeline", flush=True)
            # SRV-19 (replaces the former `ponytail: block a default-executor thread
            # on the owner's completion` shortcut -- its stated ceiling was reached).
            # That version parked a thread from the SHARED default executor for up to
            # _CAPTURE_DEDUP_TTL_S per waiter, and nothing capped the waiter count, so
            # enough retries of an in-flight run_id starved every other
            # run_in_executor/to_thread user in the process. Polling the Event costs no
            # thread at all and wakes within one tick of the owner's release.
            deadline = time.monotonic() + _CAPTURE_DEDUP_TTL_S
            while not obj.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            prior = _get_capture_terminal(run_id)
            if prior is not None:
                yield _sse(prior["event"], **prior["payload"])
            else:
                # The in-flight attempt ended without a terminal (it errored or timed
                # out). Surface an error, never a false 'done'/'duplicate' -- the GUI
                # would otherwise drop a FAILED capture as if it had succeeded. A fresh
                # attempt (new run_id) still runs the pipeline normally.
                yield _sse("error", message="Capture attempt did not complete -- please retry.")
            return
        owner = True  # role == "owner": run the pipeline below, then release the claim.

    if _is_duplicate_request(content_type, content):
        yield _sse("duplicate")
        if owner:
            _release_capture_run(run_id)  # never leave a claim a waiter would hang on
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
        # phase-5 §1.1: opt-in sync-after-capture. Off by default (batch interval covers it);
        # when on, fire ONE best-effort background pass on the terminal event (single-flight in the
        # scheduler swallows overlap). Never blocks the SSE stream; a missing scheduler is a no-op.
        # E6: this is one of the three AUTOMATIC triggers, so interval_minutes = 0 ("never
        # auto-sync") suppresses it too -- see sync_scheduler.auto_sync_disabled.
        if event == "done":
            try:
                from sync_scheduler import get_scheduler, auto_sync_disabled
                from config import get_config as _get_cfg
                _sync = _get_cfg().sync
                if _sync.sync_after_capture and _sync.enabled and not auto_sync_disabled(_sync):
                    sch = get_scheduler()
                    if sch is not None:
                        loop.run_in_executor(_executor, sch._safe_pass)
            except Exception:
                pass
        yield _sse(event, **item)
    # Release the claim on NORMAL completion only (None received). Deliberately not
    # in a finally: a client disconnect raises GeneratorExit before None arrives, and
    # releasing then -- while the real pipeline is still running in _executor -- would
    # let the retry dispatch a second run (the exact double-write this fix closes).
    # _run_pipeline_blocking's own finally holds the claim until the run truly ends;
    # this line is the fallback for test doubles that replace it (no finally). pop is
    # idempotent, so the real path releasing in both places is harmless.
    if owner:
        _release_capture_run(run_id)


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

@app.get("/ollama/reachable")
async def ollama_reachable(_: None = Depends(_require_secret)):
    """Fast, LIVE Ollama reachability probe for the pre-capture stall guard (ISS-018).

    Distinct from /health's `model_ok`: that flag is set once by the startup warmup
    and goes stale the moment Ollama stops afterward (the common repro -- Ollama was
    up at launch, stopped later). This hits Ollama directly with a short timeout so
    a capture never waits on the probe longer than the wait it's meant to avoid.
    """
    from llm_engine import _ollama_setting
    base_url = _ollama_setting("OLLAMA_BASE_URL", "base_url", "http://localhost:11434").rstrip("/")

    def _ping() -> bool:
        try:
            with urlopen(f"{base_url}/api/tags", timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    reachable = await asyncio.to_thread(_ping)
    return {"reachable": reachable}


@app.post("/capture")
async def capture(
    req: CaptureRequest,
    _: None = Depends(_require_secret),
    x_capture_run_id: Optional[str] = Header(default=None, alias="X-Capture-Run-Id"),
):
    if req.content_type not in _VALID_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content_type {req.content_type!r}. "
                   f"Expected one of: {', '.join(sorted(_VALID_CONTENT_TYPES))}.",
        )
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


@app.get("/sync/status")
async def sync_status(_: None = Depends(_require_secret)):
    """Scheduler state + last-20 pass summaries (phase-5 §1.1).

    Built for a GUI Sync tab that does not exist yet (E6) -- this endpoint has no
    consumer in gui/src today. It works; nothing calls it."""
    from sync_scheduler import get_scheduler
    sch = get_scheduler()
    if sch is None:
        return {"enabled": False, "running": False, "last_pass": None, "last_error": None, "history": []}
    return sch.status()


@app.post("/sync/run")
async def sync_run(_: None = Depends(_require_secret)):
    """Manual sync-now. Three distinct refusals, three distinct client states:
      503 -- the scheduler never started (process-level failure)
      403 -- [sync] enabled = false: the master switch is off, so the whole syncing system is off
             and a manual pass is refused SERVER-SIDE, not merely hidden in the GUI
      409 -- a pass is already running (single-flight)
    [sync] interval_minutes = 0 ("never auto-sync") does NOT refuse here by design -- that sentinel
    gates only the automatic triggers; an explicit Sync now still runs.

    Runs off the event loop so the request never blocks; returns the pass summary row (ok:false if
    the pass itself failed, e.g. no auth)."""
    from sync_scheduler import get_scheduler, SyncBusy
    from config import get_config as _get_cfg
    sch = get_scheduler()
    if sch is None:
        raise HTTPException(status_code=503, detail="sync scheduler not started")
    if not _get_cfg().sync.enabled:
        raise HTTPException(status_code=403, detail="syncing is turned off in settings")
    try:
        return await asyncio.get_event_loop().run_in_executor(_executor, sch.run_now)
    except SyncBusy:
        raise HTTPException(status_code=409, detail="a sync pass is already running")


@app.get("/drive/auth/status")
async def drive_auth_status(_: None = Depends(_require_secret)):
    """Is Drive connected? Answered WITHOUT ever opening a consent browser (E6).

    The Sync tab's first question, and the one that explains an ok:false pass. `connecting` is
    surfaced so a second tab/panel sees an in-flight consent rather than an idle disconnected
    state."""
    from drive_auth import has_cached_credentials, client_secret_present
    return {
        "connected": has_cached_credentials(),
        "client_secret_present": client_secret_present(),
        "connecting": _drive_connect_flight.locked(),
    }


@app.post("/drive/auth/connect")
async def drive_auth_connect(_: None = Depends(_require_secret)):
    """Run the installed-app OAuth flow: opens a browser once, caches the token.

    409 if a consent is already in flight -- two clicks would otherwise race two local callback
    servers and two browser windows. 400 when no client_secret.json exists, because the flow could
    only raise FileNotFoundError; the GUI must fix setup instead of retrying.
    # ponytail: no timeout -- google-auth-oauthlib's run_local_server blocks until the user
    # consents or closes the browser, so an abandoned consent holds this request (and the flight
    # lock) until the client disconnects. Bounded to one at a time and local-only. Pass
    # timeout_seconds through if an abandoned consent ever actually wedges a session."""
    from drive_auth import load_credentials, client_secret_present
    if not client_secret_present():
        raise HTTPException(
            status_code=400,
            detail="no client_secret.json next to omni_capture/ -- add a Google OAuth client first",
        )
    if not _drive_connect_flight.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a Drive consent is already in progress")
    try:
        # NOT _executor: that pool is 2 workers shared with /capture and /sync/run, and a consent
        # blocks for as long as the user takes. asyncio.to_thread gets its own thread instead, so
        # an open browser window can never starve a capture.
        await asyncio.to_thread(load_credentials)
    except Exception as exc:  # consent declined/closed, bad client file, network -- never 500
        raise HTTPException(status_code=502, detail=f"Drive connect failed: {exc}")
    finally:
        _drive_connect_flight.release()
    return {"connected": True}


@app.post("/drive/auth/disconnect")
async def drive_auth_disconnect(_: None = Depends(_require_secret)):
    """Forget the cached token on this device. Revokes nothing at Google."""
    from drive_auth import forget_credentials
    return {"connected": False, "removed": forget_credentials()}


@app.get("/lan/device-id")
def lan_device_id(_: None = Depends(_require_secret)):
    """Stable desktop device-id (contract §11.4 pairing-payload `device` anchor). The GUI reads this
    to build the v3 pairing QR so the phone can match mDNS/hub-hint discovery to THIS desktop. Same
    value lan_discovery advertises + writes into `.sync/lan_endpoint.json`.

    Deliberately a plain `def`, not `async def`: `get_or_create_device_id` reads (and on first call
    writes) a file, and as a coroutine that blocked the event loop — stalling the /config,
    /sync/status and /drive/auth/status calls the Sync settings panel fires alongside it on mount.
    FastAPI runs a sync endpoint in its threadpool, so the blocking I/O stays off the loop."""
    import lan_discovery
    return {"device": lan_discovery.get_or_create_device_id(str(_get_vault_root()))}


@app.get("/config")
async def get_config_endpoint(_: None = Depends(_require_secret)):
    """SRV-02: config.toml holds two credentials -- `[gui] secret` (this API's own
    X-Omni-Secret) and `[lan] key` (the base64 NaCl secretbox key gating /lan/push
    and /lan/changes). Neither is ever served. The GUI reads the secret from the
    `get_gui_secret` / `get_pairing_info` Tauri commands, which are the only
    sanctioned source; nothing reads either key from this endpoint."""
    if not CONFIG_PATH.exists():
        return {}
    doc = tomlkit.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for section, key in (("gui", "secret"), ("lan", "key")):
        table = doc.get(section)
        if isinstance(table, dict) and key in table:
            del table[key]
    return doc

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
        # SRV-15: a relative root resolves against whatever CWD uvicorn happens to
        # have been launched from, which silently points the whole pipeline at a
        # different (or nonexistent) tree. Absolute only.
        if not Path(patch.vault_root).is_absolute():
            raise HTTPException(status_code=400, detail="vault_root must be an absolute path")
        _set("vault", "root", patch.vault_root)
    if patch.ollama_model is not None:
        _set("ollama", "model", patch.ollama_model)
    if patch.ollama_base_url is not None:
        # SRV-15: loopback only. This URL receives every capture body, every note
        # excerpt fed to chat, and every embedding -- pointing it at a remote host
        # turns a local-first pipeline into an exfiltration channel with one PATCH.
        parsed = urlparse(patch.ollama_base_url)
        if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
            raise HTTPException(status_code=400, detail="ollama_base_url must be an http(s) URL on localhost/127.0.0.1/::1")
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
        # SRV-18: mirrors the llm_scrutiny sibling above. Without the else, an
        # invalid value was silently dropped and the GUI reported success while
        # the setting never changed.
        if delivery not in ("app", "os"):
            raise HTTPException(status_code=400, detail="reminders_delivery must be app|os")
        _set("reminders", "delivery", delivery)
    if patch.sync_enabled is not None:
        _set("sync", "enabled", bool(patch.sync_enabled))
    if patch.sync_interval_minutes is not None:
        mins = int(patch.sync_interval_minutes)
        # 0 is the "never auto-sync" sentinel and must reach config.toml unclamped; every real
        # interval still has a 5-minute floor. 1-4 is neither, so it stays a 400.
        if mins != 0 and mins < 5:
            raise HTTPException(status_code=400, detail="sync_interval_minutes must be 0 (never) or >= 5")
        _set("sync", "interval_minutes", mins)
    if patch.sync_on_launch is not None:
        _set("sync", "sync_on_launch", bool(patch.sync_on_launch))
    if patch.sync_after_capture is not None:
        _set("sync", "sync_after_capture", bool(patch.sync_after_capture))
    if patch.sync_mirror_captures is not None:
        _set("sync", "mirror_captures", bool(patch.sync_mirror_captures))

    # SRV-14: atomic. This runs on EVERY PATCH /config, and a bare write_text truncates
    # the file that holds the vault root, the Ollama settings, and the LAN key -- a crash
    # mid-write left the app unable to find its own vault.
    atomic_write_text(CONFIG_PATH, tomlkit.dumps(doc))

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
        from rag_engine import hybrid_retrieve, build_system_prompt, parse_chat_mode, REFUSAL, OFFLINE_REPLY
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
            if tier == "offline":
                # ISS-009: Ollama couldn't be reached at all -- distinct from a
                # genuine no-match so the user knows to check the engine, not
                # to distrust their own notes.
                emit("meta", confidence=round(confidence, 4), tier="offline", answerable=False)
                emit("sources", sources=[])
                emit("token", text=OFFLINE_REPLY)
                look_info("POST /look/chat Ollama unreachable — offline reply")
                emit("done")
                return
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

    # SRV-03: the guard's RETURN VALUE is the sanitized name -- calling it only for
    # its raising side effect and then passing the raw `body.target_category` on to
    # approve_scratchpad_item let a traversal segment through to the join site.
    target_category = body.target_category
    if target_category:
        target_category = vault_admin._safe_category_dir(root, target_category).name

    is_new = bool(target_category) and not (root / target_category).exists()
    sample_text = get_scratchpad_item_text(note_id, root, cfg.vault.scratchpad_folder) if is_new else None

    try:
        dest = approve_scratchpad_item(note_id, root, cfg.vault.scratchpad_folder, target_category=target_category)
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
            partial(generate_category_description, target_category, sample_text=sample_text)
        )
        if generated:
            write_category_description(root / target_category, generated)

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


# -- Full-window note editor (F-7) ---------------------------------------------

@app.get("/note")
async def get_note(path: str, _: None = Depends(_require_secret)):
    """Read a note's body + read-only frontmatter fields for the in-app editor."""
    from note_editor import read_note
    root = _get_vault_root()
    try:
        return read_note(root, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Note not found: {path!r}")


@app.put("/note")
async def put_note(body: NoteBodyUpdate, _: None = Depends(_require_secret)):
    """Write a note's body only (frontmatter carried through byte-for-byte).
    Optimistic-concurrency guarded on `expected_mtime`: a 409 means the file
    changed on disk since the editor read it -- the caller must reload
    rather than retry-clobber (body-sacred + files-are-source-of-truth)."""
    from note_editor import read_note, write_note_body, NoteConflictError
    root = _get_vault_root()
    try:
        result = write_note_body(root, body.path, body.body, body.expected_mtime)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Note not found: {body.path!r}")
    except NoteConflictError as exc:
        raise HTTPException(status_code=409, detail={
            "message": "Note changed on disk since it was opened.",
            "current_mtime": exc.current_mtime,
            "current_body": exc.current_body,
        })
    return result


# -- F-13 (desktop half): attachments -----------------------------------------

@app.post("/note/attachment")
async def add_note_attachment(body: NoteAttachmentCreate, _: None = Depends(_require_secret)):
    """Write an uploaded file into `_attachments/<note-id>/`, record it in
    the note's `attachments` frontmatter, and append a `[attachment: ...]`
    link line to the body -- a normal user file-write through note_editor.py
    (body-sacred, same mtime guard as PUT /note)."""
    from note_editor import add_attachment, NoteConflictError
    root = _get_vault_root()
    try:
        data = base64.b64decode(body.data_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 attachment data.")
    try:
        result = add_attachment(root, body.path, body.filename, data, body.expected_mtime)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Note not found: {body.path!r}")
    except NoteConflictError as exc:
        raise HTTPException(status_code=409, detail={
            "message": "Note changed on disk since it was opened.",
            "current_mtime": exc.current_mtime,
            "current_body": exc.current_body,
        })
    return result


@app.get("/note/attachment")
async def get_note_attachment(path: str, filename: str, _: None = Depends(_require_secret)):
    """Serve one attachment's raw bytes (image thumbnail / audio playback in
    the NoteEditor viewer). Resolves via the same note-id folder convention
    add_attachment writes into."""
    import re as _re
    from fastapi.responses import FileResponse
    from frontmatter import read_all_fields as _read_fields
    from note_editor import resolve_note_path
    root = _get_vault_root()
    try:
        note_path = resolve_note_path(root, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not note_path.is_file():
        raise HTTPException(status_code=404, detail=f"Note not found: {path!r}")
    fields = _read_fields(note_path.read_text(encoding="utf-8", errors="ignore"))
    note_id = fields.get("id")
    if not note_id:
        raise HTTPException(status_code=404, detail="Note has no id")
    safe_name = _re.sub(r"[^\w.\-]", "_", filename) or "attachment"
    file_path = root.resolve() / "_attachments" / note_id / safe_name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(str(file_path))


# -- F-3: version history (Drive revisions) --------------------------------

@app.get("/note/history")
async def get_note_history_endpoint(path: str, _: None = Depends(_require_secret)):
    """List Drive revisions for one note. Runs off the event loop -- Drive
    calls are network I/O. status offline/not_synced are legitimate empty
    states the GUI renders, never surfaced as an error."""
    from note_history import get_note_history
    root = _get_vault_root()
    try:
        return await asyncio.get_event_loop().run_in_executor(_executor, get_note_history, root, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Note not found: {path!r}")


@app.get("/note/history/revision")
async def get_note_history_revision_endpoint(path: str, revision_id: str, _: None = Depends(_require_secret)):
    """Fetch one past revision's body (frontmatter stripped) for preview or
    as the source of a Restore, which the GUI performs via a normal PUT
    /note write (body-sacred: restore is just another user edit)."""
    from note_history import get_revision_body
    root = _get_vault_root()
    try:
        body = await asyncio.get_event_loop().run_in_executor(_executor, get_revision_body, root, path, revision_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"body": body}


# -- F-1: conflict resolver (desktop) --------------------------------------

@app.get("/note/conflict")
async def get_note_conflict_endpoint(path: str, _: None = Depends(_require_secret)):
    """None-or-payload: whether *path*'s note currently has a conflicted-copy
    sibling, and the two-sided diff data if so."""
    from conflict_resolver import get_conflict
    root = _get_vault_root()
    try:
        conflict = get_conflict(root, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Note not found: {path!r}")
    return {"conflict": conflict}


@app.post("/note/conflict/resolve")
async def resolve_note_conflict_endpoint(body: ConflictResolveRequest, _: None = Depends(_require_secret)):
    """Apply "both" | "mine" | "theirs" -- all three are ordinary file
    operations through paths this codebase already exercises elsewhere."""
    from conflict_resolver import resolve_conflict
    from note_editor import NoteConflictError
    root = _get_vault_root()
    try:
        return resolve_conflict(root, body.path, body.conflict_path, body.action, body.expected_mtime)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NoteConflictError as exc:
        raise HTTPException(status_code=409, detail={
            "message": "Note changed on disk since the conflict was opened.",
            "current_mtime": exc.current_mtime,
            "current_body": exc.current_body,
        })

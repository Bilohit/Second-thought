"""
jobs.py - background job registry + the async transcript-summarization worker
shared by the YouTube and long-recording voice capture paths.

Split out of server.py (docs/ROADMAP.md: "Split server.py into jobs.py +
vault_admin.py"). Job SUBMISSION still happens inside
`server.py:_run_pipeline_blocking` (per CLAUDE.md hard rule, that function must
stay in server.py hand-duplicated alongside `main.py:run_pipeline()` and must
not be restructured) -- server.py reaches into this module for the registry
and the background pool via `jobs._set_job`, `jobs._bg_executor`,
`jobs._run_youtube_job`, `jobs._run_voice_job` rather than duplicating any of
this state.

Router
  GET /jobs/{job_id}   background job status (e.g. a YouTube capture), polled
                       by the GUI. Mounted into server.app by server.py via
                       app.include_router(jobs.router,
                       dependencies=[Depends(_require_secret)]) so
                       X-Omni-Secret auth is enforced identically to every
                       other route -- this module has no dependency on
                       server.py itself.
"""
from __future__ import annotations
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException

# ---------------------------------------------------------------------------
# Background job registry. In-memory dict is the hot-path cache; it is
# write-through-backed by a `jobs` table in captures.db so a server restart
# (crash, update, manual bounce) mid-job doesn't 404 a client still polling
# GET /jobs/{id}. Same "operational/derived state, own table" carve-out as
# reminders.py -- the table is authoritative for nothing but job status, and
# a DB failure must never break in-memory tracking (files/ops are truth).
# ---------------------------------------------------------------------------
_jobs: dict[str, dict] = {}   # job_id -> {status, kind, category, path, error, created, updated}
_jobs_lock = threading.Lock()
_DEFAULT_JOB_TTL_S = 3600
# SRV-23: per-job retention, kept beside _jobs rather than inside the entry so it
# never leaks into a persisted row or a /jobs/{id} response. Guarded by _jobs_lock.
_job_ttl: dict[str, int] = {}

_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id   TEXT PRIMARY KEY,
    status   TEXT,
    kind     TEXT,
    category TEXT,
    path     TEXT,
    error    TEXT,
    created  REAL,
    updated  REAL
);
"""


def _db_path() -> Path:
    # Resolved live from config each call so tests pointing OMNI_VAULT_ROOT at a
    # temp vault (via reload_config) hit the right captures.db.
    from config import get_config
    from index_writer import get_db_path
    return get_db_path(get_config().vault.root)


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute(_JOBS_DDL)
    return conn


def _persist(job_id: str, entry: dict) -> None:
    # ponytail: connect-per-write; jobs are low-volume (youtube/voice bg jobs).
    # Pool the connection if job throughput ever climbs.
    try:
        conn = _connect()
        try:
            path = entry.get("path")
            conn.execute(
                "INSERT INTO jobs (job_id, status, kind, category, path, error, created, updated) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET "
                "status=excluded.status, kind=excluded.kind, category=excluded.category, "
                "path=excluded.path, error=excluded.error, updated=excluded.updated",
                (
                    job_id, entry.get("status"), entry.get("kind"), entry.get("category"),
                    str(path) if path is not None else None,
                    entry.get("error"), entry.get("created"), entry.get("updated"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"jobs: persist failed for {job_id}: {exc}")


def _delete_jobs(job_ids: list[str]) -> None:
    if not job_ids:
        return
    try:
        conn = _connect()
        try:
            conn.executemany("DELETE FROM jobs WHERE job_id = ?", [(j,) for j in job_ids])
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"jobs: stale-delete failed: {exc}")


def _row_to_entry(row: tuple) -> dict:
    return {
        "status": row[1], "kind": row[2], "category": row[3], "path": row[4],
        "error": row[5], "created": row[6], "updated": row[7],
    }


def load_jobs() -> int:
    """Reload persisted job rows into the in-memory cache. Called once at
    server startup so GET /jobs/{id} survives a restart."""
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT job_id, status, kind, category, path, error, created, updated FROM jobs"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        print(f"jobs: load failed: {exc}")
        return 0
    with _jobs_lock:
        for r in rows:
            _jobs[r[0]] = _row_to_entry(r)
    return len(rows)

# Separate pool for long-running background jobs (e.g. YouTube transcript
# fetch + summarisation) so they cannot starve normal /capture requests.
# Also reused by server.py's startup warmup/DB-maintenance tasks -- one small
# shared pool, not duplicated.
_bg_executor = ThreadPoolExecutor(max_workers=2)


def _set_job(job_id: str, ttl_seconds: int = _DEFAULT_JOB_TTL_S, **fields) -> None:
    now = time.time()
    with _jobs_lock:
        entry = _jobs.setdefault(job_id, {"created": now})
        entry.update(fields)
        entry["updated"] = now
        snapshot = dict(entry)

        # SRV-23: the sweep used to apply THIS caller's ttl_seconds to every entry in
        # the registry, so one _set_job(ttl_seconds=60) evicted every other job older
        # than a minute -- including hour-lived ones whose owner had asked for 3600 --
        # and a long-ttl call conversely resurrected the lifetime of short-ttl jobs.
        # Each job's own ttl is remembered at set time and only that ttl retires it.
        _job_ttl[job_id] = ttl_seconds
        stale = [
            k for k, v in _jobs.items()
            if now - v.get("updated", now) > _job_ttl.get(k, _DEFAULT_JOB_TTL_S)
        ]
        for k in stale:
            _job_ttl.pop(k, None)
        for k in stale:
            del _jobs[k]
    # DB writes outside the lock -- sqlite has its own; don't serialize callers on it.
    _persist(job_id, snapshot)
    _delete_jobs(stale)


def _get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        entry = _jobs.get(job_id)
        if entry is not None:
            return dict(entry)
    # Cache miss: after a restart before load_jobs(), or an evicted-but-persisted
    # row. Fall back to the table so a poll still resolves.
    try:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT job_id, status, kind, category, path, error, created, updated "
                "FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        print(f"jobs: get fallback failed for {job_id}: {exc}")
        return None
    return _row_to_entry(row) if row is not None else None


@dataclass
class _TranscriptFetch:
    """Result of the one step that differs between the YouTube and voice
    transcript-job workers -- fetching via youtube-transcript-api vs. a
    transcript already in hand. Produced by a `fetch_transcript` closure,
    which must ALSO perform the write-before-summarize vault write (so the
    source text is never lost even if summarization later fails)."""
    full_text: str
    segments: list  # list[dict] -- chunk_transcript's expected shape
    path: Path      # vault note path, already written with the raw transcript
    category: str   # job's completed `category` field
    dedup_source: str  # `source` arg for register_in_dedup_index
    log_enriched: object  # enriched-payload-like object passed to log_capture


def _run_transcript_job(
    job_id: str,
    cfg,
    *,
    kind: str,
    ttl_seconds: Optional[int],
    fetch_transcript: Callable[[Callable[..., None]], _TranscriptFetch],
) -> None:
    """
    Shared body of the YouTube/voice background job workers -- driving the
    async map-reduce summarization pipeline:

      [fetching ->] writing_transcript -> summarizing -> [combining] ->
      finalizing -> done | error

    `fetch_transcript` is called with `set_status` and supplies the transcript
    (fetched or already in hand) plus the vault note path -- ALREADY WRITTEN
    with the full raw transcript BEFORE any LLM call, so the source text is
    never lost even if summarization later fails or the process crashes
    mid-job. `kind` ("youtube"/"voice") only affects log/print tags, never the
    job-status payload. `ttl_seconds=None` defers to `_set_job`'s own default
    (matches the original voice worker, which never overrode it).
    """

    def set_status(status: str, **extra) -> None:
        if ttl_seconds is None:
            _set_job(job_id, status=status, **extra)
        else:
            _set_job(job_id, ttl_seconds=ttl_seconds, status=status, **extra)

    try:
        import asyncio
        from functools import partial

        from storage_engine import finalize_youtube_note, register_in_dedup_index
        from summarizer import count_tokens, chunk_transcript, _map_phase, reduce_summaries
        from llm_engine import summarize_async, DETAILED_SUMMARY_PROMPT, OLLAMA_API_KEY, _normalize_base_url
        from openai import AsyncOpenAI

        # Canonical bare host (matches the project-wide invariant: base_url is
        # always bare; /v1 is added only at OpenAI-compatible client construction
        # via _normalize_base_url). count_tokens below hits Ollama's native
        # /api/tokenize and needs the bare host; the AsyncOpenAI client gets /v1.
        base_url = cfg.ollama.base_url.rstrip("/")
        model = cfg.ollama.model

        fetched = fetch_transcript(set_status)
        full_text, segments, path = fetched.full_text, fetched.segments, fetched.path
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
                print(f"[server] {kind} job {job_id} vector index skipped: {exc}", flush=True)

        # SRV-22: the dedup ledger is a rebuildable cache, so a registration failure
        # must not fail a capture whose note is already written -- but it must not be
        # invisible either. The old bare `except: pass` let the very next line report
        # an unqualified "done" while this note stayed absent from the ledger, so a
        # re-capture of the same video would silently duplicate it. Log it, record it
        # against index_health (surfaced by /health), and carry a `warning` on the
        # terminal status so "done" is honest about what did not happen.
        dedup_warning = None
        try:
            register_in_dedup_index(summary, fetched.dedup_source, cfg.vault.root, path)
        except Exception as exc:
            dedup_warning = f"dedup registration failed: {exc}"
            print(f"[server] {kind} job {job_id} {dedup_warning}", flush=True)
            import index_health
            index_health.record_failure("dedup", exc)

        set_status("done", category=fetched.category, path=str(path), warning=dedup_warning)

        try:
            from notifier import notify_capture_success
            from capture_log import log_capture
            from models import CaptureOutput
            if cfg.notifications.enabled:
                notify_capture_success(category=fetched.category,
                                       filepath=str(path),
                                       title_prefix=cfg.notifications.title_prefix)
            minimal_output = CaptureOutput(
                category=fetched.category,
                suggested_filename=path.stem,
                markdown_content=summary,
                confidence=1.0,
            )
            log_capture(minimal_output, fetched.log_enriched, str(path), cfg.ollama.model)
        except Exception:
            pass

    except Exception as exc:
        print(f"[server] {kind} job {job_id} failed: {exc}", flush=True)
        set_status("error", error=str(exc))


def _run_youtube_job(job_id: str, url: str, cfg) -> None:
    """Background worker driving the async YouTube transcript+summarize job
    (see `_run_transcript_job`). The YouTube-specific step is fetching the
    transcript via youtube-transcript-api and writing the vault note with the
    fetch-timestamp header, done by the `fetch_transcript` closure below."""

    def fetch_transcript(set_status: Callable[..., None]) -> _TranscriptFetch:
        from datetime import datetime

        from enrichment_router import fetch_youtube_transcript
        from models import EnrichedPayload
        from storage_engine import create_youtube_note

        set_status("fetching")
        transcript = fetch_youtube_transcript(url)

        if not transcript.get("transcript_available"):
            print(f"[server] youtube job {job_id} failed: no captions available "
                  f"(url={url}, detail={transcript.get('error', 'n/a')})", flush=True)
            raise RuntimeError("No captions available for this video")

        full_text = transcript["full_text"]
        title = transcript.get("title")
        segments = transcript["segments"]

        fetched_note = f"*{len(segments)} segments • fetched {datetime.now().isoformat(timespec='seconds')}*"
        transcript_md = f"{fetched_note}\n\n{full_text}"
        path = create_youtube_note(
            title, url, transcript_md, cfg.vault.root, cfg.youtube, cfg.vault.scratchpad_folder,
        )
        return _TranscriptFetch(
            full_text=full_text,
            segments=segments,
            path=path,
            category=cfg.youtube.folder_name,
            dedup_source=url,
            log_enriched=EnrichedPayload(
                raw_input=url, input_type="url_youtube", enriched_text=full_text, source_url=url,
            ),
        )

    _run_transcript_job(
        job_id, cfg, kind="youtube",
        ttl_seconds=cfg.youtube.job_ttl_seconds,
        fetch_transcript=fetch_transcript,
    )


def _run_voice_job(job_id: str, enriched, cfg) -> None:
    """Background worker driving the long-recording voice transcript+summarize
    job (see `_run_transcript_job`) -- same worker as YouTube's, minus the
    fetching phase (transcript already in hand)."""

    def fetch_transcript(set_status: Callable[..., None]) -> _TranscriptFetch:
        from storage_engine import create_voice_note

        full_text = enriched.enriched_text
        title = None
        segments = [{"text": ln} for ln in full_text.splitlines() if ln.strip()]

        path = create_voice_note(title, full_text, cfg.vault.root, cfg.vault.scratchpad_folder)
        return _TranscriptFetch(
            full_text=full_text,
            segments=segments,
            path=path,
            category=path.parent.name,
            dedup_source=str(path),
            log_enriched=enriched,
        )

    _run_transcript_job(
        job_id, cfg, kind="voice",
        ttl_seconds=None,
        fetch_transcript=fetch_transcript,
    )


# -- Router (mounted by server.py) --------------------------------------------

router = APIRouter()


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
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
        # SRV-22: non-fatal degradation recorded alongside a successful terminal
        # status (e.g. the note was written but dedup registration failed).
        "warning": job.get("warning"),
    }


if __name__ == "__main__":
    # Smoke check: registry set/get/TTL-sweep behaves like a plain dict store,
    # independent of any FastAPI wiring. _set_job now write-throughs to
    # captures.db, so isolate in a temp vault -- otherwise a standalone
    # `python jobs.py` would pollute the user's real vault DB with dummy rows.
    import os, tempfile
    import config
    _tmp = tempfile.TemporaryDirectory()
    os.environ["OMNI_VAULT_ROOT"] = _tmp.name
    config.reload_config()

    _set_job("job-a", ttl_seconds=100, status="queued", kind="voice")
    assert _get_job("job-a")["status"] == "queued"
    _set_job("job-a", status="summarizing", chunk_index=1, chunk_total=3)
    entry = _get_job("job-a")
    assert entry["status"] == "summarizing" and entry["chunk_total"] == 3
    assert _get_job("does-not-exist") is None

    # The sweep threshold is the ttl_seconds passed to the *next* _set_job
    # call, applied to every entry's age -- an old entry is swept once some
    # later call passes a ttl smaller than that entry's age.
    _set_job("job-old", ttl_seconds=1000, status="queued")
    time.sleep(0.05)
    _set_job("job-new", ttl_seconds=0.01, status="queued")
    assert _get_job("job-old") is None
    assert _get_job("job-new") is not None

    _tmp.cleanup()
    print("jobs.py smoke check OK")

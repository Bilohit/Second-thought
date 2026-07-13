"""
main.py
-------
Project Second Thought -- Pipeline Orchestrator

Wires the four pipeline stages together and provides a CLI entry point.

Usage
  python main.py                      # reads clipboard, runs full pipeline
  python main.py --text "..."         # inject text directly (testing)
  python main.py --url  "..."         # inject URL directly (testing)
  python main.py --audio /path/to.mp3 # transcribe a local audio file
  python main.py --vault /path/to/obsidian-vault
  python main.py --model llama3.2
  python main.py --dry-run            # print output without writing to vault
  python main.py --log                # tail recent captures from the audit log
  python main.py --log --stats        # show category breakdown
  python main.py --self-check         # verify environment and exit

Pipeline
  Interceptor -> Enrichment Router -> LLM Decision Engine -> Storage Engine
                                                          -> Notifier
                                                          -> Capture Log
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Second Thought: autonomous Second Brain capture pipeline."
    )

    # -- Input source (mutually exclusive) -------------------------------------
    group = p.add_mutually_exclusive_group()
    group.add_argument("--text",  metavar="TEXT",  help="Inject raw text (skip clipboard).")
    group.add_argument("--url",   metavar="URL",   help="Inject a URL (skip clipboard).")
    group.add_argument("--audio", metavar="FILE",  help="Transcribe a local audio file via Whisper.")

    # -- Config overrides ------------------------------------------------------
    p.add_argument(
        "--vault",
        metavar="PATH",
        default=None,
        help="Override vault root path (also: OMNI_VAULT_ROOT env var).",
    )
    p.add_argument(
        "--model",
        metavar="MODEL",
        default=None,
        help="Override Ollama model tag (also: OLLAMA_MODEL env var).",
    )
    p.add_argument(
        "--ollama-url",
        metavar="URL",
        default=None,
        help="Override Ollama base URL (also: OLLAMA_BASE_URL env var).",
    )
    p.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to a custom config.toml (default: omni_capture/config.toml).",
    )

    # -- Behaviour flags -------------------------------------------------------
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the LLM output as JSON without writing to disk.",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print intermediate pipeline stage outputs.",
    )
    p.add_argument(
        "--no-notify",
        action="store_true",
        help="Suppress desktop notifications for this run.",
    )

    # -- Log viewer ------------------------------------------------------------
    p.add_argument(
        "--log",
        action="store_true",
        help="Show recent capture log entries instead of running the pipeline.",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Used with --log: show category breakdown statistics.",
    )
    p.add_argument(
        "--n",
        type=int,
        default=20,
        help="Number of log entries to show (default: 20).",
    )

    # -- Self-check ------------------------------------------------------------
    p.add_argument(
        "--self-check",
        action="store_true",
        help=(
            "Verify environment and exit: checks Ollama connectivity, "
            "required model availability, vault write permissions, and config validity."
        ),
    )

    return p.parse_args()


# mirrored from server.py by design (main.py cannot import server.py -- see
# CLAUDE.md's hand-duplication rule for main.py/server.py).
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


def run_pipeline(
    text: str | None = None,
    url:  str | None = None,
    image: str | None = None,
    audio: str | None = None,
    vault_root: str | None = None,
    model: str | None = None,
    ollama_url: str | None = None,
    config_path: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    notify: bool = True,
) -> dict:
    """
    Execute the full Second Thought pipeline.

    Returns the dict representation of the final CaptureOutput,
    with an extra '_written_to' key when dry_run is False.
    """
    # -- Load config first, then apply CLI overrides ---------------------------
    from config import reload_config
    cfg = reload_config(Path(config_path) if config_path else None)

    if vault_root:
        cfg.vault.root = Path(vault_root).expanduser()
    if model:
        cfg.ollama.model = model
    if ollama_url:
        cfg.ollama.base_url = ollama_url

    # Push into env so lazy-imported modules (llm_engine) pick them up
    os.environ["OMNI_VAULT_ROOT"] = str(cfg.vault.root)
    os.environ["OLLAMA_MODEL"]    = cfg.ollama.model
    # Keep OLLAMA_BASE_URL bare (canonical host). "/v1" is appended only at
    # the moment an OpenAI-compatible client is constructed (see
    # llm_engine._normalize_base_url) -- never written back here, or it
    # leaks into cfg.ollama.base_url on the next reload_config() and
    # poisons the native Ollama vision/embeddings endpoints (/api/...).
    os.environ["OLLAMA_BASE_URL"] = cfg.ollama.base_url.rstrip("/")

    # -- Lazy imports (env vars must be set first) -----------------------------
    from interceptor       import read_clipboard, InputPayload, ClipboardEmpty, ClipboardError
    from enrichment_router import route_and_enrich
    from llm_engine        import run_llm_engine
    from storage_engine    import write_to_vault, read_existing_context, build_category_descriptions
    from notifier          import notify_capture_success, notify_capture_error
    from capture_log       import log_capture
    from pre_resolver      import pre_resolve
    from vector_store      import retrieve_related, index_note
    from timing            import StageTimer
    import uuid as _uuid
    timer = StageTimer(run_id=_uuid.uuid4().hex[:8])

    vault = cfg.vault.root
    scratchpad_folder = cfg.vault.scratchpad_folder

    # Discover categories from the vault's current folder structure.
    # This runs on every pipeline invocation so folder additions/removals
    # are picked up without restarting the process.
    category_descriptions = build_category_descriptions(vault, scratchpad_folder)

    # -- Stage 1: Intercept ----------------------------------------------------
    if text:
        payload = InputPayload(raw=text, input_type="text")
    elif url:
        payload = InputPayload(raw=url, input_type="url")
    elif image:
        payload = InputPayload(
            raw=image, input_type="image_bytes", image_bytes=Path(image).read_bytes()
        )
    elif audio:
        # Audio files bypass read_clipboard entirely; Stage 2 calls _enrich_audio
        # directly, so payload is only used for verbose logging here.
        payload = InputPayload(raw=audio, input_type="text")
    else:
        payload = read_clipboard()

    if verbose:
        print(f"\n[Stage 1 -- Interceptor]")
        print(f"  type : {payload.input_type}")
        print(f"  raw  : {payload.raw[:120]!r}")

    # -- Stage 2: Enrich -------------------------------------------------------
    if audio:
        # Direct audio path: bypass route_and_enrich and call audio handler
        from enrichment_router import _enrich_audio
        with timer.stage("enrich"):
            enriched = _enrich_audio(audio)
    else:
        with timer.stage("enrich"):
            enriched = route_and_enrich(payload)

    if verbose:
        print(f"\n[Stage 2 -- Enrichment Router]")
        print(f"  input_type : {enriched.input_type}")
        print(f"  excerpt    : {enriched.enriched_text[:200]!r}")

    if enriched.source_metadata.get("vision_available") is False:
        # Vision failed at capture time. The placeholder enriched_text carries
        # no real content -- classifying or semantically retrieving against
        # it would only launder the failure into a confident (and wrong)
        # category. Route straight to scratchpad instead, flagged for retry.
        from storage_engine import route_failed_vision
        result: dict = {"category": "Unprocessed_Images", "vision_available": False}
        if dry_run:
            print("\n[Dry Run] Vision failed -- would route to scratchpad for retry.")
            result["_written_to"] = None
        else:
            with timer.stage("write_scratchpad"):
                written_path = route_failed_vision(
                    enriched.source_metadata,
                    vault_root=vault,
                    scratchpad_folder=scratchpad_folder,
                )
            result["_written_to"] = str(written_path)
            print(f"\nVision recognition failed -- saved for retry -> {written_path}")
            if notify and cfg.notifications.enabled:
                from notifier import notify_capture_error
                notify_capture_error(
                    "Vision recognition failed -- image saved for retry.",
                    title_prefix=cfg.notifications.title_prefix,
                )
        timer.log_summary()
        return result

    # ponytail: synchronous map-reduce; promote to a background job like
    # voice/youtube if pastes ever exceed ~30k tokens.
    _large_text_original: str | None = None
    _large_text_chunk_tags: list[list[str]] = []
    if enriched.input_type == "text":
        from summarizer import _char_estimate
        # Cheap local estimate first (propose-then-verify, same pattern as
        # chunk_transcript) -- avoids a network /api/tokenize probe for every
        # ordinary-length text capture; only texts that could plausibly be
        # over threshold pay for the real count.
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

    # -- Stage 3: Pre-Resolver + Semantic Retrieval -> LLM (single pass) -------
    t_res0 = time.perf_counter()

    with timer.stage("retrieve"):
        resolved = pre_resolve(enriched, vault)

        semantic_snippets: list[str] = []
        if cfg.vector.enabled:
            semantic_snippets = retrieve_related(
                vault,
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
        existing_context: str | None = "\n\n---\n\n".join(ctx_parts) if ctx_parts else None

    t_res1 = time.perf_counter()

    if verbose:
        print(f"\n[Stage 2.5 -- Context Assembly]  ({(t_res1 - t_res0) * 1000:.1f} ms)")
        print(f"  resolver hint    : {resolved.category_hint}  certainty={resolved.certainty}")
        print(f"  resolver ctx     : {len(resolved.existing_context or '')} chars")
        print(f"  semantic snippets: {len(semantic_snippets)}")
        print(f"  total ctx chars  : {len(existing_context or '')}")

    t_llm0 = time.perf_counter()
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

            # Two-pass fallback: the pre-resolver was uncertain, but now that the LLM
            # has picked a category we can check for an existing CRM/Finance file and
            # re-run with that context loaded.
            pass_count = 1
            if resolved.certainty == "low" and output.category in ("CRM", "Finance"):
                fallback_context = read_existing_context(output, vault_root=vault)
                if fallback_context:
                    output = run_llm_engine(
                        enriched,
                        category_descriptions=category_descriptions,
                        existing_context=fallback_context,
                        max_retries=cfg.capture.llm_max_retries,
                        temperature=cfg.capture.llm_temperature,
                        scrutiny=cfg.capture.llm_scrutiny,
                    )
                    pass_count = 2
    except Exception as exc:
        # LLM enrichment failed even after the two-pass retry (Ollama down,
        # model error, or a parse failure) -- fail-soft like every other
        # enrichment path (see CLAUDE.md): route the raw captured text to the
        # scratchpad flagged for retry instead of losing it. Mirrors the
        # vision-failure early return above; this except has no access to
        # `enriched`/`vault` once it unwinds past run_pipeline(), so it must
        # be handled here rather than in the __main__ top-level catch.
        from storage_engine import route_failed_llm
        print(f"\n[Second Thought] LLM enrichment failed: {exc}", file=sys.stderr)
        result = {"category": "Unprocessed_Captures", "llm_failed": True}
        if dry_run:
            print("[Dry Run] LLM failed -- would route to scratchpad for retry.")
            result["_written_to"] = None
        else:
            # Prefer the ORIGINAL full text for large-text captures -- enriched_text
            # was overwritten above with chunk[0]+section summaries.
            fail_text = _large_text_original if _large_text_original is not None else enriched.enriched_text
            with timer.stage("write_scratchpad"):
                written_path = route_failed_llm(
                    fail_text,
                    str(exc),
                    vault_root=vault,
                    scratchpad_folder=scratchpad_folder,
                    source_url=enriched.source_url,
                )
            result["_written_to"] = str(written_path)
            print(f"LLM enrichment failed -- saved for retry -> {written_path}")
            if notify and cfg.notifications.enabled:
                notify_capture_error(
                    "LLM enrichment failed -- capture saved for retry.",
                    title_prefix=cfg.notifications.title_prefix,
                )
        timer.log_summary()
        return result
    t_llm1 = time.perf_counter()

    if verbose:
        print(f"\n[Stage 3 -- LLM Decision Engine]")
        print(f"  category          : {output.category}")
        print(f"  suggested_filename: {output.suggested_filename}")
        print(f"  requires_new_cat  : {output.requires_new_category}")
        print(f"  key_signals       : {output.key_signals}")
        print(f"  markdown_content  :\n{output.markdown_content[:300]}")
        print(f"  timing            : {(t_llm1 - t_llm0) * 1000:.0f} ms  [{pass_count}-pass]")
        print(f"  active categories : {list(category_descriptions.keys())}")

    if _large_text_original is not None:
        from index_writer import get_db_path
        from tag_vocab import load_vocab
        try:
            vocab = load_vocab(get_db_path(vault))
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

    # mirrored from server.py by design (main.py cannot import server.py --
    # see CLAUDE.md's hand-duplication rule for main.py/server.py).
    def _append_transcript(markdown: str, enriched) -> str:
        """Voice notes keep the full transcript below the LLM summary."""
        if enriched.input_type != "audio":
            return markdown
        return f"{markdown}\n\n## Transcript\n\n{enriched.enriched_text}"

    output.markdown_content = _append_transcript(output.markdown_content, enriched)

    result = output.model_dump()

    # -- Stage 4: Storage ------------------------------------------------------
    if dry_run:
        print("\n[Dry Run] Would write:")
        print(json.dumps(result, indent=2))
        result["_written_to"] = None
    else:
        with timer.stage("write"):
            written_path = write_to_vault(
                output,
                source_url=enriched.source_url,
                vault_root=vault,
                scratchpad_folder=scratchpad_folder,
                enable_semantic_merge=cfg.vector.enabled,
                embed_base_url=cfg.ollama.base_url,
                embed_model=cfg.vector.embed_model,
                source_metadata=enriched.source_metadata,
            )
        result["_written_to"] = str(written_path)
        print(f"\nCaptured -> {written_path}")

        from datetime import datetime
        from models import filter_future_events
        future = filter_future_events(output.detected_events, datetime.now())
        for e in future:
            print(f"[events] {e.when_iso} — {e.label} (set reminders from the GUI)")

        if cfg.vector.enabled:
            # Derived-index write is FAIL-SOFT: the vault .md is already written
            # (source of truth), so an embeddings/index failure must never turn a
            # successful capture into a hard error -- swallow + log, per CLAUDE.md
            # "files are the source of truth, DBs are derived indexes". Mirrors
            # the same guard in server.py:_run_pipeline_blocking.
            with timer.stage("index"):
                try:
                    note_text = Path(written_path).read_text(encoding="utf-8", errors="ignore")
                    index_note(
                        vault,
                        Path(written_path),
                        note_text,
                        cfg.ollama.base_url,
                        cfg.vector.embed_model,
                    )
                except Exception as index_exc:
                    print(f"[Second Thought] index write failed (note still saved): {index_exc}", file=sys.stderr)

        if notify and cfg.notifications.enabled:
            with timer.stage("notify"):
                notify_capture_success(
                    category=output.category,
                    filepath=str(written_path),
                    title_prefix=cfg.notifications.title_prefix,
                )

        log_capture(output, enriched, str(written_path), cfg.ollama.model)

        if output.requires_new_category:
            print(
                f"\nNote sent to scratchpad for manual review: "
                f"{vault / scratchpad_folder}"
            )

    timer.log_summary()
    return result


# -- Self-check helper ---------------------------------------------------------

def run_self_check(config_path: str | None = None) -> bool:
    """
    Verify the Second Thought environment and print a structured report.

    Checks:
      1. Config file found and parseable
      2. Vault root exists and is writable
      3. Ollama server reachable
      4. Primary LLM model available in Ollama
      5. Vision model (LLaVA) available in Ollama
      6. Whisper package importable
      7. SQLite index directory writable
      8. Index health (last captures.db / vectors.db write outcome, in-process)

    Returns True if all checks pass, False otherwise (exits non-zero in CLI).
    """
    import urllib.request
    import urllib.error

    GREEN  = "\033[32m"
    RED    = "\033[31m"
    YELLOW = "\033[33m"
    RESET  = "\033[0m"

    def ok(msg):   print(f"  {GREEN}OK{RESET}  {msg}")
    def fail(msg): print(f"  {RED}FAIL{RESET}  {msg}")
    def warn(msg): print(f"  {YELLOW}WARN{RESET}  {msg}")

    print("\n-- Second Thought Self-Check ------------------------------------------")
    all_ok = True

    # 1. Config
    print("\n[1] Config")
    try:
        from config import reload_config
        cfg = reload_config(Path(config_path) if config_path else None)
        ok(f"config loaded  (model={cfg.ollama.model}, vault={cfg.vault.root})")
    except Exception as exc:
        fail(f"Config load failed: {exc}")
        all_ok = False
        cfg = None  # type: ignore[assignment]

    if cfg is None:
        print("\n  Cannot continue without a valid config.")
        return False

    # 2. Vault root
    print("\n[2] Vault")
    vault = cfg.vault.root
    try:
        vault.mkdir(parents=True, exist_ok=True)
        probe = vault / ".omni_write_probe"
        probe.write_text("ok")
        probe.unlink()
        ok(f"vault writable  ({vault})")
    except Exception as exc:
        fail(f"Vault not writable: {vault} -- {exc}")
        all_ok = False

    # 3. Ollama reachability
    print("\n[3] Ollama server")
    base = cfg.ollama.base_url.rstrip("/")
    health_url = base.replace("/v1", "") + "/api/tags"
    try:
        with urllib.request.urlopen(health_url, timeout=5) as r:
            tags_data = json.loads(r.read())
        available_models = {m["name"] for m in tags_data.get("models", [])}
        ok(f"Ollama reachable  ({health_url})")
    except Exception as exc:
        fail(f"Ollama not reachable at {health_url}: {exc}")
        all_ok = False
        available_models = set()

    # 4. Primary model
    print("\n[4] LLM model")
    model = cfg.ollama.model
    if available_models:
        matched = any(t.startswith(model.split(":")[0]) for t in available_models)
        if matched:
            ok(f"model available  ({model})")
        else:
            fail(
                f"model '{model}' not found.  "
                f"Run: ollama pull {model}\n"
                f"     Available: {', '.join(sorted(available_models)[:6])}"
            )
            all_ok = False
    else:
        warn("Skipped model check (Ollama not reachable).")

    # 5. Vision model (LLaVA)
    print("\n[5] Vision model (LLaVA)")
    vmodel = cfg.ollama.vision_model
    if available_models:
        matched = any(t.startswith(vmodel.split(":")[0]) for t in available_models)
        if matched:
            ok(f"vision model available  ({vmodel})")
        else:
            warn(
                f"vision model '{vmodel}' not pulled -- image capture will fail.\n"
                f"       Run: ollama pull {vmodel}"
            )
    else:
        warn("Skipped vision model check (Ollama not reachable).")

    # 6. Whisper
    print("\n[6] Whisper (audio transcription)")
    try:
        import whisper  # type: ignore
        ok(f"openai-whisper importable  (model config: {cfg.whisper.model})")
    except ImportError:
        warn(
            "openai-whisper not installed -- audio capture will fail.\n"
            "       Run: pip install openai-whisper"
        )
    if shutil.which("ffmpeg"):
        ok("ffmpeg on PATH")
    else:
        fail(
            "ffmpeg not found -- GUI voice recordings (webm/opus) cannot be decoded.\n"
            "       Install: winget install Gyan.FFmpeg"
        )
        all_ok = False

    # 7. SQLite index dir
    print("\n[7] SQLite FTS index")
    try:
        idx_dir = vault / ".omni_capture"
        idx_dir.mkdir(parents=True, exist_ok=True)
        probe2 = idx_dir / ".write_probe"
        probe2.write_text("ok")
        probe2.unlink()
        ok(f"index directory writable  ({idx_dir})")
    except Exception as exc:
        fail(f"Index directory not writable: {exc}")
        all_ok = False

    # 8. Index health (last captures.db / vectors.db write outcome)
    print("\n[8] Index health")
    try:
        import index_health
        snap = index_health.snapshot()
        if index_health.degraded():
            # Non-fatal by design (see CLAUDE.md "Files are the source of
            # truth" hard rule) -- a degraded index never blocked a capture,
            # so it's surfaced as a WARN, not a FAIL, and doesn't flip all_ok.
            for name, state in snap.items():
                if not state.get("ok", True):
                    warn(
                        f"{name} index write failing: {state.get('error')} "
                        f"(last attempt: {state.get('timestamp')})"
                    )
        else:
            ok("all index writes healthy (or none attempted yet this process)")
    except Exception as exc:
        warn(f"Could not read index health: {exc}")

    print("\n" + "-" * 55)
    if all_ok:
        print(f"{GREEN}All checks passed.{RESET}  Second Thought is ready.\n")
    else:
        print(f"{RED}Some checks failed.{RESET}  See above for details.\n")

    return all_ok


# -- CLI entry-point -----------------------------------------------------------
if __name__ == "__main__":
    args = _parse_args()

    # Self-check mode
    if args.self_check:
        passed = run_self_check(config_path=args.config)
        sys.exit(0 if passed else 1)

    # Log viewer mode
    if args.log:
        if args.config:
            from config import reload_config
            reload_config(Path(args.config))
        from capture_log import print_recent, print_stats
        if args.stats:
            print_stats()
        else:
            print_recent(args.n)
        sys.exit(0)

    # Pipeline mode
    try:
        run_pipeline(
            text=args.text,
            url=args.url,
            audio=args.audio,
            vault_root=args.vault,
            model=args.model,
            ollama_url=args.ollama_url,
            config_path=args.config,
            dry_run=args.dry_run,
            verbose=args.verbose,
            notify=not args.no_notify,
        )
    except KeyboardInterrupt:
        print("\n[Second Thought] Interrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        try:
            from interceptor import ClipboardEmpty, ClipboardError
        except ImportError:
            ClipboardEmpty = ClipboardError = None  # type: ignore[assignment,misc]

        if ClipboardEmpty and isinstance(exc, ClipboardEmpty):
            print(f"[Second Thought] {exc}", file=sys.stderr)
            sys.exit(0)

        if ClipboardError and isinstance(exc, ClipboardError):
            print(f"[Second Thought] Clipboard error: {exc}", file=sys.stderr)
            sys.exit(1)

        from config import get_config
        from notifier import notify_capture_error
        try:
            cfg = get_config()
            if cfg.notifications.enabled:
                notify_capture_error(str(exc), cfg.notifications.title_prefix)
        except Exception:
            pass

        print(f"[Second Thought] Unexpected error: {exc}", file=sys.stderr)
        raise

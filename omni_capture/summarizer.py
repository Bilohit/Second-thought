"""
summarizer.py
--------------
Token counting, chunking, and Map-Reduce summarization orchestration for
long-form content (currently: YouTube transcripts).

Token counting prefers Ollama's native `/api/tokenize` endpoint (exact, pure
CPU tokenization, no GPU prefill) and falls back to a conservative
ceil(len/3) character estimate when that endpoint is missing or unreachable.
No extra dependencies (no tiktoken/transformers).

Chunking is count-driven and word/segment-granular -- count_tokens never
returns a token array we could slice, so all splitting happens at text
granularity, sized by repeated counting (propose-then-verify).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from typing import Callable, List, Optional

# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

# Remembers whether /api/tokenize works for a given base_url, so we stop
# probing after the first failure for the rest of the process.
_tokenize_available: dict[str, bool] = {}
# Cache of computed counts, keyed on a hash of (base_url, model, text).
# ponytail: unbounded; cap to N entries if a server runs for days summarizing many large transcripts.
_count_cache: dict[str, int] = {}


def _tokenize_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base + "/api/tokenize"


def _try_tokenize(text: str, base_url: str, model: str) -> Optional[int]:
    url = _tokenize_endpoint(base_url)
    body = json.dumps({"model": model, "content": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    timeout = float(os.getenv("OMNI_TOKENIZE_TIMEOUT", "2"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        tokens = data.get("tokens")
        return len(tokens) if isinstance(tokens, list) else None
    except Exception:
        return None


def _char_estimate(text: str) -> int:
    # Deliberately over-counts vs the usual ~4 chars/token so chunks can only
    # come out smaller than the real budget, never overflow it.
    return math.ceil(len(text) / 3) if text else 0


def count_tokens(text: str, *, base_url: str, model: str) -> int:
    """
    Return the token count of `text` for `model` served at `base_url`.

    Prefers the native Ollama `/api/tokenize` endpoint (exact, cheap, no GPU
    prefill). Falls back to a conservative char-based estimate when that
    endpoint is absent (older Ollama build) or unreachable, logging once at
    WARNING and not re-probing for the rest of the process.
    """
    cache_key = hashlib.sha256(
        f"{base_url}|{model}|{text}".encode("utf-8", errors="replace")
    ).hexdigest()
    cached = _count_cache.get(cache_key)
    if cached is not None:
        return cached

    if _tokenize_available.get(base_url, True):
        result = _try_tokenize(text, base_url, model)
        if result is not None:
            _tokenize_available[base_url] = True
            _count_cache[cache_key] = result
            return result
        if base_url not in _tokenize_available:
            print(
                f"[Summarizer] {_tokenize_endpoint(base_url)} not available -- "
                "using the conservative char-based token estimate instead "
                "(expected on Ollama builds without /api/tokenize; harmless, "
                "this only makes chunks a bit smaller than necessary).",
                flush=True,
            )
        _tokenize_available[base_url] = False

    estimate = _char_estimate(text)
    _count_cache[cache_key] = estimate
    return estimate


# ---------------------------------------------------------------------------
# Chunking -- token-bounded, word/segment-granular, propose-then-verify
# ---------------------------------------------------------------------------

def _word_split_oversized(text: str, count: Callable[[str], int], max_tokens: int) -> List[str]:
    """Split a single segment whose own count exceeds max_tokens, growing a
    whitespace-delimited word window until it approaches the budget."""
    words = text.split()
    if not words:
        return []
    out: List[str] = []
    window: List[str] = []
    for word in words:
        window.append(word)
        if count(" ".join(window)) > max_tokens:
            window.pop()
            if window:
                out.append(" ".join(window))
            window = [word]
    if window:
        out.append(" ".join(window))
    return out


def _trailing_overlap(text: str, count: Callable[[str], int], overlap_tokens: int) -> str:
    """Return the trailing whole-word slice of `text` whose count is ~overlap_tokens."""
    if overlap_tokens <= 0:
        return ""
    words = text.split()
    if not words:
        return ""
    for take in range(1, len(words) + 1):
        candidate = " ".join(words[-take:])
        if count(candidate) >= overlap_tokens:
            return candidate
    return " ".join(words)


def _coalesce_to_limit(chunks: List[str], max_chunks: int) -> List[str]:
    """Merge adjacent chunks pairwise until the count fits within max_chunks."""
    while len(chunks) > max_chunks:
        merged: List[str] = []
        i = 0
        while i < len(chunks):
            if i + 1 < len(chunks):
                merged.append(chunks[i] + "\n\n" + chunks[i + 1])
                i += 2
            else:
                merged.append(chunks[i])
                i += 1
        chunks = merged
    return chunks


def chunk_transcript(
    segments: List[dict],
    *,
    count: Callable[[str], int],
    max_tokens: int,
    overlap_tokens: int = 80,
    max_chunks: int = 40,
) -> List[str]:
    """
    Split transcript segments into token-bounded chunks.

    `count` is a pre-bound counter (typically count_tokens partially applied
    with base_url/model). Splitting happens at word/segment granularity --
    never by slicing a token array, since the counter is count-only.

    Propose-then-verify: a cheap local char estimate decides when a candidate
    chunk is *near* the budget before paying for a real `count()` call, so
    real counts stay roughly proportional to the number of chunks rather than
    the number of segments.
    """
    if not segments:
        return []

    chunks: List[str] = []
    current_parts: List[str] = []
    pending_overlap = ""

    def close_current() -> None:
        nonlocal current_parts, pending_overlap
        if current_parts:
            chunks.append(" ".join(current_parts))
            pending_overlap = _trailing_overlap(chunks[-1], count, overlap_tokens)
        current_parts = []

    for seg in segments:
        text = seg["text"]
        if not text:
            continue

        # Oversized single segment: word-split it on its own, bypassing the
        # normal accumulate-and-verify path entirely.
        if _char_estimate(text) > max_tokens and count(text) > max_tokens:
            close_current()
            pieces = _word_split_oversized(text, count, max_tokens)
            chunks.extend(pieces)
            if chunks:
                pending_overlap = _trailing_overlap(chunks[-1], count, overlap_tokens)
            continue

        if current_parts:
            candidate_parts = current_parts + [text]
        elif pending_overlap:
            candidate_parts = [pending_overlap, text]
        else:
            candidate_parts = [text]
        candidate = " ".join(candidate_parts)

        if _char_estimate(candidate) < max_tokens * 0.9:
            # Comfortably under budget by the cheap estimate -- skip the
            # real count call.
            current_parts = candidate_parts
            continue

        if count(candidate) <= max_tokens:
            current_parts = candidate_parts
            continue

        # Doesn't fit: close what we have (without this segment), then start
        # a fresh chunk seeded with overlap + this segment.
        close_current()
        new_parts = [pending_overlap, text] if pending_overlap else [text]
        if pending_overlap and count(" ".join(new_parts)) > max_tokens:
            new_parts = [text]
        current_parts = new_parts

    close_current()

    if len(chunks) > max_chunks:
        print(
            f"[Summarizer] {len(chunks)} chunks exceeds summary_max_chunks={max_chunks}; "
            "coalescing adjacent chunks to bound LLM call volume.",
            flush=True,
        )
        chunks = _coalesce_to_limit(chunks, max_chunks)

    return chunks


# ---------------------------------------------------------------------------
# Map phase -- parallel summarization of chunks, bounded concurrency
# ---------------------------------------------------------------------------

async def _map_phase(
    chunks: List[str],
    *,
    client,
    model: str,
    temperature: float,
    max_retries: int,
    timeout: Optional[float],
    max_concurrency: int,
    on_progress: Optional[Callable[[int, int], None]] = None,
    base_url: str = "",
) -> List[str]:
    """
    Summarize each chunk concurrently (bounded by a semaphore), preserving
    chunk order in the returned list regardless of completion order. A
    per-chunk failure becomes a visible placeholder instead of failing the
    whole phase.
    """
    from llm_engine import summarize_async, CHUNK_SUMMARY_PROMPT

    total = len(chunks)
    sem = asyncio.Semaphore(max(1, max_concurrency))
    done = 0

    async def run_one(index: int, text: str) -> str:
        nonlocal done
        async with sem:
            try:
                result = await summarize_async(
                    text,
                    instruction=CHUNK_SUMMARY_PROMPT,
                    base_url=base_url,
                    model=model,
                    temperature=temperature,
                    max_retries=max_retries,
                    timeout=timeout,
                    client=client,
                )
            except Exception as exc:
                print(f"[Summarizer] chunk {index + 1}/{total} summarization failed: {exc}", flush=True)
                result = f"> [!warning] Section {index + 1} summary unavailable (model error)."
        done += 1
        if on_progress:
            on_progress(done, total)
        return result

    tasks = [run_one(i, text) for i, text in enumerate(chunks)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: List[str] = []
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            out.append(f"> [!warning] Section {i + 1} summary unavailable (model error).")
        else:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Reduce phase -- recursive synthesis of partial summaries
# ---------------------------------------------------------------------------

async def reduce_summaries(
    partials: List[str],
    *,
    count: Callable[[str], int],
    client,
    model: str,
    temperature: float,
    max_retries: int,
    timeout: Optional[float],
    max_chunk_tokens: int,
    overlap_tokens: int,
    max_chunks: int,
    max_concurrency: int,
    reduce_max_depth: int = 3,
    depth: int = 0,
    on_progress: Optional[Callable[[int, int], None]] = None,
    base_url: str = "",
) -> str:
    """
    Combine partial (Map-phase) summaries into one cohesive summary.

    If the concatenation itself exceeds the token budget, recursively
    re-chunk and re-Map it, bounded by reduce_max_depth. If the depth cap is
    hit and it still doesn't fit, the concatenation is returned verbatim --
    work is never thrown away.
    """
    from llm_engine import summarize_async, COMBINE_PROMPT

    concatenated = "\n\n".join(f"## Section {i + 1}\n{p}" for i, p in enumerate(partials))

    if count(concatenated) > max_chunk_tokens:
        if depth >= reduce_max_depth:
            print(
                f"[Summarizer] reduce_max_depth={reduce_max_depth} reached and partials still "
                "exceed the budget; emitting concatenated partials verbatim.",
                flush=True,
            )
            return concatenated

        fake_segments = [{"text": p} for p in partials]
        sub_chunks = chunk_transcript(
            fake_segments, count=count, max_tokens=max_chunk_tokens,
            overlap_tokens=overlap_tokens, max_chunks=max_chunks,
        )
        sub_partials = await _map_phase(
            sub_chunks, client=client, model=model, temperature=temperature,
            max_retries=max_retries, timeout=timeout, max_concurrency=max_concurrency,
            on_progress=on_progress, base_url=base_url,
        )
        return await reduce_summaries(
            sub_partials, count=count, client=client, model=model, temperature=temperature,
            max_retries=max_retries, timeout=timeout, max_chunk_tokens=max_chunk_tokens,
            overlap_tokens=overlap_tokens, max_chunks=max_chunks, max_concurrency=max_concurrency,
            reduce_max_depth=reduce_max_depth, depth=depth + 1, on_progress=on_progress,
            base_url=base_url,
        )

    try:
        return await summarize_async(
            concatenated, instruction=COMBINE_PROMPT, base_url=base_url, model=model,
            temperature=temperature, max_retries=max_retries, timeout=timeout, client=client,
        )
    except Exception as exc:
        print(f"[Summarizer] final synthesis failed ({exc}); falling back to concatenated partials.", flush=True)
        return concatenated


# ---------------------------------------------------------------------------
# Smoke tests  (python summarizer.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Deterministic fake counter: word count. Lets us assert exact behaviour
    # without a live Ollama server.
    call_count = {"n": 0}

    def fake_count(s: str) -> int:
        call_count["n"] += 1
        return len(s.split())

    # T1: no chunk's counted size exceeds max_tokens
    call_count["n"] = 0
    segs = [{"text": " ".join(f"word{i}{j}" for j in range(10))} for i in range(30)]
    chunks = chunk_transcript(segs, count=fake_count, max_tokens=50, overlap_tokens=10, max_chunks=100)
    assert all(fake_count(c) <= 50 for c in chunks), "every chunk must fit max_tokens"
    print(f"[T1] no chunk exceeds max_tokens ({len(chunks)} chunks)  PASS")

    # T2: consecutive chunks share overlap text
    assert len(chunks) >= 2
    shared = False
    for a, b in zip(chunks, chunks[1:]):
        a_words, b_words = a.split(), b.split()
        if any(w in b_words[:15] for w in a_words[-15:]):
            shared = True
            break
    assert shared, "consecutive chunks should share overlap text"
    print("[T2] consecutive chunks share overlap text  PASS")

    # T3: oversized single segment is word-split
    huge_seg = [{"text": " ".join(f"tok{i}" for i in range(200))}]
    huge_chunks = chunk_transcript(huge_seg, count=fake_count, max_tokens=30, overlap_tokens=5, max_chunks=100)
    assert len(huge_chunks) > 1
    assert all(fake_count(c) <= 30 for c in huge_chunks)
    print(f"[T3] oversized single segment word-split into {len(huge_chunks)} pieces  PASS")

    # T4: max_chunks clamp holds
    many_segs = [{"text": f"segment number {i} with some words here"} for i in range(200)]
    clamped = chunk_transcript(many_segs, count=fake_count, max_tokens=15, overlap_tokens=3, max_chunks=10)
    assert len(clamped) <= 10
    print(f"[T4] max_chunks clamp holds ({len(clamped)} <= 10)  PASS")

    # T5: propose step keeps real-count calls roughly proportional to chunk count,
    # not segment count (most segments accepted via the cheap estimate alone).
    call_count["n"] = 0
    big_segs = [{"text": f"x{i}"} for i in range(500)]
    big_chunks = chunk_transcript(big_segs, count=fake_count, max_tokens=2000, overlap_tokens=20, max_chunks=100)
    # The fake counter only fires near a chunk boundary or in overlap/word-split
    # paths -- bounded by a small multiple of the chunk count, not 500.
    assert call_count["n"] < len(big_segs), (
        f"expected real-count calls ({call_count['n']}) << segment count ({len(big_segs)})"
    )
    print(f"[T5] real-count calls ({call_count['n']}) << segment count ({len(big_segs)})  PASS")

    # T6: _try_tokenize uses a short, env-configurable timeout (regression test
    # for the 10s probe stall -- see OMNI_TOKENIZE_TIMEOUT).
    import unittest.mock as mock

    seen_timeout = {}

    def _fake_urlopen(req, timeout=None):
        seen_timeout["value"] = timeout
        raise urllib.error.URLError("no /api/tokenize on this server")

    with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        result = _try_tokenize("hello world", "http://localhost:11434", "llama3.2")
        assert result is None, "unreachable endpoint must fall back to None"
        assert seen_timeout["value"] == 2.0, f"expected default timeout 2.0, got {seen_timeout['value']}"

        os.environ["OMNI_TOKENIZE_TIMEOUT"] = "5"
        try:
            _try_tokenize("hello world", "http://localhost:11434", "llama3.2")
            assert seen_timeout["value"] == 5.0, f"expected configured timeout 5.0, got {seen_timeout['value']}"
        finally:
            del os.environ["OMNI_TOKENIZE_TIMEOUT"]
    print("[T6] _try_tokenize uses short, env-configurable timeout  PASS")

    print("\nAll summarizer.py smoke tests passed.")

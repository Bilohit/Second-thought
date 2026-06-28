"""
rag_engine.py — strict local RAG for the Look panel's Chat mode.

Hybrid retrieval (semantic cosine + FTS5 lexical, fused with Reciprocal Rank
Fusion) over the existing derived indexes, plus vault/talk system prompts.
Kept separate from the capture pipeline (main.py/server.py) by design.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from vector_store import _embed, _connect, _MAX_SNIPPET_CHARS, _cosine_all  # reuse Ollama embed + DB
from index_writer import search as fts_search
from look_log import look_debug, look_warn
from frontmatter import strip_frontmatter

REFUSAL = "Information not found in vault"
_RRF_K = 60
_CITE_SNIPPET_CHARS = 1500

DEFAULT_CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant for the Second Thought vault app. "
    "Answer clearly and concisely. When you do not have vault-specific context, "
    "use your general knowledge. Do not invent facts about the user's personal notes."
)

TALK_PREFIX = "/talk"


def parse_chat_mode(question: str) -> tuple[str, str]:
    """Return (question, mode). Default vault (strict RAG); /talk = general knowledge."""
    q = (question or "").strip()
    if not q.lower().startswith(TALK_PREFIX):
        return q, "vault"
    rest = q[len(TALK_PREFIX):].lstrip()
    return rest, "talk"


# Topic-question prefixes whose boilerplate is stripped before retrieval.
_TOPIC_PREFIXES = (
    "what do you know about ",
    "tell me about ",
    "summarize ",
    "what is ",
    "what are ",
    "describe ",
    "explain ",
)


class Source(TypedDict):
    n: int
    path: str
    category: str
    filename: str
    snippet: str


def _semantic_ranked(vault_root: Path, query: str, base_url: str, embed_model: str,
                     limit: int) -> tuple[list[str], float, dict[str, float]]:
    """Return ([vault_relative_path,...] best-first, best_similarity, path->sim)."""
    try:
        with _connect(vault_root) as conn:
            rows = conn.execute(
                "SELECT id, embedding, document, category FROM embeddings").fetchall()
        if not rows:
            return [], 0.0, {}
        q = _embed(query, base_url, embed_model)
        results = _cosine_all(q, rows)
        if not results:
            return [], 0.0, {}
        best = results[0][0]
        paths = [rel for _s, rel, _doc in results[:limit]]
        sim_by_abs = {str(vault_root / rel): sim for sim, rel, _doc in results}
        return paths, best, sim_by_abs
    except Exception as exc:
        look_warn(f"semantic retrieval failed: {exc}")
        return [], 0.0, {}


def _read_snippet(p: Path, query: str = "") -> str:
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    text = " ".join(strip_frontmatter(text).split())
    if not text:
        return ""
    q = (query or "").strip()
    if q:
        for tok in q.split():
            if len(tok) < 3:
                continue
            idx = text.lower().find(tok.lower())
            if idx >= 0:
                half = _CITE_SNIPPET_CHARS // 2
                start = max(0, idx - half)
                end = min(len(text), start + _CITE_SNIPPET_CHARS)
                start = max(0, end - _CITE_SNIPPET_CHARS)
                return text[start:end]
    return text[:_CITE_SNIPPET_CHARS]


def _expand_query(question: str, history: list[dict] | None) -> str:
    """Strip topic-question boilerplate; optionally append last user turn."""
    q = question.strip().lower()
    remainder = question.strip()
    for prefix in _TOPIC_PREFIXES:
        if q.startswith(prefix):
            remainder = question.strip()[len(prefix):].strip()
            break
    if history:
        last_user = next(
            (m["content"] for m in reversed(history) if m.get("role") == "user"), None
        )
        if last_user and last_user.strip() != question.strip():
            remainder = f"{remainder} {last_user.strip()}"
    return remainder or question.strip()


def hybrid_retrieve(
    vault_root: Path,
    question: str,
    base_url: str,
    embed_model: str,
    top_k: int = 8,
    min_similarity_floor: float = 0.32,
    history: list[dict] | None = None,
    **_ignored: object,
) -> tuple[list[Source], float, str]:
    """
    Return (sources, confidence, tier).
    tier: "high" when sources found, else "none".
    Sources below min_similarity_floor are dropped — FTS-only noise never injected.
    """
    question = (question or "").strip()
    if not question:
        return [], 0.0, "none"

    retrieval_query = _expand_query(question, history)
    sem_paths, best_sim, sim_by_abs = _semantic_ranked(
        vault_root, retrieval_query, base_url, embed_model, top_k * 2,
    )
    fts_rows = fts_search(retrieval_query, vault_root, limit=top_k * 2)
    fts_paths = [r["path"] for r in fts_rows]

    # Reciprocal Rank Fusion — semantic paths only contribute when above floor.
    rrf: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for rank, rel in enumerate(sem_paths):
        ap = str(vault_root / rel)
        if sim_by_abs.get(ap, 0.0) < min_similarity_floor:
            continue
        rrf[ap] = rrf.get(ap, 0.0) + 1.0 / (_RRF_K + rank)
    for rank, ap in enumerate(fts_paths):
        rrf[ap] = rrf.get(ap, 0.0) + 1.0 / (_RRF_K + rank)
    for r in fts_rows:
        meta[r["path"]] = {"category": r.get("category", ""), "filename": r.get("filename") or ""}

    if not rrf:
        return [], best_sim, "none"

    ranked = sorted(rrf, key=lambda p: rrf[p], reverse=True)[:top_k]
    sources: list[Source] = []
    for ap in ranked:
        p = Path(ap)
        if not p.exists():
            look_debug(f"skip missing file: {ap}")
            continue
        m = meta.get(ap, {})
        sources.append(Source(
            n=len(sources) + 1,
            path=ap,
            category=m.get("category") or p.parent.name,
            filename=m.get("filename") or p.name,
            snippet=_read_snippet(p, retrieval_query),
        ))

    if not sources:
        return [], best_sim, "none"

    confidence = best_sim

    look_debug(
        f"hybrid_retrieve q={question!r} expand={retrieval_query!r} "
        f"sem={len(sem_paths)} fts={len(fts_rows)} sources={len(sources)} "
        f"best_sim={best_sim:.3f} floor={min_similarity_floor} tier=high"
    )
    return sources, confidence, "high"


def build_system_prompt(
    sources: list[Source],
    mode: str,
    custom_prompt: str | None = None,
) -> str:
    """Build the system message. mode='talk' → general knowledge; vault → CONTEXT-only RAG."""
    base = (custom_prompt or "").strip() or DEFAULT_CHAT_SYSTEM_PROMPT
    if mode == "talk" or not sources:
        return base

    numbered = "\n\n".join(
        f"[{s['n']}] ({s['category']}/{s['filename']})\n{s['snippet']}" for s in sources
    )
    rules = (
        "Rules:\n"
        "1. Use only facts stated in the CONTEXT. Do not use outside knowledge.\n"
        "2. Synthesize everything in CONTEXT that answers the user's question; "
        "broad questions warrant a broad summary from the notes.\n"
        "3. After every sentence that uses a source, cite it inline as [n]. Cite multiple as [1][3].\n"
        "4. Do not apologize, speculate, or describe what the vault might contain.\n"
        "5. Be concise. Prefer the user's own wording from the notes."
    )
    return (
        f"{base}\n\n"
        "You are answering from the user's vault. Answer ONLY from the CONTEXT below.\n"
        "The CONTEXT is a list of numbered sources from the user's personal notes.\n\n"
        f"{rules}\n\n"
        f"CONTEXT:\n{numbered}"
    )


if __name__ == "__main__":
    assert DEFAULT_CHAT_SYSTEM_PROMPT in build_system_prompt([], "talk")
    vault_prompt = build_system_prompt(
        [{"n": 1, "path": "/v/a.md", "category": "T", "filename": "a.md", "snippet": "dinosaur facts"}],
        "vault",
    )
    assert "[1] (T/a.md)" in vault_prompt
    assert "dinosaur facts" in vault_prompt
    assert REFUSAL not in vault_prompt
    assert parse_chat_mode("/talk what is rust") == ("what is rust", "talk")
    assert parse_chat_mode("/TALK  notes") == ("notes", "talk")
    assert parse_chat_mode("what is rust") == ("what is rust", "vault")
    assert parse_chat_mode("/talk") == ("", "talk")
    print("rag_engine smoke: OK")

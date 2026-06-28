"""
rag_engine.py — strict local RAG for the Look panel's Chat mode.

Hybrid retrieval (semantic cosine + FTS5 lexical, fused with Reciprocal Rank
Fusion) over the existing derived indexes, plus a tier-aware system prompt.
Kept separate from the capture pipeline (main.py/server.py) by design.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

import numpy as np

from vector_store import _embed, _connect, _MAX_SNIPPET_CHARS  # reuse Ollama embed + DB
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

STRICT_PREFIX = "/strict"


def parse_strict_prefix(question: str) -> tuple[str, bool]:
    """Return (question without /strict prefix, strict_flag). Prefix is case-insensitive."""
    q = (question or "").strip()
    if not q.lower().startswith(STRICT_PREFIX):
        return q, False
    rest = q[len(STRICT_PREFIX):].lstrip()
    return rest, True


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
        qv = np.asarray(q, dtype=np.float32)
        qn = np.linalg.norm(qv) or 1.0
        qv = qv / qn
        scored: list[tuple[float, str]] = []
        sim_by_rel: dict[str, float] = {}
        for rel, blob, _doc, _cat in rows:
            emb = np.frombuffer(blob, dtype=np.float32)
            n = np.linalg.norm(emb)
            if n == 0:
                continue
            sim = float(np.dot(qv, emb / n))
            sim_by_rel[rel] = sim
            scored.append((sim, rel))
        scored.sort(key=lambda t: t[0], reverse=True)
        best = scored[0][0] if scored else 0.0
        paths = [rel for _s, rel in scored[:limit]]
        sim_by_abs = {str(vault_root / rel): sim for rel, sim in sim_by_rel.items()}
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


def _classify_tier(confidence: float, has_sources: bool,
                   min_similarity_high: float, min_similarity_medium: float) -> str:
    if not has_sources:
        return "none"
    if confidence >= min_similarity_high:
        return "high"
    if confidence >= min_similarity_medium:
        return "medium"
    return "low"


def hybrid_retrieve(
    vault_root: Path,
    question: str,
    base_url: str,
    embed_model: str,
    top_k: int = 8,
    min_similarity_high: float = 0.45,
    min_similarity_medium: float = 0.35,
    min_similarity_floor: float = 0.32,
    history: list[dict] | None = None,
) -> tuple[list[Source], float, str]:
    """
    Return (sources, confidence, tier).
    tier: "high" | "medium" | "low" | "none"
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
    if any(ap in fts_paths for ap in ranked):
        confidence = max(confidence, min_similarity_medium)
    tier = _classify_tier(confidence, True, min_similarity_high, min_similarity_medium)

    look_debug(
        f"hybrid_retrieve q={question!r} expand={retrieval_query!r} "
        f"sem={len(sem_paths)} fts={len(fts_rows)} sources={len(sources)} "
        f"best_sim={best_sim:.3f} floor={min_similarity_floor} tier={tier}"
    )
    return sources, confidence, tier


def build_system_prompt(
    sources: list[Source],
    tier: str,
    custom_prompt: str | None = None,
) -> str:
    """Build the system message. tier='general' → no vault context injected."""
    base = (custom_prompt or "").strip() or DEFAULT_CHAT_SYSTEM_PROMPT
    if tier == "general" or not sources:
        return base

    numbered = "\n\n".join(
        f"[{s['n']}] ({s['category']}/{s['filename']})\n{s['snippet']}" for s in sources
    )
    if tier == "high":
        rules = (
            "Rules:\n"
            "1. Use only facts stated in the CONTEXT. Do not use outside knowledge.\n"
            "2. After every sentence that uses a source, cite it inline as [n]. Cite multiple as [1][3].\n"
            "3. If the CONTEXT does not contain enough information, reply EXACTLY: " + REFUSAL + "\n"
            "4. Do not apologize, speculate, or describe what the vault might contain.\n"
            "5. Be concise. Prefer the user's own wording from the notes."
        )
    else:
        rules = (
            "Rules:\n"
            "1. Use only facts and content stated in the CONTEXT — the user's personal vault notes.\n"
            "2. Synthesize everything relevant about the topic from all provided sources.\n"
            "3. After every sentence that uses a source, cite it inline as [n]. Cite multiple as [1][3].\n"
            "4. If coverage is partial, briefly note what is and isn't covered — do not invent gaps.\n"
            "5. Do not use outside knowledge. Do not apologize or speculate beyond the notes.\n"
            "6. Be thorough but concise."
        )
    return (
        f"{base}\n\n"
        "You are answering from the user's vault. Answer ONLY from the CONTEXT below.\n"
        "The CONTEXT is a list of numbered sources from the user's personal notes.\n\n"
        f"{rules}\n\n"
        f"CONTEXT:\n{numbered}"
    )


if __name__ == "__main__":
    cases = [
        (0.5, True,  0.45, 0.35, "high"),
        (0.4, True,  0.45, 0.35, "medium"),
        (0.33, True, 0.45, 0.35, "low"),
        (0.1, False, 0.45, 0.35, "none"),
    ]
    for sim, has_sources, hi, med, expected in cases:
        t = _classify_tier(sim, has_sources, hi, med)
        assert t == expected, f"{sim=} {has_sources=} → {t!r} != {expected!r}"
    assert DEFAULT_CHAT_SYSTEM_PROMPT in build_system_prompt([], "general")
    assert REFUSAL in build_system_prompt(
        [{"n": 1, "path": "/v/a.md", "category": "T", "filename": "a.md", "snippet": "x"}],
        "high",
    )
    assert parse_strict_prefix("/strict what is rust") == ("what is rust", True)
    assert parse_strict_prefix("/STRICT  notes") == ("notes", True)
    assert parse_strict_prefix("what is rust") == ("what is rust", False)
    assert parse_strict_prefix("/strict") == ("", True)
    print("rag_engine smoke: OK")

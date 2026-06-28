"""
rag_engine.py — strict local RAG for the Look panel's Chat mode.

Hybrid retrieval (semantic cosine + FTS5 lexical, fused with Reciprocal Rank
Fusion) over the existing derived indexes, plus a zero-hallucination system
prompt. Kept separate from the capture pipeline (main.py/server.py) by design.
"""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import numpy as np

from vector_store import _embed, _connect, _MAX_SNIPPET_CHARS  # reuse Ollama embed + DB
from index_writer import search as fts_search

REFUSAL = "Information not found in vault"
_RRF_K = 60
_CITE_SNIPPET_CHARS = 1500


class Source(TypedDict):
    n: int
    path: str
    category: str
    filename: str
    snippet: str


def _semantic_ranked(vault_root: Path, query: str, base_url: str, embed_model: str,
                     limit: int) -> tuple[list[str], float]:
    """Return ([vault_relative_path,...] best-first, best_similarity)."""
    try:
        with _connect(vault_root) as conn:
            rows = conn.execute(
                "SELECT id, embedding, document, category FROM embeddings").fetchall()
        if not rows:
            return [], 0.0
        q = _embed(query, base_url, embed_model)
        qv = np.asarray(q, dtype=np.float32)
        qn = np.linalg.norm(qv) or 1.0
        qv = qv / qn
        scored: list[tuple[float, str]] = []
        for rel, blob, _doc, _cat in rows:
            emb = np.frombuffer(blob, dtype=np.float32)
            n = np.linalg.norm(emb)
            if n == 0:
                continue
            scored.append((float(np.dot(qv, emb / n)), rel))
        scored.sort(key=lambda t: t[0], reverse=True)
        best = scored[0][0] if scored else 0.0
        return [rel for _s, rel in scored[:limit]], best
    except Exception:
        return [], 0.0


def _read_snippet(p: Path) -> str:
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return " ".join(text.split())[:_CITE_SNIPPET_CHARS]


def hybrid_retrieve(vault_root: Path, query: str, base_url: str, embed_model: str,
                    top_k: int = 5, min_similarity: float = 0.4) -> tuple[list[Source], bool]:
    query = (query or "").strip()
    if not query:
        return [], False

    sem_paths, best_sim = _semantic_ranked(vault_root, query, base_url, embed_model, top_k * 2)
    fts_rows = fts_search(query, vault_root, limit=top_k * 2)
    fts_paths = [r["path"] for r in fts_rows]

    # Reciprocal Rank Fusion — no score normalization needed across the two lists.
    rrf: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for rank, rel in enumerate(sem_paths):
        ap = str((vault_root / rel))
        rrf[ap] = rrf.get(ap, 0.0) + 1.0 / (_RRF_K + rank)
    for rank, ap in enumerate(fts_paths):
        rrf[ap] = rrf.get(ap, 0.0) + 1.0 / (_RRF_K + rank)
    for r in fts_rows:
        meta[r["path"]] = {"category": r.get("category", ""), "filename": r.get("filename") or ""}

    if not rrf:
        return [], False

    ranked = sorted(rrf, key=lambda p: rrf[p], reverse=True)[:top_k]
    sources: list[Source] = []
    for i, ap in enumerate(ranked, start=1):
        p = Path(ap)
        m = meta.get(ap, {})
        sources.append(Source(
            n=i, path=ap,
            category=m.get("category") or p.parent.name,
            filename=m.get("filename") or p.name,
            snippet=_read_snippet(p),
        ))

    answerable = bool(sources) and best_sim >= min_similarity
    return sources, answerable


def build_system_prompt(sources: list[Source]) -> str:
    numbered = "\n\n".join(
        f"[{s['n']}] ({s['category']}/{s['filename']})\n{s['snippet']}" for s in sources
    )
    return (
        "You are the vault's retrieval assistant. Answer ONLY from the CONTEXT below.\n"
        "The CONTEXT is a list of numbered sources from the user's personal notes.\n\n"
        "Rules:\n"
        "1. Use only facts stated in the CONTEXT. Do not use outside knowledge.\n"
        "2. After every sentence that uses a source, cite it inline as [n] with the\n"
        "   source's number. Cite multiple as [1][3].\n"
        "3. If the CONTEXT does not contain enough information to answer, reply with\n"
        f"   EXACTLY this and nothing else: {REFUSAL}\n"
        "4. Do not apologize, speculate, or describe what the vault might contain.\n"
        "5. Be concise. Prefer the user's own wording from the notes.\n\n"
        f"CONTEXT:\n{numbered}"
    )

"""
vector_store.py
---------------
Local semantic memory for Second Thought.

Stores note embeddings in a SQLite database (.omni_capture/vectors.db)
and retrieves top-k semantically similar notes using cosine similarity
computed with numpy — no external vector-DB framework required.

Embeddings are produced by nomic-embed-text via the Ollama /api/embeddings
endpoint, keeping everything fully local.

Public API
----------
index_note(vault_root, note_path, content, base_url, embed_model)
    Upsert one note's embedding. Silently skips on any failure.

retrieve_related(vault_root, query_text, base_url, embed_model, top_k) -> list[str]
    Return up to top_k formatted excerpt strings. Returns [] on any failure.

semantic_search(vault_root, query_text, base_url, embed_model, top_k) -> list[dict]
    F-10: structured {path, similarity, excerpt, category} rows for the Look
    "Semantic" results band. Same ranking as retrieve_related. [] on failure.

_embed(text, base_url, model) -> list[float]
    Call Ollama. Exposed for mocking in tests.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

import index_health

# Indian Standard Time (UTC+05:30). Prefer the tz database via zoneinfo so the
# offset stays correct if the rules ever change; fall back to a fixed offset
# (IST has no DST) when tzdata is unavailable.
try:
    from zoneinfo import ZoneInfo
    _IST = ZoneInfo("Asia/Kolkata")
except Exception:
    _IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _ist_now() -> str:
    """Current time formatted in IST for log timestamps."""
    return datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S %Z")

_EMBED_TIMEOUT_S     = 30
_MAX_EMBED_CHARS     = 4_000
_MAX_SNIPPET_CHARS   = 500
_DEFAULT_EMBED_MODEL = "nomic-embed-text"
_DB_NAME             = "vectors.db"
# ponytail: char-based chunk boundary (~1k tokens); switch to summarizer token
# chunking if retrieval quality demands.
_CHUNK_CHARS         = 4_000


def _preview(text: str, n: int = 80) -> str:
    """Single-line truncated preview for diagnostic logs."""
    one_line = " ".join((text or "").split())
    return (one_line[:n] + "…") if len(one_line) > n else one_line


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS embeddings (
    id          TEXT PRIMARY KEY,
    embedding   BLOB NOT NULL,
    document    TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    provisional INTEGER NOT NULL DEFAULT 0
);
"""


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_path(vault_root: Path) -> Path:
    db_dir = vault_root / ".omni_capture"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / _DB_NAME


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Migration-safe: add `provisional` to embeddings tables created before
    the LAN overlay existed (contract §11). Additive column, default 0."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(embeddings)").fetchall()}
    if "provisional" not in cols:
        conn.execute("ALTER TABLE embeddings ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def _get_conn(vault_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(vault_root)))
    # WAL is a persistent on-disk setting (re-issuing is a no-op) so readers
    # and the writer don't block each other; busy_timeout is per-connection
    # and must be set on every open so a lock contention window is waited
    # out instead of raising "database is locked".
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(_CREATE_TABLE)
        conn.commit()
        _migrate_schema(conn)
    except Exception:
        # A corrupt db raises "file is not a database" on the first PRAGMA/CREATE.
        # sqlite3.connect() already opened an OS handle; if we let the exception
        # propagate without closing it the handle leaks, and on Windows that lock
        # makes heal_corrupt_db's unlink fail (WinError 32) — so a store that was
        # read even once could never be healed until process exit. Close, re-raise.
        conn.close()
        raise
    return conn


@contextmanager
def _connect(vault_root: Path) -> Iterator[sqlite3.Connection]:
    # `with conn:` on a bare sqlite3.Connection only manages the transaction
    # (commit/rollback) -- it never closes the connection, so each call here
    # leaked a handle on vectors.db. On Windows that left the file locked,
    # so tests that index a note into a tempdir-backed vault then tear the
    # tempdir down failed with PermissionError. Always close explicitly.
    conn = _get_conn(vault_root)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Ollama embedding ──────────────────────────────────────────────────────────

class OllamaConnectionError(RuntimeError):
    """Raised when Ollama could not be reached at all (connection refused/
    timed out/DNS failure), as opposed to a reachable-but-erroring Ollama
    (404, bad model, malformed response -> plain RuntimeError). Callers use
    this to distinguish "the engine is offline" from "the engine answered
    but found nothing" -- see rag_engine.hybrid_retrieve."""


def _post_json(url: str, payload: dict) -> dict:
    """POST a JSON body and return the decoded JSON response.

    Raises urllib.error.HTTPError on a non-2xx status (so the caller can
    distinguish a 404 from a connection failure) and RuntimeError otherwise.
    """
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_EMBED_TIMEOUT_S) as resp:
        return json.loads(resp.read())


def _embed(text: str, base_url: str,
           model: str = _DEFAULT_EMBED_MODEL) -> list[float]:
    """
    Embed `text` via Ollama and return a float vector.

    Ollama's embedding endpoint has changed across versions:
      * Newer builds expose POST /api/embed   with {"model","input"}  -> {"embeddings": [[...]]}
      * Older builds expose POST /api/embeddings with {"model","prompt"} -> {"embedding": [...]}

    The original code only called /api/embed, which 404s on older daemons
    (the "[VectorStore] ... HTTP Error 404" the user is seeing).  We now try
    /api/embed first and transparently fall back to /api/embeddings on a 404,
    so embeddings work regardless of the installed Ollama version.

    Raises RuntimeError when Ollama is unreachable on both endpoints or the
    response shape is unrecognised.
    """
    import urllib.error

    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    snippet = text[:_MAX_EMBED_CHARS]

    # Blank/whitespace input tokenizes to nothing -> Ollama returns
    # {"embeddings": []}. Reject it here (caller bug / degraded placeholder)
    # before spending a network round-trip, with a diagnostic.
    if not snippet.strip():
        raise RuntimeError(
            f"refusing to embed blank input (len={len(text)}, preview={_preview(text)!r})"
        )

    new_url = f"{base}/api/embed"
    old_url = f"{base}/api/embeddings"

    # 1. Try the modern batch endpoint.
    new_was_404 = False
    try:
        data = _post_json(new_url, {"model": model, "input": snippet})
        embeddings = data.get("embeddings")
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            return embeddings[0]
        embedding = data.get("embedding")
        if isinstance(embedding, list) and embedding:
            return embedding
        raise RuntimeError(
            f"Ollama returned empty/unknown embedding shape from {new_url} "
            f"(input len={len(snippet)}, preview={_preview(snippet)!r}). "
            f"If embeddings==[], the model '{model}' may not be resident "
            f"(GPU thrash after a vision call) or the input was non-tokenizable. "
            f"Raw: {data!r}"
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(
                f"Ollama embedding call failed ({new_url}): {exc}"
            ) from exc
        # A 404 here is ambiguous: either this Ollama build lacks /api/embed
        # (old daemon -> retry the legacy endpoint) or the model isn't pulled.
        # We disambiguate after the legacy call also 404s.
        new_was_404 = True
    except RuntimeError:
        raise
    except urllib.error.URLError as exc:
        # A true connection failure (refused/timed out/DNS) rather than an
        # HTTP error response -- Ollama isn't reachable at all.
        raise OllamaConnectionError(
            f"Cannot reach Ollama at {new_url}: {exc.reason}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Ollama embedding call failed ({new_url}): {exc}") from exc

    # 2. Legacy endpoint fallback (Ollama builds without /api/embed).
    try:
        data = _post_json(old_url, {"model": model, "prompt": snippet})
    except urllib.error.HTTPError as exc:
        if new_was_404 and exc.code == 404:
            # Both endpoints 404 => the endpoints exist but Ollama can't find
            # the model. This is the common "model not pulled" case; give the
            # user an actionable message instead of a raw HTTP 404.
            raise RuntimeError(
                f"Embedding model '{model}' not found in Ollama. "
                f"Pull it with `ollama pull {model}`, or set a different "
                f"[vector].embed_model in config.toml (an installed embedding "
                f"model, e.g. all-minilm). Disable semantic features with "
                f"[vector].enabled = false."
            ) from exc
        raise RuntimeError(
            f"Ollama embedding call failed on both {new_url} and {old_url}: {exc}"
        ) from exc
    except urllib.error.URLError as exc:
        raise OllamaConnectionError(
            f"Cannot reach Ollama at {old_url}: {exc.reason}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Ollama embedding call failed on both {new_url} and {old_url}: {exc}"
        ) from exc

    embedding = data.get("embedding")
    if isinstance(embedding, list) and embedding:
        return embedding
    embeddings = data.get("embeddings")
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return embeddings[0]

    raise RuntimeError(f"Ollama returned unexpected shape from {old_url}: {data!r}")


# ── numpy cosine similarity ───────────────────────────────────────────────────

def _cosine_all(
    query_vec: list[float],
    rows: list[tuple],  # (id, embedding_blob, document, category)
) -> list[tuple[float, str, str]]:
    """Batch cosine similarity. Return [(sim, doc_id, document), ...] sorted desc."""
    if not rows:
        return []
    q = np.array(query_vec, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    q = q / q_norm

    ids   = [r[0] for r in rows]
    docs  = [r[2] for r in rows]
    mat   = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    norms = np.linalg.norm(mat, axis=1)
    mask  = norms != 0
    sims  = np.where(mask, mat @ q / np.where(mask, norms, 1.0), 0.0)
    order = np.argsort(sims)[::-1]
    return [(float(sims[i]), ids[i], docs[i]) for i in order if mask[i]]


def _cosine_top_k(
    query_vec: list[float],
    rows: list[tuple],
    top_k: int,
) -> list[tuple[float, str, str]]:
    """Return top-k [(similarity, doc_id, document), ...] sorted desc."""
    return _cosine_all(query_vec, rows)[:top_k]


def _dedupe_to_parent(
    ranked: list[tuple[float, str, str]],
    top_k: int,
) -> list[tuple[float, str, str]]:
    """
    Collapse chunk rows (id `f"{parent}::c{i}"`) to their parent note, keeping
    only the best-scoring chunk per parent, then truncate to top_k.

    `ranked` must already be sorted descending by similarity (as returned by
    _cosine_all/_cosine_top_k), so the first occurrence of each parent is its
    best-scoring row.
    """
    seen: set[str] = set()
    out: list[tuple[float, str, str]] = []
    for sim, doc_id, doc in ranked:
        parent = doc_id.split("::c")[0]
        if parent in seen:
            continue
        seen.add(parent)
        out.append((sim, parent, doc))
        if len(out) >= top_k:
            break
    return out


# ── Public API ────────────────────────────────────────────────────────────────

def index_note(
    vault_root: Path,
    note_path: Path,
    content: str,
    base_url: str,
    embed_model: str = _DEFAULT_EMBED_MODEL,
    provisional: bool = False,
) -> None:
    """
    Embed content and upsert it into the SQLite vector store.
    Keyed by vault-relative path so re-indexing is idempotent.
    Failures are swallowed so they never abort a capture.

    provisional: tag the row as a LAN-overlay embedding (contract §11) --
    # ponytail: provisional rows indexed for search/RAG only; never authoritative
    -- files remain source of truth. Excluded from best_match() (merge.py's
    semantic-merge authority); still visible to retrieve_related() (RAG display,
    where the LAN overlay is meant to surface). No current pipeline calls this
    with provisional=True yet -- exposed for the future embedder wiring.
    """
    try:
        if not (content or "").strip():
            print(f"[VectorStore] skip index: blank content (len={len(content or '')})",
                  file=sys.stderr, flush=True)
            return
        try:
            rel = str(note_path.relative_to(vault_root)).replace("\\", "/")
        except ValueError:
            rel = str(note_path).replace("\\", "/")

        category = note_path.parent.name

        with _connect(vault_root) as conn:
            # Clear any stale rows (single-row or prior chunk rows) before
            # re-inserting, so re-indexing is idempotent regardless of
            # whether the chunk count changed between runs.
            conn.execute(
                "DELETE FROM embeddings WHERE id = ? OR id LIKE ?",
                (rel, rel + "::c%"),
            )

            prov = 1 if provisional else 0
            if len(content) <= _CHUNK_CHARS:
                embedding = _embed(content, base_url, embed_model)
                vec_bytes = np.array(embedding, dtype=np.float32).tobytes()
                snippet = content[:_MAX_SNIPPET_CHARS]
                conn.execute(
                    "INSERT OR REPLACE INTO embeddings "
                    "(id, embedding, document, category, provisional) VALUES (?,?,?,?,?)",
                    (rel, vec_bytes, snippet, category, prov),
                )
            else:
                slices = [
                    content[i:i + _CHUNK_CHARS]
                    for i in range(0, len(content), _CHUNK_CHARS)
                ]
                for i, slice_ in enumerate(slices):
                    embedding = _embed(slice_, base_url, embed_model)
                    vec_bytes = np.array(embedding, dtype=np.float32).tobytes()
                    snippet = slice_[:_MAX_SNIPPET_CHARS]
                    conn.execute(
                        "INSERT OR REPLACE INTO embeddings "
                        "(id, embedding, document, category, provisional) VALUES (?,?,?,?,?)",
                        (f"{rel}::c{i}", vec_bytes, snippet, category, prov),
                    )
        print(f"[VectorStore] indexed: {rel}", flush=True)
        index_health.record_ok("vectors")

    except Exception as exc:
        print(f"[{_ist_now()}] [VectorStore] non-fatal index error: {exc}",
              file=sys.stderr, flush=True)
        index_health.record_failure("vectors", exc)


def remove_from_index(vault_root: Path, note_path: Path) -> None:
    """Delete a note's embedding row by vault-relative path. Fails silently."""
    try:
        try:
            rel = str(note_path.relative_to(vault_root)).replace("\\", "/")
        except ValueError:
            rel = str(note_path).replace("\\", "/")
        with _connect(vault_root) as conn:
            conn.execute(
                "DELETE FROM embeddings WHERE id = ? OR id LIKE ?",
                (rel, rel + "::c%"),
            )
        print(f"[VectorStore] removed: {rel}", flush=True)
        index_health.record_ok("vectors")
    except Exception as exc:
        print(f"[{_ist_now()}] [VectorStore] remove_from_index error: {exc}",
              file=sys.stderr, flush=True)
        index_health.record_failure("vectors", exc)


def retrieve_related(
    vault_root: Path,
    query_text: str,
    base_url: str,
    embed_model: str = _DEFAULT_EMBED_MODEL,
    top_k: int = 3,
    min_similarity: float = 0.0,
) -> list[str]:
    """
    Return up to top_k excerpt strings from semantically related notes.

    Each string is formatted as:
        ### Related note: <vault-relative-path>  (similarity 0.XX)
        <first 500 chars of note content>

    Candidates below min_similarity are dropped entirely (defense-in-depth:
    an off-topic or low-signal query -- e.g. a degraded-vision placeholder --
    should inject zero context rather than the nearest noise). Returns []
    when the store is empty, nothing clears the floor, or any error occurs.

    Intentionally does NOT exclude provisional=1 rows: this is RAG/context
    display, exactly where the LAN overlay (contract §11) is meant to surface.
    Only merge/dedup/link authority paths (best_match, above) must exclude it.
    """
    try:
        if not (query_text or "").strip():
            print(f"[VectorStore] skip retrieve: blank query (len={len(query_text or '')})",
                  file=sys.stderr, flush=True)
            return []
        with _connect(vault_root) as conn:
            rows = conn.execute(
                "SELECT id, embedding, document, category FROM embeddings"
            ).fetchall()

        if not rows:
            return []

        embedding = _embed(query_text, base_url, embed_model)
        # ponytail: 3x overfetch heuristic so k parents survive dedupe
        candidates = _cosine_top_k(embedding, rows, top_k * 3)
        ranked     = _dedupe_to_parent(candidates, top_k)

        return [
            f"### Related note: {doc_id}  (similarity {sim:.2f})\n{doc}"
            for sim, doc_id, doc in ranked
            if sim >= min_similarity
        ]

    except Exception as exc:
        print(f"[{_ist_now()}] [VectorStore] non-fatal retrieve error: {exc}",
              file=sys.stderr, flush=True)
        return []


def semantic_search(
    vault_root: Path,
    query_text: str,
    base_url: str,
    embed_model: str = _DEFAULT_EMBED_MODEL,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> list[dict]:
    """F-10: structured counterpart to retrieve_related() for the Look
    "Semantic" results band -- same ranking (_cosine_top_k + _dedupe_to_parent
    over the same `embeddings` table) but returns machine-shaped rows
    (path/similarity/excerpt/category) instead of a pre-formatted prompt
    string, so the GUI can render + dedupe them against FTS hits by path.

    Returns [] on an empty store, a blank query, or any error -- same
    fail-soft contract as retrieve_related/best_match.
    """
    try:
        if not (query_text or "").strip():
            return []
        with _connect(vault_root) as conn:
            rows = conn.execute(
                "SELECT id, embedding, document, category FROM embeddings"
            ).fetchall()
        if not rows:
            return []

        embedding = _embed(query_text, base_url, embed_model)
        candidates = _cosine_top_k(embedding, rows, top_k * 3)
        ranked = _dedupe_to_parent(candidates, top_k)
        cat_by_id = {r[0].split("::c")[0]: r[3] for r in rows}

        return [
            {
                "path": doc_id,
                "similarity": round(sim, 4),
                "excerpt": doc[:280],
                "category": cat_by_id.get(doc_id),
            }
            for sim, doc_id, doc in ranked
            if sim >= min_similarity
        ]
    except Exception as exc:
        print(f"[{_ist_now()}] [VectorStore] non-fatal semantic_search error: {exc}",
              file=sys.stderr, flush=True)
        return []


def best_match(
    vault_root: Path,
    query_text: str,
    base_url: str,
    embed_model: str = _DEFAULT_EMBED_MODEL,
    category: Optional[str] = None,
) -> Optional[tuple[str, float]]:
    """
    Return (vault_relative_path, cosine_similarity) of the single most
    semantically similar indexed note, optionally restricted to one category.

    Returns None when the store is empty, embeddings are unavailable, or any
    error occurs -- callers must treat None as "no semantic signal" and fall
    back to deterministic logic.

    This is the merge/dedup authority path: merge.py's find_merge_target calls
    best_match to decide whether a new capture should be silently appended into
    an existing note. provisional=1 rows (LAN overlay, contract §11) are
    excluded -- a not-yet-Drive-confirmed body must never win a merge decision.
    # ponytail: provisional rows indexed for search/RAG only; never authoritative
    -- files remain source of truth.
    """
    try:
        if not (query_text or "").strip():
            print(f"[VectorStore] skip best_match: blank query (len={len(query_text or '')})",
                  file=sys.stderr, flush=True)
            return None
        with _connect(vault_root) as conn:
            if category:
                rows = conn.execute(
                    "SELECT id, embedding, document, category FROM embeddings "
                    "WHERE category = ? AND provisional = 0",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, embedding, document, category FROM embeddings WHERE provisional = 0"
                ).fetchall()

        if not rows:
            return None

        embedding = _embed(query_text, base_url, embed_model)
        # ponytail: 3x overfetch heuristic so k parents survive dedupe
        candidates = _cosine_top_k(embedding, rows, top_k=3)
        ranked = _dedupe_to_parent(candidates, top_k=1)
        if not ranked:
            return None
        sim, doc_id, _doc = ranked[0]
        return (doc_id, sim)

    except Exception as exc:
        print(f"[{_ist_now()}] [VectorStore] non-fatal best_match error: {exc}",
              file=sys.stderr, flush=True)
        return None


def count(vault_root: Path) -> int:
    """Return the number of indexed notes (0 if DB does not exist yet)."""
    try:
        with _connect(vault_root) as conn:
            return conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    except Exception:
        return 0


def heal_corrupt_db(vault_root: Path) -> bool:
    """Discard vectors.db if it is unreadable, so the caller can re-create it.

    Mirror of index_writer.heal_corrupt_db for the embedding store: vectors.db is a
    derived cache — every row re-embeds from the vault .md files — so discarding an
    unreadable one is the sanctioned recovery, not data loss. Without this a
    truncated/half-flushed/bad-sector vectors.db raised sqlite3.DatabaseError on the
    first read inside index_note (swallowed) and inside every search (fail-soft to
    []), so semantic search was silently dead and never repaired (OF-1). Detection
    must run BEFORE anything else opens the store.

    Returns True if a corrupt db was discarded. OperationalError (SQLITE_BUSY/LOCKED,
    a permissions fault) is caught FIRST and never heals — a healthy-but-unavailable
    store must not be deleted; the same exact split as index_writer's captures heal.
    """
    db_path = _db_path(vault_root)
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            # Touches the schema pages — connect() alone does not read the file.
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
        return False
    except sqlite3.OperationalError as exc:
        print(f"[VectorStore] vectors.db unavailable ({exc}) — leaving it intact; "
              "this is not corruption", file=sys.stderr, flush=True)
        index_health.record_failure("vectors", exc)
        return False
    except sqlite3.DatabaseError as exc:
        print(f"[VectorStore] vectors.db unreadable ({exc}) — discarding the corrupt "
              "derived cache; it rebuilds from the vault files", file=sys.stderr, flush=True)
        try:
            db_path.unlink()
            # A stale -wal/-shm can resurrect the pages we just destroyed.
            for extra in db_path.parent.glob(db_path.name + "-*"):
                extra.unlink()
        except OSError as unlink_exc:   # locked by another process — stay fail-soft
            print(f"[VectorStore] could not discard corrupt vectors.db: {unlink_exc}",
                  file=sys.stderr, flush=True)
            index_health.record_failure("vectors", exc)
            return False
        return True


def embedded_parents(vault_root: Path) -> set[str]:
    """Vault-relative parent paths that have at least one authoritative embedding row.

    The re-embed decision in vault_sync consults THIS (the vector store's own
    contents), never captures.hash (OF-1): so a destroyed/emptied vectors.db with an
    intact captures.db is re-embedded instead of skipped forever. Chunk rows are
    keyed "<parent>::c<i>"; provisional=1 (LAN overlay, contract §11) rows use
    synthetic paths that never match a real vault file and are excluded. Returns an
    empty set on any read failure (empty/absent store), which routes every note to a
    re-embed — the safe direction."""
    try:
        with _connect(vault_root) as conn:
            ids = conn.execute("SELECT id FROM embeddings WHERE provisional = 0").fetchall()
        return {r[0].split("::c")[0] for r in ids}
    except Exception:
        return set()


# ── Smoke tests ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import unittest.mock as mock, tempfile, pathlib, math

    def _fake_embed(text: str, base_url: str,
                    model: str = _DEFAULT_EMBED_MODEL) -> list[float]:
        import hashlib
        words = text.lower().split()
        vec = [0.0] * 8
        for word in words:
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            for i in range(8):
                vec[i] += ((h >> (i * 4)) & 0xF) / 15.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    with tempfile.TemporaryDirectory() as tmp:
        vault = pathlib.Path(tmp)
        (vault / "Tech_Notes").mkdir()

        with mock.patch.object(sys.modules[__name__], "_embed", side_effect=_fake_embed):

            # T1: index two notes
            n1 = vault / "Tech_Notes" / "asyncio.md"
            n1.write_text("Async IO patterns in Python asyncio.")
            index_note(vault, n1, n1.read_text(), "http://localhost:11434")

            n2 = vault / "Tech_Notes" / "fastapi.md"
            n2.write_text("Building async HTTP APIs with FastAPI and Python.")
            index_note(vault, n2, n2.read_text(), "http://localhost:11434")

            assert count(vault) == 2, f"Expected 2, got {count(vault)}"
            print("[T1] Two notes indexed  PASS")

            # T2: retrieve returns non-empty
            snippets = retrieve_related(vault, "async python", "http://localhost:11434")
            assert len(snippets) > 0, "Expected >= 1 snippet"
            assert "Related note:" in snippets[0]
            print(f"[T2] retrieve_related returned {len(snippets)} snippet(s)  PASS")

            # T3: empty vault returns []
            with tempfile.TemporaryDirectory() as tmp2:
                result = retrieve_related(pathlib.Path(tmp2), "anything",
                                          "http://localhost:11434")
                assert result == []
                print("[T3] Empty vault returns []  PASS")

            # T4: upsert is idempotent
            index_note(vault, n1, "Updated content.", "http://localhost:11434")
            assert count(vault) == 2, f"Expected 2 after upsert, got {count(vault)}"
            print("[T4] Upsert idempotent  PASS")

            # T5: top_k respected
            for i in range(3):
                ni = vault / "Tech_Notes" / f"note-{i}.md"
                ni.write_text(f"python async note {i}")
                index_note(vault, ni, ni.read_text(), "http://localhost:11434")

            snippets2 = retrieve_related(vault, "async python",
                                         "http://localhost:11434", top_k=2)
            assert len(snippets2) <= 2, f"top_k not respected: {len(snippets2)}"
            print("[T5] top_k respected  PASS")

    print("\nAll vector_store.py smoke tests passed.")

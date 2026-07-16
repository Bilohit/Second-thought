"""
vault_admin.py - vault-administration endpoints extracted from server.py:
category CRUD, full-text search, and capture statistics.

Split out of server.py (docs/ROADMAP.md: "Split server.py into jobs.py +
vault_admin.py"). Mounted into server.app by server.py via
`app.include_router(vault_admin.router, dependencies=[Depends(_require_secret)])`
so X-Omni-Secret auth is enforced identically to every other route without
this module needing to import `_require_secret` itself.

Every route resolves the vault root via `_srv()._get_vault_root()` (looked up
on the already-loaded server module at call time, never imported by value)
so that tests which monkeypatch `server._get_vault_root` (test_index_and_search.py,
test_server.py) keep pointing these moved routes at a temp vault exactly as
they did before the split.
"""
from __future__ import annotations
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

import anyio
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

router = APIRouter()


def _srv():
    """Resolve the already-loaded server module whether it was imported as
    'server' (tests) or 'omni_capture.server' (packaged uvicorn launch).
    A bare top-level `import server` creates a SECOND module identity under
    packaged launch and re-triggers server.py's import -> circular crash."""
    return sys.modules.get("omni_capture.server") or sys.modules["server"]


# -- Pydantic models -----------------------------------------------------------

class CategoryCreate(BaseModel):
    name: str

class CategoryRename(BaseModel):
    new_name: str

class CategoryDescriptionPatch(BaseModel):
    description: Optional[str] = None  # None = clear description; str = set/update (max 500 chars)


# -- Vault-path safety helpers --------------------------------------------------
# Also used by server.py's /inbox/{note_id}/approve (target_category validation)
# via `vault_admin._safe_category_dir` -- kept here since category-directory
# safety is fundamentally a vault-CRUD concern.

def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-. ]", "_", name).strip()


def _safe_category_dir(root: Path, name: str) -> Path:
    """
    Resolve a category directory and guarantee it stays directly inside the
    vault root. Rejects path-traversal, path separators, and any name
    that would escape or nest below the vault.

    Raises HTTPException(400) on any invalid / unsafe name.
    """
    cleaned = _safe_name(name)
    cleaned = re.sub(r"[. ]+$", "", cleaned)  # Windows silently strips trailing dots/spaces
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


# -- Vault management endpoints -----------------------------------------------

@router.get("/vault/categories")
async def list_categories():
    root = _srv()._get_vault_root()
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

@router.post("/vault/categories")
async def create_category(body: CategoryCreate):
    from config import get_config
    root = _srv()._get_vault_root()
    new_dir = _safe_category_dir(root, body.name)
    name = new_dir.name
    if new_dir.exists():
        raise HTTPException(status_code=409, detail=f"'{name}' already exists.")
    new_dir.mkdir(parents=True, exist_ok=False)

    description = None
    if get_config().capture.auto_describe_new_folders:
        from storage_engine import generate_category_description, write_category_description
        # generate_category_description() ends in a blocking asyncio.run(), which
        # raises if called from a thread that already has a running event loop
        # (true here -- this is an async route). Run it on a worker thread instead.
        generated = await anyio.to_thread.run_sync(generate_category_description, name)
        if generated:
            description = write_category_description(new_dir, generated)

    return {"ok": True, "name": name, "path": str(new_dir), "description": description}

@router.patch("/vault/categories/{name}")
async def rename_category(name: str, body: CategoryRename):
    root = _srv()._get_vault_root()
    src = _safe_category_dir(root, name)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")
    dst = _safe_category_dir(root, body.new_name)
    new_name = dst.name
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"'{new_name}' already exists.")
    src.rename(dst)
    return {"ok": True, "old_name": name, "new_name": new_name}

@router.patch("/vault/categories/{name}/description")
async def update_category_description(name: str, body: CategoryDescriptionPatch):
    """
    Set or clear the LLM routing description for a category folder.

    The description is persisted in <vault>/<category>/.category.toml under
    the 'description' key.  This file is read by build_category_descriptions()
    and injected verbatim into the LLM system prompt on every capture so the
    model can route files more precisely.

    Pass description=null (JSON null) or an empty string to clear it.
    Maximum length: 500 characters.
    """
    from storage_engine import write_category_description
    root = _srv()._get_vault_root()
    target = _safe_category_dir(root, name)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")

    desc = write_category_description(target, body.description)
    return {"ok": True, "name": name, "description": desc}


@router.delete("/vault/categories/{name}")
async def delete_category(name: str, force: bool = False):
    root = _srv()._get_vault_root()
    target = _safe_category_dir(root, name)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")
    files = [f for f in target.iterdir() if f.is_file()]
    if files and not force:
        raise HTTPException(status_code=409,
            detail=f"'{name}' contains {len(files)} file(s). Pass force=true to delete anyway.")
    shutil.rmtree(target)
    return {"ok": True, "deleted": name}

@router.get("/vault/categories/{name}/files")
async def list_category_files(name: str):
    root = _srv()._get_vault_root()
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

_TAG_TOKEN_RE = re.compile(r"(?:^|\s)tag:(\S+)")


def _extract_tag_filter(q: str) -> tuple[str, Optional[str]]:
    """F-4: pull a leading/embedded `tag:xxx` token out of a free-text query
    string (Library's tags browser hands off exactly this shape). Returns
    (remaining_query, tag) -- remaining_query has the token stripped so it
    doesn't also get FTS-matched as literal text."""
    m = _TAG_TOKEN_RE.search(q)
    if not m:
        return q, None
    tag = m.group(1)
    remaining = (q[: m.start()] + q[m.end():]).strip()
    return remaining, tag


@router.get("/search")
async def search_captures(
    q: str = "",
    category: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 25,
    x_log_level: Optional[str] = Header(None, alias="X-Log-Level"),
):
    """Full-text search over captured notes via the SQLite FTS5 index.
    `q` may embed a `tag:<value>` token (F-4 tags browser hand-off) -- it is
    stripped from the free-text match and applied as an exact-tag filter."""
    from index_writer import search as idx_search
    from look_log import debug_logging_from_level, set_look_verbose, look_debug, look_info
    set_look_verbose(debug_logging_from_level(x_log_level))
    limit = min(max(1, limit), 200)
    free_q, tag = _extract_tag_filter(q)
    look_debug(f"GET /search q={q!r} category={category} since={since} limit={limit} tag={tag}")
    results = idx_search(free_q, _srv()._get_vault_root(), category=category, since=since, limit=limit, tag=tag)
    look_info(f"GET /search returned {len(results)} result(s) for q={q!r}")
    return {"results": results, "count": len(results), "query": q}


@router.get("/stats")
async def capture_stats():
    """Aggregated capture statistics backed by SQLite."""
    from index_writer import stats as idx_stats
    return idx_stats(_srv()._get_vault_root())


# -- F-10: semantic search band ------------------------------------------------

@router.get("/search/semantic")
async def search_semantic(q: str = "", limit: int = 5):
    """Top-k semantically related notes for the Look "Semantic" band beneath
    FTS results. Reuses the same embeddings store/ranking as retrieve_related
    (RAG context) -- just returns structured rows instead of a prompt string.
    Empty query or a disabled/empty vector store both resolve to []."""
    from config import get_config
    from vector_store import semantic_search
    cfg = get_config()
    if not q.strip() or not cfg.vector.enabled:
        return {"results": []}
    root = _srv()._get_vault_root()
    results = await anyio.to_thread.run_sync(
        lambda: semantic_search(
            root, q, cfg.ollama.base_url, cfg.vector.embed_model,
            top_k=min(max(1, limit), 25), min_similarity=cfg.vector.min_similarity,
        )
    )
    return {"results": results}


# -- F-4: Tags browser ----------------------------------------------------

def _build_tag_tree(index: dict[str, dict[str, str]]) -> list[dict]:
    """One level of `namespace/leaf` nesting (matches mock 05-desktop-tags.html:
    `project/` groups `project/alpha`, `project/beta`; a bare tag like `reading`
    has no children). *index* is tag_index.scan_tag_paths' `tag -> {path: label}`.

    Every count is a number of DISTINCT notes -- `len` of the tag's path set --
    and a namespace row unions its children rather than summing their counts, so
    a note tagged both `project/alpha` and `project/beta` counts once under
    `project/`. That is exactly the set `/search?q=tag:project/` lists, which is
    the whole point of both sides resolving through the same scan.

    ponytail: deeper nesting (`a/b/c`) still collapses into the first-segment
    namespace bucket for DISPLAY -- upgrade to a real N-level tree only if a
    vault's tag vocabulary actually grows that deep. Counts and listing agree
    either way: both resolve a namespace by prefix.
    """
    top: list[dict] = []
    ns_index: dict[str, int] = {}
    ns_paths: dict[str, set[str]] = {}
    for t in sorted(index):
        paths = index[t]
        recent = list(dict.fromkeys(paths.values()))[:2]
        if "/" in t:
            ns = t.split("/", 1)[0] + "/"
            if ns not in ns_index:
                ns_index[ns] = len(top)
                ns_paths[ns] = set()
                top.append({"tag": ns, "count": 0, "recent": [], "children": []})
            node = top[ns_index[ns]]
            node["children"].append({"tag": t, "count": len(paths), "recent": recent})
            ns_paths[ns].update(paths)
            node["count"] = len(ns_paths[ns])
        else:
            top.append({"tag": t, "count": len(paths), "recent": recent, "children": []})
    return top


@router.get("/tags")
async def list_tags():
    """Tag tree for Library's Tags view, read from the vault files -- the same
    scan `/search?q=tag:<x>` resolves through (tag_index.py), so a row's count
    always matches the number of notes its click lists.

    This used to union the captures.db `tags` column (captures) with a
    frontmatter scan (`origin: note` only), while the listing side saw the DB
    column alone -- the two halves disagreed by construction. tag_index reads
    both frontmatter shapes off disk instead, so captures need no DB half."""
    from tag_index import scan_tag_paths
    return {"tags": _build_tag_tree(scan_tag_paths(_srv()._get_vault_root()))}


# -- F-1: Conflict resolver (desktop) --------------------------------------

@router.get("/vault/conflicts")
async def list_vault_conflicts_endpoint():
    """Bulk conflict scan so VaultManager/Library can badge affected rows
    with ONE request instead of one /note/conflict round trip per file."""
    from conflict_resolver import list_vault_conflicts
    return {"conflicts": list_vault_conflicts(_srv()._get_vault_root())}


# -- F-2: Trash (desktop) ---------------------------------------------------

@router.get("/trash")
async def list_trash_endpoint():
    """List of notes currently sitting in `_trash/` for Library's Trash view."""
    from trash import list_trash
    return {"items": list_trash(_srv()._get_vault_root())}


class TrashRestore(BaseModel):
    filename: str


@router.post("/trash/restore")
async def restore_trash_endpoint(body: TrashRestore):
    """Move a trashed note back to its original category folder."""
    from trash import restore_from_trash
    root = _srv()._get_vault_root()
    try:
        return restore_from_trash(root, body.filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"'{body.filename}' not found in trash.")


# -- F-5: Per-note sync-ignore (desktop-local, no contract change) ----------

@router.get("/sync/ignore")
async def list_sync_ignore():
    """Vault-relative paths currently excluded from Drive sync (local-only)."""
    from sync_ignore import load_ignored
    return {"ignored": sorted(load_ignored(_srv()._get_vault_root()))}


class SyncIgnorePatch(BaseModel):
    path: str
    ignored: bool


@router.post("/sync/ignore")
async def set_sync_ignore(body: SyncIgnorePatch):
    from sync_ignore import set_ignored
    root = _srv()._get_vault_root()
    updated = set_ignored(root, body.path, body.ignored)
    return {"ok": True, "ignored": sorted(updated)}


if __name__ == "__main__":
    # Smoke check: _safe_category_dir accepts a plain name and rejects
    # traversal/separator attempts, independent of any FastAPI wiring.
    root = Path(".").resolve()
    ok = _safe_category_dir(root, "My Notes")
    assert ok.parent == root and ok.name == "My Notes"

    for bad in ("..", ".", "", "   "):
        try:
            _safe_category_dir(root, bad)
            raise AssertionError(f"expected rejection for {bad!r}")
        except HTTPException:
            pass

    # Path separators are sanitized into a literal single-segment name rather
    # than traversing -- the result must always land directly inside root.
    sanitized = _safe_category_dir(root, "../escape")
    assert sanitized.parent == root

    print("vault_admin.py smoke check OK")

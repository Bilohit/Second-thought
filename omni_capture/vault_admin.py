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

@router.get("/search")
async def search_captures(
    q: str = "",
    category: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 25,
    x_log_level: Optional[str] = Header(None, alias="X-Log-Level"),
):
    """Full-text search over captured notes via the SQLite FTS5 index."""
    from index_writer import search as idx_search
    from look_log import debug_logging_from_level, set_look_verbose, look_debug, look_info
    set_look_verbose(debug_logging_from_level(x_log_level))
    limit = min(max(1, limit), 200)
    look_debug(f"GET /search q={q!r} category={category} since={since} limit={limit}")
    results = idx_search(q, _srv()._get_vault_root(), category=category, since=since, limit=limit)
    look_info(f"GET /search returned {len(results)} result(s) for q={q!r}")
    return {"results": results, "count": len(results), "query": q}


@router.get("/stats")
async def capture_stats():
    """Aggregated capture statistics backed by SQLite."""
    from index_writer import stats as idx_stats
    return idx_stats(_srv()._get_vault_root())


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

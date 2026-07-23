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

import path_safety

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


class SetupFolder(BaseModel):
    name: str
    description: str


class VaultSetupRequest(BaseModel):
    root: str
    folders: list[SetupFolder] = []


# -- Vault-path safety helpers --------------------------------------------------
# Also used by server.py's /inbox/{note_id}/approve (target_category validation)
# via `vault_admin._safe_category_dir` -- kept here since category-directory
# safety is fundamentally a vault-CRUD concern.

_safe_name = path_safety.safe_name


def _safe_category_dir(root: Path, name: str) -> Path:
    """
    Resolve a category directory and guarantee it stays directly inside the
    vault root.

    The logic lives in `path_safety.safe_subdir` so that trash.py and
    mobile_sync_agent.py can reuse the same resolve-and-compare backstop
    without importing this server-adjacent module. This wrapper only maps
    its ValueError onto the HTTP 400 that route handlers expect.
    """
    try:
        return path_safety.safe_subdir(root, name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category name.")


# -- Vault management endpoints -----------------------------------------------

@router.get("/vault/categories")
async def list_categories():
    """ISS-014: dot-prefixed folders (`.omni_capture`, `.sync`) are internal
    pipeline/sync bookkeeping, never user categories -- they must never reach
    this list at all (no Rename/Delete affordance should exist for them).

    Deliberately NOT reusing storage_engine._SYSTEM_FOLDER_PREFIXES ("_", ".")
    wholesale: that constant also excludes the scratchpad folder by its "_"
    prefix, which is correct for discover_categories (the LLM must never pick
    scratchpad as a routing target) but wrong here -- VaultManager's Library
    view surfaces `_scratchpad` in this same list under a friendlier "Needs
    review" label, so it must keep coming through this endpoint. Only the
    dot-prefix half of that exclusion applies to a CRUD listing."""
    root = _srv()._get_vault_root()
    if not root.exists():
        return {"categories": [], "vault_root": str(root)}
    from storage_engine import read_category_config
    result = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            md_files = [f for f in entry.iterdir() if f.suffix == ".md"]
            cfg = read_category_config(entry)
            result.append({
                "name": entry.name,
                "file_count": len(md_files),
                # SRV-24: was `"path": str(entry)` -- an absolute filesystem path
                # nothing consumed (the GUI addresses categories by `name`) and that
                # merely restated `vault_root` + `name`. Vault-relative now.
                "rel_path": entry.name,
                "description": cfg.get("description", None),
            })
    return {"categories": result, "vault_root": str(root)}

def _set_vault_root_config(root: Path) -> None:
    """Persist `[vault] root` to config.toml -- mirrors PATCH /config's
    vault_root branch (server.py:patch_config's `_set`/atomic_write_text/
    reload_config sequence) so both entry points write the SAME way: tomlkit
    read+merge (preserves comments/ordering), one atomic write, then
    reload_config() so the new root is live for every subsequent request
    without a restart. Self-contained here (not calling into patch_config)
    because that function batches many unrelated config keys into a single
    write at the end of its own request -- reusing its local `doc` would risk
    two atomic writes racing over the same file within one request.

    Reads `_srv().CONFIG_PATH` / calls `_srv().reload_config()` (not a direct
    `from config import ...`) so a test that monkeypatches `server.CONFIG_PATH`
    / `server.reload_config` -- the same pattern test_server.py's
    `_client_config` already uses for PATCH /config -- governs this write too.
    """
    import tomlkit
    from atomic_io import atomic_write_text

    srv = _srv()
    config_path = srv.CONFIG_PATH
    if config_path.exists():
        doc = tomlkit.loads(config_path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()
    if "vault" not in doc:
        doc.add(tomlkit.comment("  [vault] added by GUI"))
        doc.add("vault", tomlkit.table())
    doc["vault"]["root"] = str(root)
    atomic_write_text(config_path, tomlkit.dumps(doc))
    srv.reload_config()


@router.get("/vault/setup/check")
async def check_vault_setup(root: str):
    """ISS-002/P-WIZARD: detect whether *root* is already an existing vault
    with user categories, BEFORE it is ever written to config -- so the
    first-run wizard can skip its folder-picker step (mock's "existing vault
    found" branch) for a path the user Browse'd to that's already set up.
    Read-only: never mutates config. *root* is whatever the Tauri folder
    dialog returned, not (yet) the configured vault root."""
    if not Path(root).is_absolute():
        raise HTTPException(status_code=400, detail="root must be an absolute path")
    p = Path(root).expanduser()
    if not p.exists():
        return {"exists": False, "has_categories": False, "categories": []}
    from storage_engine import discover_categories
    cats = discover_categories(p)
    return {"exists": True, "has_categories": len(cats) > 0, "categories": cats}


@router.post("/vault/setup")
async def setup_vault(body: VaultSetupRequest):
    """First-run vault-setup wizard (ISS-002/P-WIZARD). Sets the vault root
    (same write path as PATCH /config, see _set_vault_root_config above),
    eagerly runs init_vault() so the scratchpad + .omni_capture dirs exist
    before the very first capture, and creates every chosen starter folder
    WITH its .category.toml description written at creation time
    (write_category_description) -- a fresh vault must never ship a
    description-less folder; ISS-002's root cause was exactly that empty
    category_descriptions dict reaching the LLM. Vault categories are never
    hardcoded: this only SEEDS folders on disk, models.py's category enum is
    still built live from whatever folders actually exist at capture time."""
    if not Path(body.root).is_absolute():
        raise HTTPException(status_code=400, detail="root must be an absolute path")
    root = Path(body.root).expanduser()

    _set_vault_root_config(root)

    from storage_engine import init_vault, write_category_description
    init_vault(root)

    created = []
    for folder in body.folders:
        folder_dir = _safe_category_dir(root, folder.name)
        folder_dir.mkdir(parents=True, exist_ok=True)
        desc = write_category_description(folder_dir, folder.description)
        created.append({"name": folder_dir.name, "description": desc})

    return {"ok": True, "root": str(root), "folders": created}


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
    """Task 2.6: also carries `hub_name`/`name_clash` per note -- the SAME
    resolution mobile_sync_agent runs before a hub upload (_resolve_hub_names
    over every note in the folder, by title+created), so a row whose stored
    on-disk filename differs from its title can still be flagged as the
    clash LOSER before it ever reaches the hub. Authoritative server-side;
    the GUI only displays it (never recomputes the naming rule)."""
    from frontmatter import read_all_fields
    from mobile_sync_agent import _hub_filename, _resolve_hub_names

    root = _srv()._get_vault_root()
    target = _safe_category_dir(root, name)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")

    md_files = [f for f in sorted(target.iterdir()) if f.is_file() and f.suffix == ".md"]

    # _resolve_hub_names needs id/title/created/category for every note in the
    # folder (its clash grouping is per (category, name)) -- only notes that
    # have an id are sync-addressable, so id-less files (e.g. a stray capture)
    # sit out the resolution and are never flagged.
    notes = []
    fields_by_path: dict = {}
    unreadable: set = set()
    for f in md_files:
        try:
            fields = read_all_fields(f.read_text(encoding="utf-8", newline=""))
        except Exception as exc:
            # SRV-25: a note we could not read has UNKNOWN frontmatter, not empty
            # frontmatter. Falling through with `fields = {}` made it look id-less,
            # which the loop below then reported as a definitive `name_clash: False`
            # -- a note whose hub name may well collide, presented as safe. Remember
            # the failure so the response can say "unknown" instead of "no".
            print(f"[vault_admin] unreadable note {f.name}: {exc}", flush=True)
            fields = {}
            unreadable.add(f)
        fields_by_path[f] = fields
        note_id = fields.get("id")
        if note_id:
            notes.append({
                "id": note_id,
                "title": fields.get("title", ""),
                "created": fields.get("created", ""),
                "category": name,
            })
    resolved = _resolve_hub_names(notes)

    files = []
    for f in md_files:
        stat = f.stat()
        fields = fields_by_path[f]
        note_id = fields.get("id")
        if f in unreadable:
            # SRV-25: unknown, not clash-free. `None` is the third state -- clients
            # must render it as "unknown" (and `unreadable` says why), never fold it
            # into the `False` bucket alongside notes actually checked and cleared.
            hub_name = f.name
            name_clash = None
        elif note_id and note_id in resolved:
            hub_name = resolved[note_id]
            name_clash = hub_name != _hub_filename(fields.get("title", ""), fields.get("created", ""))
        else:
            hub_name = f.name
            name_clash = False
        # `path` is absolute by contract: the GUI opens the file with it, and the
        # caller already holds `vault_root` from /vault/categories. `rel_path` is the
        # vault-relative form for anything that only needs to identify the note.
        files.append({"name": f.stem, "filename": f.name, "path": str(f),
                      "rel_path": f"{name}/{f.name}",
                      "size_bytes": stat.st_size, "modified": stat.st_mtime,
                      "hub_name": hub_name, "name_clash": name_clash,
                      "unreadable": f in unreadable})
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


# SRV-24: /search used to return `dict(row)` straight off captures.db, so every
# internal column of the index cache went over the wire -- content hashes, body
# excerpts, the provisional flag, note ids, the model name, all of it, for every
# hit. The response is an explicit projection now: exactly the fields the client
# contract declares (gui/src/lib/api.ts SearchResult), nothing the cache happens
# to also store. Adding a column to captures.db no longer widens the API.
# P-DSEARCH: `tier` ("exact"|"substring"|"semantic") and `score` (0..1, higher
# == more relevant) are now part of that published shape -- see index_writer.search.
_SEARCH_ROW_FIELDS = ("id", "timestamp", "category", "path", "filename",
                      "source_url", "confidence", "tags", "tier", "score")


def _shape_search_row(row: dict) -> dict:
    """Project one captures.db row onto the published /search result shape."""
    return {k: row.get(k) for k in _SEARCH_ROW_FIELDS}


def _shape_semantic_row(row: dict) -> dict:
    """Project one vector_store.semantic_search row onto the SAME /search result
    shape as _shape_search_row, tagged tier="semantic" -- so FTS and semantic hits
    fuse into one scored, tier-labeled list (P-DSEARCH item 6) instead of the GUI
    fetching+merging two independent endpoints itself. Fields the vector store
    doesn't carry (id/timestamp/source_url/confidence/tags) are left None; the
    GUI already treats those as optional for this reason."""
    path = row.get("path") or ""
    filename = path.replace("\\", "/").rsplit("/", 1)[-1] or None
    return {
        "id": None,
        "timestamp": None,
        "category": row.get("category"),
        "path": path,
        "filename": filename,
        "source_url": None,
        "confidence": None,
        "tags": None,
        "tier": "semantic",
        "score": row.get("similarity"),
    }


@router.get("/search")
async def search_captures(
    q: str = "",
    category: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 25,
    x_log_level: Optional[str] = Header(None, alias="X-Log-Level"),
):
    """Unified, scored, tier-labeled search (P-DSEARCH, ISS-011/ISS-012):
    fuses the SQLite FTS5 index's "exact"/"substring" tiers (index_writer.search,
    bm25-ranked) with the embeddings store's "semantic" tier (cosine-ranked) into
    ONE result list, sorted by score descending. `q` may embed a `tag:<value>`
    token (F-4 tags browser hand-off) -- it is stripped from the free-text match
    and applied as an exact-tag filter (and the semantic tier, which has no
    concept of tags, is skipped for a tag-only query)."""
    from index_writer import search as idx_search
    from config import get_config
    from vector_store import semantic_search
    from look_log import debug_logging_from_level, set_look_verbose, look_debug, look_info
    set_look_verbose(debug_logging_from_level(x_log_level))
    limit = min(max(1, limit), 200)
    free_q, tag = _extract_tag_filter(q)
    look_debug(f"GET /search q={q!r} category={category} since={since} limit={limit} tag={tag}")
    root = _srv()._get_vault_root()
    rows = idx_search(free_q, root, category=category, since=since, limit=limit, tag=tag)
    results = [_shape_search_row(r) for r in rows]

    cfg = get_config()
    if free_q.strip() and cfg.vector.enabled:
        sem_rows = await anyio.to_thread.run_sync(
            lambda: semantic_search(
                root, free_q, cfg.ollama.base_url, cfg.vector.embed_model,
                top_k=min(max(1, limit), 25), min_similarity=cfg.vector.min_similarity,
            )
        )
        # Dedupe against the FTS hits by path -- semantic paths are vault-relative,
        # FTS paths are absolute, so compare by suffix (same convention LookPanel
        # used client-side before this fused into one server-side list).
        existing = {r["path"].replace("\\", "/") for r in results if r.get("path")}
        for sr in sem_rows:
            rel = (sr.get("path") or "").replace("\\", "/")
            if rel and any(p.endswith(rel) for p in existing):
                continue
            results.append(_shape_semantic_row(sr))

    results.sort(key=lambda r: r["score"] if r.get("score") is not None else -1.0, reverse=True)
    results = results[:limit]
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


class TrashMove(BaseModel):
    path: str  # vault-relative or absolute note path (as any /vault or /search endpoint returns)


@router.post("/trash")
async def move_to_trash_endpoint(body: TrashMove):
    """ISS-005 A: user-originated soft-delete — move a live note into `_trash/`.

    The desktop had no delete affordance at all (the Trash tab was unreachable); this is the
    endpoint the Library row/toolbar delete button (a separate package) calls. A soft MOVE only —
    body bytes untouched, frontmatter (incl. original category) preserved for restore. Symmetric
    with the phone's queued `delete` op (data-model §3). Restore uses the existing POST /trash/restore.
    """
    from note_editor import resolve_note_path
    from trash import move_to_trash
    root = _srv()._get_vault_root()
    try:
        note_path = resolve_note_path(root, body.path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid note path.")
    try:
        return move_to_trash(root, note_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"'{body.path}' not found.")


@router.get("/trash/delete-prompts")
async def list_delete_prompts_endpoint():
    """ISS-005 C (basic entry point): the cross-device DELETE-PROMPTs the desktop is holding —
    notes a peer deleted that this device still holds locally, awaiting a keep-here / delete-both
    decision. Read-only; the reconcile pass records them non-destructively (delete_detect.py). The
    interactive resolve UI is a separate surface (P-VAULTUI)."""
    from delete_detect import load_delete_prompts
    root = _srv()._get_vault_root()
    state_path = str(root / ".omni_capture" / "mobile_sync_state.json")
    prompts = load_delete_prompts(state_path).get("prompts", {})
    items = [
        {"note_id": nid, "kind": rec.get("kind"), "first_seen": rec.get("first_seen")}
        for nid, rec in prompts.items()
    ]
    return {"prompts": items, "count": len(items)}


class DeletePromptResolve(BaseModel):
    id: str
    choice: str  # "delete_both" | "keep_here"


@router.post("/trash/delete-prompts/resolve")
async def resolve_delete_prompt_endpoint(body: DeletePromptResolve):
    """ISS-005 A follow-up: resolve a held cross-device DELETE-PROMPT (a note a peer deleted that this
    desktop still holds locally). Non-destructive by contract (§6 case 2):

      - `delete_both` → soft-MOVE the local note into `_trash/` (body bytes untouched) so it is trashed
        on both peers; the next sync pass propagates the local trash to the hub `_trash/` (delete_detect
        outbound path), and for the common inbound case the hub copy is already trashed/removed by the
        peer. The durable prompt is cleared.
      - `keep_here` → keep the local note as-is and leave the remote removed ("keep here / just remove
        there"); a durable `keep_here` marker stops the prompt re-raising each pass.

    UNKNOWN id → 404, malformed `choice` → 400 — NEVER a blind delete."""
    from delete_detect import load_delete_prompts, save_delete_prompts
    import time as _time

    if body.choice not in ("delete_both", "keep_here"):
        raise HTTPException(status_code=400, detail="choice must be 'delete_both' or 'keep_here'")

    root = _srv()._get_vault_root()
    state_path = str(root / ".omni_capture" / "mobile_sync_state.json")
    store = load_delete_prompts(state_path)
    prompts = store.get("prompts", {})
    if body.id not in prompts:
        raise HTTPException(status_code=404, detail=f"no delete-prompt held for {body.id!r}")

    if body.choice == "delete_both":
        from mobile_sync_agent import read_vault_notes
        from trash import move_to_trash
        note = read_vault_notes(str(root)).get(body.id)
        trashed = None
        if note:
            try:
                trashed = move_to_trash(root, Path(note["path"]))
            except FileNotFoundError:
                trashed = None  # already gone locally — the prompt is still cleared below
        prompts.pop(body.id, None)
        save_delete_prompts(state_path, store)
        return {"ok": True, "id": body.id, "choice": "delete_both", "trashed": trashed}

    # keep_here: keep local, leave remote removed, and durably suppress re-prompting.
    store.setdefault("keep_here", {})[body.id] = {
        "resolved_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    }
    prompts.pop(body.id, None)
    save_delete_prompts(state_path, store)
    return {"ok": True, "id": body.id, "choice": "keep_here"}


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

"""
vault_admin.py - vault-administration endpoints extracted from server.py:
project-registry CRUD, full-text search, and capture statistics.

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
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import anyio
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

import path_safety
import project_registry
import projects

router = APIRouter()


def _srv():
    """Resolve the already-loaded server module whether it was imported as
    'server' (tests) or 'omni_capture.server' (packaged uvicorn launch).
    A bare top-level `import server` creates a SECOND module identity under
    packaged launch and re-triggers server.py's import -> circular crash."""
    return sys.modules.get("omni_capture.server") or sys.modules["server"]


# -- Pydantic models -----------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectRename(BaseModel):
    new_name: str

class ProjectDescriptionPatch(BaseModel):
    description: Optional[str] = None  # None = clear description; str = set/update (max 500 chars)


class SetupFolder(BaseModel):
    name: str
    description: str


class VaultSetupRequest(BaseModel):
    root: str
    folders: list[SetupFolder] = []


# -- Registry helpers -----------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_project_entry(description: Optional[str] = None) -> dict:
    """A fresh registry entry (contract §13.1). `device` is "desktop" -- the same
    origin vocabulary note frontmatter uses ("phone"/"desktop"/"shared")."""
    from storage_engine import PROJECT_DESC_MAX_CHARS
    now = _now_iso()
    return {
        "description": (description or "").strip()[:PROJECT_DESC_MAX_CHARS],
        "created": now,
        "modified": now,
        "device": "desktop",
    }


def _require_eligible(name: str) -> str:
    """Registry-eligible names only (contract §1.3). Anything else would be dangling --
    i.e. loose -- the instant it were accepted, so it is rejected at the door."""
    name = (name or "").strip()
    if not projects.is_valid_project_name(name):
        raise HTTPException(
            status_code=400,
            detail=f"{name!r} is not a valid project name (letters, digits, '-' and '_'; "
                   "must start with a letter or digit).",
        )
    return name


def _project_file_count(root: Path, name: str) -> int:
    d = root / name
    if not d.is_dir():
        return 0
    return len([f for f in d.iterdir() if f.suffix == ".md"])


# -- Vault-path safety helpers --------------------------------------------------
# Also used by server.py's /inbox/{note_id}/approve (target-folder validation)
# via `vault_admin._safe_folder_dir` -- kept here since vault-directory
# safety is fundamentally a vault-CRUD concern.

_safe_name = path_safety.safe_name


def _safe_folder_dir(root: Path, name: str) -> Path:
    """
    Resolve a vault folder and guarantee it stays directly inside the
    vault root. The name is a project name or a reserved folder (`_loose`,
    `_scratchpad`, ...) -- this guard does not care which.

    The logic lives in `path_safety.safe_subdir` so that trash.py and
    mobile_sync_agent.py can reuse the same resolve-and-compare backstop
    without importing this server-adjacent module. This wrapper only maps
    its ValueError onto the HTTP 400 that route handlers expect.
    """
    try:
        return path_safety.safe_subdir(root, name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid folder name.")


# -- Vault management endpoints -----------------------------------------------

@router.get("/vault/folders")
async def list_vault_folders():
    """The vault's top-level DIRECTORY listing (Library's folder browser), not the
    project registry -- `GET /vault/projects` is that. Both exist because they answer
    different questions: this one shows what is on disk (including `_scratchpad` and
    `_loose`, which are not projects and never appear in the registry).

    ISS-014: dot-prefixed folders (`.omni_capture`, `.sync`) are internal
    pipeline/sync bookkeeping and must never reach this list at all.

    Descriptions come from the registry (`.category.toml` is gone), so a folder
    that is not a registered project simply has none.
    """
    root = _srv()._get_vault_root()
    if not root.exists():
        return {"folders": [], "vault_root": str(root)}
    registry = project_registry.load(root).get("projects", {})
    result = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            md_files = [f for f in entry.iterdir() if f.suffix == ".md"]
            result.append({
                "name": entry.name,
                "file_count": len(md_files),
                # SRV-24: was `"path": str(entry)` -- an absolute filesystem path
                # nothing consumed (the GUI addresses folders by `name`) and that
                # merely restated `vault_root` + `name`. Vault-relative now.
                "rel_path": entry.name,
                "description": (registry.get(entry.name) or {}).get("description") or None,
            })
    return {"folders": result, "vault_root": str(root)}

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
    with user projects, BEFORE it is ever written to config -- so the
    first-run wizard can skip its folder-picker step (mock's "existing vault
    found" branch) for a path the user Browse'd to that's already set up.
    Read-only: never mutates config. *root* is whatever the Tauri folder
    dialog returned, not (yet) the configured vault root."""
    if not Path(root).is_absolute():
        raise HTTPException(status_code=400, detail="root must be an absolute path")
    p = Path(root).expanduser()
    if not p.exists():
        return {"exists": False, "has_projects": False, "projects": []}
    # "Already set up" now means "has projects registered", not "has folders on disk":
    # a folder is a consequence of filing a note, never the definition of a project.
    names = sorted(project_registry.load(p).get("projects", {}))
    return {"exists": True, "has_projects": len(names) > 0, "projects": names}


@router.post("/vault/setup")
async def setup_vault(body: VaultSetupRequest):
    """First-run vault-setup wizard (ISS-002/P-WIZARD). Sets the vault root
    (same write path as PATCH /config, see _set_vault_root_config above),
    eagerly runs init_vault() so the scratchpad + .omni_capture dirs exist
    before the very first capture, and REGISTERS every chosen starter project
    with its description -- a fresh vault must never ship a description-less
    project; ISS-002's root cause was exactly an empty description set reaching
    the LLM. No directory is created for a project here: a project's folder
    appears the first time a note is filed into it."""
    if not Path(body.root).is_absolute():
        raise HTTPException(status_code=400, detail="root must be an absolute path")
    root = Path(body.root).expanduser()

    _set_vault_root_config(root)

    from storage_engine import init_vault
    init_vault(root)

    created = []
    for folder in body.folders:
        name = _require_eligible(folder.name)
        project_registry.update(
            root, lambda r, n=name, d=folder.description: r["projects"].__setitem__(n, new_project_entry(d))
        )
        created.append({"name": name, "description": (folder.description or "").strip() or None})

    return {"ok": True, "root": str(root), "folders": created}


# -- Project-registry CRUD ------------------------------------------------------
#
# A project EXISTS in `.projects.toml` and nowhere else. Its directory is created the
# first time a note is filed into it, and removed by the tidy pass when it empties --
# no endpoint here ever creates or deletes a directory, and none of them ever touches a
# note's bytes except the rename below, under an explicit provenance gate.

@router.get("/vault/projects")
async def list_projects():
    root = _srv()._get_vault_root()
    reg = project_registry.load(root).get("projects", {})
    return {
        "projects": [
            {
                "name": name,
                "description": entry.get("description") or None,
                "renamed_from": entry.get("renamed_from"),
                "created": entry.get("created", ""),
                "modified": entry.get("modified", ""),
                "file_count": _project_file_count(root, name),
            }
            for name, entry in sorted(reg.items())
        ],
        "vault_root": str(root),
    }


@router.post("/vault/projects")
async def create_project(body: ProjectCreate):
    from config import get_config
    root = _srv()._get_vault_root()
    name = _require_eligible(body.name)

    reg = project_registry.load(root).get("projects", {})
    if name in reg:
        raise HTTPException(status_code=409, detail=f"'{name}' already exists.")
    # A `renamed_from` still pointing at this name reserves it (contract §13.3): notes
    # carrying the old tag would silently join a different project.
    if any(e.get("renamed_from") == name for e in reg.values()):
        raise HTTPException(status_code=409, detail=f"'{name}' is reserved by a recent rename.")

    description = body.description
    if description is None and get_config().capture.auto_describe_new_folders:
        from storage_engine import generate_project_description
        # generate_project_description() ends in a blocking asyncio.run(), which raises
        # from a thread that already has a running event loop (true here -- async route).
        description = await anyio.to_thread.run_sync(generate_project_description, name)

    project_registry.update(root, lambda r: r["projects"].__setitem__(name, new_project_entry(description)))
    return {"ok": True, "name": name, "description": (description or "").strip() or None}


@router.patch("/vault/projects/{name}/description")
async def update_project_description(name: str, body: ProjectDescriptionPatch):
    """Set or clear a project's description -- the ONE thing the registry holds that
    exists nowhere else (contract §13). It is injected verbatim into the LLM system
    prompt on every capture, so the engine can route into it.

    Pass description=null (JSON null) or an empty string to clear it.
    """
    from storage_engine import PROJECT_DESC_MAX_CHARS
    root = _srv()._get_vault_root()
    if name not in project_registry.load(root).get("projects", {}):
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")

    desc = (body.description or "").strip()[:PROJECT_DESC_MAX_CHARS]

    def _set(reg):
        entry = reg["projects"][name]
        entry["description"] = desc
        entry["modified"] = _now_iso()

    project_registry.update(root, _set)
    return {"ok": True, "name": name, "description": desc or None}


def _is_user_authored(text: str) -> bool:
    """`origin: note` marks a body the USER wrote in an editor (desktop or phone) --
    sacred, never machine-rewritten. Everything else in the vault is a pipeline capture
    whose body this device authored end to end."""
    m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    return bool(re.search(r"^origin:[ \t]*note[ \t]*$", m.group(1) if m else text[:500], re.MULTILINE))


@router.patch("/vault/projects/{name}")
async def rename_project(name: str, body: ProjectRename):
    """Rename a project.

    The entry keeps `renamed_from: <old>` so every note still carrying the OLD body tag
    keeps resolving to this project while the retag rolls out (contract §13.3) -- no note
    is ever loose mid-rename, and nothing depends on the peer being reachable.

    Bodies are then retagged UNDER THE PROVENANCE GATE: machine-authored captures are
    rewritten with no prompt (this device authored every byte of them), user-authored
    notes (`origin: note`) are only OFFERED back to the caller in `offered`. A
    user-authored body is NEVER rewritten here.
    """
    root = _srv()._get_vault_root()
    new_name = _require_eligible(body.new_name)

    reg = project_registry.load(root).get("projects", {})
    if name not in reg:
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")
    if new_name != name and new_name in reg:
        raise HTTPException(status_code=409, detail=f"'{new_name}' already exists.")
    if new_name == name:
        return {"ok": True, "old_name": name, "new_name": name, "retagged": 0, "offered": []}

    def _rename(r):
        entry = dict(r["projects"].pop(name))
        entry["renamed_from"] = name
        entry["modified"] = _now_iso()
        r["projects"][new_name] = entry

    project_registry.update(root, _rename)

    retagged = 0
    offered: list[str] = []
    old_tag, new_tag = f"#project@{name}", f"#project@{new_name}"
    for path in _filed_notes(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if projects.parse_project_tag(text) != name:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        if _is_user_authored(text):
            offered.append(rel)
            continue
        path.write_text(text.replace(old_tag, new_tag), encoding="utf-8")
        retagged += 1

    _tidy(root)
    return {"ok": True, "old_name": name, "new_name": new_name,
            "retagged": retagged, "offered": offered}


@router.delete("/vault/projects/{name}")
async def delete_project(name: str):
    """Remove a project from the REGISTRY ONLY (contract §1.3).

    It never deletes, trashes, moves or edits a note. Every note still tagged with the
    removed name is now dangling, which reads as LOOSE by the one resolution rule, and
    the tidy pass below moves those notes into `_loose/` and removes the emptied
    directory. Nothing is lost and nothing is unreachable: retagging is a body edit the
    user makes, or re-creating the project restores every note to it.
    """
    root = _srv()._get_vault_root()
    if name not in project_registry.load(root).get("projects", {}):
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")

    project_registry.update(root, lambda r: r["projects"].pop(name, None))
    result = _tidy(root)
    return {"ok": True, "deleted": name, "went_loose": result.moved}


# Top-level folders the tidy pass must never touch. A note in the review inbox, the
# trash or the phone's drop box is NOT mis-filed -- it is exactly where it belongs, and
# moving it into `_loose/` on a project delete would silently un-trash or un-inbox it.
# `_loose` itself IS tidyable (a note can move out of it when its project appears).
_TIDY_EXEMPT = {"_scratchpad", "_trash", "_attachments", "_mobile_inbox"}


def _filed_notes(root: Path):
    """Every note the tidy pass owns: `<dir>/<note>.md` at depth 1, excluding the
    exempt folders and any dot-prefixed bookkeeping directory."""
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in _TIDY_EXEMPT:
            continue
        for path in sorted(entry.iterdir()):
            if path.is_file() and path.suffix == ".md":
                yield path


def _tidy(root: Path):
    """Re-file every note into the directory its tag now implies, and drop directories
    the move emptied. Desktop alone re-paths a file (project_tidy.py's whole premise)."""
    import project_tidy
    entries = []
    for path in _filed_notes(root):
        try:
            entries.append(project_tidy.NoteLoc(path, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    reg = project_registry.load(root)
    return project_tidy.apply_tidy(root, project_tidy.plan_tidy(entries, root, reg))


@router.get("/vault/folders/{name}/files")
async def list_folder_files(name: str):
    """Task 2.6: also carries `hub_name`/`name_clash` per note -- the SAME
    resolution mobile_sync_agent runs before a hub upload (_resolve_hub_names
    over every note in the folder, by title+created), so a row whose stored
    on-disk filename differs from its title can still be flagged as the
    clash LOSER before it ever reaches the hub. Authoritative server-side;
    the GUI only displays it (never recomputes the naming rule)."""
    from frontmatter import read_all_fields
    from mobile_sync_agent import _hub_filename, _resolve_hub_names

    root = _srv()._get_vault_root()
    target = _safe_folder_dir(root, name)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")

    md_files = [f for f in sorted(target.iterdir()) if f.is_file() and f.suffix == ".md"]

    # _resolve_hub_names needs id/title/created/folder for every note in the
    # folder (its clash grouping is per (folder, name)) -- only notes that
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
                # Task 12 re-keyed _resolve_hub_names' grouping onto "folder"; this dict was
                # still handing it "category", so every note grouped under None. Harmless here
                # (one folder per call, so the key was constant) but wrong by construction.
                "folder": name,
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
        # caller already holds `vault_root` from /vault/folders. `rel_path` is the
        # vault-relative form for anything that only needs to identify the note.
        files.append({"name": f.stem, "filename": f.name, "path": str(f),
                      "rel_path": f"{name}/{f.name}",
                      "size_bytes": stat.st_size, "modified": stat.st_mtime,
                      "hub_name": hub_name, "name_clash": name_clash,
                      "unreadable": f in unreadable})
    return {"folder": name, "files": files}


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
# Projects S1: captures.db's `category` column was renamed to `project` -- this
# projection follows it, and `_shape_semantic_row` below maps vector_store's own
# `category` column (a separate schema this task does not touch) onto the same
# published key, so both tiers of one result list agree on their field names.
_SEARCH_ROW_FIELDS = ("id", "timestamp", "project", "path", "filename",
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
        # vector_store's `embeddings.category` column has always held the note's parent
        # directory name, i.e. its project (or `_loose`) -- published under the same key
        # as the FTS tier's `project` so one list never carries two names for one field.
        "project": row.get("category"),
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
    project: Optional[str] = None,
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
    look_debug(f"GET /search q={q!r} project={project} since={since} limit={limit} tag={tag}")
    root = _srv()._get_vault_root()
    rows = idx_search(free_q, root, project=project, since=since, limit=limit, tag=tag)
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
    # Smoke check: _safe_folder_dir accepts a plain name and rejects
    # traversal/separator attempts, independent of any FastAPI wiring.
    root = Path(".").resolve()
    ok = _safe_folder_dir(root, "My Notes")
    assert ok.parent == root and ok.name == "My Notes"

    for bad in ("..", ".", "", "   "):
        try:
            _safe_folder_dir(root, bad)
            raise AssertionError(f"expected rejection for {bad!r}")
        except HTTPException:
            pass

    # Path separators are sanitized into a literal single-segment name rather
    # than traversing -- the result must always land directly inside root.
    sanitized = _safe_folder_dir(root, "../escape")
    assert sanitized.parent == root

    print("vault_admin.py smoke check OK")

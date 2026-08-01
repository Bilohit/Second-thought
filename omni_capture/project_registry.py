"""`.projects.toml` — the project registry (data-model contract v3.1 §13).

One hidden TOML file at the vault root holding every project and its description. It syncs like any
other hub file, so its version token is `headRevisionId`, never mtime.

The registry holds exactly one thing that exists nowhere else: the DESCRIPTION. A project's
existence, membership and directory are all derivable from the `#project@` tags in note bodies, so
losing this file is a degradation (empty descriptions, matcher leaves new notes loose) and never a
data loss — see §13.3 and `rebuild_from_vault`.
"""
import tomllib
from pathlib import Path
from typing import Any, Dict

import tomlkit
from tomlkit.items import KeyType, SingleKey

from projects import is_valid_project_name, parse_project_tag

REGISTRY_FILENAME = ".projects.toml"
SCHEMA = 1

Registry = Dict[str, Any]


def _registry_lock_path(vault_root: Path) -> Path:
    # Vault-root sidecar, same convention as merge.py's _merge_lock_path. Callers doing a
    # load->merge->save cycle (contract §13.2) hold this for the ENTIRE cycle -- acquired
    # before the read, released after the write. `save()` itself does not acquire it (its
    # docstring already states callers hold the lock), this just names the path.
    return Path(vault_root) / ".projects.lock"


class UnknownSchemaError(Exception):
    """The file declares a schema this build does not understand. Leave it alone and surface it —
    rewriting would drop fields we cannot see (contract §13.2)."""


def empty_registry() -> Registry:
    return {"schema": SCHEMA, "projects": {}}


def load(vault_root: Path) -> Registry:
    """Read the registry. A missing or malformed file is an empty registry, never an error —
    the app must keep working with no projects at all."""
    path = Path(vault_root) / REGISTRY_FILENAME
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return empty_registry()

    schema = raw.get("schema", SCHEMA)
    entries = raw.get("projects") or {}
    projects = {
        name: dict(entry)
        for name, entry in entries.items()
        if isinstance(entry, dict) and is_valid_project_name(name)
    }
    return {"schema": schema, "projects": projects}


def save(vault_root: Path, reg: Registry) -> None:
    """Whole-file rewrite. CALLERS MUST HOLD `dedup._vault_lock` (contract §13.2 as corrected in
    v3.1) — this function does not acquire it, so a caller can merge-then-write atomically."""
    schema = reg.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise UnknownSchemaError(f"registry schema {schema!r} is not readable by this build")

    doc = tomlkit.document()
    doc["schema"] = SCHEMA
    table = tomlkit.table(is_super_table=True)
    for name in sorted(reg.get("projects", {})):
        if not is_valid_project_name(name):
            raise ValueError(f"refusing to write ineligible project name {name!r}")
        entry = tomlkit.table()
        # Unknown keys are round-tripped verbatim: a future field written by the phone must
        # survive a desktop rewrite (contract §13.1, mirroring §10's frontmatter rule).
        for key, value in reg["projects"][name].items():
            entry[key] = value
        # tomlkit writes a bare `[projects.research]` by default; the contract (§13.1) requires
        # the quoted form so a dotted name (`#project@a.b`) can never silently nest a table.
        table[SingleKey(name, t=KeyType.Basic)] = entry
    doc["projects"] = table

    path = Path(vault_root) / REGISTRY_FILENAME
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def update(vault_root: Path, mutate) -> Registry:
    """Locked load -> mutate -> save cycle, the ONLY way a CRUD caller should write.

    `save()` deliberately does not take the lock (so a sync pass can merge-then-write
    atomically); this holds it across the ENTIRE cycle, per contract §13.2 and
    `dedup._vault_lock`'s own contract. `mutate` is handed the loaded Registry and
    edits it in place.
    """
    from dedup import _vault_lock

    vault_root = Path(vault_root)
    vault_root.mkdir(parents=True, exist_ok=True)
    with _vault_lock(_registry_lock_path(vault_root)):
        reg = load(vault_root)
        mutate(reg)
        save(vault_root, reg)
        return reg


def _merge_entry(local: dict, remote: dict) -> dict:
    """Per-field: newest entry `modified` wins, exact tie goes to remote (contract §13.2 row 5).
    `created` is immutable — on divergence take the EARLIER value."""
    winner, loser = (local, remote) if local.get("modified", "") > remote.get("modified", "") else (remote, local)
    merged = {**loser, **winner}
    created = [e.get("created") for e in (local, remote) if e.get("created")]
    if created:
        merged["created"] = min(created)
    return merged


def merge(base: Registry, local: Registry, remote: Registry) -> Registry:
    """Three-way merge, per entry, keyed by project name (contract §13.2).

    NEVER last-writer-wins on the whole file: two devices editing DIFFERENT projects in one batch
    window write the same file, and a whole-file rule silently discards one of them.
    """
    # `schema` is not merged (contract §13.2): a peer carrying a schema this build cannot read
    # must never be silently rewritten as SCHEMA, dropping fields it cannot see.
    for reg in (base, local, remote):
        schema = reg.get("schema", SCHEMA)
        if schema != SCHEMA:
            raise UnknownSchemaError(f"registry schema {schema!r} is not readable by this build")

    b, l, r = base.get("projects", {}), local.get("projects", {}), remote.get("projects", {})
    out: Dict[str, dict] = {}

    for name in set(b) | set(l) | set(r):
        in_base, in_local, in_remote = name in b, name in l, name in r

        if not in_base:
            if in_local and in_remote:
                out[name] = _merge_entry(l[name], r[name])          # row 3
            elif in_local:
                out[name] = dict(l[name])                            # row 1
            else:
                out[name] = dict(r[name])                            # row 2
            continue

        if in_local and in_remote:
            out[name] = _merge_entry(l[name], r[name])               # row 5
        elif in_local:
            # deleted remotely; local edit beats the delete, an untouched local does not (row 6)
            if l[name] != b[name]:
                out[name] = dict(l[name])
        elif in_remote:
            if r[name] != b[name]:
                out[name] = dict(r[name])                            # row 6
        # deleted on both sides -> gone (row 4 with the delete on either side)

    return {"schema": SCHEMA, "projects": out}


def resolve_project(body: str, reg: Registry) -> str | None:
    """THE single resolution rule. Every surface calls this — never reimplement it.

    A tag resolves only if the name is registry-eligible AND the registry holds it, under its
    current key or as some entry's transitional `renamed_from`. Everything else — no tag, invalid
    name, unregistered name, registry not synced yet — is LOOSE. That one rule absorbs deletion,
    invalid names, rename lag and sync lag alike (contract §1.3, "dangling reads as loose").
    """
    name = parse_project_tag(body)
    if not name or not is_valid_project_name(name):
        return None

    projects_ = reg.get("projects", {})
    if name in projects_:
        return name
    for key, entry in projects_.items():
        if entry.get("renamed_from") == name:
            return key
    return None


def rebuild_from_vault(vault_root: Path) -> Registry:
    """Contract §13.3: if the registry is lost, rebuild it by scanning bodies for `#project@`.
    Every project reappears with an EMPTY description; `renamed_from` cannot be reconstructed and
    is simply absent, so a note still carrying an old name reads as loose — the correct fallback,
    no special case. No note is lost, no note changes project, no grouping breaks."""
    names: set = set()
    for path in Path(vault_root).rglob("*.md"):
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        name = parse_project_tag(body)
        if name and is_valid_project_name(name):
            names.add(name)

    reg = empty_registry()
    for name in sorted(names):
        reg["projects"][name] = {"description": "", "created": "", "modified": "", "device": ""}
    return reg


def clear_stale_renamed_from(reg: Registry, live_names: set) -> Registry:
    """`renamed_from` clears once no vault note still carries the old name (contract §13.3).
    While set, the old name is reserved — no new project may claim it."""
    out = {"schema": reg.get("schema", SCHEMA), "projects": {}}
    for name, entry in reg.get("projects", {}).items():
        entry = dict(entry)
        if entry.get("renamed_from") and entry["renamed_from"] not in live_names:
            entry.pop("renamed_from")
        out["projects"][name] = entry
    return out

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

from projects import is_valid_project_name

REGISTRY_FILENAME = ".projects.toml"
SCHEMA = 1

Registry = Dict[str, Any]


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

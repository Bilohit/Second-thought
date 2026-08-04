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

from projects import is_valid_project_dir, is_valid_project_name, parse_project_tag

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


def is_dir_available(reg: Registry, name: str, dirname: str) -> bool:
    """May `dirname` be project `name`'s home in `reg`? (contract §13.1, v3.2)

    Two halves: the per-value shape rule (`projects.is_valid_project_dir`) and the cross-entry
    rule that needs the whole registry — a directory belongs to at most ONE project, so it may
    not equal another entry's `name` NOR another entry's `dir`. `name`'s own entry is exempt, so
    re-asserting a project's existing home is always available to it.
    """
    if not is_valid_project_dir(dirname):
        return False
    for other, entry in reg.get("projects", {}).items():
        if other == name:
            continue
        if other == dirname or entry.get("dir") == dirname:
            return False
    return True


def _prune_conflicting_dirs(projects: Dict[str, dict]) -> Dict[str, dict]:
    """Drop every `dir` that is not writable, so `load -> dumps` and `merge -> save` can never
    raise on data this build produced or read.

    This is the read/normalize-side valve that makes `dumps`' refusal safe, exactly parallel to
    `parse` dropping an ineligible project NAME while `dumps` raises on one. It is not merely a
    hand-edit guard: `merge` can SYNTHESIZE a collision from two clean registries — device A
    gives project `P` the home `X` while device B creates a project literally named `X`, and the
    merged result holds both. Without this, that entirely legal pair of edits would make every
    subsequent registry save raise.

    Resolution is first-wins in sorted name order, so both peers prune identically and converge.
    Entry order is otherwise preserved, because `parse` hands its result straight back to callers.
    """
    drop: set = set()
    claimed: set = set()
    for name in sorted(projects):                       # sorted => both peers prune identically
        dirname = projects[name].get("dir")
        if dirname is None:
            continue
        if (not is_valid_project_dir(dirname)
                or (dirname != name and (dirname in projects or dirname in claimed))):
            drop.add(name)
        else:
            claimed.add(dirname)

    out: Dict[str, dict] = {}
    for name, entry in projects.items():
        entry = dict(entry)
        if name in drop:
            entry.pop("dir", None)
        out[name] = entry
    return out


def parse(text: str) -> Registry:
    """Registry from TOML TEXT. Malformed text is an empty registry, never an error — same rule
    `load` applies to a malformed file. Split out for the sync pass, which holds the hub copy's
    bytes in memory (downloaded by `headRevisionId`) and never touches a second file."""
    try:
        raw = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, AttributeError, TypeError):
        return empty_registry()

    schema = raw.get("schema", SCHEMA)
    entries = raw.get("projects") or {}
    projects = {
        name: dict(entry)
        for name, entry in entries.items()
        if isinstance(entry, dict) and is_valid_project_name(name)
    }
    return {"schema": schema, "projects": _prune_conflicting_dirs(projects)}


def load(vault_root: Path) -> Registry:
    """Read the registry. A missing or malformed file is an empty registry, never an error —
    the app must keep working with no projects at all."""
    path = Path(vault_root) / REGISTRY_FILENAME
    try:
        return parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return empty_registry()


def dumps(reg: Registry) -> str:
    """The registry's canonical TOML text. Split out of `save` so the sync pass can upload the
    exact bytes it wrote without a second read of a file that may not exist on disk."""
    schema = reg.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise UnknownSchemaError(f"registry schema {schema!r} is not readable by this build")

    doc = tomlkit.document()
    doc["schema"] = SCHEMA
    table = tomlkit.table(is_super_table=True)
    for name in sorted(reg.get("projects", {})):
        if not is_valid_project_name(name):
            raise ValueError(f"refusing to write ineligible project name {name!r}")
        # Contract §13.1 (v3.2): a writer MUST reject an invalid `dir` rather than write it, the
        # same rule `name` already has. `dir` names a real directory on the user's disk, so a bad
        # or double-claimed value would silently relocate files.
        dirname = reg["projects"][name].get("dir")
        if dirname is not None and not is_dir_available(reg, name, dirname):
            raise ValueError(f"refusing to write ineligible project dir {dirname!r} for {name!r}")
        entry = tomlkit.table()
        # Unknown keys are round-tripped verbatim: a future field written by the phone must
        # survive a desktop rewrite (contract §13.1, mirroring §10's frontmatter rule).
        for key, value in reg["projects"][name].items():
            entry[key] = value
        # tomlkit writes a bare `[projects.research]` by default; the contract (§13.1) requires
        # the quoted form so a dotted name (`#project@a.b`) can never silently nest a table.
        table[SingleKey(name, t=KeyType.Basic)] = entry
    doc["projects"] = table
    return tomlkit.dumps(doc)


def save(vault_root: Path, reg: Registry) -> None:
    """Whole-file rewrite. CALLERS MUST HOLD the registry lock (`_registry_lock_path`, obtained
    through the `dedup._vault_lock(lock_path)` factory — contract §13.2 as corrected in v3.1);
    this function does not acquire it, so a caller can merge-then-write atomically.

    The write itself goes through `atomic_write_text` (temp sibling + os.replace) so a crash
    or partial write mid-save can never leave a truncated/empty registry on disk — the lock
    only ever serializes *concurrent writers*, it says nothing about a torn write from one."""
    from atomic_io import atomic_write_text

    path = Path(vault_root) / REGISTRY_FILENAME
    atomic_write_text(path, dumps(reg))


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

    # `dir` merges as an ordinary per-entry field (§13.1, no special case) -- but merging two
    # individually-valid registries can leave two entries claiming the same directory, which
    # `dumps` refuses to write. Prune here so the merge result is always savable.
    return {"schema": SCHEMA, "projects": _prune_conflicting_dirs(out)}


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
    no special case. No note is lost, no note changes project, no grouping breaks.

    ponytail: `dir` is not recovered either — contract §13.3 names that degradation as acceptable
    ("a rebuild that does not bother degrades to `dir` absent -> directory == name -> the tidy
    pass proposes the moves again, which is precisely today's behaviour"). Upgrade path if a
    rebuild ever needs to keep the user's folder names: this loop already knows each tagged
    note's `path`, so take the modal `path.parent.name` per project name and set it as `dir`
    when it differs from the name and `is_dir_available` says it is free."""
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

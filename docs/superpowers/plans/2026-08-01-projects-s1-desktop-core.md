# Projects S1 — Desktop Tag/Registry Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Build the Python core that makes `#project@<name>` body tags the sole grouping mechanism, and
delete the `category` concept end to end.

**Architecture:** Three new pure-first modules (`projects.py`, `project_registry.py`,
`project_tidy.py`) land first with **zero callers**, fully tested, gates green — that is the bisect
point. Then `category` is ripped out across 66 files in reviewed batches and the new modules are wired
in. The body tag is the only truth; the `project:` frontmatter line and the `project` index column are
both derived caches of it, produced by one shared resolution function.

**Tech Stack:** Python 3, `tomllib` (stdlib, read) + `tomlkit` (write, format-preserving), pytest, no
config file, no linter. Plain functions and module-level singletons — no classes, no DI.

## Global Constraints

Copied verbatim from the binding sources. **Every task's requirements implicitly include this section.**

- **Contract is `Second Thought - Android App/data-model-and-contracts.md` v3.1** — §1, §1.3, §13. The
  contract is already amended; build against it, never ahead of it.
- **Spec is `docs/superpowers/specs/2026-08-01-projects-s1-desktop-core-design.md`.** Parent design:
  `2026-08-01-projects-rework-design.md`.
- **A note's body is sacred.** Only the user's editor writes below the frontmatter, with the single
  provenance-gated exception (ISS-051) of the originating device's trailing `tags: #a #b` line. **Every
  op that touches a note asserts body byte-identity before/after.**
- **Sync is pure transport.** It moves bytes and writes sync bookkeeping; it never edits file content in
  either direction. Frontmatter writes come only from an explicit local save/enrichment pass.
- **Files are the source of truth.** `captures.db`, `vectors.db`, `dedup_index.json`, `.projects.toml`
  are derived rebuildable caches. No SQLite table is ever authoritative over a `.md` file.
- **`main.py:run_pipeline()` and `server.py:_run_pipeline_blocking()` are hand-duplicated BY DESIGN.**
  Mirror every pipeline change into both by hand. **Never collapse them** — repo hard rule.
- **`cfg.ollama.base_url` stays bare** (`http://localhost:11434`), never `/v1`-suffixed.
- **Every note stays at depth 1**: `<project>/<file>.md` or `_loose/<file>.md`. This is what keeps
  `![alt](../_attachments/<id>/<file>)` body refs valid across every move.
- **Desktop alone re-paths a file.** The phone never moves a file, never creates a directory.
- **Registry-eligible name:** `^[A-Za-z0-9][A-Za-z0-9_-]*$`. Anything else is dangling → **loose**.
- **`project:` frontmatter is ALWAYS bracketed, ALWAYS present:** `project: [research]` set,
  `project: [-]` loose. Single-valued; brackets are parse-shape consistency, never a list.
- **Icons/UI copy:** inline SVG only, never emoji. Geist Mono. Semantic colour only. (Applies to the
  Task 14 gui patch.)
- **`ponytail:` comments mark a deliberate ceiling with its upgrade path.** Preserve existing ones; add
  one for any new deliberate shortcut. Never silently "fix" a marked shortcut.
- **Non-trivial logic ships one runnable check.** New branch/loop/parser → a sibling `test_*.py` case,
  and it must be RUN before the task is done.
- **Gates to beat:** desktop **1173** passed / 4 skipped · gui **545** + `npm run build` clean · phone
  **1823** / 6 skipped + both typechecks.
- **`FUZZ=1 pytest test_fuzz_races.py -q` is REQUIRED for Step B** (Tasks 9–13 move sync-agent and
  sync-state surfaces). Not required for Step A.
- **No `Co-Authored-By` trailer.** Commit directly per repo when gates are green; **never push.**

### A rule about this plan's code blocks — read before Task 1

**Step A tasks (1–8) carry literal, complete code.** Those modules do not exist yet, so the code cannot
disagree with reality.

**Step B tasks (9–15) deliberately carry anchors, rules and test contracts instead of literal
replacement code.** In session s124 the plan's literal code was wrong three separate times — a safety
regex that was a prefix match, a hardcoded expected path that `write_to_vault` actually derives from the
title, and a `row["filepath"]` whose real column is `path`. **Verify every symbol at source before you
touch it.** A literal diff written blind for a 129-hit file would be a fabrication, and the plan says so
rather than pretending otherwise.

---

# STEP A — new modules, zero callers

## Task 1: `projects.py` — the tag parser and name rules

**Files:**
- Create: `omni_capture/projects.py`
- Test: `omni_capture/test_projects.py`

**Interfaces:**
- Consumes: `body_tags._FENCED_CODE`, `body_tags._INLINE_CODE` (existing, `body_tags.py:24-25`)
- Produces: `parse_project_tags(body: str) -> list[str]`,
  `parse_project_tag(body: str) -> str | None`,
  `is_valid_project_name(name: str) -> bool`,
  `is_structural_tag(tag: str) -> bool`,
  `project_cache_value(resolved: str | None) -> str`,
  `note_dir_for(resolved: str | None) -> str`,
  `LOOSE_DIR = "_loose"`

- [ ] **Step 1: Write the failing test**

Create `omni_capture/test_projects.py`:

```python
import pytest

from projects import (
    LOOSE_DIR,
    is_structural_tag,
    is_valid_project_name,
    note_dir_for,
    parse_project_tag,
    parse_project_tags,
    project_cache_value,
)


def test_parses_a_simple_tag():
    assert parse_project_tag("some text #project@research more") == "research"


def test_no_tag_is_none():
    assert parse_project_tag("plain note with #ordinary tags") is None


def test_case_is_preserved_verbatim():
    assert parse_project_tag("#project@Cancer-Imaging") == "Cancer-Imaging"


def test_tag_ends_at_first_whitespace():
    assert parse_project_tag("#project@research and more") == "research"


def test_tag_must_be_whitespace_anchored_so_a_url_fragment_never_files_a_note():
    # The contract writes the parser as /#project@([^\s]+)/ in shorthand. Implemented bare, this
    # URL would file the note into project "x". See spec s1 §2.1 and DECISIONS s125 item 7.
    body = "see https://example.com/page#project@x for details"
    assert parse_project_tag(body) is None


def test_tag_inside_a_fenced_code_block_is_ignored():
    body = "intro\n```\n#project@fake\n```\nouttro"
    assert parse_project_tag(body) is None


def test_tag_inside_an_inline_code_span_is_ignored():
    assert parse_project_tag("type `#project@fake` to file it") is None


def test_two_tags_first_in_document_order_wins():
    assert parse_project_tag("#project@alpha then #project@beta") == "alpha"


def test_parse_project_tags_exposes_every_capture_for_the_ui_to_flag():
    assert parse_project_tags("#project@alpha then #project@beta") == ["alpha", "beta"]


def test_start_of_string_counts_as_anchored():
    assert parse_project_tag("#project@research") == "research"


@pytest.mark.parametrize("name", ["research", "R", "a-b_c", "Project2", "0start"])
def test_valid_names(name):
    assert is_valid_project_name(name) is True


@pytest.mark.parametrize(
    "name",
    ["", "_loose", "_trash", "-lead", "a.b", "a/b", "a b", "café", "a@b"],
)
def test_invalid_names(name):
    # Leading `_` is rejected on purpose: it makes every reserved hub folder unreachable
    # as a project name (contract §1.3).
    assert is_valid_project_name(name) is False


def test_structural_tags():
    assert is_structural_tag("project@research") is True
    assert is_structural_tag("sys/llm-failed") is True
    assert is_structural_tag("sys") is True


def test_descriptive_tags_are_not_structural():
    assert is_structural_tag("research") is False
    assert is_structural_tag("@work") is False
    assert is_structural_tag("systems") is False       # prefix must not over-match
    assert is_structural_tag("projects") is False      # ditto


def test_cache_value_formatting():
    assert project_cache_value("research") == "[research]"
    assert project_cache_value(None) == "[-]"


def test_note_dir():
    assert note_dir_for("research") == "research"
    assert note_dir_for(None) == LOOSE_DIR
    assert LOOSE_DIR == "_loose"
```

- [ ] **Step 2: Run test to verify it fails**

Run from `omni_capture/`: `python -m pytest test_projects.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'projects'`

- [ ] **Step 3: Write minimal implementation**

Create `omni_capture/projects.py`:

```python
"""The project tag layer (data-model contract v3.1 §1.3).

A note's project is the body tag `#project@<name>`. The tag is the ONLY truth: the `project:`
frontmatter line and the `project` index column are both derived caches of it, and both are
produced from `resolve_project` (project_registry.py) so they can never disagree.

Grammar note, deliberate: the contract writes the parser as `/#project@([^\\s]+)/` in shorthand.
This module implements it whitespace-anchored and code-stripped, matching the grammar body_tags.py
already enforces for every other tag. The bare form matches inside
`https://example.com/page#project@x`, which would file a note from a URL fragment. The phone mirror
(bodyTags.ts) must carry the identical tightening or the two peers drift. See DECISIONS §5 s125 item 7.
"""
import re

from body_tags import _FENCED_CODE, _INLINE_CODE

LOOSE_DIR = "_loose"

# Whitespace-anchored, like body_tags._TAG_TOKEN. Group 2 is the name; it runs to the first
# whitespace, exactly as the contract specifies, and is NOT validated here — validity is a
# separate question (is_valid_project_name), because an invalid name must read as loose rather
# than as "no tag at all".
_PROJECT_TAG = re.compile(r"(^|\s)#project@([^\s]+)")

# Contract §1.3: narrower than the tag parser, because the name is simultaneously a tag, a TOML
# key and a directory name. The leading-character rule also makes every reserved `_`-prefixed hub
# folder (_loose, _trash, _attachments, _mobile_inbox) unreachable as a project name.
_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _strip_code(body: str) -> str:
    return _INLINE_CODE.sub(" ", _FENCED_CODE.sub(" ", body))


def parse_project_tags(body: str) -> list[str]:
    """Every `#project@` capture, in document order. Exposed so a UI can flag the two-tag case."""
    return [m.group(2) for m in _PROJECT_TAG.finditer(_strip_code(body))]


def parse_project_tag(body: str) -> str | None:
    """The note's project tag, or None. Two tags is a validation error the UI prevents; the model
    must still not crash on a hand-typed file, so the FIRST in document order wins."""
    tags = parse_project_tags(body)
    return tags[0] if tags else None


def is_valid_project_name(name: str) -> bool:
    return bool(_VALID_NAME.match(name))


def is_structural_tag(tag: str) -> bool:
    """Structural tags say where a note is FILED; descriptive tags say what it is ABOUT.
    Only descriptive tags belong in the derived `tags:` cache (contract §1, §1.3)."""
    return tag == "sys" or tag.startswith("sys/") or tag.startswith("project@")


def project_cache_value(resolved: str | None) -> str:
    """The `project:` frontmatter value. ALWAYS bracketed, ALWAYS present (contract §1)."""
    return f"[{resolved}]" if resolved else "[-]"


def note_dir_for(resolved: str | None) -> str:
    """The note's directory name. Every note stays at depth 1 so `../_attachments/` refs survive
    every move without a body rewrite (contract §1.3)."""
    return resolved if resolved else LOOSE_DIR
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_projects.py -q`
Expected: PASS, all cases.

- [ ] **Step 5: Run the full suite to prove nothing moved**

Run: `python -m pytest -q`
Expected: **1173 passed, 4 skipped** — unchanged, since nothing calls this module yet.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/projects.py omni_capture/test_projects.py
git commit -m "feat(projects): tag parser, name validity and structural-tag rules"
```

---

## Task 2: `project_registry.py` — load and save `.projects.toml`

**Files:**
- Create: `omni_capture/project_registry.py`
- Test: `omni_capture/test_project_registry.py`

**Interfaces:**
- Consumes: `projects.is_valid_project_name`
- Produces: `REGISTRY_FILENAME = ".projects.toml"`, `SCHEMA = 1`,
  `empty_registry() -> Registry`,
  `load(vault_root: Path) -> Registry`,
  `save(vault_root: Path, reg: Registry) -> None`
- **`Registry` shape** (a plain dict, mirroring the file; repo style is plain functions and dicts,
  no classes): `{"schema": int, "projects": {name: {"description": str, "created": str,
  "modified": str, "device": str, ...unknown keys preserved...}}}`

- [ ] **Step 1: Write the failing test**

Create `omni_capture/test_project_registry.py`:

```python
from pathlib import Path

import pytest

import project_registry as pr


def _write(vault: Path, text: str) -> None:
    (vault / pr.REGISTRY_FILENAME).write_text(text, encoding="utf-8")


def test_missing_file_loads_as_empty_never_raises(tmp_path):
    reg = pr.load(tmp_path)
    assert reg == {"schema": pr.SCHEMA, "projects": {}}


def test_loads_entries(tmp_path):
    _write(
        tmp_path,
        'schema = 1\n\n'
        '[projects."research"]\n'
        'description = "Cancer imaging leads."\n'
        'created = "2026-08-01T10:00:00Z"\n'
        'modified = "2026-08-01T10:12:00Z"\n'
        'device = "desktop-a1b2"\n',
    )
    reg = pr.load(tmp_path)
    assert reg["projects"]["research"]["description"] == "Cancer imaging leads."
    assert reg["projects"]["research"]["created"] == "2026-08-01T10:00:00Z"


def test_a_name_with_a_dot_would_nest_a_toml_table_and_is_dropped_on_load(tmp_path):
    # Quoted keys mean a dotted name cannot silently nest, but a hand-edited file can still
    # carry an ineligible name. It is not registered, so its notes read as loose (contract §13.1).
    _write(tmp_path, 'schema = 1\n\n[projects."a.b"]\ndescription = ""\n')
    assert pr.load(tmp_path)["projects"] == {}


def test_unknown_keys_round_trip(tmp_path):
    _write(
        tmp_path,
        'schema = 1\n\n[projects."research"]\n'
        'description = "d"\ncreated = "c"\nmodified = "m"\ndevice = "dev"\n'
        'future_field = "written by a newer phone"\n',
    )
    reg = pr.load(tmp_path)
    pr.save(tmp_path, reg)
    text = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")
    assert "future_field" in text
    assert "written by a newer phone" in text


def test_keys_are_always_quoted_on_write(tmp_path):
    reg = pr.empty_registry()
    reg["projects"]["research"] = {
        "description": "d", "created": "c", "modified": "m", "device": "dev",
    }
    pr.save(tmp_path, reg)
    text = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")
    assert '[projects."research"]' in text


def test_save_rejects_an_invalid_name(tmp_path):
    reg = pr.empty_registry()
    reg["projects"]["a/b"] = {"description": "", "created": "c", "modified": "m", "device": "d"}
    with pytest.raises(ValueError):
        pr.save(tmp_path, reg)


def test_an_unreadable_schema_is_surfaced_and_the_file_is_never_rewritten(tmp_path):
    # Contract §13.2: a peer reading a schema it does not understand must leave the file alone,
    # never rewrite it with fields it would drop.
    _write(tmp_path, 'schema = 99\n\n[projects."research"]\ndescription = "keep me"\n')
    reg = pr.load(tmp_path)
    assert reg["schema"] == 99
    with pytest.raises(pr.UnknownSchemaError):
        pr.save(tmp_path, reg)
    assert "keep me" in (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")


def test_malformed_toml_loads_as_empty_rather_than_crashing_the_app(tmp_path):
    _write(tmp_path, "this is not { valid toml")
    assert pr.load(tmp_path) == {"schema": pr.SCHEMA, "projects": {}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_project_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_registry'`

- [ ] **Step 3: Write minimal implementation**

Create `omni_capture/project_registry.py`:

```python
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
        table[name] = entry
    doc["projects"] = table

    path = Path(vault_root) / REGISTRY_FILENAME
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_project_registry.py -q`
Expected: PASS.

**If `tomlkit` writes bare rather than quoted keys**, the assertion in
`test_keys_are_always_quoted_on_write` is the one that catches it. Quoted keys are contract-mandated
(§13.1) — a bare key lets `#project@a.b` silently nest a table. Fix the writer, never the test.

- [ ] **Step 5: Commit**

```bash
git add omni_capture/project_registry.py omni_capture/test_project_registry.py
git commit -m "feat(projects): .projects.toml load/save with unknown-key round-trip"
```

---

## Task 3: `project_registry.merge` — contract §13.2's table, verbatim

**This is the correctness core of the whole sub-project.** A last-writer-wins shortcut here silently
eats a description written on the other device and produces no error, no log line, and no failing test
unless you write these cases.

**Files:**
- Modify: `omni_capture/project_registry.py` (add `merge`)
- Test: `omni_capture/test_project_registry.py` (add the table cases)

**Interfaces:**
- Consumes: `Registry` from Task 2
- Produces: `merge(base: Registry, local: Registry, remote: Registry) -> Registry`

- [ ] **Step 1: Write the failing test**

Append to `omni_capture/test_project_registry.py`:

```python
def _entry(desc="", created="2026-08-01T10:00:00Z", modified="2026-08-01T10:00:00Z", device="d"):
    return {"description": desc, "created": created, "modified": modified, "device": device}


def _reg(**projects):
    return {"schema": pr.SCHEMA, "projects": dict(projects)}


# Contract §13.2, row by row. Each test quotes its row.

def test_row1_absent_present_absent_added_locally_keep():
    out = pr.merge(_reg(), _reg(a=_entry("mine")), _reg())
    assert out["projects"]["a"]["description"] == "mine"


def test_row2_absent_absent_present_added_remotely_keep():
    out = pr.merge(_reg(), _reg(), _reg(a=_entry("theirs")))
    assert out["projects"]["a"]["description"] == "theirs"


def test_row3_absent_present_present_both_added_same_name_merge_per_field():
    local = _reg(a=_entry("mine", modified="2026-08-01T10:00:00Z"))
    remote = _reg(a=_entry("theirs", modified="2026-08-01T11:00:00Z"))
    out = pr.merge(_reg(), local, remote)
    assert out["projects"]["a"]["description"] == "theirs"   # newest modified wins


def test_row4_present_absent_unchanged_deleted_locally_delete_applies():
    base = _reg(a=_entry("d"))
    out = pr.merge(base, _reg(), _reg(a=_entry("d")))
    assert "a" not in out["projects"]


def test_row5_present_present_differing_newest_modified_wins():
    base = _reg(a=_entry("old", modified="2026-08-01T09:00:00Z"))
    local = _reg(a=_entry("local edit", modified="2026-08-01T12:00:00Z"))
    remote = _reg(a=_entry("remote edit", modified="2026-08-01T11:00:00Z"))
    out = pr.merge(base, local, remote)
    assert out["projects"]["a"]["description"] == "local edit"


def test_row5_exact_tie_goes_to_remote():
    base = _reg(a=_entry("old", modified="2026-08-01T09:00:00Z"))
    same = "2026-08-01T12:00:00Z"
    out = pr.merge(base, _reg(a=_entry("local", modified=same)),
                   _reg(a=_entry("remote", modified=same)))
    assert out["projects"]["a"]["description"] == "remote"


def test_row6_edit_beats_delete_entry_is_resurrected():
    # The row that needs stating out loud (contract §13.2). Resurrecting costs the user one
    # redundant delete; honouring the delete would destroy a description they just wrote.
    base = _reg(a=_entry("old", modified="2026-08-01T09:00:00Z"))
    remote = _reg(a=_entry("just written", modified="2026-08-01T12:00:00Z"))
    out = pr.merge(base, _reg(), remote)
    assert out["projects"]["a"]["description"] == "just written"


def test_row6_mirrored_local_edit_beats_remote_delete():
    base = _reg(a=_entry("old", modified="2026-08-01T09:00:00Z"))
    local = _reg(a=_entry("just written", modified="2026-08-01T12:00:00Z"))
    out = pr.merge(base, local, _reg())
    assert out["projects"]["a"]["description"] == "just written"


def test_deleted_on_both_sides_stays_deleted():
    assert pr.merge(_reg(a=_entry()), _reg(), _reg())["projects"] == {}


def test_created_is_immutable_and_takes_the_earlier_value():
    base = _reg(a=_entry(created="2026-08-01T10:00:00Z"))
    local = _reg(a=_entry(created="2026-08-01T10:00:00Z", modified="2026-08-01T12:00:00Z"))
    remote = _reg(a=_entry(created="2026-07-30T08:00:00Z", modified="2026-08-01T11:00:00Z"))
    out = pr.merge(base, local, remote)
    assert out["projects"]["a"]["created"] == "2026-07-30T08:00:00Z"


def test_unrelated_entries_on_each_side_both_survive():
    # The whole reason this is not last-writer-wins: two devices editing DIFFERENT projects in
    # one batch window write the same file.
    base = _reg()
    out = pr.merge(base, _reg(mine=_entry("m")), _reg(theirs=_entry("t")))
    assert set(out["projects"]) == {"mine", "theirs"}


def test_unknown_keys_survive_a_merge():
    base = _reg()
    local = _reg(a={**_entry("m"), "future_field": "keep"})
    out = pr.merge(base, local, _reg())
    assert out["projects"]["a"]["future_field"] == "keep"


def test_renamed_from_is_carried_through_a_merge():
    out = pr.merge(_reg(), _reg(new={**_entry("d"), "renamed_from": "old"}), _reg())
    assert out["projects"]["new"]["renamed_from"] == "old"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_project_registry.py -q -k merge or row`
Expected: FAIL — `AttributeError: module 'project_registry' has no attribute 'merge'`

- [ ] **Step 3: Write minimal implementation**

Append to `omni_capture/project_registry.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_project_registry.py -q`
Expected: PASS, every row.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: **1173 passed, 4 skipped** plus the new files' cases. Still zero callers.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/project_registry.py omni_capture/test_project_registry.py
git commit -m "feat(projects): three-way per-entry registry merge per contract 13.2"
```

---

## Task 4: `resolve_project`, `rebuild_from_vault`, `clear_stale_renamed_from`

**Files:**
- Modify: `omni_capture/project_registry.py`
- Test: `omni_capture/test_project_registry.py`

**Interfaces:**
- Consumes: `projects.parse_project_tag`, `projects.is_valid_project_name`, `Registry`
- Produces: `resolve_project(body: str, reg: Registry) -> str | None`,
  `rebuild_from_vault(vault_root: Path) -> Registry`,
  `clear_stale_renamed_from(reg: Registry, live_names: set[str]) -> Registry`

**Why `resolve_project` lives here and not in `projects.py`:** it needs the registry, and `projects.py`
must stay dependency-free so the parser can be tested and mirrored without one.

- [ ] **Step 1: Write the failing test**

Append to `omni_capture/test_project_registry.py`:

```python
def test_resolve_returns_the_project_when_registered():
    reg = _reg(research=_entry())
    assert pr.resolve_project("body #project@research", reg) == "research"


def test_no_tag_is_loose():
    assert pr.resolve_project("plain body", _reg(research=_entry())) is None


def test_an_unregistered_name_is_loose_this_one_rule_absorbs_deletion_and_sync_lag():
    assert pr.resolve_project("#project@deleted", _reg()) is None


def test_an_ineligible_name_is_loose_and_never_registered():
    assert pr.resolve_project("#project@a/b", _reg()) is None


def test_renamed_from_resolves_the_old_name_to_the_new_project():
    # Required for CORRECTNESS, not convenience: a note on an offline phone still carries the old
    # tag, and without this a rename silently empties its own project (contract §1.3).
    reg = _reg(**{"research-cancer": {**_entry(), "renamed_from": "cancer"}})
    assert pr.resolve_project("#project@cancer", reg) == "research-cancer"
    assert pr.resolve_project("#project@research-cancer", reg) == "research-cancer"


def test_a_current_key_beats_another_entrys_renamed_from():
    reg = {"schema": pr.SCHEMA, "projects": {
        "cancer": _entry(),
        "research-cancer": {**_entry(), "renamed_from": "cancer"},
    }}
    assert pr.resolve_project("#project@cancer", reg) == "cancer"


def test_rebuild_from_vault_finds_every_project_with_an_empty_description(tmp_path):
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "a.md").write_text("---\nid: 1\n---\n\nbody #project@research\n", encoding="utf-8")
    (tmp_path / "_loose").mkdir()
    (tmp_path / "_loose" / "b.md").write_text("---\nid: 2\n---\n\nno tag here\n", encoding="utf-8")
    reg = pr.rebuild_from_vault(tmp_path)
    assert set(reg["projects"]) == {"research"}
    assert reg["projects"]["research"]["description"] == ""


def test_rebuild_skips_ineligible_names(tmp_path):
    (tmp_path / "a.md").write_text("---\nid: 1\n---\n\n#project@a/b\n", encoding="utf-8")
    assert pr.rebuild_from_vault(tmp_path)["projects"] == {}


def test_clear_stale_renamed_from_clears_when_no_note_carries_the_old_name():
    reg = _reg(new={**_entry(), "renamed_from": "old"})
    out = pr.clear_stale_renamed_from(reg, live_names=set())
    assert "renamed_from" not in out["projects"]["new"]


def test_clear_stale_renamed_from_keeps_it_while_a_note_still_carries_the_old_name():
    reg = _reg(new={**_entry(), "renamed_from": "old"})
    out = pr.clear_stale_renamed_from(reg, live_names={"old"})
    assert out["projects"]["new"]["renamed_from"] == "old"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_project_registry.py -q -k "resolve or rebuild or renamed"`
Expected: FAIL — `AttributeError: module 'project_registry' has no attribute 'resolve_project'`

- [ ] **Step 3: Write minimal implementation**

Append to `omni_capture/project_registry.py`:

```python
from projects import parse_project_tag  # add to the existing import line from projects


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
    names: set[str] = set()
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


def clear_stale_renamed_from(reg: Registry, live_names: set[str]) -> Registry:
    """`renamed_from` clears once no vault note still carries the old name (contract §13.3).
    While set, the old name is reserved — no new project may claim it."""
    out = {"schema": reg.get("schema", SCHEMA), "projects": {}}
    for name, entry in reg.get("projects", {}).items():
        entry = dict(entry)
        if entry.get("renamed_from") and entry["renamed_from"] not in live_names:
            entry.pop("renamed_from")
        out["projects"][name] = entry
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_project_registry.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omni_capture/project_registry.py omni_capture/test_project_registry.py
git commit -m "feat(projects): resolve_project, registry rebuild, renamed_from clearing"
```

---

## Task 5: `project_tidy.py` — the pure move planner

**Files:**
- Create: `omni_capture/project_tidy.py`
- Test: `omni_capture/test_project_tidy.py`

**Interfaces:**
- Consumes: `projects.note_dir_for`, `project_registry.resolve_project`, `Registry`
- Produces: `NoteLoc = NamedTuple(path: Path, body: str)`, `Move = NamedTuple(src: Path, dst: Path)`,
  `plan_tidy(entries: list[NoteLoc], vault_root: Path, reg: Registry) -> list[Move]`

- [ ] **Step 1: Write the failing test**

Create `omni_capture/test_project_tidy.py`:

```python
from pathlib import Path

import project_tidy as pt
from project_registry import SCHEMA


def _reg(*names):
    return {"schema": SCHEMA,
            "projects": {n: {"description": "", "created": "", "modified": "", "device": ""}
                         for n in names}}


VAULT = Path("/vault")


def test_a_tagged_note_in_the_wrong_folder_moves_to_its_project():
    entries = [pt.NoteLoc(VAULT / "_loose" / "a.md", "body #project@research")]
    moves = pt.plan_tidy(entries, VAULT, _reg("research"))
    assert moves == [pt.Move(VAULT / "_loose" / "a.md", VAULT / "research" / "a.md")]


def test_a_note_already_in_place_does_not_move():
    entries = [pt.NoteLoc(VAULT / "research" / "a.md", "body #project@research")]
    assert pt.plan_tidy(entries, VAULT, _reg("research")) == []


def test_an_untagged_note_moves_to_loose_not_to_the_vault_root():
    # Depth 1 is the invariant that keeps `../_attachments/<id>/<file>` body refs valid across
    # every move without rewriting a sacred body (contract §1.3).
    entries = [pt.NoteLoc(VAULT / "research" / "a.md", "no tag")]
    moves = pt.plan_tidy(entries, VAULT, _reg("research"))
    assert moves == [pt.Move(VAULT / "research" / "a.md", VAULT / "_loose" / "a.md")]


def test_a_dangling_tag_is_treated_as_loose():
    entries = [pt.NoteLoc(VAULT / "gone" / "a.md", "#project@gone")]
    moves = pt.plan_tidy(entries, VAULT, _reg())
    assert moves == [pt.Move(VAULT / "gone" / "a.md", VAULT / "_loose" / "a.md")]


def test_every_planned_destination_is_at_depth_one():
    entries = [
        pt.NoteLoc(VAULT / "_loose" / "a.md", "#project@research"),
        pt.NoteLoc(VAULT / "research" / "b.md", "no tag"),
    ]
    for move in pt.plan_tidy(entries, VAULT, _reg("research")):
        assert move.dst.relative_to(VAULT).parts[:-1] == (move.dst.parent.name,)


def test_a_name_collision_at_the_destination_is_planned_with_a_suffixed_filename():
    entries = [
        pt.NoteLoc(VAULT / "_loose" / "a.md", "#project@research"),
        pt.NoteLoc(VAULT / "research" / "a.md", "#project@research"),
    ]
    moves = pt.plan_tidy(entries, VAULT, _reg("research"))
    assert len(moves) == 1
    assert moves[0].dst != VAULT / "research" / "a.md"
    assert moves[0].dst.parent == VAULT / "research"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_project_tidy.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_tidy'`

- [ ] **Step 3: Write minimal implementation**

Create `omni_capture/project_tidy.py`:

```python
"""Derived housekeeping: move each note into the directory its tag implies.

DESKTOP ALONE RE-PATHS A FILE. The phone never moves a file and never creates a directory — that is
the load-bearing safety property of the rework, because a path change is the one operation Drive
reconcile cannot merge field-wise (contract §1.3).

Worst case with the desktop off for a week: the vault on disk is untidy while both apps read
correctly, because both read the tag. Self-healing, never wrong.

This module is the PURE planner. The applier that touches the filesystem is `apply_tidy` (Task 6).
"""
import uuid
from pathlib import Path
from typing import Dict, List, NamedTuple

from project_registry import Registry, resolve_project
from projects import note_dir_for


class NoteLoc(NamedTuple):
    path: Path
    body: str


class Move(NamedTuple):
    src: Path
    dst: Path


def plan_tidy(entries: List[NoteLoc], vault_root: Path, reg: Registry) -> List[Move]:
    """Every note's target is `vault_root / note_dir_for(resolve_project(body, reg))` — a project
    directory, or `_loose/`. Notes already in place are not moved."""
    vault_root = Path(vault_root)
    taken: Dict[Path, int] = {}
    for entry in entries:
        taken[entry.path] = taken.get(entry.path, 0) + 1

    moves: List[Move] = []
    for entry in entries:
        target_dir = vault_root / note_dir_for(resolve_project(entry.body, reg))
        dst = target_dir / entry.path.name
        if dst == entry.path:
            continue
        if dst in taken:
            # Never clobber. Mirrors _unique_file_path's 6-char suffix convention
            # (storage_engine.py:525).
            dst = dst.with_name(f"{dst.stem}-{uuid.uuid4().hex[:6]}{dst.suffix}")
        taken[dst] = taken.get(dst, 0) + 1
        moves.append(Move(entry.path, dst))
    return moves
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_project_tidy.py -q`
Expected: PASS. The collision test asserts only that the destination differs and stays in the project
directory, because the suffix is random.

- [ ] **Step 5: Commit**

```bash
git add omni_capture/project_tidy.py omni_capture/test_project_tidy.py
git commit -m "feat(projects): pure tidy-pass move planner"
```

---

## Task 6: `apply_tidy` — the locked, atomic applier

**Files:**
- Modify: `omni_capture/project_tidy.py`
- Test: `omni_capture/test_project_tidy.py`

**Interfaces:**
- Consumes: `Move` from Task 5, `dedup._vault_lock` (existing — **verify its exact name and call
  shape at source**, `dedup.py:218` and `dedup.py:318`, before using it)
- Produces: `TidyResult = NamedTuple(moved: int, skipped: int, removed_dirs: int)`,
  `apply_tidy(vault_root: Path, moves: list[Move]) -> TidyResult`

- [ ] **Step 1: Verify the lock at source**

Read `omni_capture/dedup.py:210-230` and `omni_capture/dedup.py:310-325`. Note the exact name, whether
it is a context manager, and what argument it takes. **Do not guess it from this plan.** s124 shipped
three plan-literal symbols that did not exist; this is the same class of error.

- [ ] **Step 2: Write the failing test**

Append to `omni_capture/test_project_tidy.py`:

```python
def test_apply_moves_files_and_creates_the_destination_directory(tmp_path):
    src_dir = tmp_path / "_loose"
    src_dir.mkdir()
    src = src_dir / "a.md"
    src.write_text("---\nid: 1\n---\n\nbody #project@research\n", encoding="utf-8")

    result = pt.apply_tidy(tmp_path, [pt.Move(src, tmp_path / "research" / "a.md")])

    assert result.moved == 1
    assert (tmp_path / "research" / "a.md").exists()
    assert not src.exists()


def test_apply_never_edits_file_content(tmp_path):
    # A tidy pass MOVES files and does nothing else. Body-sacred, and sync-is-pure-transport.
    (tmp_path / "_loose").mkdir()
    src = tmp_path / "_loose" / "a.md"
    original = "---\nid: 1\n---\n\nbody #project@research\ntrailing spaces   \n"
    src.write_bytes(original.encode("utf-8"))

    pt.apply_tidy(tmp_path, [pt.Move(src, tmp_path / "research" / "a.md")])

    assert (tmp_path / "research" / "a.md").read_bytes() == original.encode("utf-8")


def test_apply_refuses_to_clobber_an_existing_destination(tmp_path):
    (tmp_path / "_loose").mkdir()
    (tmp_path / "research").mkdir()
    src = tmp_path / "_loose" / "a.md"
    dst = tmp_path / "research" / "a.md"
    src.write_text("new", encoding="utf-8")
    dst.write_text("PRECIOUS", encoding="utf-8")

    result = pt.apply_tidy(tmp_path, [pt.Move(src, dst)])

    assert result.skipped == 1
    assert dst.read_text(encoding="utf-8") == "PRECIOUS"
    assert src.exists()


def test_apply_removes_an_emptied_project_directory_but_never_loose(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "_loose").mkdir()
    src = tmp_path / "old" / "a.md"
    src.write_text("x", encoding="utf-8")

    pt.apply_tidy(tmp_path, [pt.Move(src, tmp_path / "_loose" / "a.md")])

    assert not (tmp_path / "old").exists()
    assert (tmp_path / "_loose").exists()


def test_apply_on_an_empty_move_list_is_a_no_op(tmp_path):
    assert pt.apply_tidy(tmp_path, []) == pt.TidyResult(0, 0, 0)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest test_project_tidy.py -q -k apply`
Expected: FAIL — `AttributeError: module 'project_tidy' has no attribute 'apply_tidy'`

- [ ] **Step 4: Write the implementation**

Append to `omni_capture/project_tidy.py`. **Use the real lock name you read in Step 1** — the call below
shows the intent, and the symbol must be corrected to what `dedup.py` actually exports:

```python
class TidyResult(NamedTuple):
    moved: int
    skipped: int
    removed_dirs: int


def apply_tidy(vault_root: Path, moves: List[Move]) -> TidyResult:
    """Apply planned moves. Serialized under the existing vault write lock (contract §13.2 as
    corrected in v3.1 — v3.0 named `_LEDGER_FILES`, which is a category->filename map with no lock).

    NEVER edits file content: this moves files and nothing else. `os.replace` is atomic on the same
    volume; a destination that already exists is SKIPPED, never clobbered, mirroring
    `mobile_sync_agent._maybe_refile_local` (mobile_sync_agent.py:686).
    """
    vault_root = Path(vault_root)
    moved = skipped = 0
    source_dirs: set = set()

    with _vault_lock(vault_root):        # <- CORRECT THIS to dedup.py's real symbol and signature
        for move in moves:
            if not move.src.exists() or move.dst.exists():
                skipped += 1
                continue
            move.dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(move.src, move.dst)
            source_dirs.add(move.src.parent)
            moved += 1

        removed_dirs = 0
        for directory in source_dirs:
            if directory.name == LOOSE_DIR or directory == vault_root:
                continue
            try:
                directory.rmdir()          # only succeeds when empty
                removed_dirs += 1
            except OSError:
                pass

    return TidyResult(moved, skipped, removed_dirs)
```

Add `import os` and extend the `projects` import with `LOOSE_DIR`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest test_project_tidy.py -q` → PASS
Run: `python -m pytest -q` → **1173 passed, 4 skipped** plus the new cases. Still zero callers.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/project_tidy.py omni_capture/test_project_tidy.py
git commit -m "feat(projects): atomic locked tidy-pass applier"
```

---

## Task 7: `body_tags.py` — exclude structural tags from the derived cache

> **DONE (commit `b92c5e6`).** Two corrections landed from execution, kept here because Task 15 mirrors
> this change into the phone:
> - The function is **`extract_body_tags(body: str) -> list[str]`** (`body_tags.py:103`), returning
>   first-seen order, deduped, leading `#` stripped. This plan originally called it `parse_body_tags`,
>   which does not exist anywhere in the module — corrected throughout.
> - The import cycle **did** occur and was resolved by the prescribed route: `_FENCED_CODE` and
>   `_INLINE_CODE` now live in `projects.py:20-21`, and `body_tags.py:24` imports them plus
>   `is_structural_tag` back from there. No duplication, no function-local import.
> - **No pre-existing test asserted the old inclusive behaviour**, so none were modified.

**Files:**
- Modify: `omni_capture/body_tags.py` (the `extract_body_tags` function — **read it at source first**)
- Test: `omni_capture/test_body_tags.py` if it exists, else create it

**Interfaces:**
- Consumes: `projects.is_structural_tag`
- Produces: unchanged signature; `extract_body_tags` now omits structural tags

**This is the only Step A change to an existing module, and it is behaviour-changing.** The functional
reason, not tidiness: `tag_vocab.py` normalizes new tags against the vault's existing vocabulary, so an
unfiltered `project@research` in the cache can capture a genuine new tag.

- [ ] **Step 1: Read `extract_body_tags` at source**

Read `omni_capture/body_tags.py` in full. Note the exact function name, its return type and ordering
guarantees, and whether a sibling test file already exists. **`body_tags.py` is required to stay
grammar-identical to `phone/src/lib/bodyTags.ts` — the docstrings of both say so.** Task 15 mirrors this
change into the phone. Do not change the grammar itself, only which parsed tags survive.

- [ ] **Step 2: Write the failing test**

```python
from body_tags import extract_body_tags


def test_project_tag_is_excluded_from_the_derived_cache():
    # `tags:` holds DESCRIPTIVE vocabulary only — what a note is ABOUT. `#project@x` is
    # STRUCTURAL: it says where the note is FILED. Contract v3.1 §1, §1.3.
    tags = extract_body_tags("#research and #project@cancer-imaging")
    assert "research" in tags
    assert not any(t.startswith("project@") for t in tags)


def test_sys_tags_are_excluded():
    assert "sys/llm-failed" not in extract_body_tags("#sys/llm-failed #real")


def test_gtd_context_tags_still_survive():
    # `@` is in the token charset FOR these; the exclusion must not over-reach.
    assert "@work" in extract_body_tags("call them #@work")


def test_a_tag_merely_starting_with_project_is_not_structural():
    assert "projects" in extract_body_tags("#projects")
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest test_body_tags.py -q`
Expected: FAIL — the project tag is currently present in the returned list.

- [ ] **Step 4: Implement**

In `extract_body_tags`, drop any tag for which `is_structural_tag` holds, at the single point the list is
built. Import from `projects`. **Check for an import cycle**: `projects.py` imports `_FENCED_CODE` /
`_INLINE_CODE` from `body_tags`. If importing `projects` at `body_tags` module level creates a cycle,
move the two regexes into `projects.py` and have `body_tags` import them from there instead — do NOT
duplicate the regexes into both files, and do NOT paper over it with a function-local import.

- [ ] **Step 5: Run tests**

Run: `python -m pytest test_body_tags.py -q` → PASS
Run: `python -m pytest -q` → any pre-existing test asserting a `sys/*` tag reaches the cache will now
fail. **Read each failure and decide at source**: if it asserts the old inclusive behaviour, update it
and say so in the commit body. If it asserts something else, you have broken something — stop and report.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/body_tags.py omni_capture/test_body_tags.py
git commit -m "feat(projects): exclude structural tags from the derived tags cache"
```

---

## Task 8: the `project:` frontmatter cache

> **DONE (commit `894b08a`), and it corrected this plan.** Source-verified anchors:
> - The serializer is **`note_model.serialize_note(note: Note) -> str`** (`note_model.py:181`).
> - **`tags:`/`attachments:` are NOT recomputed in `note_model.py`.** This plan said they were; they
>   are recomputed at `mobile_sync_agent.py:1425-1434`, inside the desktop-authoritative enrich pass,
>   provenance-gated to `origin_device in ("desktop", "shared")`. `note_model.py` only serializes what
>   is already on the struct.
> - Key order is `id, title, origin, created, modified, device, tags, project, origin_device, aliases,
>   attachments, enriched, enrich_source, remind_at` — `project` sits immediately after `tags`, matching
>   the contract's adjacency.
> - `frontmatter.py` needed **no change** — its `_FM_RE`/`read_all_fields`/`add_fields` serve unrelated
>   read-only paths, not the known-key serializer.
> - `project` is **not stored on the struct**: it is computed from `note.body` + registry at serialize
>   time, so a hand-edited or missing line is discarded on parse and rebuilt on serialize — which is
>   exactly the cache semantics the contract requires, achieved without a field to drift.
>
> **⚠ STEP B MUST CLOSE THIS — the signature is `serialize_note(note, registry: Registry | None = None)`
> and every existing call site still passes nothing, so NO `project:` LINE IS EMITTED ANYWHERE YET.**
> That default keeps Step A a true zero-caller change, but the contract says the line is ALWAYS present.
> Task 12 owns the wiring. The known call sites are `mobile_sync_agent.py:992, 1036, 1457` and
> `today_view.py:122` — **verify that list at source before relying on it**, and add a test asserting
> every serialize path emits the line, so a missed call site fails loudly instead of silently dropping
> it from real notes.

**Files:**
- Modify: `omni_capture/note_model.py` (**read `note_model.py:21-24, 105, 140` at source first** — it
  already parses and drops a legacy `category:` line)
- Modify: `omni_capture/frontmatter.py` (**read `frontmatter.py:8`, `_FM_RE`, at source first**)
- Test: `omni_capture/test_note_model.py`

**Interfaces:**
- Consumes: `projects.project_cache_value`, `project_registry.resolve_project`
- Produces: notes serialize with a `project:` line, always present, always bracketed

- [ ] **Step 1: Read both modules at source**

Establish: where the derived `tags:` line is recomputed on save, where `attachments:` is recomputed
beside it, and the exact serialization order of frontmatter keys. **`project:` is recomputed at exactly
the same point as those two, by the same trigger.** Report the anchors before writing code.

- [ ] **Step 2: Write the failing test**

```python
def test_project_line_is_written_bracketed_when_resolved():
    # ... build a note whose body carries #project@research, with `research` registered
    assert "project: [research]" in serialized


def test_loose_notes_get_an_explicit_marker_never_an_absent_line():
    assert "project: [-]" in serialized


def test_a_dangling_tag_caches_as_loose():
    # The value written is the RESOLVED project, so an unregistered tag caches as [-] —
    # because that note IS loose (contract §1.3).
    assert "project: [-]" in serialized


def test_hand_edited_project_line_is_overwritten_from_the_body():
    # Identical to how `tags:` behaves today: the frontmatter is a cache, the body is truth.
    ...


def test_deleting_the_project_line_rebuilds_it_losslessly():
    ...


def test_the_body_is_byte_identical_after_a_recompute():
    # Mandatory on every non-editor op, both repos.
    assert after_body_bytes == before_body_bytes
```

Fill each body against the real serializer signature you found in Step 1. **Do not invent a helper that
does not exist** — use the module's real entry point.

- [ ] **Step 3: Run to verify it fails.** Expected: no `project:` line is emitted.

- [ ] **Step 4: Implement.** Recompute `project` beside `tags` and `attachments`, writing
`project_cache_value(resolve_project(body, registry))`. Legacy `category:` lines continue to be dropped
on read exactly as they are today.

- [ ] **Step 5: Run** `python -m pytest -q`. Expected: green, plus new cases.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/note_model.py omni_capture/frontmatter.py omni_capture/test_note_model.py
git commit -m "feat(projects): derived project frontmatter cache"
```

---

## GATE A — Opus review checkpoint

**Do not start Step B until this passes.** Report to the orchestrator:

- `python -m pytest -q` from `omni_capture/` — the number, verbatim.
- `git log --oneline -8` — the eight Step A commits.
- The three anchors you verified at source: `dedup.py`'s real lock symbol, `extract_body_tags`'s real
  name and return type, and the frontmatter recompute point.
- Any place where this plan's literal code disagreed with the real codebase, and what you did.

---

# STEP B — rip-out and wire

**Every Step B task starts by reading its target files at source.** The anchors below come from a survey
and are starting points, not truth. Line numbers drift as earlier tasks land.

**Common rules for Tasks 9–15:**
1. **Never find-and-replace across a file.** Read the responsibility, then change it.
2. **`main.py` and `server.py` are hand-duplicated by design** — mirror by hand, never collapse.
3. **A task that cannot stay behaviour-preserving is STOPPED and reported, not bent.**
4. Delete the four hardcoded category names when your task reaches them (authorised, s125 item 5):
   `storage_engine._LEDGER_FILES`, `pre_resolver`'s Finance/CRM hints, `link_resolver.py:154`'s CRM
   word-count case, `scratchpad.py:360`'s `_CATEGORY_DEFAULT_STATUS`.
5. Legacy `category:` frontmatter is **ignored on read and dropped at first recompute** — no migration.

## Task 9: models, LLM engine, and the death of `key_signals` tags

**Files:** `models.py:42, 93-118` · `llm_engine.py:266-332` · `storage_engine.py:537` (`_signals_to_tags`)
· tests: `test_pre_resolver.py`, `test_llm_timeout.py`, `tests/test_e2e.py`

- [ ] Delete `CaptureOutput.category` and the live folder-name enum in `build_capture_model`. The repo
  hard rule "vault categories are never hardcoded" retires with the concept; **record its replacement**
  in `CLAUDE.md` in Task 15: project names come from the registry, never from a literal.
- [ ] `llm_engine`'s prompt and output schema take **project descriptions from the registry**
  (`project_registry.load`) in place of `build_category_descriptions`. The engine **picks only from
  projects that already exist and may never create one** (parent design §3).
- [ ] **Delete `key_signals` → arbitrary tag generation** (`storage_engine._signals_to_tags`). Auto
  enrichment writes a project assignment and nothing else.
- [ ] Delete `pre_resolver`'s Finance/CRM hints.
- [ ] Run `python -m pytest -q`; report the number and every test you changed, with the reason.
- [ ] Commit.

## Task 10: the write path

**Files:** `storage_engine.py:114-201, 346, 515-522, 718-734, 920-1043` · tests: `test_storage_engine.py`
(HEAVY, 40 hits), `test_routing_and_merge.py`, `test_capture_idempotency.py`

- [ ] Delete `discover_categories`, `read_category_config`, `build_category_descriptions`,
  `write_category_description`, `ensure_category`, `_category_str`, `_LEDGER_FILES`,
  `write_to_named_category`.
- [ ] `_resolve_file_path` and `write_to_vault` route via `note_dir_for(resolve_project(body, reg))`.
  **A capture whose project does not resolve lands in `_loose/` and that is a success, not a failure** —
  this is what deletes OF-6's entire failure class.
- [ ] Keep `_unique_file_path`'s no-clobber behaviour.
- [ ] Run `python -m pytest -q`; report. Commit.

## Task 11: index column rename

**Files:** `index_writer.py:13, 76, 91, 709-721, 963-1057` · tests: `test_index_and_search.py` (HEAVY,
43), `test_index_health.py`, `test_store_rebuild.py`

- [ ] Rename the `captures` table's `category` column to `project`; migrate forward, or drop and rebuild
  from the `.md` files — **the files are the truth and the DB is a rebuildable cache**, so a rebuild is
  always legal and is usually the smaller diff.
- [ ] `_row_filter_clauses` and the `by_category` aggregation become `by_project`, including the
  `--category` CLI flag → `--project`.
- [ ] The column is written from `resolve_project`, so it agrees with the `project:` frontmatter cache
  by construction. Add one test asserting the two agree for the same note.
- [ ] Run `python -m pytest -q`; report. Commit.

## Task 12: sync agent + `base_projects`

**Files:** `mobile_sync_agent.py:36, 593, 686, 945-1664, 1375-1484, 1827` · tests:
`test_mobile_sync_agent.py` (HEAVIEST, 95 hits), `test_fable_s23_sync.py`, `test_reconcile.py`,
`test_conflict_and_trash.py`

**Highest-risk task in the plan. Sync correctness core — expect the most careful reasoning tier.**

- [ ] `_resolve_dest_folder` and `_maybe_refile_local` re-key onto the resolved project / `_loose`.
- [ ] Add `base_projects` to `.omni_capture/mobile_sync_state.json` beside the per-note `base_parent`
  bookkeeping, and wire `project_registry.merge(base, local, remote)` into the sync pass. **Hold
  `dedup._vault_lock` across merge-then-save** so the two are atomic.
- [ ] **`.projects.toml`'s version token is `headRevisionId`, never mtime.**
- [ ] **Sync is pure transport**: it must not edit note content in either direction. Add an explicit
  test asserting a synced note's bytes are unchanged by a sync pass.
- [ ] §1.2's divergent-move arm is now unreachable (only desktop re-paths) — delete it, and delete K-1 /
  `category_source` (parent design §10).
- [ ] Run `python -m pytest -q` **and** `FUZZ=1 pytest test_fuzz_races.py -q` — **required here**.
  Report both numbers. Commit.

## Task 13: server, CLI, scratchpad, retry engine

**Files:** `server.py:907, 1683-1747` · `main.py:182-197, 522` · `scratchpad.py:231-278, 360-369` ·
`retry_engine.py:133-227` · tests: `test_server.py` (HEAVY, 34), `test_api_surface.py`,
`test_inbox_approve_guard.py`, `test_route_failed_llm.py`, `test_retry_engine.py`

- [ ] Category-CRUD endpoints become project-registry endpoints (list / create / update description /
  rename / delete). **Delete removes the registry entry only — it never deletes, trashes, moves or
  edits a note** (contract §1.3). Its notes go loose by the dangling rule and the tidy pass removes the
  emptied directory.
- [ ] **Rename** writes `renamed_from` on the entry, rewrites machine-authored bodies under the existing
  provenance gate with no prompt, and **offers** user-authored notes to the user. Never rewrite a
  user-authored body unprompted.
- [ ] `scratchpad.approve` routes to a project or `_loose`; delete `_CATEGORY_DEFAULT_STATUS`.
- [ ] **`retry_pending()`'s precondition collapses to "Ollama is reachable."** The ≥1-category-folder
  gate was correct against s124's code and is wrong under projects, because a retry can now always
  succeed — worst case the repaired note lands loose. Carried from `HANDOVER.md` §5 item 4.
- [ ] Mirror every pipeline change into **both** `main.py` and `server.py` by hand.
- [ ] Run `python -m pytest -q`; report. Commit.

## Task 14: remaining carriers + the gui keep-green patch

**Files:** `jobs.py` `capture_log.py` `delete_detect.py` `link_resolver.py:154` `note_editor.py`
`rag_engine.py` `merge.py` `reconcile.py` `notifier.py` `enrichment_router.py:523` `path_safety.py` ·
then `gui/src/` (~27 files, 203 hits)

- [ ] Re-key or delete each remaining carrier per its role. Delete `link_resolver`'s CRM word-count
  special-case.
- [ ] gui: the **minimum patch that typechecks and keeps 545 green** — drop category fields and columns,
  **no new project UI** (that is sub-projects 3 and 4). Deliberately throwaway.
- [ ] Run from `gui/`: `npm run build` and `npm test`. Report both. **Never emoji; inline SVG only.**
- [ ] Run `python -m pytest -q`. Commit both repos' halves separately.

## Task 15: phone parity slice + doc truth

**Files:** `phone/src/lib/bodyTags.ts` · `phone/src/lib/frontmatter.ts` · `Second Thought/CLAUDE.md`

**Why this cannot wait for sub-project 5:** the moment desktop writes its first `#project@` tag, an
unmodified phone harvests it into `tags:` on the next save, the peers disagree about the same file's
derived cache, and each save churns the other's. The user's stated first priority forbids exactly that.

- [ ] `bodyTags.ts` — the identical structural-tag exclusion, **including the whitespace-anchoring
  tightening** from Task 1. The two grammars are required to stay identical; their docstrings say so.
- [ ] `frontmatter.ts` — read/write/derive `project:` with the identical bracket form,
  `[research]` / `[-]`.
- [ ] Out of scope here: the phone's index column, tiles, assign menu, semantic matching — all
  sub-project 5.
- [ ] Update `Second Thought/CLAUDE.md`: the hard rule "vault categories are never hardcoded" is
  replaced by its projects equivalent, and the file-structure block gains the three new modules.
- [ ] Run from `phone/`: `npm test`, `npm run typecheck`, `npm run typecheck:app`. Report all three.
- [ ] Commit in the phone repo separately.

---

# GATE B — final Opus review

Report, each number run in the main thread, never carried from a subagent:

| Gate | Command | Beat |
|---|---|---|
| desktop | `python -m pytest -q` (from `omni_capture/`) | 1173 / 4 skipped |
| desktop fuzz | `FUZZ=1 pytest test_fuzz_races.py -q` | 4 passed |
| gui | `npm test` + `npm run build` (from `gui/`) | 545, build exit 0 |
| phone | `npm test` + `npm run typecheck` + `npm run typecheck:app` (from `phone/`) | 1823 / 6 skipped |

Then: a round-trip proof that a note's `tags:` and `project:` derive byte-identically on both peers, and
a body-sacred assertion on every op that touched a note.

**Do not push.** Six commits are already held back by user decision; these join them.

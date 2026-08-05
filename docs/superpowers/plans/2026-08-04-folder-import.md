# Folder-structure import (FR-23 Option C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offer a folder-organised vault a one-time, consent-gated import that turns each top-level folder into a real project — writing `#project@<name>` into the notes inside it and registering the name in `.projects.toml` — so the tidy pass stops flattening a tree the user meant.

**Architecture:** A pure planner (`folder_import.py`) computes candidate folders and their notes from an on-disk scan plus the registry; two routes in `vault_admin.py` expose preview and apply; the GUI reuses the FR-23 Option A tidy strip in `VaultManager.tsx`, adding one action that opens a per-folder checklist. The applier writes each note by re-serialising it through `note_model.serialize_note(note, registry)`, which recomputes the derived `project:` frontmatter from the new body, then re-indexes via `note_editor._reindex`.

**Tech Stack:** Python 3 / FastAPI / pytest (no config file, run from `omni_capture/`); React 18 + TypeScript strict / Vitest / Tailwind v3 in `gui/`.

## Global Constraints

- **A project name must match `^[A-Za-z0-9][A-Za-z0-9_-]*$`** (`projects.py:32`, `_VALID_NAME`). It is simultaneously a tag token, a TOML key and a directory name.
- **A tag resolves only if the registry also holds the name** (`project_registry.py:183-190`, `resolve_project`). The import MUST write the registry entry and the body tag, or the note still reads loose and the tidy pass moves it anyway.
- **Bodies are written only on an explicit per-folder confirmation.** Nothing in this feature runs automatically, on launch, or as a side effect of any other route.
- **Files never move.** This feature makes folders legitimate; `project_tidy` remains the only code that re-paths a note.
- **Tag placement: one line immediately after the first `# ` heading; if the body has no heading, the first line of the body** — identical to `today_view._daily_body`'s `#daily` placement. Never the trailing machine `tags:` line (`mobile_sync_agent.py:1484-1487` replaces that line wholesale).
- **Exempt from every scan:** `_scratchpad`, `_trash`, `_attachments`, `_mobile_inbox` (`vault_admin.py:424`, `_TIDY_EXEMPT`), any dot-prefixed directory, and `_loose`.
- **A note that already carries a `#project@` tag is never re-tagged** — it is not a candidate.
- **No emoji anywhere.** Icons are inline SVG from `gui/src/components/PillMenu/icons.tsx`. Geist Mono, 0-radius, semantic colour only.
- **`ponytail:` comments mark deliberate ceilings.** Non-trivial logic ships one runnable check.
- **This plan file is gitignored** (`Second Thought/.gitignore:22`, `*.md`) and cannot be committed. It lives on disk only.

---

### Task 1: The pure planner

**Files:**
- Create: `omni_capture/folder_import.py`
- Test: `omni_capture/test_folder_import.py`

**Interfaces:**
- Consumes: `projects.parse_project_tag`, `projects.is_valid_project_name`, `project_registry.Registry`
- Produces: `FolderCandidate` (dataclass: `folder: str`, `suggested: str`, `valid: bool`, `existing: bool`, `note_paths: list[Path]`), `sanitise_name(folder: str) -> str`, `plan_import(root: Path, reg: Registry) -> list[FolderCandidate]`, `tag_line_insert(body: str, name: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# omni_capture/test_folder_import.py
from pathlib import Path
import folder_import


def test_sanitise_replaces_illegal_runs_with_single_dash():
    assert folder_import.sanitise_name("My Notes") == "My-Notes"
    assert folder_import.sanitise_name("r&d") == "r-d"
    assert folder_import.sanitise_name("2026 ideas") == "2026-ideas"


def test_sanitise_strips_leading_and_trailing_dashes_and_may_return_empty():
    # A leading char must be alphanumeric; a name of only illegal chars has no suggestion.
    assert folder_import.sanitise_name("_hidden") == "hidden"
    assert folder_import.sanitise_name("!!!") == ""


def test_tag_line_goes_under_the_first_heading():
    body = "# Q3 planning\n\nKickoff is the 14th.\n"
    assert folder_import.tag_line_insert(body, "Work") == (
        "# Q3 planning\n#project@Work\n\nKickoff is the 14th.\n"
    )


def test_tag_line_goes_first_when_there_is_no_heading():
    body = "Kickoff is the 14th.\n"
    assert folder_import.tag_line_insert(body, "Work") == "#project@Work\nKickoff is the 14th.\n"


def test_plan_skips_exempt_loose_dot_dirs_and_already_tagged_notes(tmp_path):
    (tmp_path / "Work").mkdir()
    (tmp_path / "Work" / "a.md").write_text("---\nid: 1\n---\n# A\n", encoding="utf-8")
    (tmp_path / "Work" / "b.md").write_text("---\nid: 2\n---\n# B\n#project@Work\n", encoding="utf-8")
    (tmp_path / "_loose").mkdir()
    (tmp_path / "_loose" / "c.md").write_text("---\nid: 3\n---\n# C\n", encoding="utf-8")
    (tmp_path / "_trash").mkdir()
    (tmp_path / "_trash" / "d.md").write_text("---\nid: 4\n---\n# D\n", encoding="utf-8")
    (tmp_path / ".omni_capture").mkdir()

    plan = folder_import.plan_import(tmp_path, {"schema": 1, "projects": {}})

    assert [c.folder for c in plan] == ["Work"]
    assert [p.name for p in plan[0].note_paths] == ["a.md"]


def test_plan_reports_validity_suggestion_and_existing_project(tmp_path):
    for folder in ("My Notes", "Recipes"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "n.md").write_text("---\nid: x\n---\n# N\n", encoding="utf-8")

    plan = {c.folder: c for c in folder_import.plan_import(
        tmp_path, {"schema": 1, "projects": {"Recipes": {"created": "2026-01-01"}}})}

    assert plan["My Notes"].valid is False
    assert plan["My Notes"].suggested == "My-Notes"
    assert plan["Recipes"].valid is True
    assert plan["Recipes"].existing is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `omni_capture/`: `python -m pytest test_folder_import.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'folder_import'`

- [ ] **Step 3: Write the module**

```python
"""folder_import.py -- FR-23 Option C's pure planner.

A vault that predates the s127 tag model organises notes in folders and carries no
`#project@` tags at all, so the tidy pass correctly concludes every note belongs in
`_loose/` and flattens the tree. This module plans the other repair: keep the tree and
make it legitimate, by tagging the notes and registering the folder names.

Pure by design, exactly like project_tidy.py: it reads the vault and returns a plan.
Nothing here writes a byte -- the applier lives in vault_admin.py behind an explicit
user confirmation, because this is the one surface in the product that edits note
bodies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from projects import LOOSE_DIR, is_valid_project_name, parse_project_tag

# Mirrors vault_admin._TIDY_EXEMPT, plus `_loose` -- a loose note is not mis-filed, it is
# exactly where the model says an untagged note belongs, so it is never an import candidate.
_EXEMPT = {"_scratchpad", "_trash", "_attachments", "_mobile_inbox", LOOSE_DIR}

_ILLEGAL_RUN = re.compile(r"[^A-Za-z0-9_-]+")
_EDGE_DASHES = re.compile(r"^[-_]+|[-_]+$")


@dataclass
class FolderCandidate:
    folder: str
    suggested: str
    valid: bool
    existing: bool
    note_paths: list[Path] = field(default_factory=list)


def sanitise_name(folder: str) -> str:
    """A SUGGESTION for an unusable folder name -- never applied without the user seeing it.

    Collapses every illegal run to one `-` and trims the edges, because a project name must
    start with an alphanumeric. Returns "" when nothing usable survives, which the UI shows
    as an empty field for the user to fill rather than a bad guess."""
    candidate = _EDGE_DASHES.sub("", _ILLEGAL_RUN.sub("-", folder))
    return candidate if is_valid_project_name(candidate) else ""


def tag_line_insert(body: str, name: str) -> str:
    """Insert `#project@<name>` as its own line directly under the first `# ` heading, or
    as the first line when there is none.

    The same placement `today_view._daily_body` uses for `#daily`: ordinary body text the
    user can see and delete, deliberately NOT the trailing machine `tags:` line, which
    enrichment replaces wholesale (mobile_sync_agent.py:1484-1487)."""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines.insert(i + 1, f"#project@{name}")
            return "\n".join(lines)
    return f"#project@{name}\n{body}"


def plan_import(root: Path, reg: dict) -> list[FolderCandidate]:
    """Every top-level folder holding at least one untagged note, in directory order.

    A note that already carries a `#project@` tag is not a candidate -- it already has a
    project, and re-tagging it would be the product overwriting the user's own answer."""
    registered = set(reg.get("projects", {}))
    out: list[FolderCandidate] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in _EXEMPT:
            continue
        notes = []
        for path in sorted(entry.iterdir()):
            if not (path.is_file() and path.suffix == ".md"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if parse_project_tag(text) is None:
                notes.append(path)
        if not notes:
            continue
        valid = is_valid_project_name(entry.name)
        out.append(FolderCandidate(
            folder=entry.name,
            suggested=entry.name if valid else sanitise_name(entry.name),
            valid=valid,
            existing=entry.name in registered,
            note_paths=notes,
        ))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest test_folder_import.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add omni_capture/folder_import.py omni_capture/test_folder_import.py
git commit -F <message-file>
```

---

### Task 2: The two routes

**Files:**
- Modify: `omni_capture/vault_admin.py` (add after `apply_tidy_endpoint`, `:495-504`)
- Test: `omni_capture/test_folder_import_routes.py`

**Interfaces:**
- Consumes: `folder_import.plan_import`, `folder_import.tag_line_insert`, `note_model.serialize_note`, `note_editor._reindex`, `project_registry.update`
- Produces: `GET /vault/folder-import/preview` → `{"folders": [{"folder", "suggested", "valid", "existing", "count"}], "count": <total notes>}` · `POST /vault/folder-import/apply` with body `{"folders": [{"folder": str, "name": str}]}` → `{"ok": True, "tagged": int, "registered": [str], "skipped": [{"folder", "reason"}]}`

- [ ] **Step 1: Write the failing tests**

```python
# omni_capture/test_folder_import_routes.py
from fastapi.testclient import TestClient


def test_preview_lists_candidate_folders_with_counts(client, vault):
    (vault / "Work").mkdir()
    (vault / "Work" / "a.md").write_text("---\nid: 1\n---\n# A\n", encoding="utf-8")
    (vault / "My Notes").mkdir()
    (vault / "My Notes" / "b.md").write_text("---\nid: 2\n---\n# B\n", encoding="utf-8")

    body = client.get("/vault/folder-import/preview").json()

    assert body["count"] == 2
    by_folder = {f["folder"]: f for f in body["folders"]}
    assert by_folder["Work"]["valid"] is True and by_folder["Work"]["count"] == 1
    assert by_folder["My Notes"]["valid"] is False
    assert by_folder["My Notes"]["suggested"] == "My-Notes"


def test_apply_writes_the_tag_the_registry_and_the_derived_cache(client, vault):
    (vault / "Work").mkdir()
    note = vault / "Work" / "a.md"
    note.write_text("---\nid: 1\nproject: [-]\n---\n# A\n\nprose\n", encoding="utf-8")

    res = client.post("/vault/folder-import/apply",
                      json={"folders": [{"folder": "Work", "name": "Work"}]}).json()

    text = note.read_text(encoding="utf-8")
    assert res["tagged"] == 1 and res["registered"] == ["Work"]
    assert "# A\n#project@Work\n" in text
    assert "project: [Work]" in text          # derived cache recomputed, not left stale
    assert "prose\n" in text                   # every other body byte survives


def test_apply_rejects_an_invalid_name_without_touching_the_folder(client, vault):
    (vault / "My Notes").mkdir()
    note = vault / "My Notes" / "b.md"
    before = "---\nid: 2\n---\n# B\n"
    note.write_text(before, encoding="utf-8")

    res = client.post("/vault/folder-import/apply",
                      json={"folders": [{"folder": "My Notes", "name": "My Notes"}]}).json()

    assert res["tagged"] == 0
    assert res["skipped"] == [{"folder": "My Notes", "reason": "invalid-name"}]
    assert note.read_text(encoding="utf-8") == before


def test_apply_is_idempotent_and_never_double_tags(client, vault):
    (vault / "Work").mkdir()
    note = vault / "Work" / "a.md"
    note.write_text("---\nid: 1\n---\n# A\n", encoding="utf-8")
    payload = {"folders": [{"folder": "Work", "name": "Work"}]}

    client.post("/vault/folder-import/apply", json=payload)
    first = note.read_text(encoding="utf-8")
    second_res = client.post("/vault/folder-import/apply", json=payload).json()

    assert second_res["tagged"] == 0
    assert note.read_text(encoding="utf-8") == first
```

Use the same `client` / `vault` fixture idiom the neighbouring `test_vault_admin`-style route tests already use in this repo (this repo has no `conftest.py`; copy the fixture construction from the existing route test file that drives the real FastAPI app).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest test_folder_import_routes.py -q`
Expected: FAIL — 404 from both routes.

- [ ] **Step 3: Implement the routes**

```python
class FolderImportSelection(BaseModel):
    folder: str
    name: str


class FolderImportRequest(BaseModel):
    folders: list[FolderImportSelection]


@router.get("/vault/folder-import/preview")
async def folder_import_preview_endpoint():
    """FR-23 Option C: every top-level folder that could become a project, with the
    number of untagged notes inside it. Read-only -- no registry write, no body byte
    touched. The GUI shows this as a per-folder checklist before anything is applied."""
    import folder_import
    root = _srv()._get_vault_root()
    reg = project_registry.load(root)
    plan = folder_import.plan_import(root, reg)
    return {
        "folders": [
            {"folder": c.folder, "suggested": c.suggested, "valid": c.valid,
             "existing": c.existing, "count": len(c.note_paths)}
            for c in plan
        ],
        "count": sum(len(c.note_paths) for c in plan),
    }


@router.post("/vault/folder-import/apply")
async def folder_import_apply_endpoint(req: FolderImportRequest):
    """FR-23 Option C: write `#project@<name>` into the notes of the folders the user
    ticked, and register each name.

    THE ONLY ROUTE IN THIS PRODUCT THAT EDITS A NOTE BODY OUTSIDE THE EDITOR. It runs
    only from an explicit per-folder confirmation and never as a side effect of anything
    else. Both writes are required, not one: `resolve_project` (project_registry.py:183)
    resolves a tag only when the registry also holds the name, so a tag alone would leave
    the note reading loose and the tidy pass would move it anyway.

    Files are NOT moved. This makes the folders legitimate; project_tidy stays the only
    code that re-paths a note."""
    import folder_import
    from note_editor import _reindex
    from note_model import parse_note, serialize_note

    root = _srv()._get_vault_root()
    plan = {c.folder: c for c in folder_import.plan_import(root, project_registry.load(root))}
    tagged, registered, skipped = 0, [], []

    for sel in req.folders:
        candidate = plan.get(sel.folder)
        if candidate is None:
            skipped.append({"folder": sel.folder, "reason": "not-a-candidate"})
            continue
        if not projects.is_valid_project_name(sel.name):
            skipped.append({"folder": sel.folder, "reason": "invalid-name"})
            continue

        project_registry.update(root, lambda r, n=sel.name: r["projects"].setdefault(
            n, {"created": _now_iso(), "modified": _now_iso()}))
        registered.append(sel.name)
        reg = project_registry.load(root)

        for path in candidate.note_paths:
            note = parse_note(path.read_text(encoding="utf-8"))
            note.body = folder_import.tag_line_insert(note.body, sel.name)
            # serialize_note recomputes the derived `project:` line from the NEW body via
            # resolve_project, so the cache can never disagree with the tag we just wrote.
            atomic_io.atomic_write_verbatim(path, serialize_note(note, reg))
            _reindex(root, path, "folder import")
            tagged += 1

    return {"ok": True, "tagged": tagged, "registered": registered, "skipped": skipped}
```

Read `note_model.py`'s actual `parse_note` / `serialize_note` signatures and `vault_admin.py`'s existing `_now_iso` / import style before writing this — match them exactly rather than the shapes sketched here, and correct this plan if they differ.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest test_folder_import_routes.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Run the whole Python gate**

Run: `python -m pytest -q`
Expected: `1312 passed` + the 10 new tests, 4 skipped, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/vault_admin.py omni_capture/test_folder_import_routes.py
git commit -F <message-file>
```

---

### Task 3: The API client

**Files:**
- Modify: `gui/src/lib/api.ts` (beside the existing `getTidyPreview` / `applyTidy` pair)
- Test: `gui/src/lib/api.test.ts` if the neighbouring tidy calls are tested there; otherwise none — a typed fetch wrapper with no branching needs no test.

**Interfaces:**
- Produces: `type FolderImportCandidate = { folder: string; suggested: string; valid: boolean; existing: boolean; count: number }` · `getFolderImportPreview(): Promise<{ folders: FolderImportCandidate[]; count: number }>` · `applyFolderImport(folders: { folder: string; name: string }[]): Promise<{ ok: true; tagged: number; registered: string[]; skipped: { folder: string; reason: string }[] }>`

- [ ] **Step 1: Add the two calls, copying the exact idiom of `getTidyPreview`/`applyTidy` immediately above them** (same `X-Omni-Secret` header helper, same error handling, same naming).

- [ ] **Step 2: Typecheck**

Run from `gui/`: `npm run build`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add gui/src/lib/api.ts
git commit -F <message-file>
```

---

### Task 4: The per-folder checklist UI

**Files:**
- Modify: `gui/src/components/VaultManager.tsx` — the tidy strip at `:1196-1223` and its state at `:744-745`
- Create: `gui/src/lib/folderImport.ts` — pure selection/validation state
- Test: `gui/src/lib/folderImport.test.ts`

**Interfaces:**
- Consumes: `isValidProjectName` from `gui/src/lib/projectsView.ts`, `INVALID_NAME_MESSAGE` (already used at `ProjectsRail.tsx:182`)
- Produces: `type ImportRow = { folder: string; name: string; checked: boolean; valid: boolean; existing: boolean; count: number }` · `rowsFrom(candidates): ImportRow[]` · `toggle(rows, folder): ImportRow[]` · `rename(rows, folder, name): ImportRow[]` · `selection(rows): { folder: string; name: string }[]` · `selectedNoteCount(rows): number`

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from "vitest";
import { rowsFrom, rename, toggle, selection, selectedNoteCount } from "./folderImport";

const CANDS = [
  { folder: "Work", suggested: "Work", valid: true, existing: false, count: 12 },
  { folder: "My Notes", suggested: "My-Notes", valid: false, existing: false, count: 4 },
];

describe("folderImport rows", () => {
  it("checks valid folders by default and leaves ineligible ones unchecked", () => {
    const rows = rowsFrom(CANDS);
    expect(rows.map((r) => r.checked)).toEqual([true, false]);
    // the sanitised name is a PREFILL, never applied on its own
    expect(rows[1].name).toBe("My-Notes");
  });

  it("a renamed folder becomes selectable only once the name validates", () => {
    let rows = rowsFrom(CANDS);
    rows = rename(rows, "My Notes", "two words");
    expect(rows[1].valid).toBe(false);
    rows = toggle(rows, "My Notes");
    expect(rows[1].checked).toBe(false);        // cannot tick an invalid name
    rows = rename(rows, "My Notes", "My-Notes");
    rows = toggle(rows, "My Notes");
    expect(rows[1].checked).toBe(true);
  });

  it("selection omits unchecked rows and counts only what will be written", () => {
    const rows = rowsFrom(CANDS);
    expect(selection(rows)).toEqual([{ folder: "Work", name: "Work" }]);
    expect(selectedNoteCount(rows)).toBe(12);
  });

  it("an empty suggestion leaves the field blank rather than guessing", () => {
    const rows = rowsFrom([{ folder: "!!!", suggested: "", valid: false, existing: false, count: 2 }]);
    expect(rows[0].name).toBe("");
    expect(rows[0].valid).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run from `gui/`: `npx vitest run src/lib/folderImport.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `folderImport.ts`** — pure functions only, no fetch, no React. `valid` is recomputed by `isValidProjectName(name)` on every `rename`; `toggle` refuses to set `checked: true` when `valid` is false.

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run src/lib/folderImport.test.ts`
Expected: PASS, 4 tests.

- [ ] **Step 5: Wire the UI into the existing tidy strip**

In `VaultManager.tsx`, add a third action to the strip rendered at `:1203`, labelled **"Keep my folders — add the tags"**, shown only when `getFolderImportPreview()` reports `count > 0`. It opens a list below the strip: one row per folder with a checkbox, the folder name, and its note count; an ineligible folder renders instead with a text input prefilled from `suggested`, the `INVALID_NAME_MESSAGE` hint, and a disabled checkbox until the name validates. A folder whose name already exists as a project shows "joins existing project". The confirm button reads **"Add tags to N notes"** from `selectedNoteCount`. Match the strip's existing inline-style idiom exactly — grayscale `--surface-2` / `--border`, no new CSS file, no component-local `<style>` tag (FR-24: production CSP is `style-src 'self'`, so a `<style>` block contributes zero rules and fails silently).

- [ ] **Step 6: Run the gui gate**

Run from `gui/`: `npm test` then `npm run build` redirected to a file (a piped build reports the pipe's exit code, not the build's).
Expected: `788 passed` + the 4 new tests, build exit 0.

- [ ] **Step 7: Commit**

```bash
git add gui/src/lib/folderImport.ts gui/src/lib/folderImport.test.ts gui/src/components/VaultManager.tsx gui/src/lib/api.ts
git commit -F <message-file>
```

---

### Task 5: Live verification on a real vault

- [ ] **Step 1:** Build a fresh release exe: `npx tauri build --no-bundle` from `gui/`. Check the exe mtime against the clock before trusting it.
- [ ] **Step 2:** On a temp vault, create `Work/` (2 untagged notes), `My Notes/` (1), `_trash/` (1), `_loose/` (1), and one already-tagged note in `Work/`. Launch with the CDP env var set.
- [ ] **Step 3:** Trigger a tidy preview (delete a throwaway project), confirm the new action appears beside "Move the files" and "Not now".
- [ ] **Step 4:** Import `Work` only. Verify by reading the files: 2 notes tagged (not the third), `project: [Work]` recomputed, `.projects.toml` holds `Work`, `_trash/` and `_loose/` untouched, nothing moved.
- [ ] **Step 5:** Re-run the tidy preview. Expected: the `Work` notes are no longer pending a move — the import removed the reason they were being flattened. **That round trip is the whole feature; if it does not hold, the feature does not work.**

## Resolved decisions

1. **Phone-origin notes are included — USER-AFFIRMED 2026-08-04 (s140), mock `gui/mocks/2026-08-04-folder-import-provenance.html`.** The import tags every untagged note in a ticked folder regardless of `origin_device`, and the folder's row **discloses the count** (`"includes 3 notes written on your phone"`). Verified at source first: the provenance gate is inside the desktop's *enrichment* pass only (`mobile_sync_agent.py:1459-1466`, a `continue`), not a global write barrier, so nothing blocks or reverts this write. **The enrichment gate is NOT touched by this feature.**
   **The carve-out is narrow and its three preconditions are binding** — a surface may write into a note it did not author only when ALL of: (a) user-initiated per item, in this session, never scheduled or background; (b) the exact count and folders are shown at the moment of consent; (c) idempotent, so a re-run is a no-op and can never oscillate against the peer. No enrichment, sync or reconcile path can satisfy (a).
2. **Name collision.** A folder whose name already exists as a project merges into it (`existing: true` in the preview, "joins existing project" in the row). Decided, not open — but it is new behaviour the first mock did not draw.

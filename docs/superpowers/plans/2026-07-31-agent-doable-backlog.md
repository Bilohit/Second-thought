# Agent-Doable Backlog Milestone — Implementation Plan (s123)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Spec:** `Second Thought/docs/superpowers/specs/2026-07-31-agent-doable-backlog-design.md` — read it
first; it records the interview decisions and the three ledger rows that investigation proved wrong.

**Goal:** Close the agent-doable backlog: give the gui real component tests, make the enrichment retry
that `needs_llm_retry` has always promised actually happen, watchdog the panel geometry, and land the
phone/desktop ride-alongs.

**Architecture:** Five independent packages. Each is separately executable, separately committable, and
lands on a green gate on its own. Task IDs are **package-prefixed** (`P1-1`, `P2a-3`) rather than
globally numbered, so packages can be executed out of order or dropped without renumbering.

**Tech Stack:** Python 3.12 + pytest (desktop pipeline) · React 18 + Vite + Vitest + TypeScript strict
(gui) · Expo SDK 54 / RN 0.81 + Vitest (phone).

## Global Constraints

Every task's requirements implicitly include this section.

- **Gates.** desktop `python -m pytest -q` ≥ **1152** passed / 4 skipped / 0 failed · gui `npm test`
  ≥ **534** passed + `npm run build` clean · phone `npm test` ≥ **1816** passed / 6 skipped +
  `npm run typecheck` + `npm run typecheck:app` both clean. P1/P2 add tests, so their numbers must
  **rise**. Report actuals from the summary line — never the target.
- **`FUZZ=1` is not required** by any task here (nothing touches op-queue/sync/reconcile). If a task
  drifts into one of those surfaces, **stop and report** — the fuzz gate becomes mandatory.
- **Hand-duplication hard rule.** `main.py:run_pipeline()` and `server.py:_run_pipeline_blocking()` are
  duplicated **by design**. Changes land in both, mirrored by hand. Never collapse into a shared
  generator or `on_step` callback.
- **Vault categories are never hardcoded** (`models.py:build_capture_model` builds the enum live from
  folder names). No task may create a category folder.
- **Tauri geometry:** only `LogicalPosition`/`LogicalSize`; every monitor read goes through
  `gui/src/lib/monitor.ts`. Never write a physical coordinate into a `Logical*` call.
- **Pure logic lives in `lib/*.ts` (or a pure Python module) with a sibling test.** Stateful
  orchestration stays in components/hooks. TS strict + `noUnusedLocals` + `noUnusedParameters` are on —
  satisfy them, never `@ts-ignore`. No ESLint/Prettier exists in either repo; match surrounding style.
- **`ponytail:` comments** mark a deliberate ceiling with its upgrade path. Don't silently "fix" one.
- **Icons are inline SVG from the repo's icon module. Never emoji** — in app, mocks, or previews.
- **Commits:** conventional-commit subject, **no `Co-Authored-By` trailer** (repo convention). New
  commits over amends. Never `--no-verify`. Committing is pre-authorized when gates are green;
  **pushing needs the user's go each time.**
- **Review discipline:** the orchestrator reviews every subagent diff against the file, even when this
  plan carries literal code (s119 lesson). A task that cannot stay behavior-preserving is **stopped and
  reported, not bent** (s121).

**Two things to verify at execution start, not assume:**

1. `route_failed_llm`'s canonical import path — it is defined in `scratchpad.py` but `main.py` imports
   it `from storage_engine`. Confirm which module re-exports it before copying an import line.
2. `NoteEditor.tsx` contains a literal `\x00` (`Array.join("\x00")`, ~line 562). Git and grep call the
   file **binary** — that is not corruption. Read it with offset/limit, not grep.

---

# Package P1 — gui component testing + NoteEditor coverage

**Files:**
- Modify: `Second Thought/gui/package.json` (devDependencies)
- Create: `Second Thought/gui/src/components/NoteEditor.test.tsx`
- **Not touched:** `vite.config.ts` — no global `test.environment`. Opt in per file.

**Source facts every task below depends on (read during planning):**
- `NoteEditor` (`NoteEditor.tsx:230`) takes `{ open, path, onClose, onOpenExternal }` and returns
  `null` until `if (!everOpened || !path) return null;` (line 618). `everOpened` flips true in the
  mount effect (287-295), so tests must `await` the note load before querying.
- It imports `getNoteContent, saveNoteContent, searchCaptures, createReminder, getNoteHistory,
  getNoteHistoryRevision, getNoteConflict, resolveNoteConflict, addNoteAttachment, fetchAttachmentBlob,
  NoteConflictError` from `"../lib/api"` (3-21). Keep `NoteConflictError` **real** via `importOriginal`
  — `saveNoteContent`'s `.catch` does `err instanceof NoteConflictError`.
- `NoteContent` (`api.ts:872-881`): `{ path, title, category, status, tags, body, mtime, has_frontmatter }`.
- **No `@testing-library/jest-dom`** is being added, so no `toBeInTheDocument`/`toHaveAttribute`.
  Every assertion uses plain vitest `expect` against raw DOM (`el.getAttribute(...)`).
- Two elements render the note title (topbar `span` 748, `h1` 816) — use
  `getByRole("heading", { name })` to avoid "multiple elements" failures.

### Task P1-1: Install devDeps + mount smoke test

**Files:** Modify `gui/package.json` · Create `gui/src/components/NoteEditor.test.tsx`

**Interfaces:**
- Consumes: `NoteEditor` default export; `NoteContent` and the named exports of `lib/api.ts`.
- Produces: the shared harness (`vi.mock`, `noteFixture`, `renderEditor()`, `beforeEach`/`afterEach`)
  that every later P1 task appends `describe` blocks onto.

- [ ] **Step 1: Install the three devDependencies**

```bash
cd "Second Thought/gui"
npm install --save-dev @testing-library/react @testing-library/user-event happy-dom
```

Expected: three new `devDependencies` entries + a `package-lock.json` update. Do **not** add
`@testing-library/jest-dom` — every assertion here is written without it.

- [ ] **Step 2: Verify the install didn't touch vite.config.ts**

```bash
git diff --stat
```

Expected: only `package.json` and `package-lock.json`. If `vite.config.ts` shows a diff, something
generated a `test` block — revert it. Environment opt-in stays per-file.

- [ ] **Step 3: Write the failing mount smoke test + shared harness**

Create `Second Thought/gui/src/components/NoteEditor.test.tsx`:

```tsx
// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NoteEditor from "./NoteEditor";
import * as api from "../lib/api";
import type { NoteContent } from "../lib/api";

// ponytail: happy-dom ships no layout engine (getBoundingClientRect/offsetWidth
// all read 0 here) -- these tests assert DOM structure, ARIA attributes, and
// mock call sequencing ONLY. Every real pixel/geometry assertion (dropdown
// top:56 non-overlap, 640px no-overlap, hit-testability) stays CDP-only. Do
// not "upgrade" a geometry check into this file: it will silently pass against
// all-zero rects and prove nothing.
vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    getNoteContent: vi.fn(),
    saveNoteContent: vi.fn(),
    getNoteConflict: vi.fn(),
    getNoteHistory: vi.fn(),
    getNoteHistoryRevision: vi.fn(),
    resolveNoteConflict: vi.fn(),
    searchCaptures: vi.fn(),
    createReminder: vi.fn(),
    addNoteAttachment: vi.fn(),
    fetchAttachmentBlob: vi.fn(),
  };
});

const noteFixture: NoteContent = {
  path: "Test/note.md",
  title: "Test Note",
  category: "Test",
  status: null,
  tags: [],
  body: "hello world",
  mtime: 1000,
  has_frontmatter: true,
};

function renderEditor(path = "Test/note.md") {
  const onClose = vi.fn();
  const onOpenExternal = vi.fn();
  const utils = render(
    <NoteEditor open path={path} onClose={onClose} onOpenExternal={onOpenExternal} />,
  );
  return { ...utils, onClose, onOpenExternal };
}

beforeEach(() => {
  vi.mocked(api.getNoteContent).mockResolvedValue(noteFixture);
  vi.mocked(api.getNoteConflict).mockResolvedValue(null);
  vi.mocked(api.getNoteHistory).mockResolvedValue({ status: "ok", revisions: [] });
  vi.mocked(api.saveNoteContent).mockResolvedValue({ mtime: 2000 });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("NoteEditor — mount", () => {
  it("mounts without throwing and renders the dialog with the loaded note", async () => {
    renderEditor();
    expect(await screen.findByRole("heading", { name: "Test Note" })).toBeTruthy();
    const dialog = screen.getByRole("dialog", { name: "Note editor" });
    expect(dialog).toBeTruthy();
  });
});
```

This is the regression class the package targets: a TDZ `ReferenceError` (the s122 bug) throws
synchronously during render, which `render()` propagates out of the `it()` block. The test failing to
even reach `expect` **is** the signal — no special assertion needed.

- [ ] **Step 4: Run it**

```bash
npm test -- NoteEditor
```

Expected: 1 test file, 1 test, passing; total ≥ 535. Distinguish real failures: `Failed to load
"happy-dom"` → Step 1 didn't finish. `getByRole("dialog")` not found → the note never loaded; check the
mock resolves within `findByRole`'s 1s default.

- [ ] **Step 5: Full gate**

```bash
npm test
npm run build
```

Expected: no environment bleed — vitest logs the environment per file when mixed; confirm only
`NoteEditor.test.tsx` shows `happy-dom`. `npm run build` (`tsc && vite build`) clean. If `tsc` flags an
unused import (e.g. `fireEvent` before Task P1-2 uses it), drop it now and re-add where first used.

- [ ] **Step 6: Commit**

```bash
git add "Second Thought/gui/package.json" "Second Thought/gui/package-lock.json" "Second Thought/gui/src/components/NoteEditor.test.tsx"
git commit -m "test(gui): add component-testing infra + NoteEditor mount smoke test"
```

### Task P1-2: Escape precedence chain

**Files:** Modify `gui/src/components/NoteEditor.test.tsx`

**Interfaces:** Consumes the Escape effect (`NoteEditor.tsx:421-432`: `if (menuOpen) {…return;} if
(toolbarLocked) {…return;} if (pinnedDrawer) {…return;} onClose();`), the More button
(`aria-label="More"`, `aria-expanded={menuOpen}`, line 900), the lock button (`title={toolbarLocked ?
"Unlock toolbar" : "Lock toolbar open"}`, `aria-pressed`, 883-889), the Metadata menu row
(`role="menuitem"`, line 930) and the `METADATA` drawer heading (943).

- [ ] **Step 1: Write the 4 failing tests**

```tsx
describe("NoteEditor — Escape precedence", () => {
  it("closes the corner menu first, without unlocking or closing the drawer/editor", async () => {
    const user = userEvent.setup({ delay: null });
    const { onClose } = renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const moreBtn = screen.getByRole("button", { name: "More" });
    await user.click(moreBtn);
    expect(moreBtn.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(moreBtn.getAttribute("aria-expanded")).toBe("false");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("unlocks the toolbar next, when the menu is already closed", async () => {
    const user = userEvent.setup({ delay: null });
    const { onClose } = renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const lockBtn = screen.getByTitle("Lock toolbar open");
    await user.click(lockBtn);
    expect(screen.getByTitle("Unlock toolbar").getAttribute("aria-pressed")).toBe("true");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.getByTitle("Lock toolbar open").getAttribute("aria-pressed")).toBe("false");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes the pinned drawer next, when the menu is closed and the toolbar is unlocked", async () => {
    const user = userEvent.setup({ delay: null });
    const { onClose } = renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("menuitem", { name: "Metadata" }));
    expect(screen.queryByText("METADATA")).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.queryByText("METADATA")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes the editor last, when menu/lock/drawer are all already closed", async () => {
    const { onClose } = renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run**

```bash
npm test -- NoteEditor
```

Expected: 4/4 new pass, total ≥ 539. If the drawer test fails, check the `menuitem` `onClick` at line
930 — it calls `setMenuOpen(false); togglePin("meta")`.

- [ ] **Step 3: Full gate**

```bash
npm test
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add "Second Thought/gui/src/components/NoteEditor.test.tsx"
git commit -m "test(gui): cover NoteEditor Escape-key precedence chain"
```

### Task P1-3: toggleToolbarLock mode restore

**Files:** Modify `gui/src/components/NoteEditor.test.tsx`

**Interfaces:** Consumes `toggleToolbarLock` (`:406-418`) and the mode toggle
(`aria-label={mode === "view" ? "Switch to edit" : "Switch to view"}`, 758-765). Default `mode` is
`"edit"` (236).

- [ ] **Step 1: Write the 2 failing tests**

```tsx
describe("NoteEditor — toggleToolbarLock mode restore", () => {
  it("restores view mode on unlock when the lock was engaged from view mode", async () => {
    const user = userEvent.setup({ delay: null });
    renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });

    await user.click(screen.getByRole("button", { name: "Switch to view" }));
    expect(screen.getByRole("button", { name: "Switch to edit" })).toBeTruthy();

    await user.click(screen.getByTitle("Lock toolbar open"));
    // toggleToolbarLock: mode === "view" -> lockPriorModeRef = "view", forces mode back to "edit"
    expect(screen.getByRole("button", { name: "Switch to view" })).toBeTruthy();

    await user.click(screen.getByTitle("Unlock toolbar"));
    // unlock: lockPriorModeRef.current === "view" -> restores view mode
    expect(screen.getByRole("button", { name: "Switch to edit" })).toBeTruthy();
  });

  it("does not change mode on unlock when the lock was engaged from edit mode", async () => {
    const user = userEvent.setup({ delay: null });
    renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });

    await user.click(screen.getByTitle("Lock toolbar open"));
    // mode was already "edit" -> lockPriorModeRef = null, mode stays "edit"
    expect(screen.getByRole("button", { name: "Switch to view" })).toBeTruthy();

    await user.click(screen.getByTitle("Unlock toolbar"));
    // lockPriorModeRef.current !== "view" -> no restore
    expect(screen.getByRole("button", { name: "Switch to view" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run**

```bash
npm test -- NoteEditor
```

Expected: 2/2 pass. If the mid-assertion after locking fails, check `toggleToolbarLock`'s
`if (mode === "view") setMode("edit");` branch (line 412) — that's the mechanism under test.

- [ ] **Step 3: Full gate**

```bash
npm test
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add "Second Thought/gui/src/components/NoteEditor.test.tsx"
git commit -m "test(gui): cover toggleToolbarLock's view-mode restore asymmetry"
```

### Task P1-4: Menu resets on note switch + outside click

**Files:** Modify `gui/src/components/NoteEditor.test.tsx`

**Interfaces:** Consumes the outside-click effect (`:297-302`) and the load-effect reset
`setMenuOpen(false)` (line 314) that runs whenever `[open, path]` changes.

- [ ] **Step 1: Write the 2 failing tests**

```tsx
describe("NoteEditor — menu reset on note switch + outside click", () => {
  it("closes the menu when clicking outside it", async () => {
    const user = userEvent.setup({ delay: null });
    renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const moreBtn = screen.getByRole("button", { name: "More" });
    await user.click(moreBtn);
    expect(moreBtn.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(document.body);

    expect(moreBtn.getAttribute("aria-expanded")).toBe("false");
  });

  it("resets menuOpen when the editor switches to a different note", async () => {
    const user = userEvent.setup({ delay: null });
    const { rerender, onClose, onOpenExternal } = renderEditor("Test/note.md");
    await screen.findByRole("heading", { name: "Test Note" });
    await user.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("button", { name: "More" }).getAttribute("aria-expanded")).toBe("true");

    vi.mocked(api.getNoteContent).mockResolvedValue({
      ...noteFixture,
      path: "Test/other.md",
      title: "Other Note",
    });
    rerender(<NoteEditor open path="Test/other.md" onClose={onClose} onOpenExternal={onOpenExternal} />);
    await screen.findByRole("heading", { name: "Other Note" });

    expect(screen.getByRole("button", { name: "More" }).getAttribute("aria-expanded")).toBe("false");
  });
});
```

- [ ] **Step 2: Run**

```bash
npm test -- NoteEditor
```

Expected: 2/2 pass. Note: the effect at `:297-302` has **no** target/`contains` check — it closes on
any document click while `menuOpen`. That is asserted as-is, not endorsed as a design.

- [ ] **Step 3: Full gate**

```bash
npm test
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add "Second Thought/gui/src/components/NoteEditor.test.tsx"
git commit -m "test(gui): cover menu outside-click close + reset on note switch"
```

### Task P1-5: Peek chevron `data-hidden` + click

**Files:** Modify `gui/src/components/NoteEditor.test.tsx`

**Interfaces:** Consumes the peek-arrow button (`:848-858`): `className="ne-toolbar-btn ne-peek-arrow"`,
`data-hidden={toolbarLocked || toolbarOut}`, `aria-label="Show formatting toolbar"`,
`onClick={() => setToolbarPeeking(true)}`. `toolbarOut = toolbarPeeking || toolbarLocked` (244); both
start false, so initial `data-hidden` is `"false"`.

- [ ] **Step 1: Write the failing test**

```tsx
describe("NoteEditor — toolbar peek chevron", () => {
  it("is visible while the toolbar is closed, and hides itself once clicked", async () => {
    renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const chevron = screen.getByRole("button", { name: "Show formatting toolbar" });
    expect(chevron.className).toContain("ne-peek-arrow");
    expect(chevron.getAttribute("data-hidden")).toBe("false");

    fireEvent.click(chevron);

    // onClick only ever sets toolbarPeeking(true) -- there is no toggle-off on
    // this element. data-hidden flips true because toolbarOut is now true,
    // hiding the "come here" arrow once the toolbar it points at is already out.
    expect(chevron.getAttribute("data-hidden")).toBe("true");
  });
});
```

- [ ] **Step 2: Run**

```bash
npm test -- NoteEditor
```

Expected: 1/1 pass. React stringifies `data-*` booleans, hence the string-literal comparisons.

- [ ] **Step 3: Full gate**

```bash
npm test
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add "Second Thought/gui/src/components/NoteEditor.test.tsx"
git commit -m "test(gui): cover the toolbar peek chevron's data-hidden + click behavior"
```

### Task P1-6: Autosave debounce + backoff

**Files:** Modify `gui/src/components/NoteEditor.test.tsx`

**Interfaces:** Consumes the autosave effect (`:352-389`), `SAVE_BASE_DELAY_MS` (`lib/saveRetry.ts:12`,
`900`), `saveRetryDelayMs` (`saveRetry.ts:36-39`, `900 * 2^failureCount` capped at `60_000`), the
textarea (`aria-label="Note body (editable)"`, 826), and mocked `api.saveNoteContent`.

- [ ] **Step 1: Write the failing test**

```tsx
import { SAVE_BASE_DELAY_MS } from "../lib/saveRetry";

describe("NoteEditor — autosave debounce + backoff", () => {
  it("debounces the save, and backs off to 2x the base delay after a failure", async () => {
    renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const textarea = screen.getByLabelText("Note body (editable)") as HTMLTextAreaElement;

    vi.useFakeTimers();
    vi.mocked(api.saveNoteContent).mockRejectedValueOnce(new Error("network down"));

    fireEvent.change(textarea, { target: { value: "hello world, edited" } });
    expect(api.saveNoteContent).not.toHaveBeenCalled();

    // Base debounce fires once at 900ms and fails.
    await vi.advanceTimersByTimeAsync(SAVE_BASE_DELAY_MS);
    expect(api.saveNoteContent).toHaveBeenCalledTimes(1);

    // Backoff is 2x base from the failure -- one more base tick alone must NOT retry.
    await vi.advanceTimersByTimeAsync(SAVE_BASE_DELAY_MS);
    expect(api.saveNoteContent).toHaveBeenCalledTimes(1);

    // The remaining half elapses -> retry fires.
    await vi.advanceTimersByTimeAsync(SAVE_BASE_DELAY_MS);
    expect(api.saveNoteContent).toHaveBeenCalledTimes(2);
  });
});
```

`vi.useFakeTimers()` is called **after** the `await findByRole`, so the mount (whose animation effect
uses `requestAnimationFrame`, line 290) completes under real timers. The harness `afterEach` already
restores real timers.

- [ ] **Step 2: Run and verify the timing math**

```bash
npm test -- NoteEditor
```

If the third assertion is off by a tick, re-derive rather than tweaking the advance amounts:
`isSaveRetry` (`saveRetry.ts:28-30`) keys on `body === lastAttemptedBodyRef.current`, set right before
the failing call — so the 1800ms window starts at the ~900ms mark, landing call 2 at ~2700ms.

- [ ] **Step 3: Full gate**

```bash
npm test
npm run build
```

Expected: 11 new tests total across P1 (1+4+2+2+1+1). Recount from the actual summary line rather than
trusting this arithmetic.

- [ ] **Step 4: Commit**

```bash
git add "Second Thought/gui/src/components/NoteEditor.test.tsx"
git commit -m "test(gui): cover NoteEditor autosave debounce and failure backoff"
```

---

# Package P2a — enrichment retry engine (Python)

**Files:**
- Create: `omni_capture/retry_engine.py`, `omni_capture/test_retry_engine.py`
- Modify: `omni_capture/server.py` (`~1199-1219` extract `_ollama_reachable`; `~350` startup hook;
  `~1017-1027` post-capture hook; `~913-944` failure-log call; `~1713` manual route)
- Modify: `omni_capture/capture_log.py` (~59, add `log_capture_failure`)
- Modify: `omni_capture/main.py` (~184 import; ~384-403 failure branch)
- Modify: `omni_capture/test_server.py`, `omni_capture/test_route_failed_llm.py`

### Task P2a-1: Pure predicates — the safety gate

**Files:** Create `omni_capture/retry_engine.py`, `omni_capture/test_retry_engine.py`

**Interfaces:** Produces `is_retryable(text: str) -> bool` and `placeholder_matches(text: str) -> bool`.

- [ ] **Step 1: Write the failing test file**

Create `omni_capture/test_retry_engine.py`:

```python
"""
test_retry_engine.py
---------------------
P2a: the enrichment retry engine that needs_llm_retry has always promised but
never performed. No fixtures/conftest -- plain functions, pytest's tmp_path only.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from storage_engine import route_failed_llm
from retry_engine import is_retryable, placeholder_matches


def test_is_retryable_true_for_flagged_placeholder(tmp_path: Path):
    path = route_failed_llm(
        "raw text that must not be lost", "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )
    text = path.read_text(encoding="utf-8")
    assert is_retryable(text) is True


def test_is_retryable_false_without_the_flag():
    text = "---\ncreated: 2026-07-31T00:00:00\ntags: []\n---\n\nordinary note body\n"
    assert is_retryable(text) is False


def test_placeholder_matches_true_for_untouched_placeholder(tmp_path: Path):
    path = route_failed_llm(
        "raw text that must not be lost", "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )
    text = path.read_text(encoding="utf-8")
    assert placeholder_matches(text) is True


def test_placeholder_matches_false_for_hand_edited_body(tmp_path: Path):
    """SAFETY GATE negative test: a user who has started editing the note (even one
    extra line) must be skipped FOREVER -- needs_llm_retry: true alone is not proof
    the body is still the untouched placeholder."""
    path = route_failed_llm(
        "raw text that must not be lost", "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )
    text = path.read_text(encoding="utf-8")
    edited = text.replace(
        "raw text that must not be lost",
        "raw text that must not be lost\n\nActually let me add my own note here.",
    )
    assert is_retryable(edited) is True          # flag still set...
    assert placeholder_matches(edited) is False  # ...but body no longer matches


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
```

**Before running:** confirm `route_failed_llm` is importable from `storage_engine` (it is defined in
`scratchpad.py`; `main.py` imports it from `storage_engine`). Fix the import to the real path if needed.

- [ ] **Step 2: Run and see it fail**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q
```

Expected: `ModuleNotFoundError: No module named 'retry_engine'`.

- [ ] **Step 3: Create `retry_engine.py` with the two predicates**

```python
"""
retry_engine.py -- enrichment retry engine for needs_llm_retry scratchpad placeholders.

route_failed_llm() has always flagged a failed capture `needs_llm_retry: true` and
preserved the raw text -- but nothing has ever consumed that flag. retry_pending()
is the consumer: it re-runs the LLM decision stage over each flagged placeholder
still in _scratchpad and re-files it into a real category, like a fresh capture.

SAFETY GATE (this module's whole safety argument): a placeholder is repaired ONLY
when is_retryable() AND placeholder_matches() both hold. The flag alone is not proof
the body is untouched -- a user who started hand-editing the note (even one extra
line) fails placeholder_matches() and is skipped FOREVER.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Optional

from frontmatter import strip_frontmatter
from scratchpad import _extract_frontmatter_field, _scratchpad_path

# Mirrors route_failed_llm()'s exact body shape (scratchpad.py):
#   f"> [!warning] LLM enrichment failed\n> {reason}\n\n{enriched_text}\n"
_PLACEHOLDER_RE = re.compile(r"\A> \[!warning\] LLM enrichment failed\n> .*\n\n")

DEFAULT_MAX_ITEMS = 5


def is_retryable(text: str) -> bool:
    """True when a scratchpad note's frontmatter still carries needs_llm_retry: true."""
    return _extract_frontmatter_field(text, "needs_llm_retry") == "true"


def placeholder_matches(text: str) -> bool:
    """True when the body is still BYTE-FOR-BYTE route_failed_llm's placeholder shape
    (warning banner, reason line, blank line). Any hand edit breaks this match."""
    body = strip_frontmatter(text)
    return bool(_PLACEHOLDER_RE.match(body))
```

- [ ] **Step 4: Run and see it pass**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add omni_capture/retry_engine.py omni_capture/test_retry_engine.py
git commit -m "feat(retry): pure predicates for the needs_llm_retry safety gate"
```

### Task P2a-2: `_extract_original_text`

**Files:** Modify `omni_capture/retry_engine.py`, `omni_capture/test_retry_engine.py`

**Interfaces:** Produces `_extract_original_text(body: str) -> str` — returns the `enriched_text`
originally passed to `route_failed_llm`. Caller must have already confirmed `placeholder_matches`.

- [ ] **Step 1: Add the failing test**

```python
from retry_engine import _extract_original_text

def test_extract_original_text_returns_the_raw_capture(tmp_path: Path):
    path = route_failed_llm(
        "the raw captured text that must not be lost",
        "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )
    from frontmatter import strip_frontmatter
    body = strip_frontmatter(path.read_text(encoding="utf-8"))
    assert _extract_original_text(body) == "the raw captured text that must not be lost"
```

- [ ] **Step 2: Run and see it fail**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q -k extract_original_text
```

Expected: `ImportError: cannot import name '_extract_original_text'`.

- [ ] **Step 3: Implement — append to `retry_engine.py`**

```python
def _extract_original_text(body: str) -> str:
    """Strip route_failed_llm()'s warning-banner prefix off an already-verified
    placeholder body, returning the raw enriched_text it wrapped."""
    m = _PLACEHOLDER_RE.match(body)
    raw = body[m.end():]
    return raw[:-1] if raw.endswith("\n") else raw
```

- [ ] **Step 4: Run and see it pass**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add omni_capture/retry_engine.py omni_capture/test_retry_engine.py
git commit -m "feat(retry): extract raw capture text back out of the LLM-failure placeholder"
```

### Task P2a-3: Hoist `_ollama_reachable` — reuse the existing probe

**Files:** Modify `omni_capture/server.py` (~1199-1219), `omni_capture/test_server.py`

**Interfaces:** Produces module-level `_ollama_reachable(base_url: str, timeout: float = 1.5) -> bool`.
Same probe `/ollama/reachable` already performs — hoisted so `retry_engine` reuses the identical check
instead of a second, possibly-inconsistent one.

- [ ] **Step 1: Baseline the existing route test**

```bash
cd omni_capture && python -m pytest test_server.py -q -k ollama_reachable
```

Expected: `1 passed`.

- [ ] **Step 2: Add a test for the extracted function**

```python
def test_ollama_reachable_is_a_reusable_module_function():
    """server._ollama_reachable must be a plain, importable function -- retry_engine's
    precondition check calls this exact function rather than re-implementing the probe."""
    with _mock.patch("server.urlopen") as m:
        m.return_value.__enter__.return_value.status = 200
        assert server._ollama_reachable("http://localhost:11434") is True

    with _mock.patch("server.urlopen", side_effect=OSError("refused")):
        assert server._ollama_reachable("http://localhost:11434") is False
```

- [ ] **Step 3: Run and see it fail**

```bash
cd omni_capture && python -m pytest test_server.py -q -k reusable_module_function
```

Expected: `AttributeError: module 'server' has no attribute '_ollama_reachable'`.

- [ ] **Step 4: Extract the closure** — replace the `/ollama/reachable` route in `server.py`:

```python
def _ollama_reachable(base_url: str, timeout: float = 1.5) -> bool:
    """Fast Ollama /api/tags ping. Module-level so retry_engine.retry_pending()'s
    precondition check reuses this EXACT probe instead of a second, possibly-
    inconsistent health check (ISS-018's rationale still applies: /health's
    model_ok is set once at startup and goes stale)."""
    try:
        with urlopen(f"{base_url}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


@app.get("/ollama/reachable")
async def ollama_reachable(_: None = Depends(_require_secret)):
    """Fast, LIVE Ollama reachability probe for the pre-capture stall guard (ISS-018).

    Distinct from /health's `model_ok`: that flag is set once by the startup warmup
    and goes stale the moment Ollama stops afterward.
    """
    from llm_engine import _ollama_setting
    base_url = _ollama_setting("OLLAMA_BASE_URL", "base_url", "http://localhost:11434").rstrip("/")
    reachable = await asyncio.to_thread(_ollama_reachable, base_url)
    return {"reachable": reachable}
```

- [ ] **Step 5: Run both tests**

```bash
cd omni_capture && python -m pytest test_server.py -q -k "ollama_reachable"
```

Expected: `2 passed`.

- [ ] **Step 6: Full server suite, no regression**

```bash
cd omni_capture && python -m pytest test_server.py -q
```

Expected: prior count + 1.

- [ ] **Step 7: Commit**

```bash
git add omni_capture/server.py omni_capture/test_server.py
git commit -m "refactor(server): hoist ollama_reachable's ping into a module-level function"
```

### Task P2a-4: `retry_pending()` — precondition gate

**Files:** Modify `omni_capture/retry_engine.py`, `omni_capture/test_retry_engine.py`

**Interfaces:** Produces
`retry_pending(vault: Path, deps: Optional[dict] = None, scratchpad_folder: str = "_scratchpad",
max_items: int = DEFAULT_MAX_ITEMS) -> dict` returning
`{"attempted": int, "recovered": int, "skipped": int, "failed": int}`. `deps` override keys:
`is_ollama_reachable`, `run_llm_engine`, `write_to_vault`, `index_note`, `log_capture`.

- [ ] **Step 1: Add the failing tests**

```python
from retry_engine import retry_pending

def test_retry_pending_noop_when_scratchpad_missing(tmp_path: Path):
    summary = retry_pending(tmp_path, deps={"is_ollama_reachable": lambda: True})
    assert summary == {"attempted": 0, "recovered": 0, "skipped": 0, "failed": 0}


def test_retry_pending_skips_pass_when_no_categories_exist(tmp_path: Path):
    """Vault categories are never hardcoded, and the retry must never CREATE one --
    so with zero category folders there is nothing safe to retry into."""
    route_failed_llm(
        "raw text", "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )
    summary = retry_pending(tmp_path, deps={"is_ollama_reachable": lambda: True})
    assert summary["attempted"] == 0


def test_retry_pending_skips_pass_when_ollama_unreachable(tmp_path: Path):
    (tmp_path / "Tech_Notes").mkdir()
    route_failed_llm(
        "raw text", "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )
    summary = retry_pending(tmp_path, deps={"is_ollama_reachable": lambda: False})
    assert summary["attempted"] == 0
```

- [ ] **Step 2: Run and see it fail**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q -k retry_pending
```

Expected: `ImportError: cannot import name 'retry_pending'`.

- [ ] **Step 3: Implement the gate** — append to `retry_engine.py`:

```python
def _default_ollama_reachable() -> bool:
    """Reuses server.py's own probe (Task P2a-3) instead of a second health check."""
    from server import _ollama_reachable
    from llm_engine import _ollama_setting
    base_url = _ollama_setting("OLLAMA_BASE_URL", "base_url", "http://localhost:11434").rstrip("/")
    return _ollama_reachable(base_url)


def retry_pending(
    vault: Path,
    deps: Optional[dict] = None,
    scratchpad_folder: str = "_scratchpad",
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict:
    """Re-run the LLM decision stage for every needs_llm_retry placeholder still in
    the scratchpad, BOUNDED to `max_items` repairs per call (s104 precedent: an
    unbounded retry loop produced 44 failures in 3 minutes).

    Preconditions, checked once before touching any file:
      * >=1 real category folder exists -- run_llm_engine() hard-refuses an empty
        category_descriptions dict (llm_engine.py:322-326), and a retry must never
        CREATE a category folder to satisfy it.
      * Ollama is reachable.

    Failures are contained PER NOTE: one bad placeholder is logged and left exactly
    as it was (still needs_llm_retry: true) for the next call -- never aborts the pass.
    """
    deps = deps or {}
    is_ollama_reachable = deps.get("is_ollama_reachable", _default_ollama_reachable)

    summary = {"attempted": 0, "recovered": 0, "skipped": 0, "failed": 0}

    sp = _scratchpad_path(vault, scratchpad_folder)
    if not sp.exists():
        return summary

    from storage_engine import discover_categories
    if not discover_categories(vault, scratchpad_folder):
        print("[RetryEngine] no category folders yet -- skipping retry pass.", flush=True)
        return summary

    if not is_ollama_reachable():
        print("[RetryEngine] Ollama unreachable -- skipping retry pass.", flush=True)
        return summary

    return summary  # item loop lands in Task P2a-5
```

- [ ] **Step 4: Run and see it pass**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add omni_capture/retry_engine.py omni_capture/test_retry_engine.py
git commit -m "feat(retry): retry_pending() precondition gate (categories + Ollama reachable)"
```

### Task P2a-5: `retry_pending()` — repair path + safety-gate end-to-end test

**Files:** Modify `omni_capture/retry_engine.py`, `omni_capture/test_retry_engine.py`

**Interfaces consumed (real signatures):**

```python
storage_engine.build_category_descriptions(vault_root: Path, scratchpad_folder: str = "_scratchpad") -> Dict[str, str]
storage_engine.write_to_vault(output, source_url=None, vault_root=DEFAULT_VAULT_ROOT, scratchpad_folder="_scratchpad", enable_semantic_merge=False, embed_base_url=None, embed_model="nomic-embed-text", source_metadata=None, merge_info=None) -> Path
llm_engine.run_llm_engine(enriched, category_descriptions, existing_context=None, today=None, max_retries=None, temperature=None, scrutiny="balanced") -> CaptureOutput
vector_store.index_note(vault_root, note_path, content, base_url, embed_model=..., provisional=False) -> None
vector_store.remove_from_index(vault_root, note_path) -> None
index_writer.remove_capture_by_path(vault_root, abs_path) -> None
capture_log.log_capture(output, enriched, filepath: str, model: str) -> None
```

- [ ] **Step 1: Add the failing tests**

```python
from models import CaptureOutput
from config import Config

def _make_cfg(vault_root: Path) -> Config:
    cfg = Config()
    cfg.vault.root = vault_root
    cfg.vault.scratchpad_folder = "_scratchpad"
    cfg.vector.enabled = False
    return cfg


def test_retry_pending_repairs_a_matching_placeholder(tmp_path: Path):
    (tmp_path / "Tech_Notes").mkdir()
    placeholder_path = route_failed_llm(
        "the raw captured text that must not be lost",
        "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )

    good_output = CaptureOutput(
        category="Tech_Notes", suggested_filename="recovered-note",
        markdown_content="# Recovered\n\nrepaired body", rationale="ok",
        key_signals=["k"], confidence=0.9, requires_new_category=False,
    )

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={
                "is_ollama_reachable": lambda: True,
                "run_llm_engine": mock.Mock(return_value=good_output),
            },
        )

    assert summary == {"attempted": 1, "recovered": 1, "skipped": 0, "failed": 0}
    assert not placeholder_path.exists(), "the old placeholder must be removed after repair"
    recovered = tmp_path / "Tech_Notes" / "recovered-note.md"
    assert recovered.exists()
    text = recovered.read_text(encoding="utf-8")
    assert "needs_llm_retry" not in text
    assert "repaired body" in text


def test_retry_pending_never_touches_a_hand_edited_placeholder(tmp_path: Path):
    """SAFETY GATE end-to-end: a hand-edited body is skipped and left byte-identical,
    even though needs_llm_retry: true is still set."""
    (tmp_path / "Tech_Notes").mkdir()
    placeholder_path = route_failed_llm(
        "raw text", "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )
    original = placeholder_path.read_text(encoding="utf-8")
    edited = original + "\nmy own edit\n"
    placeholder_path.write_text(edited, encoding="utf-8")

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={
                "is_ollama_reachable": lambda: True,
                "run_llm_engine": mock.Mock(side_effect=AssertionError("must not be called")),
            },
        )

    assert summary == {"attempted": 0, "recovered": 0, "skipped": 1, "failed": 0}
    assert placeholder_path.exists()
    assert placeholder_path.read_text(encoding="utf-8") == edited, "hand-edited body must be byte-identical"
```

- [ ] **Step 2: Run and see the repair test fail**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q -k "repairs_a_matching or never_touches_a_hand_edited"
```

Expected: the repair test fails on the `summary ==` assertion.

- [ ] **Step 3: Implement the item loop** — replace `return summary  # item loop lands in Task P2a-5`:

```python
    from storage_engine import build_category_descriptions, write_to_vault as _default_write_to_vault
    from llm_engine import run_llm_engine as _default_run_llm_engine
    from vector_store import index_note as _default_index_note, remove_from_index
    from index_writer import remove_capture_by_path
    from capture_log import log_capture as _default_log_capture
    from config import get_config
    from models import EnrichedPayload

    run_llm_engine = deps.get("run_llm_engine", _default_run_llm_engine)
    write_to_vault = deps.get("write_to_vault", _default_write_to_vault)
    index_note = deps.get("index_note", _default_index_note)
    log_capture = deps.get("log_capture", _default_log_capture)

    cfg = get_config()
    category_descriptions = build_category_descriptions(vault, scratchpad_folder)

    for f in sorted(sp.iterdir()):
        if summary["attempted"] >= max_items:
            break
        if not (f.is_file() and f.suffix == ".md"):
            continue

        text = f.read_text(encoding="utf-8", errors="ignore")
        if not is_retryable(text):
            continue
        if not placeholder_matches(text):
            # Flag is set but the body has been hand-edited -- never touch it again.
            summary["skipped"] += 1
            continue

        summary["attempted"] += 1
        try:
            body = strip_frontmatter(text)
            source_url = _extract_frontmatter_field(text, "source")
            raw_text = _extract_original_text(body)

            enriched = EnrichedPayload(
                raw_input=raw_text,
                input_type="url" if source_url else "text",
                enriched_text=raw_text,
                source_url=source_url,
            )

            output = run_llm_engine(
                enriched,
                category_descriptions=category_descriptions,
                max_retries=cfg.capture.llm_max_retries,
                temperature=cfg.capture.llm_temperature,
                scrutiny=cfg.capture.llm_scrutiny,
            )

            written_path = write_to_vault(
                output,
                source_url=source_url,
                vault_root=vault,
                scratchpad_folder=scratchpad_folder,
                enable_semantic_merge=cfg.vector.enabled,
                embed_base_url=cfg.ollama.base_url,
                embed_model=cfg.vector.embed_model,
            )

            if cfg.vector.enabled:
                try:
                    note_text = Path(written_path).read_text(encoding="utf-8", errors="ignore")
                    index_note(vault, Path(written_path), note_text, cfg.ollama.base_url, cfg.vector.embed_model)
                except Exception as index_exc:
                    print(f"[RetryEngine] index write failed (note still saved): {index_exc}", file=sys.stderr)

            # write_to_vault picked a fresh path in the real category -- the OLD
            # placeholder is a different file and needs its own cleanup, mirroring
            # discard_scratchpad_item's cleanup (scratchpad.py).
            try:
                remove_from_index(vault, f)
                remove_capture_by_path(vault, f)
            except Exception as cleanup_exc:
                print(f"[RetryEngine] index cleanup on retry error: {cleanup_exc}", file=sys.stderr)
            f.unlink()

            log_capture(output, enriched, str(written_path), cfg.ollama.model)
            print(f"[RetryEngine] recovered {f.name} -> {written_path}", flush=True)
            summary["recovered"] += 1
        except Exception as exc:
            print(f"[RetryEngine] retry failed for {f.name}: {exc}", file=sys.stderr)
            summary["failed"] += 1

    return summary
```

- [ ] **Step 4: Run and see both pass**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q
```

Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add omni_capture/retry_engine.py omni_capture/test_retry_engine.py
git commit -m "feat(retry): retry_pending() repairs matching placeholders, skips hand-edited ones"
```

### Task P2a-6: Prove the pass is bounded and contains per-item failures

**Files:** Modify `omni_capture/test_retry_engine.py` (no production change expected)

- [ ] **Step 1: Add the tests**

```python
def test_retry_pending_is_bounded_per_run(tmp_path: Path):
    (tmp_path / "Tech_Notes").mkdir()
    for i in range(3):
        route_failed_llm(
            f"raw text {i}", "Ollama connection refused",
            vault_root=tmp_path, scratchpad_folder="_scratchpad",
        )

    good_output = CaptureOutput(
        category="Tech_Notes", suggested_filename="recovered",
        markdown_content="body", rationale="ok",
        key_signals=[], confidence=0.9, requires_new_category=False,
    )

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={
                "is_ollama_reachable": lambda: True,
                "run_llm_engine": mock.Mock(return_value=good_output),
            },
            max_items=2,
        )

    assert summary["attempted"] == 2, "must stop at max_items even with 3 eligible placeholders"
    remaining = [f for f in (tmp_path / "_scratchpad").glob("*.md")]
    assert len(remaining) == 1, "the un-attempted placeholder must be left for the next pass"


def test_retry_pending_contains_a_per_item_failure(tmp_path: Path):
    """One bad capture must not abort the pass -- the other eligible item in the
    same run still gets repaired."""
    (tmp_path / "Tech_Notes").mkdir()
    route_failed_llm(
        "bad raw text", "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )
    route_failed_llm(
        "good raw text", "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )

    good_output = CaptureOutput(
        category="Tech_Notes", suggested_filename="recovered",
        markdown_content="body", rationale="ok",
        key_signals=[], confidence=0.9, requires_new_category=False,
    )

    def _flaky_llm(enriched, **kwargs):
        if "bad" in enriched.enriched_text:
            raise RuntimeError("model still unavailable")
        return good_output

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={"is_ollama_reachable": lambda: True, "run_llm_engine": _flaky_llm},
        )

    assert summary == {"attempted": 2, "recovered": 1, "skipped": 0, "failed": 1}
    remaining = [f for f in (tmp_path / "_scratchpad").glob("*.md")]
    assert len(remaining) == 1, "the failed item stays in place, still needs_llm_retry: true"
    assert is_retryable(remaining[0].read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run**

```bash
cd omni_capture && python -m pytest test_retry_engine.py -q
```

Expected: `12 passed` with **no production change** — Task P2a-5's loop already has the `max_items`
break and the per-item `try/except`. If either fails, the bug is in that loop; fix the loop, do not add
new surface area.

- [ ] **Step 3: Commit**

```bash
git add omni_capture/test_retry_engine.py
git commit -m "test(retry): prove retry_pending() is bounded and contains per-item failures"
```

### Task P2a-7: `log_capture_failure()` — stop `--log` from lying

**Files:** Modify `omni_capture/capture_log.py` (~59), `omni_capture/main.py` (~184, ~384-403),
`omni_capture/server.py` (~918-933), `omni_capture/test_route_failed_llm.py`

**Interfaces:** Produces
`log_capture_failure(reason: str, enriched: EnrichedPayload, filepath: str, model: str, category: str) -> None`.

- [ ] **Step 1: Extend the existing failure-path tests**

Add to `test_run_pipeline_saves_capture_when_llm_fails`:

```python
    from index_writer import search
    logged = search("", tmp_path, limit=10)
    assert any(row["filepath"] == written for row in logged), \
        "an LLM failure must still upsert an audit-log row, not leave --log silent"
```

And the equivalent at the end of `test_server_pipeline_saves_capture_when_llm_fails`:

```python
    from index_writer import search
    logged = search("", tmp_path, limit=10)
    assert any(row["filepath"] == str(written_path) for row in logged)
```

- [ ] **Step 2: Run and see both fail**

```bash
cd omni_capture && python -m pytest test_route_failed_llm.py -q
```

Expected: 2 failures on the new `assert any(...)` lines.

- [ ] **Step 3: Add `log_capture_failure`** to `capture_log.py`, right after `log_capture`:

```python
def log_capture_failure(
    reason: str,
    enriched: EnrichedPayload,
    filepath: str,
    model: str,
    category: str,
) -> None:
    """Upsert a FAILED capture into captures.db, mirroring log_capture()'s success
    path. Only successes were logged before, so `--log`/`--stats` showed a clean
    history while captures silently degraded to the scratchpad. Fails silently,
    same as log_capture."""
    cfg = get_config()

    entry = {
        "timestamp":      datetime.now().isoformat(timespec="seconds"),
        "category":       category,
        "filename":       None,
        "filepath":       filepath,
        "input_type":     enriched.input_type,
        "source_url":     enriched.source_url,
        "model":          model,
        "confidence":     0.0,
        "tags":           [],
        "new_category":   None,
    }

    _log_or_warn("SQLite write (failure)", log_capture_db, entry, cfg.vault.root)
```

- [ ] **Step 4: Wire into `main.py`** — change the lazy import at ~184:

```python
    from capture_log       import log_capture, log_capture_failure
```

and in the `except Exception as exc:` branch, right after `written_path = route_failed_llm(...)`:

```python
            log_capture_failure(str(exc), enriched, str(written_path), cfg.ollama.model, "Unprocessed_Captures")
```

- [ ] **Step 5: Mirror BY HAND into `server.py`** (~918-933 — hand-duplication rule, do **not** extract
a shared helper). After `from storage_engine import route_failed_llm`:

```python
            from capture_log import log_capture_failure
```

and after the `written_path = route_failed_llm(...)` block, before `emit("step", step="write", status="done")`:

```python
            log_capture_failure(str(llm_exc), enriched, str(written_path), cfg.ollama.model, "Unprocessed_Captures")
```

- [ ] **Step 6: Run**

```bash
cd omni_capture && python -m pytest test_route_failed_llm.py -q
```

Expected: `3 passed`.

- [ ] **Step 7: Commit**

```bash
git add omni_capture/capture_log.py omni_capture/main.py omni_capture/server.py omni_capture/test_route_failed_llm.py
git commit -m "feat(capture-log): log_capture_failure() extends the audit trail to the LLM-failure path"
```

### Task P2a-8: Wire the three triggers

**Files:** Modify `omni_capture/server.py` (~350 startup, ~1017-1027 post-capture, ~1713 route),
`omni_capture/test_server.py`

**Scope note:** the post-capture trigger is **server.py-only**. `main.py` is a one-shot CLI that exits
right after its single capture — a background retry pass there buys nothing and would need its own
mirrored copy under the hand-duplication rule for no benefit.

- [ ] **Step 1: Add the failing route test**

```python
def test_retry_inbox_route_runs_a_bounded_pass(tmp_path: Path):
    cfg = Config()
    cfg.vault.root = tmp_path
    cfg.vault.scratchpad_folder = "_scratchpad"

    with mock.patch("server._get_vault_root", return_value=tmp_path), \
         mock.patch("retry_engine.retry_pending", return_value={"attempted": 0, "recovered": 0, "skipped": 0, "failed": 0}) as m:
        client = TestClient(server.app, headers=_AUTH)
        resp = client.post("/inbox/retry")

    assert resp.status_code == 200
    assert resp.json() == {"attempted": 0, "recovered": 0, "skipped": 0, "failed": 0}
    m.assert_called_once()
```

- [ ] **Step 2: Run and see it fail**

```bash
cd omni_capture && python -m pytest test_server.py -q -k retry_inbox_route
```

Expected: `404 Not Found`.

- [ ] **Step 3: Add the manual route** after the `/inbox/{note_id}` DELETE route:

```python
@app.post("/inbox/retry")
async def retry_inbox(_: None = Depends(_require_secret)):
    """Manually trigger a bounded retry pass over needs_llm_retry scratchpad
    placeholders -- the GUI's Retry action."""
    from retry_engine import retry_pending
    root = _get_vault_root()
    return await anyio.to_thread.run_sync(retry_pending, root)
```

- [ ] **Step 4: Run and see it pass**

```bash
cd omni_capture && python -m pytest test_server.py -q -k retry_inbox_route
```

Expected: `1 passed`.

- [ ] **Step 5: Add the startup hook** after `_startup_lan_listener`:

```python
@app.on_event("startup")
def _startup_retry_pending() -> None:
    """Recover any needs_llm_retry scratchpad placeholders left over from a previous
    run (e.g. Ollama was down). Bounded + per-item fail-soft -- see retry_engine.py."""
    try:
        from retry_engine import retry_pending
        from config import get_config
        summary = retry_pending(get_config().vault.root)
        if summary["attempted"]:
            print(f"[RetryEngine] startup pass: {summary}", flush=True)
    except Exception as exc:
        print(f"[RetryEngine] startup pass failed: {exc}", flush=True)
```

- [ ] **Step 6: Add the post-capture hook** — in `_run_pipeline_blocking`'s success path, after the
existing `with timer.stage("notify"):` block:

```python
        try:
            from retry_engine import retry_pending
            retry_pending(cfg.vault.root)
        except Exception as retry_exc:
            print(f"[server] {tag}post-capture retry pass failed: {retry_exc}", flush=True)
```

- [ ] **Step 7: Add the post-capture trigger test**

```python
def test_successful_capture_triggers_a_retry_pass():
    """After ANY successful capture, server.py must run a bounded retry pass over
    needs_llm_retry placeholders -- one of P2a's three triggers."""
    cfg = Config()
    cfg.vault.root = tempfile.mkdtemp()
    cfg.vault.scratchpad_folder = "_scratchpad"
    cfg.vector.enabled = False
    cfg.notifications.enabled = False

    good_output = CaptureOutput(
        category="Notes", suggested_filename="ok", markdown_content="body",
        rationale="ok", key_signals=[], confidence=0.9, requires_new_category=False,
    )

    class _FakeQueue:
        def put_nowait(self, item): pass

    class _FakeLoop:
        def call_soon_threadsafe(self, fn, *args): fn(*args)

    import config as config_module
    with mock.patch.object(config_module, "reload_config", lambda *a, **k: cfg), \
         mock.patch.object(llm_engine, "run_llm_engine", return_value=good_output), \
         mock.patch.object(server, "write_to_vault", side_effect=lambda output, **kw: (
             Path(cfg.vault.root, "Notes", "ok.md").parent.mkdir(parents=True, exist_ok=True) or
             Path(cfg.vault.root, "Notes", "ok.md").write_text("body", encoding="utf-8") or
             Path(cfg.vault.root, "Notes", "ok.md")
         )), \
         mock.patch("retry_engine.retry_pending") as m:
        server._run_pipeline_blocking("text", "some capture text", _FakeQueue(), _FakeLoop(), run_id="rp1")

    m.assert_called_once()
```

- [ ] **Step 8: Run**

```bash
cd omni_capture && python -m pytest test_server.py -q -k "retry_inbox_route or successful_capture_triggers_a_retry_pass"
```

Expected: `2 passed`.

- [ ] **Step 9: Commit**

```bash
git add omni_capture/server.py omni_capture/test_server.py
git commit -m "feat(server): wire retry_pending into startup, post-capture, and a manual route"
```

### Task P2a-9: Full desktop gate

**Files:** none (verification only)

- [ ] **Step 1: Run the gate**

```bash
cd omni_capture && python -m pytest -q
```

Expected: **0 failed**, 4 skipped, and a passed count strictly greater than the 1152 baseline
(≈ 1164+). Reconcile the delta against the actual summary line rather than trusting arithmetic.

- [ ] **Step 2: No commit** — P2a's commits landed per-task. This is a gate, not a commit point.

---

# Package P2b — retry UI + first-run empty state (gui)

**Design gate.** This package contains the milestone's only user-facing design work. Load
`impeccable-pbakaus`, `uiux-pro-max`, `taste-skill` and `animotion` **before** Task P2b-2. Void identity
binds every pixel: Geist Mono, 0-radius, grayscale accent, border-based elevation, semantic color only,
inline SVG from `PillMenu/icons.tsx`, **never emoji**.

**Files:**
- Modify: `Second Thought/gui/src/lib/api.ts` (add `retryInbox`)
- Modify: `Second Thought/gui/src/components/InboxPanel.tsx` (Retry action on failed rows)
- Create: `Second Thought/gui/mocks/2026-07-31-empty-vault-state.html` (mock board, not shipped code)
- Modify: the component the user's mock pick lands in (InboxPanel / VaultManager / dashboard banner)

### Task P2b-1: `retryInbox` API client + Retry action on the failed row

**Files:** Modify `gui/src/lib/api.ts`, `gui/src/components/InboxPanel.tsx`

**Interfaces:**
- Consumes: `POST /inbox/retry` from Task P2a-8, returning
  `{ attempted, recovered, skipped, failed }`; the existing `GET /inbox` row shape, whose failed rows
  already carry `failure: "enrichment unavailable"` (`scratchpad.py:185-186`).
- Produces: `retryInbox(): Promise<{attempted:number; recovered:number; skipped:number; failed:number}>`.

- [ ] **Step 1: Read the real shapes before writing anything**

```bash
cd "Second Thought/gui" && npm test -- InboxPanel
```

Read `src/lib/api.ts` (copy the exact fetch/secret-header helper the neighbouring calls use — do not
hand-roll a new `fetch`) and `src/components/InboxPanel.tsx` (find where a row's `failure` field is
rendered, and the existing per-row action buttons). Record the real names before Step 2; if `failure`
is not surfaced in the row type yet, add it to the type in this task.

- [ ] **Step 2: Add `retryInbox` to `api.ts`**, matching the surrounding call style exactly (same
auth-header helper, same error handling as the neighbouring `/inbox` calls).

- [ ] **Step 3: Add the Retry action to failed Inbox rows** in `InboxPanel.tsx` — visible only when the
row's `failure` field is set. On click: call `retryInbox()`, then refresh the inbox list. Disable the
button while in flight. Icon comes from `PillMenu/icons.tsx` (use `RefreshIcon` — it already exists);
never emoji.

- [ ] **Step 4: Gate**

```bash
npm test
npm run build
```

Expected: ≥ 534 + P1's additions, build clean.

- [ ] **Step 5: Commit**

```bash
git add "Second Thought/gui/src/lib/api.ts" "Second Thought/gui/src/components/InboxPanel.tsx"
git commit -m "feat(gui): retry action on enrichment-failed inbox rows"
```

### Task P2b-2: Empty-vault first-run state — mock board (USER GATE) — ❌ CANCELLED s124 (2026-08-01)

> **CANCELLED — do not execute, do not resurrect.** The user replaced folders/categories with
> **projects** (spec: `docs/superpowers/specs/2026-08-01-projects-rework-design.md`). Under projects a
> brand-new vault is no longer broken: "loose at vault root" is a valid destination, so nothing has to
> exist before a capture can be filed. This task's entire premise — prompt the user to create a first
> category folder — is the failure the rework deletes. The mock board built for it was discarded.
> The remaining content below is retained only as a record of what was cancelled.

**Files:** Create `Second Thought/gui/mocks/2026-07-31-empty-vault-state.html`

- [ ] **Step 1: Load the design skills** — `impeccable-pbakaus`, `uiux-pro-max`, `taste-skill`,
`animotion`. Not optional; this is UI work in a repo whose doctrine requires them.

- [ ] **Step 2: Build the mock board** — a single self-contained HTML file presenting **three placement
options** for the zero-category empty state, each rendered to Void identity:

  1. **Inbox-level** — the empty state lives where the captures are landing.
  2. **Vault Manager-level** — it lives where folders are actually created.
  3. **Dashboard-level first-run banner** — it lives where a first-run user looks first.

Each option shows: the copy (plain language, no jargon, no em-dashes), the call to action that creates
the first category folder, and the quiet state after one folder exists. Include the motion treatment
per `animotion` (respecting `prefers-reduced-motion`).

- [ ] **Step 3: Present the board to the user and get a pick.** Do **not** implement a placement before
the user picks — this is the design gate. Ask about placement and copy in the mock, not in prose.

- [ ] **Step 4: Commit the mock**

```bash
git add "Second Thought/gui/mocks/2026-07-31-empty-vault-state.html"
git commit -m "docs(gui): empty-vault first-run state mock options"
```

### Task P2b-3: Implement the picked empty state — ❌ CANCELLED s124 (2026-08-01)

> **CANCELLED, never built.** Depended on P2b-2's pick, which was cancelled with it. Under the projects
> rework there is no first-run empty state to build: a new vault files everything loose and works. The
> replacement work is the projects rework itself, not a re-scoped version of this task.

**Files:** the component the user's pick lands in (decided in P2b-2)

- [ ] **Step 1: Implement only the picked option.** Detection is "the vault has zero category folders"
— reuse the existing category source (`discover_categories` via whatever endpoint the gui already uses
for the vault's category list); do **not** add a new endpoint if one already reports categories.

- [ ] **Step 2: The action creates a user-named folder.** The user types the name. **Never** seed a
default category — the hard rule forbids hardcoded categories, and that rule is why OF-6 stayed open.

- [ ] **Step 3: Gate**

```bash
npm test
npm run build
```

- [ ] **Step 4: Live CDP QA** against a freshly built release exe (`npm run tauri -- build --no-bundle`;
check the exe's mtime first — it goes stale silently; `cargo` needs
`export PATH="$HOME/.cargo/bin:$PATH"` in Git Bash). Verify with an actual empty vault: the empty state
appears, creating a folder dismisses it, and a capture then files correctly instead of going to
`_scratchpad`. Use DOM `element.click()` — raw CDP mouse dispatch is unreliable on this WebView2 app.

- [ ] **Step 5: Commit**

```bash
git add <the picked component>
git commit -m "feat(gui): first-run empty-vault category prompt"
```

---

# Package P3 — panel-geometry watchdog

**Files:** Modify `Second Thought/gui/src/App.tsx` · Read-only reference: `gui/src/lib/compactPanel.ts`

**Root cause:** `targetWinW`/`targetWinH` (`App.tsx:1101-1102`) are computed unconditionally from
`panelOpenGrowsPillWindow` — the OS window resizes to panel dimensions regardless of whether geometry
computation succeeded. But `computeCapsulePanelGeometry`/`computeIslandMorphRects` run inside a
`try { … } catch (e) { logger.warn(...) }` (1917-1979) that can leave `capsulePanelGeom`/
`islandMorphGeom` `null` — either `getActiveWorkArea()` throws, or the reconcile token is superseded at
`if (token !== reconcileToken.current) return;` (1923) before the setters run. Meanwhile
`setPanelReady(true)` (2122) fires unconditionally on `openingPanel || panelModeSwitch` with no
geometry check. `PillOverlay.tsx:470` (`if (!capsuleTarget || !panelGeom) return capsuleMenu;`) and the
`islandTarget && islandGeom` guard (273/278) then silently fall back to the bare bar/pill — the window
sits at panel size while nothing panel-shaped renders. That is the s114 "blank-but-grown panel" class.

### Task P3-1: Add the panelGeom watchdog

**Files:** Modify `gui/src/App.tsx`

**Interfaces:** No new exports. Adds `PANEL_GEOM_WATCHDOG_MS` and one `useEffect` reading existing
state (`compactPanel`, `displayMode`, `capsulePanelGeom`, `islandMorphGeom`) and calling the existing
`closeCompactPanelRef.current()`.

- [ ] **Step 1: Add the ceiling constant** immediately after line 286
(`const RENDER_PILL_WATCHDOG_MS = 1000;`):

```ts
// panelGeom watchdog ceiling: targetWinW/targetWinH grow the OS window to panel
// size unconditionally, but capsulePanelGeom/islandMorphGeom are only set inside
// the panel-open try/catch below -- a thrown getActiveWorkArea() or a superseded
// reconcileToken can leave them null while panelReady still flips true
// (blank-but-grown panel, s114). Same ceiling as PANEL_READY_WATCHDOG_MS --
// exceeds any legitimate compute+commit lag.
const PANEL_GEOM_WATCHDOG_MS = 1000;
```

- [ ] **Step 2: Add the effect AFTER `closeCompactPanelRef` is wired** (App.tsx:738-744). It must go
after that ref assignment, not next to the `panelReady` watchdog at 537-541, which predates the ref.
Insert directly after `useEffect(() => { closeCompactPanelRef.current = closeCompactPanel; }, [closeCompactPanel]);`:

```ts
// s114 panelGeom watchdog: mirrors the panelReady watchdog's discipline -- only
// ever forces the SAFE state. There is no safe way to fabricate a geometry, so
// the safe state here is CLOSED (revert to the idle pill), never "assume the
// panel is ready" the way panelReady's own watchdog does. It never fights a
// legitimate open: the moment the active mode's geometry commits, the guard
// clause returns before arming the timer.
useEffect(() => {
  if (compactPanel === null) return;
  const geom = displayMode === "capsule" ? capsulePanelGeom : islandMorphGeom;
  if (geom !== null) return;
  const t = setTimeout(() => closeCompactPanelRef.current(), PANEL_GEOM_WATCHDOG_MS);
  return () => clearTimeout(t);
}, [compactPanel, displayMode, capsulePanelGeom, islandMorphGeom]);
```

- [ ] **Step 3: Typecheck**

```bash
cd "Second Thought/gui" && npm run build
```

Expected: clean — every symbol used is already in scope at that point in the component body.

- [ ] **Step 4: Unit gate (no new pure code, so no new lib test)**

```bash
cd "Second Thought/gui" && npm test
```

Expected: unchanged pass count. This task is App.tsx-only; there is no new pure geometry to unit-test.

- [ ] **Step 5: Live CDP QA — the only real verification**

Run `.\launch.ps1`, open the compact panel (capsule and minimal), then force the failure: either
breakpoint/throw inside `getActiveWorkArea`, or rapid-fire open/close to hit the
`token !== reconcileToken.current` supersede window. Confirm the window returns to idle pill size
within ~1s instead of sitting oversized with null geometry. **Measure** via
`getCurrentWindow().outerSize()` in the CDP console — rect math, not screenshots. State plainly in the
QA note that `npm test` does not exercise this path: it is a timing race in a live Tauri window with no
pure-function seam.

- [ ] **Step 6: Commit**

```bash
git -C "Second Thought" add gui/src/App.tsx
git -C "Second Thought" commit -m "fix(gui): add panelGeom watchdog to close a blank-but-grown compact panel (s114)"
```

---

# Package P4 — phone ride-alongs

**Files:**
- Create: `phone/src/lib/scalarStore.ts`, `phone/src/lib/scalarStore.test.ts`
- Modify: `phone/src/lib/chatModelConfig.ts`, `chatConfig.ts`, `semanticConfig.ts`, `syncDotConfig.ts`,
  `tagsViewModeStore.ts`, `phone/app.json`

**Scope note (carry into execution):** the factory was requested by the user, explicitly overriding the
orchestrator's ponytail objection to a shared abstraction across five working one-file modules. If the
factory needs to grow beyond the three cache modes below to fit a real call site — a sixth shape
appears, or a frozen signature can't be expressed through `get`/`set`/`load`/`getSync`/`reset` —
**stop and report** rather than expanding it. Do **not** touch `pinStore.ts`, `syncIgnoreStore.ts` or
`noteModeStore.ts` (collection-valued, out of scope).

### Task P4-1: Build the `scalarStore` factory

**Files:** Create `phone/src/lib/scalarStore.ts`, `phone/src/lib/scalarStore.test.ts`

**Interfaces:**

```ts
export interface ScalarStoreOptions<T> {
  key: string;
  decode: (raw: string | null) => T;
  encode: (value: T) => string;
  cache: "none" | "lazy" | "preload";
}
export interface ScalarStore<T> {
  get: () => Promise<T>;
  getSync: () => T;
  load: () => Promise<void>;
  set: (value: T) => Promise<void>;
  reset: () => void;
}
export function createAsyncScalarStore<T>(opts: ScalarStoreOptions<T>): ScalarStore<T>;
```

- [ ] **Step 1: Write the failing test**

Create `phone/src/lib/scalarStore.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from "vitest";

const store = new Map<string, string>();
vi.mock("@react-native-async-storage/async-storage", () => ({
  default: {
    setItem: vi.fn(async (k: string, v: string) => void store.set(k, v)),
    getItem: vi.fn(async (k: string) => store.get(k) ?? null),
  },
}));

import AsyncStorage from "@react-native-async-storage/async-storage";
import { createAsyncScalarStore } from "./scalarStore";

beforeEach(() => {
  store.clear();
  vi.clearAllMocks();
});

describe("cache: none", () => {
  it("reads storage on every get (no cache)", async () => {
    const s = createAsyncScalarStore<boolean>({
      key: "test.none", decode: (raw) => raw === "1", encode: (v) => (v ? "1" : "0"), cache: "none",
    });
    await s.get();
    await s.get();
    expect(AsyncStorage.getItem).toHaveBeenCalledTimes(2);
  });

  it("round-trips a set value", async () => {
    const s = createAsyncScalarStore<boolean>({
      key: "test.none2", decode: (raw) => raw === "1", encode: (v) => (v ? "1" : "0"), cache: "none",
    });
    await s.set(true);
    expect(await s.get()).toBe(true);
  });
});

describe("cache: lazy", () => {
  it("defaults true and reads storage only once", async () => {
    const s = createAsyncScalarStore<boolean>({
      key: "test.lazy", decode: (raw) => (raw === null ? true : raw === "1"), encode: (v) => (v ? "1" : "0"), cache: "lazy",
    });
    expect(await s.get()).toBe(true);
    expect(await s.get()).toBe(true);
    expect(AsyncStorage.getItem).toHaveBeenCalledTimes(1);
  });

  it("set updates the cache without a re-read", async () => {
    const s = createAsyncScalarStore<boolean>({
      key: "test.lazy2", decode: (raw) => (raw === null ? true : raw === "1"), encode: (v) => (v ? "1" : "0"), cache: "lazy",
    });
    await s.set(false);
    expect(await s.get()).toBe(false);
    expect(AsyncStorage.getItem).not.toHaveBeenCalled();
  });

  it("reset forces the next get to re-read storage", async () => {
    const s = createAsyncScalarStore<boolean>({
      key: "test.lazy3", decode: (raw) => (raw === null ? true : raw === "1"), encode: (v) => (v ? "1" : "0"), cache: "lazy",
    });
    await s.get();
    s.reset();
    await s.get();
    expect(AsyncStorage.getItem).toHaveBeenCalledTimes(2);
  });
});

describe("cache: preload", () => {
  it("getSync defaults to decode(null) before load", () => {
    const s = createAsyncScalarStore<boolean>({
      key: "test.preload", decode: (raw) => raw === "1", encode: (v) => (v ? "1" : "0"), cache: "preload",
    });
    expect(s.getSync()).toBe(false);
  });

  it("load hydrates the sync cache from storage", async () => {
    const s = createAsyncScalarStore<boolean>({
      key: "test.preload2", decode: (raw) => raw === "1", encode: (v) => (v ? "1" : "0"), cache: "preload",
    });
    await s.set(true);
    s.reset();
    expect(s.getSync()).toBe(false);
    await s.load();
    expect(s.getSync()).toBe(true);
  });
});
```

- [ ] **Step 2: Run and see it fail**

```bash
cd "Second Thought - Android App/phone" && npx vitest run src/lib/scalarStore.test.ts
```

Expected: `Cannot find module './scalarStore'`.

- [ ] **Step 3: Implement `scalarStore.ts`**

```ts
// Shared thin AsyncStorage seam for scalar (boolean/enum) persisted settings.
// Three cache disciplines cover every current call site: "none" (read storage
// every get -- chatModelConfig/chatConfig, toggled rarely, no stale reads),
// "lazy" (async-cached after first read -- semanticConfig), and "preload"
// (explicit load() hydrates a SYNC cache for render-time getters --
// syncDotConfig/tagsViewModeStore, which read every list frame and cannot
// await AsyncStorage). Each *Config.ts / *Store.ts keeps its frozen public
// API; this factory is the only shared internal.

import AsyncStorage from "@react-native-async-storage/async-storage";

export interface ScalarStoreOptions<T> {
  key: string;
  decode: (raw: string | null) => T;
  encode: (value: T) => string;
  cache: "none" | "lazy" | "preload";
}

export interface ScalarStore<T> {
  get: () => Promise<T>;
  getSync: () => T;
  load: () => Promise<void>;
  set: (value: T) => Promise<void>;
  reset: () => void;
}

export function createAsyncScalarStore<T>(opts: ScalarStoreOptions<T>): ScalarStore<T> {
  const { key, decode, encode, cache: mode } = opts;
  let cached: T | undefined = mode === "preload" ? decode(null) : undefined;

  async function get(): Promise<T> {
    if (mode === "none") return decode(await AsyncStorage.getItem(key));
    if (cached !== undefined) return cached;
    cached = decode(await AsyncStorage.getItem(key));
    return cached;
  }

  function getSync(): T {
    return cached as T; // preload mode only -- seeded above, never undefined
  }

  async function load(): Promise<void> {
    cached = decode(await AsyncStorage.getItem(key));
  }

  async function set(value: T): Promise<void> {
    cached = value;
    await AsyncStorage.setItem(key, encode(value));
  }

  function reset(): void {
    cached = mode === "preload" ? decode(null) : undefined;
  }

  return { get, getSync, load, set, reset };
}
```

- [ ] **Step 4: Run and see it pass**

```bash
cd "Second Thought - Android App/phone" && npx vitest run src/lib/scalarStore.test.ts
```

Expected: 7 tests pass.

- [ ] **Step 5: Typecheck**

```bash
cd "Second Thought - Android App/phone" && npm run typecheck
```

- [ ] **Step 6: Commit**

```bash
git -C "Second Thought - Android App" add phone/src/lib/scalarStore.ts phone/src/lib/scalarStore.test.ts
git -C "Second Thought - Android App" commit -m "feat(phone): add createAsyncScalarStore factory for scalar AsyncStorage seams"
```

### Task P4-2: Migrate `chatModelConfig` + `chatConfig` (cache: "none")

**Files:** Modify `phone/src/lib/chatModelConfig.ts`, `phone/src/lib/chatConfig.ts`

**Interfaces (frozen, unchanged):** `getChatModelEnabled(): Promise<boolean>`,
`setChatModelEnabled(on: boolean): Promise<void>`, `getContinuousEnabled(): Promise<boolean>`,
`setContinuousEnabled(on: boolean): Promise<void>`.

- [ ] **Step 1: Baseline the existing sibling tests**

```bash
cd "Second Thought - Android App/phone" && npx vitest run src/lib/chatModelConfig.test.ts src/lib/chatConfig.test.ts
```

Expected: 6 pass. This is the green baseline the refactor must not move.

- [ ] **Step 2: Rewrite `chatModelConfig.ts`** (keep the file header comment):

```ts
import { createAsyncScalarStore } from "./scalarStore";

const store = createAsyncScalarStore<boolean>({
  key: "st.chat.model.enabled",
  decode: (raw) => raw === "1",
  encode: (v) => (v ? "1" : "0"),
  cache: "none",
});

export const getChatModelEnabled = store.get;
export const setChatModelEnabled = store.set;
```

- [ ] **Step 3: Rewrite `chatConfig.ts`** (keep the file header comment):

```ts
import { createAsyncScalarStore } from "./scalarStore";

const store = createAsyncScalarStore<boolean>({
  key: "st.chat.continuous",
  decode: (raw) => raw === "1",
  encode: (v) => (v ? "1" : "0"),
  cache: "none",
});

export const getContinuousEnabled = store.get;
export const setContinuousEnabled = store.set;
```

**Verify the two storage keys against the originals before saving** — a changed key silently orphans
the user's existing setting.

- [ ] **Step 4: Run — the same tests, unedited, must still pass**

```bash
cd "Second Thought - Android App/phone" && npx vitest run src/lib/chatModelConfig.test.ts src/lib/chatConfig.test.ts
```

Expected: same 6 pass. The test files are **not** edited — that is what "frozen API" means.

- [ ] **Step 5: Typecheck both projects**

```bash
cd "Second Thought - Android App/phone" && npm run typecheck && npm run typecheck:app
```

- [ ] **Step 6: Commit**

```bash
git -C "Second Thought - Android App" add phone/src/lib/chatModelConfig.ts phone/src/lib/chatConfig.ts
git -C "Second Thought - Android App" commit -m "refactor(phone): route chatModelConfig/chatConfig through the scalarStore factory"
```

### Task P4-3: Migrate `semanticConfig` (cache: "lazy")

**Files:** Modify `phone/src/lib/semanticConfig.ts`

**Interfaces (frozen):** `getSemanticEnabled()`, `setSemanticEnabled(on)`,
`_resetSemanticConfigForTests()`.

- [ ] **Step 1: Baseline**

```bash
cd "Second Thought - Android App/phone" && npx vitest run src/lib/semanticConfig.test.ts
```

Expected: 4 pass, including the call-count assertion (`toHaveBeenCalledTimes(1)`) — the exact contract
"lazy" mode must reproduce.

- [ ] **Step 2: Rewrite `semanticConfig.ts`** (keep the header comment):

```ts
import { createAsyncScalarStore } from "./scalarStore";

const store = createAsyncScalarStore<boolean>({
  key: "st.semantic.enabled",
  decode: (raw) => (raw === null ? true : raw === "1"), // default ON
  encode: (v) => (v ? "1" : "0"),
  cache: "lazy",
});

export const getSemanticEnabled = store.get;
export const setSemanticEnabled = store.set;

// Test seam.
export const _resetSemanticConfigForTests = store.reset;
```

- [ ] **Step 3: Run**

```bash
cd "Second Thought - Android App/phone" && npx vitest run src/lib/semanticConfig.test.ts
```

Expected: same 4 pass — especially the "caches after the first read" test.

- [ ] **Step 4: Typecheck**

```bash
cd "Second Thought - Android App/phone" && npm run typecheck && npm run typecheck:app
```

- [ ] **Step 5: Commit**

```bash
git -C "Second Thought - Android App" add phone/src/lib/semanticConfig.ts
git -C "Second Thought - Android App" commit -m "refactor(phone): route semanticConfig through the scalarStore factory"
```

### Task P4-4: Migrate `syncDotConfig` + `tagsViewModeStore` (cache: "preload")

**Files:** Modify `phone/src/lib/syncDotConfig.ts`, `phone/src/lib/tagsViewModeStore.ts`

**Interfaces (frozen):** `loadSyncDotConfig()`, `getAlwaysShowSyncDot()`, `setAlwaysShowSyncDot(v)`,
`_resetSyncDotConfigForTests()`; `loadTagsViewMode()`, `getTagsViewMode()`, `setTagsViewMode(mode)`,
`_resetTagsViewModeStoreForTests()`, `type TagsViewMode = "list" | "tiles"`.

- [ ] **Step 1: Baseline**

```bash
cd "Second Thought - Android App/phone" && npx vitest run src/lib/syncDotConfig.test.ts src/lib/tagsViewModeStore.test.ts
```

Expected: 4 + 5 = 9 pass.

- [ ] **Step 2: Rewrite `syncDotConfig.ts`** (keep the header comment):

```ts
import { createAsyncScalarStore } from "./scalarStore";

const store = createAsyncScalarStore<boolean>({
  key: "syncDot.alwaysShow",
  decode: (raw) => raw === "1",
  encode: (v) => (v ? "1" : "0"),
  cache: "preload",
});

export const loadSyncDotConfig = store.load;
export const getAlwaysShowSyncDot = store.getSync;
export const setAlwaysShowSyncDot = store.set;

// Test seam.
export const _resetSyncDotConfigForTests = store.reset;
```

- [ ] **Step 3: Rewrite `tagsViewModeStore.ts`** (keep the header comment and the type export):

```ts
import { createAsyncScalarStore } from "./scalarStore";

export type TagsViewMode = "list" | "tiles";

const store = createAsyncScalarStore<TagsViewMode>({
  key: "tagsViewMode.mode",
  decode: (raw) => (raw === "tiles" ? "tiles" : "list"),
  encode: (v) => v,
  cache: "preload",
});

export const loadTagsViewMode = store.load;
export const getTagsViewMode = store.getSync;
export const setTagsViewMode = store.set;

// Test seam.
export const _resetTagsViewModeStoreForTests = store.reset;
```

**Verify both storage keys against the originals before saving.**

- [ ] **Step 4: Run**

```bash
cd "Second Thought - Android App/phone" && npx vitest run src/lib/syncDotConfig.test.ts src/lib/tagsViewModeStore.test.ts
```

Expected: same 9 pass — especially the "defaults before load" sync-getter tests, proving `"preload"`'s
`decode(null)` seed matches the originals.

- [ ] **Step 5: Typecheck**

```bash
cd "Second Thought - Android App/phone" && npm run typecheck && npm run typecheck:app
```

- [ ] **Step 6: Commit**

```bash
git -C "Second Thought - Android App" add phone/src/lib/syncDotConfig.ts phone/src/lib/tagsViewModeStore.ts
git -C "Second Thought - Android App" commit -m "refactor(phone): route syncDotConfig/tagsViewModeStore through the scalarStore factory"
```

### Task P4-5: Delete the dead `userInterfaceStyle` key + full phone gate

**Files:** Modify `phone/app.json`

- [ ] **Step 1: Confirm `expo-system-ui` is genuinely absent**

```bash
cd "Second Thought - Android App/phone" && grep -c expo-system-ui package.json
```

Expected: `0`. Absent means the SDK 54 native dark-mode hint (which routes through `expo-system-ui`)
is a no-op, and the app already forces dark theme in JS — so the key is dead config, not a missing
feature.

- [ ] **Step 2: Delete line 12** (`"userInterfaceStyle": "dark",`) from the `expo` object, keeping the
JSON valid (no trailing comma left dangling).

- [ ] **Step 3: Validate the JSON**

```bash
cd "Second Thought - Android App/phone" && node -e "JSON.parse(require('fs').readFileSync('app.json','utf8')); console.log('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Full phone gate**

```bash
cd "Second Thought - Android App/phone" && npm test
npm run typecheck
npm run typecheck:app
```

Expected: ≥ 1816 passed / 6 skipped (plus the 7 new `scalarStore` tests), both typechecks clean.

- [ ] **Step 5: Commit**

```bash
git -C "Second Thought - Android App" add phone/app.json
git -C "Second Thought - Android App" commit -m "chore(phone): delete dead userInterfaceStyle key (expo-system-ui not a dependency)"
```

---

# Package P5 — desktop ride-alongs + ledger truth

**Files:** Modify `omni_capture/notifier.py`, `omni_capture/test_notifier.py` · Regenerate
`graphify-out/` · Modify `BUILD-STATE/PROGRESS/CURRENT.md`, `BUILD-STATE/PROGRESS/DECISIONS.md`

### Task P5-1: Inline `_notify_windows`

**Files:** Modify `omni_capture/notifier.py`, `omni_capture/test_notifier.py`

**Interfaces:** `_notify_windows(full_title: str, message: str) -> None` is **deleted**; its one caller
in `send_notification` calls `_plyer_notify(full_title, message)` directly (`_plyer_notify` already
exists at `notifier.py:61-66`, unchanged).

- [ ] **Step 1: Baseline**

```bash
cd "Second Thought/omni_capture" && pytest test_notifier.py -q
```

Expected: 4 passed.

- [ ] **Step 2: Inline the call site.** Delete the 2-line function at `notifier.py:69-70`:

```python
def _notify_windows(full_title: str, message: str) -> None:
    _plyer_notify(full_title, message)
```

and change its caller at line 105 from `_notify_windows(full_title, message)` to
`_plyer_notify(full_title, message)`.

- [ ] **Step 3: Run and see the tests fail**

```bash
cd "Second Thought/omni_capture" && pytest test_notifier.py -q
```

Expected: 2 failures — `AttributeError: <module 'notifier'> does not have the attribute
'_notify_windows'` (monkeypatch.setattr raises when the target is missing).

- [ ] **Step 4: Update the two monkeypatch targets** in `test_notifier.py`:

line 31 → `monkeypatch.setattr(notifier, "_plyer_notify", fake_plyer_notify)`
line 43 → `monkeypatch.setattr(notifier, "_plyer_notify", lambda ft, m: calls.append(ft))`

- [ ] **Step 5: Run**

```bash
cd "Second Thought/omni_capture" && pytest test_notifier.py -q
```

Expected: 4 passed.

- [ ] **Step 6: Full gate**

```bash
cd "Second Thought/omni_capture" && pytest -q
```

Expected: ≥ 1152 passed / 4 skipped / 0 failed.

- [ ] **Step 7: Commit**

```bash
git -C "Second Thought" add omni_capture/notifier.py omni_capture/test_notifier.py
git -C "Second Thought" commit -m "refactor(notifier): inline _notify_windows into its one caller"
```

### Task P5-2: Refresh the graphify knowledge graph

**Files:** none hand-edited — `graphify-out/` is regenerated output.

Frozen at `graphify-out/2026-07-21/` (5231 nodes · 11733 edges · 229 communities), missing s84–s122.
There is **no bare `graphify` CLI on PATH** — invoke as `python -m graphify`; a BOM in
`.graphify_root`/`.graphify_python` breaks the bare command.

- [ ] **Step 1: Confirm the module is reachable**

```bash
cd "c:\Users\biloh\Claude\Projects\Second Thought Full Codebase" && python -m graphify --version
```

Expected: a version string, no `path not found`. If it fails, re-check the sidecars for a BOM — do
**not** fall back to the bare `graphify` command.

- [ ] **Step 2: Run the update**

```bash
cd "c:\Users\biloh\Claude\Projects\Second Thought Full Codebase" && python -m graphify --update
```

- [ ] **Step 3: Verify a new dated subfolder exists**

```bash
ls "graphify-out" | grep -E "^2026-"
```

Expected: a subfolder dated later than `2026-07-21`.

- [ ] **Step 4: Verify the counts moved**

```bash
head -10 "graphify-out/GRAPH_REPORT.md"
```

Expected: node/edge counts different from the frozen `5231 / 11733 / 229` baseline.

- [ ] **Step 5: Check tracking before committing**

```bash
git -C "c:\Users\biloh\Claude\Projects\Second Thought Full Codebase" check-ignore graphify-out
```

If ignored, **skip the commit** — regenerated cache, not source.

### Task P5-3: Ledger truth corrections (doc-only) — ✅ ALREADY DONE s123

**Files:** Modify `BUILD-STATE/PROGRESS/CURRENT.md`, `BUILD-STATE/PROGRESS/DECISIONS.md`

Facts land in the §-file that owns them — never in the baton.

> **This task was executed during the s123 planning session, not deferred to execution.** All three
> edits are already in the ledger — do NOT redo them. Steps are checked and kept here as the record of
> what changed and why. Step 4's commit is the only thing that may still be outstanding.

- [x] **Step 1: Correct the O-16 row** in `CURRENT.md` §4.6 — the "Stop waiting is DEAD" P1 is **fixed
at source** (`SyncWizard.tsx:186-193` single Cancel → `onSkipDrive`; `SyncPanel.tsx:234-247` 60s
`CONSENT_TIMEOUT_MS` auto-escape). Record that the s109 observation reflected a stale release exe, and
that the capsule-QA half of O-16 remains open.

- [ ] **Step 2: Re-anchor OF-6** in `CURRENT.md` §4.2 — from `models.py:100-104` to
`llm_engine.py:322-326` (the guard that actually fires), reclassified as **one of four triggers** of
the retry hole, and pointed at P2a as its fix.

- [ ] **Step 3: Add the s123 decision block** to `DECISIONS.md` §5 recording the interview calls:
full component-testing setup for gui · retry engine **plus** first-run prompt (not legibility-only) ·
ship path deferred entirely until the product is fully ready and tested · ride-along set including the
phone store factory over the orchestrator's ponytail objection.

- [ ] **Step 4: Commit the ledger**

```bash
git add BUILD-STATE/PROGRESS/CURRENT.md BUILD-STATE/PROGRESS/DECISIONS.md
git commit -m "docs(ledger): correct O-16 and OF-6 at source, record s123 decisions"
```

---

## Execution notes

**Suggested order:** P1 → P2a → P2b → P3 → P4 → P5. P4 is a different repo and can run in parallel
with any desktop package. P2b's mock round (P2b-2) can start while P1 is still building, since it
blocks on the user, not on code.

**Delegation:** one task per `cavecrew-builder` subagent at Sonnet tier; the orchestrator reviews every
diff against the file and runs every gate in the main thread. **Exception:** P2a-5's item loop rewrites
capture bodies — keep it on the orchestrator or a high-tier agent and review the safety gate line by
line.

**Stop conditions:** a task that cannot stay behavior-preserving · P4's factory needing a fourth cache
mode · any task drifting into op-queue/sync/reconcile (fuzz gate becomes mandatory) · P2b-3 before the
user has picked a mock.

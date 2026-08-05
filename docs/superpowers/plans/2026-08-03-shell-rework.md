# Desktop Shell Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap the pill menus at six items, merge Today into Inbox, add a Sticky-Notes-style quick pad
in place of Hide, and fix the full window's rail, note editor, and format toolbar.

**Architecture:** One shared `MenuTarget` array drives both the radial and capsule menus, so the
six-item cap is a single union edit that cascades through width math, fan layout, and panel geometry.
The quick pad is a sixth `CompactPanels/` component hosted by the existing `CompactShell`, so it
inherits capsule's clip-path extrusion and minimal's island morph with no new motion code. The full
window's note editor stops being a self-mounting absolute overlay and becomes an ordinary keyed view
inside the existing `<ErrorBoundary key={view}>` switch, which is what makes the left rail responsive
again.

**Tech Stack:** React 18 hooks-only, TypeScript strict, Vite 8, Tauri v2, TailwindCSS 3, Vitest.
FastAPI + pytest on the Python side. **No new dependency is added by this plan.**

**Spec:** `docs/superpowers/specs/2026-08-03-shell-rework-design.md`
**Decisions:** `BUILD-STATE/PROGRESS/DECISIONS.md` §5 s135
**Design board:** `gui/mocks/2026-08-03-shell-rework-decisions.html`

## Global Constraints

Every task's requirements implicitly include all of these.

- **Never a component-local `<style>` block.** Production CSP is `style-src 'self'`; `devCsp` allows
  inline. WebView2 emits **no** CSP-violation event, so the console stays clean while the feature is
  dead. Every `:hover` / `:focus-visible` / pseudo-class rule goes in `gui/src/index.css`.
- **Never weaken the production CSP** to make something work.
- **Icons are inline SVG** exported from `gui/src/components/PillMenu/icons.tsx`. Never emoji. No new
  one-off SVG copies when an export exists.
- **Geist Mono, 0-radius surfaces, border-based elevation, grayscale accent.** Green/yellow/red for
  semantic state only. Round is allowed only on focal/instrument affordances.
- **TS strict** with `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`. Satisfy
  them; never `// @ts-ignore` and never loosen `tsconfig.json`.
- **No linter or formatter exists** in either repo. Match surrounding file style exactly. Do not add one.
- **`ponytail:` comments mark deliberate ceilings.** Preserve existing ones; add one for any new
  shortcut, naming the ceiling and the upgrade path.
- **A note's body is sacred.** Only the user's editor writes below the frontmatter.
- **happy-dom has no layout engine.** No rect assertions in component tests — extract the math into a
  pure `lib/*.ts` function and test that.
- **Agents never commit and never run the full gate.** The orchestrator gates and commits scoped paths
  on a quiet tree between tasks. **Never `git add -A`** — agents share one worktree.
- **TS tasks are strictly serial.** One tsc/vitest project; concurrent editors poison each other's
  gates. Task 1 (Python) is the only task safe to run in parallel with a TS task.
- **Every agent is invited to correct this plan.** s134's agents corrected the brief in five of six
  dispatches and every correction was right. If a `file:line` anchor here does not match what you read,
  **stop and report** rather than editing the nearest similar thing.

---

## File Structure

| File | Responsibility after this plan |
|---|---|
| `omni_capture/today_view.py` | Owns the shared desktop note-origination write path; `create_daily_note` and the new generic create both call it |
| `omni_capture/server.py` | `POST /note` route; the corrected `POST /today/daily-note` docstring |
| `gui/src/lib/api.ts` | `createNote()` client |
| `gui/src/components/PillMenu/icons.tsx` | The `MenuTarget` union, labels, the ordered target array, `MenuIcon`, and a new `newnote` glyph |
| `gui/src/lib/fanLayout.ts` | Radial geometry with no `hide` special case |
| `gui/src/lib/compactPanel.ts` | `PANEL_W` re-derived from the new item count |
| `gui/src/lib/quickPad.ts` | **NEW** — pure quick-pad state machine (create-on-keystroke, discard, reopen) |
| `gui/src/components/CompactPanels/CompactQuickNote.tsx` | **NEW** — the pad surface, hosted by `CompactShell` |
| `gui/src/components/InboxPanel.tsx` | Gains the daily-note strip, full window only |
| `gui/src/components/FullWindow/FullWindow.tsx` | Rail order, `RailView` with `note`, the editor as a keyed view |
| `gui/src/components/NoteEditor.tsx` | A view not an overlay; consolidated top bar; clipped 19px toolbar |
| `gui/src/lib/tauri.ts` + `src-tauri/src/lib.rs` | Runtime always-on-top setter for the pin |
| `gui/src/components/FullWindow/TodayView.tsx` | **DELETED** |

---

## Task 1: `POST /note` — generic desktop note origination (Python)

**This is the only Python task. It may run in parallel with one TS task.**

**Files:**
- Modify: `omni_capture/today_view.py` — extract the create path used by `create_daily_note`
- Modify: `omni_capture/server.py:1870-1898` — new route + corrected docstring
- Test: `omni_capture/test_today_view.py` (existing) and/or `omni_capture/test_server.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `POST /note` accepting `{"title": str | null}` and returning the same JSON shape
  `POST /today/daily-note` returns (the object `TodayDailyNote` in `gui/src/lib/api.ts` is typed
  against). Task 2 writes the TS client against this shape.

- [ ] **Step 1: Read the existing origination path before writing anything**

Read `omni_capture/today_view.py:create_daily_note` in full and `omni_capture/server.py:1870-1898`.
Record the exact frontmatter keys it writes (`origin`, `id`, `created`, device field, anything else).
**The new endpoint must emit that identical set.** If it cannot — if `create_daily_note` bakes in
date-derived fields that a generic note has no analogue for — **STOP and report**, do not invent a
frontmatter shape. Note frontmatter is a contract owned by
`Second Thought - Android App/data-model-and-contracts.md`.

- [ ] **Step 2: Write the failing test**

Add to `omni_capture/test_server.py`. Adapt the client fixture and auth header to whatever the
surrounding tests in that file already use — **read a neighbouring test first and copy its shape.**

```python
def test_post_note_creates_note_with_daily_note_frontmatter_shape(tmp_vault_client):
    """POST /note must emit the SAME frontmatter keys as POST /today/daily-note.
    A second origination path with a different shape is a contract fork."""
    client = tmp_vault_client

    daily = client.post("/today/daily-note")
    assert daily.status_code == 200
    daily_path = Path(daily.json()["path"])
    daily_keys = set(read_frontmatter(daily_path).keys())

    made = client.post("/note", json={"title": "scratch thought"})
    assert made.status_code == 200
    note_path = Path(made.json()["path"])
    assert note_path.exists()

    assert set(read_frontmatter(note_path).keys()) == daily_keys
    assert read_frontmatter(note_path)["origin"] == "note"
    # generic notes do NOT go in Daily/
    assert note_path.parent != daily_path.parent


def test_post_note_twice_creates_two_distinct_notes(tmp_vault_client):
    """Unlike the daily note, /note is not find-or-create. Two calls, two files."""
    a = tmp_vault_client.post("/note", json={"title": "one"}).json()["path"]
    b = tmp_vault_client.post("/note", json={"title": "one"}).json()["path"]
    assert a != b
    assert Path(a).exists() and Path(b).exists()
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd "Second Thought/omni_capture" && python -m pytest test_server.py -k post_note -q
```
Expected: FAIL — 404 on `/note`, because the route does not exist yet.

- [ ] **Step 4: Implement**

Extract whatever `create_daily_note` uses to write a note into a reusable module-level helper in
`today_view.py` (e.g. `create_note(title: str | None, folder: Path | None = None) -> dict`), have
`create_daily_note` call it with the `Daily/` folder, and add the route in `server.py` next to the
existing one, guarded by `Depends(_require_secret)` exactly like every sibling route.
**Reuse, do not re-author, the write path** — a second implementation of note origination is the
defect this task exists to avoid.

- [ ] **Step 5: Correct the docstring that this task makes false**

`server.py:1872` currently reads *"The ONLY action by which the desktop originates a note"*. That
sentence documents a doctrine boundary and is now untrue. Rewrite it to name both routes and say what
distinguishes them (find-or-create + `Daily/` folder vs. always-new + vault root).

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd "Second Thought/omni_capture" && python -m pytest test_server.py -k post_note -q
```
Expected: PASS, 2 passed.

- [ ] **Step 7: Report to the orchestrator**

Report: the exact frontmatter key set, the new helper's signature, the route's request/response JSON,
and your new test count. **Do not commit and do not run the full pytest suite** — the orchestrator
gates on a quiet tree.

---

## Task 2: The six-item target set

**Files:**
- Modify: `gui/src/components/PillMenu/icons.tsx:11-24` (union, labels, arrays) + the `MenuIcon` switch
- Modify: `gui/src/lib/fanLayout.ts:176-184` (the `hide`-opposite-`search` pin)
- Modify: `gui/src/lib/compactPanel.ts:22` (`PANEL_W`)
- Modify: `gui/src/components/PillMenu/RadialMenu.tsx:23,53,57,138-148`
- Modify: `gui/src/components/PillMenu/CapsuleMenu.tsx:23,47-49,252-263`
- Modify: `gui/src/App.tsx:2304-2346` (`handleMenuSelect`, `handleMenuHide`)
- Modify: `gui/src/lib/api.ts` (add `createNote`)
- Test: `gui/src/lib/compactPanel.test.ts`, `gui/src/lib/fanLayout.test.ts`

**Interfaces:**
- Consumes: Task 1's `POST /note` request/response shape.
- Produces: `MenuTarget` = `"search" | "vault" | "settings" | "inbox" | "stats" | "newnote"` (no
  `today`, no `hide`), the ordered menu array, and `createNote(title?: string)` from `api.ts`.
  Tasks 3, 7 and 8 all depend on this union.

- [ ] **Step 1: Read before editing**

Read `icons.tsx:1-40`, `fanLayout.ts:130-200`, `compactPanel.ts:1-40`, and
`compactPanel.test.ts:15-30`. Confirm the arithmetic: `CAPSULE_ICON_W` × count + `CAPSULE_PAD_X` × 2.
At 7 items that is 7 × 44 + 24 = 332, matching today's `PANEL_W`. **If your read gives different
constants, stop and report** — the whole task's arithmetic depends on them.

- [ ] **Step 2: Update the equality-lock test FIRST, and make it derive rather than hardcode**

`compactPanel.test.ts:19` currently asserts `expect(PANEL_W).toBe(332)`. A hardcoded literal is what
makes this a tripwire instead of a guard. Replace it so the count drives the number:

```ts
import { ALL_TARGETS } from "../components/PillMenu/icons";
import { CAPSULE_ICON_W, CAPSULE_PAD_X } from "../components/PillMenu/CapsuleMenu";

it("panel width tracks the menu item count, not a frozen literal", () => {
  expect(PANEL_W).toBe(ALL_TARGETS.length * CAPSULE_ICON_W + CAPSULE_PAD_X * 2);
});

it("the compact panel is exactly as wide as the open capsule bar", () => {
  expect(PANEL_W).toBe(CAPSULE_OPEN_W);
});
```

If `CAPSULE_ICON_W` / `CAPSULE_PAD_X` are not exported from `CapsuleMenu.tsx`, export them. **Do not
delete the equality assertion** — the panel matching the bar's width is a deliberate visual lock.

- [ ] **Step 3: Run it to verify it fails**

```bash
cd "Second Thought/gui" && npx vitest run src/lib/compactPanel.test.ts
```
Expected: PASS at this point (332 still equals 7 × 44 + 24). This step exists to prove the derived
form is equivalent **before** the count changes, so a later failure means the count moved and nothing
else. Record the output.

- [ ] **Step 4: Change the union and the arrays**

In `icons.tsx`: remove `"today"` and `"hide"` from `MenuTarget`, remove their `MENU_LABELS` entries,
add `newnote: "New Note"`. The array becomes:

```ts
export const NAV_TARGETS: MenuTarget[] = ["search", "vault", "settings", "inbox", "stats", "newnote"];
export const ALL_TARGETS: MenuTarget[] = NAV_TARGETS;
```

`ALL_TARGETS` and `NAV_TARGETS` are now identical, because they only ever differed by `hide`. **Keep
both exports in this task** so the diff stays reviewable; collapsing to one name is Task 11's cleanup.
Add a plus glyph case to `MenuIcon`'s switch for `newnote` — `PlusIcon` already exists in this file,
reuse it rather than drawing a new path.

- [ ] **Step 5: Delete the `hide` special cases**

- `fanLayout.ts:176-184` — the pin placing `hide` diametrically opposite `search` has no subject any
  more. Remove it and let the six items distribute evenly. **Read the surrounding function first**;
  if removing the pin changes the angle of the other five spokes, that is expected and correct.
- `RadialMenu.tsx:138-148` — remove the `spoke-hide` class branch and the `onHide` call.
- `CapsuleMenu.tsx:253-263` — remove the `capsule-item-hide` branch.
- `App.tsx:2343-2346` — `handleMenuHide` loses its menu callers. **Do not delete the function**;
  Task 4 rebinds it to Escape. Leave it and its `onHide` prop drilling in place if TS allows;
  if `noUnusedLocals` complains, report it and Task 4 will be pulled forward.

- [ ] **Step 6: Route the new target in `handleMenuSelect`**

`App.tsx:2304-2314`'s `today` branch is deleted outright. Add a `newnote` branch that respects the
locked asymmetry: in full window it navigates to the editor view; in compact it opens the pad panel
like every other compact target. Task 8 owns the full-window half, so for now:

```ts
// newnote is deliberately asymmetric: full window opens the real editor (Task 8),
// compact opens the quick pad. See DECISIONS.md §5 s135.
if (target === "newnote" && displayMode === "full") {
  closePillMenu(); setExpanded(true); setView("note"); bumpNavToken(); return;
}
```

If `"note"` is not yet a valid `View` when you get here, add it to the `View` union at `App.tsx:218`
and to `lib/viewRouting.ts`'s maps. **`setDisplayMode("full")` must not appear anywhere in this
function when you are done** — that was Today's violation and it is not coming back.

- [ ] **Step 7: Add the API client**

In `gui/src/lib/api.ts`, next to `createDailyNote` (~line 856), add `createNote` against Task 1's
route. Copy the surrounding functions' exact shape — `authHeaders`, `assertOk`, the return type.
**Note `createDailyNote:857` contains a real bug** — backslashes in the template literal
(`${BASE}\today\daily-note`). Do not copy that; do not fix it in this task either, report it.

- [ ] **Step 8: Run the tests**

```bash
cd "Second Thought/gui" && npx vitest run src/lib/compactPanel.test.ts src/lib/fanLayout.test.ts
```
Expected: `compactPanel.test.ts` PASSES with `PANEL_W` now 288 (6 × 44 + 24). If it fails, you changed
the count without re-deriving `PANEL_W` — fix `compactPanel.ts:22`, do not edit the assertion.

`fanLayout.test.ts:4` uses its own hardcoded `SIX` fixture decoupled from the real `ALL_TARGETS`, so
it will not fail automatically. **Import the real array into it** so it actually guards the shipped
set from now on.

- [ ] **Step 9: Report**

Report: the final union, `PANEL_W`'s new value and its arithmetic, every file you touched, your test
deltas, and anything in this task's anchors that did not match what you read.

---

## Task 3: Merge Today into Inbox

**Files:**
- Delete: `gui/src/components/FullWindow/TodayView.tsx`
- Delete: `gui/src/components/FullWindow/TodayView.test.tsx`
- Modify: `gui/src/components/InboxPanel.tsx:70-95` (props) and `:514-632` (JSX)
- Modify: `gui/src/components/FullWindow/FullWindow.tsx:33-55` and `:355-360`
- Modify: `gui/src/lib/viewRouting.ts`
- Modify: `gui/src/App.tsx:218` (`View` union)
- Test: `gui/src/components/InboxPanel` — new sibling test for the strip's gating

**Interfaces:**
- Consumes: Task 2's `MenuTarget` union.
- Produces: `InboxPanel` renders a daily-note strip when `compactHeader === false`.

- [ ] **Step 1: Count what you are about to delete**

```bash
cd "Second Thought/gui" && npx vitest run src/components/FullWindow/TodayView.test.tsx
```
**Record the exact passing count.** The gui suite total will fall by that number, and an unitemised
falling test count is treated as a regression in this repo's ledger until proven otherwise. Report
the number.

- [ ] **Step 2: Confirm what actually has to move**

Read `TodayView.tsx:55-122` and `InboxPanel.tsx:592-628`. Verify for yourself that:
(a) Inbox's Reminders tab already renders reminders, from `listReminders()`, and shows a superset of
Today's overdue+due-today subset; (b) Today's scratchpad count comes off the same `list_scratchpad()`
source as Inbox's own header count. **If either is false, stop and report** — the merge's scope
depends on both being true. If both hold, **only the daily-note card moves. The other two cards are
deleted.**

- [ ] **Step 3: Write the failing test for the strip's gating**

The strip must render in full window and NOT in compact. That gate is `compactHeader`, per
`Second Thought/CLAUDE.md`'s hard rule — **never `embedded`**, because FullWindow passes `embedded`
too and overloading it silently changes every current caller.

```tsx
// @vitest-environment happy-dom
it("renders the daily-note strip in full window", async () => {
  render(<InboxPanel visible embedded compactHeader={false} onClose={() => {}} />);
  expect(await screen.findByRole("button", { name: /start today's note/i })).toBeTruthy();
});

it("hides the daily-note strip when hosted in a compact panel", async () => {
  render(<InboxPanel visible embedded compactHeader onClose={() => {}} onHeaderActionsChange={() => {}} />);
  await screen.findByText(/inbox/i);              // panel mounted
  expect(screen.queryByRole("button", { name: /start today's note/i })).toBeNull();
});
```

Mock `lib/api` the way the existing component tests in this repo do — **read `NoteEditor.test.tsx`
first and copy its mocking and `@vitest-environment` docblock convention exactly.**

- [ ] **Step 4: Run to verify failure**

```bash
cd "Second Thought/gui" && npx vitest run src/components/InboxPanel.test.tsx
```
Expected: FAIL — no such button.

- [ ] **Step 5: Implement the strip**

Add a single slim row **above** the `<div key={tab} className="seg-swap-panel">` at `InboxPanel.tsx:~530`
so it is visible in both tabs and survives tab switching. It calls `getToday()` for
`daily_note`/`date` and `createDailyNote(date)` on click, then `onOpenNote(note.path)`. Render it only
when `!compactHeader`. Style it from `index.css` tokens like its neighbours — **no local `<style>`
block, no new colours.**

- [ ] **Step 6: Delete TodayView and its route**

- Delete both TodayView files.
- `FullWindow.tsx:33-55` — drop `"today"` from `MainView`, `MAIN_VIEWS`, and `TITLES`.
- `FullWindow.tsx:~359` — remove the `<TodayView …>` render branch and its import.
- `lib/viewRouting.ts` — remove `"today"` from `LegacyView` and `RailDestination` and from
  `VIEW_TO_RAIL`.
- `App.tsx:218` — remove `"today"` from the `View` union.
- Grep `"today"` across `gui/src` and resolve every remaining hit. **`App.tsx`'s Tauri `listen`
  handlers have no `open-today` listener** (verified in recon), so there is nothing to unwire there.

- [ ] **Step 7: Run the tests**

```bash
cd "Second Thought/gui" && npx vitest run && npm run build
```
Expected: PASS. Build exit 0. Total = previous total − (Step 1's count) + 2.

- [ ] **Step 8: Report**

Report: Step 1's deleted count, your net delta with the arithmetic, and whether Step 2's two premises
held.

---

## Task 4: Esc-to-hide

**Files:**
- Modify: `gui/src/App.tsx` — keydown handling near the existing pill/compact key handlers
- Test: a pure predicate in `gui/src/lib/` with a sibling test

**Interfaces:**
- Consumes: `handleMenuHide` from `App.tsx:2343-2346`, left in place by Task 2.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Find the existing Escape handling and do not fight it**

Grep `"Escape"` across `gui/src`. `NoteEditor.tsx` has Escape precedence logic and **FR-09 is an open
finding there** (Escape drifts the background rail). Full window is explicitly out of scope for this
binding. Report every Escape handler you find before adding one.

- [ ] **Step 2: Write the failing test for the predicate**

Extract the decision, not the effect — that is what makes it testable without a layout engine.

```ts
// gui/src/lib/hideOnEscape.ts
export type EscapeContext = {
  displayMode: "minimal" | "capsule" | "full";
  menuOpen: boolean;
  compactPanel: string | null;
};

// gui/src/lib/hideOnEscape.test.ts
it("hides from the bare pill", () => {
  expect(shouldHideOnEscape({ displayMode: "minimal", menuOpen: false, compactPanel: null })).toBe(true);
});
it("closes the menu instead of hiding when the menu is open", () => {
  expect(shouldHideOnEscape({ displayMode: "capsule", menuOpen: true, compactPanel: null })).toBe(false);
});
it("closes the panel instead of hiding when a compact panel is open", () => {
  expect(shouldHideOnEscape({ displayMode: "capsule", menuOpen: false, compactPanel: "vault" })).toBe(false);
});
it("never hides from full window", () => {
  expect(shouldHideOnEscape({ displayMode: "full", menuOpen: false, compactPanel: null })).toBe(false);
});
```

- [ ] **Step 3: Run to verify failure**

```bash
cd "Second Thought/gui" && npx vitest run src/lib/hideOnEscape.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 4: Implement the predicate and wire it**

Escape unwinds one layer at a time: panel → menu → hide. Only the innermost-empty case hides.

- [ ] **Step 5: Run the tests**

```bash
cd "Second Thought/gui" && npx vitest run src/lib/hideOnEscape.test.ts && npm run build
```
Expected: PASS ×4, build exit 0.

---

## Task 5: Runtime always-on-top setter

**Files:**
- Modify: `gui/src-tauri/src/lib.rs` — a new `#[tauri::command]`
- Modify: `gui/src-tauri/capabilities/` — permit it if the manifest requires an entry
- Modify: `gui/src/lib/tauri.ts` — the JS wrapper, next to `setWindowNoactivate:92`

**Interfaces:**
- Produces: `setAlwaysOnTop(on: boolean): Promise<void>` from `lib/tauri.ts`. Task 7's pin calls it.

- [ ] **Step 1: Read the existing pattern**

Read `lib/tauri.ts:85-130` and find `setWindowNoactivate`'s Rust counterpart in `src-tauri/src/lib.rs`.
**Copy that command's exact shape** — error handling, naming, capability registration. Note
`tauri.conf.json:28` sets `"alwaysOnTop": true` statically; the runtime setter overrides it, it does
not replace it, so the window still starts on top.

- [ ] **Step 2: Implement the Rust command and the JS wrapper**

- [ ] **Step 3: Verify it compiles**

```bash
cd "Second Thought/gui/src-tauri" && cargo check
```
Expected: exit 0. **`cargo` may not be on PATH** — `launch.ps1` self-heals this; put cargo on PATH
first if `cargo check` is not found.

- [ ] **Step 4: Report**

There is no unit test for this — it is a native window call. It is covered by live QA success
criterion 6. Say so in your report rather than writing a test that only asserts the mock was called.

---

## Task 6: The quick pad state machine (pure)

**Files:**
- Create: `gui/src/lib/quickPad.ts`
- Create: `gui/src/lib/quickPad.test.ts`

**Interfaces:**
- Consumes: `createNote` from `api.ts` (Task 2) — **as an injected function, not an import**, so the
  state machine stays pure and testable.
- Produces: the reducer and types `CompactQuickNote.tsx` (Task 7) consumes.

- [ ] **Step 1: Write the failing tests**

These encode the locked behaviour: create on first keystroke, never on click; reopen to the last note;
discard throws away without touching the vault when nothing was written.

```ts
it("starts empty with no note and writes nothing", () => {
  const s = initialPadState(null);
  expect(s.noteId).toBeNull();
  expect(s.dirty).toBe(false);
});

it("does not create a note when the pad merely opens", () => {
  const created: string[] = [];
  reduce(initialPadState(null), { type: "open" }, { create: (t) => { created.push(t); } });
  expect(created).toEqual([]);
});

it("creates exactly one note on the first keystroke, not on the second", () => {
  const created: string[] = [];
  const deps = { create: (t: string) => { created.push(t); return "note-1"; } };
  let s = reduce(initialPadState(null), { type: "type", text: "r" }, deps);
  s = reduce(s, { type: "type", text: "ri" }, deps);
  s = reduce(s, { type: "type", text: "rin" }, deps);
  expect(created).toHaveLength(1);
  expect(s.noteId).toBe("note-1");
});

it("reopens to the last note made", () => {
  const s = initialPadState("note-7");
  expect(s.noteId).toBe("note-7");
});

it("plus clears the pad and arms a fresh create", () => {
  let s = { ...initialPadState("note-7"), text: "old", dirty: true };
  s = reduce(s, { type: "new" }, { create: () => "unused" });
  expect(s.text).toBe("");
  expect(s.noteId).toBeNull();
});

it("discarding an untouched pad deletes nothing", () => {
  const deleted: string[] = [];
  reduce(initialPadState(null), { type: "discard" }, { del: (id: string) => { deleted.push(id); } });
  expect(deleted).toEqual([]);
});

it("discarding a written pad deletes exactly that note", () => {
  const deleted: string[] = [];
  const s = { ...initialPadState("note-3"), text: "x", dirty: true };
  reduce(s, { type: "discard" }, { del: (id: string) => { deleted.push(id); } });
  expect(deleted).toEqual(["note-3"]);
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd "Second Thought/gui" && npx vitest run src/lib/quickPad.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Plain reducer, no side effects inside it — effects go through the injected `deps`. Persist only the
last note id, and mark the persistence as a ceiling:

```ts
// ponytail: last note id only, in localStorage. A real recents list if the pad ever grows tabs.
```

- [ ] **Step 4: Run to verify pass**

```bash
cd "Second Thought/gui" && npx vitest run src/lib/quickPad.test.ts
```
Expected: PASS ×7.

---

## Task 7: `CompactQuickNote` — the pad surface

**Files:**
- Create: `gui/src/components/CompactPanels/CompactQuickNote.tsx`
- Modify: `gui/src/components/PillOverlay.tsx:243-268` (`renderPanelBody` switch)
- Modify: `gui/src/index.css` (all pad hover/focus rules)

**Interfaces:**
- Consumes: `quickPad.ts` (Task 6), `setAlwaysOnTop` (Task 5), `createNote` (Task 2),
  `CompactShell`'s `headerActions` slot.

- [ ] **Step 1: Read `CompactShell` and one existing panel**

Read `CompactPanels/CompactShell.tsx:31-70` and `CompactPanels/CompactVault.tsx` end to end. The pad is
a sibling of these, not a new kind of thing. Note `showClose` is caller-supplied:
`PillOverlay.tsx:302` passes `true` for minimal (no bar to click off of), `:488` passes `false` for
capsule. **The pad changes none of that.**

- [ ] **Step 2: Build the B2 layout — exactly one band of chrome**

Everything lives in `CompactShell`'s `headerActions`: `[+] [B] [checklist]` left, `[pin] [discard]`
right. The body is the text area and nothing else. **Two format actions only** — bold and checklist.
No headings, no links, no italics, no code. The pin reflects state visually and calls
`setAlwaysOnTop`.

- [ ] **Step 3: Wire the panel**

`PillOverlay.tsx:243-268` — add `target === "newnote" ? <CompactQuickNote … /> : …` to the switch,
matching the surrounding cases' prop shape exactly.

- [ ] **Step 4: Put every pseudo-class rule in `index.css`**

**This is the step that killed FR-03 and then FR-24.** Both failures were a component-local `<style>`
block that works in dev and is silently dead in the release build. Add the pad's `:hover` /
`:focus-visible` / active-pin rules to `index.css` beside the other `.compact-panel` rules.

- [ ] **Step 5: Verify**

```bash
cd "Second Thought/gui" && npx vitest run && npm run build
```
Expected: PASS, build exit 0.

- [ ] **Step 6: Report the pad's rendered width**

Report what `PANEL_W` resolves to now (Task 2 made it 288) and your honest read on whether the pad is
usable at that width. **Do not change `PANEL_W` or unlock the equality assertion** — spec §11 open
question 1 says that is the user's call after live QA.

---

## Task 8: FullWindow — rail order and the note editor as a view

**The largest task. Read everything in Step 1 before touching anything.**

**Files:**
- Modify: `gui/src/components/FullWindow/FullWindow.tsx:33-55, 188, 197-283, 331-404`
- Modify: `gui/src/components/NoteEditor.tsx:231-296, 619-633`
- Create: `gui/src/components/FullWindow/FullWindow.test.tsx` — **this file has zero coverage today**

- [ ] **Step 1: Read the mount as it exists**

Read `FullWindow.tsx:188` (`editorPath` state), `:331-398` (the `<ErrorBoundary key={view}>` switch),
`:399-404` (the `<NoteEditor>` sibling), and `NoteEditor.tsx:231-296` (`everOpened`) and `:625-633`
(`wrapStyle`). Understand precisely why the rail appears dead: the rail buttons **are** mounted and
clickable and `setView` **does** fire, but `NoteEditor` never closes on a view change, and its
`position:absolute; inset:0; zIndex:20` overlay keeps covering the content column. **The bug is not a
disabled button.**

- [ ] **Step 2: Write the failing tests — the first tests this component has ever had**

```tsx
// @vitest-environment happy-dom
it("switches view when a rail tab is clicked while a note is open", async () => {
  render(<FullWindow {...baseProps} initialView="library" />);
  await openANote();
  fireEvent.click(screen.getByRole("button", { name: /history/i }));
  expect(screen.queryByRole("dialog", { name: /note editor/i })).toBeNull();
  expect(await screen.findByText(/by project/i)).toBeTruthy();
});

it("puts Settings last in the rail, below New Note", () => {
  render(<FullWindow {...baseProps} />);
  const rail = screen.getByTestId("fw-rail");
  const labels = within(rail).getAllByRole("button").map((b) => b.getAttribute("aria-label"));
  expect(labels.slice(-2)).toEqual(["New Note", "Settings"]);
});

it("has no Hide control", () => {
  render(<FullWindow {...baseProps} />);
  expect(screen.queryByRole("button", { name: /hide/i })).toBeNull();
});
```

Add `data-testid="fw-rail"` to the rail div and `aria-label` to every rail button if they are missing —
the buttons need accessible names regardless, per the a11y bar.

- [ ] **Step 3: Run to verify failure**

```bash
cd "Second Thought/gui" && npx vitest run src/components/FullWindow/FullWindow.test.tsx
```
Expected: FAIL.

- [ ] **Step 4: Rail order (D1)**

`FullWindow.tsx:197-283`: destinations stay one uninterrupted group; below the divider, **New Note
then Settings**, Settings bottom-most. Delete the Hide button at `:272-280`. `App.tsx:2678-2680`'s
`onHideToTray` prop loses its full-window consumer — remove the prop rather than leaving a dead one.

- [ ] **Step 5: Make the editor a view**

- Add `"note"` to `RailView`, with a `TITLES` entry.
- Move `<NoteEditor>` **inside** the `<ErrorBoundary key={view}>` switch as a `view === "note"` branch,
  rendered with `className="fw-view-panel"` like its siblings.
- In `NoteEditor.tsx`: delete `everOpened` and the `position:absolute` / `zIndex:20` overlay styles
  from `wrapStyle`. It is now an ordinary panel filling the content column.
- Keep the `[open, path]` load-reset effect firing on a new `path` — **it resets ~15 pieces of local
  state and dropping it silently is the regression this step risks.**
- Rail "New Note": sets `view="note"` with a null path (empty pad-less editor). Per the locked
  decision, **the note is created on first keystroke, not on click** — the editor must tolerate a null
  path until then.

- [ ] **Step 6: Run the tests**

```bash
cd "Second Thought/gui" && npx vitest run && npm run build
```
Expected: PASS, build exit 0.

- [ ] **Step 7: Report**

Report every prop you removed, whether the load-reset still fires, and your test delta.

---

## Task 9: Note editor top bar (C1)

**Files:**
- Modify: `gui/src/components/NoteEditor.tsx:744-770` (top bar) and `:899-935` (corner column)
- Modify: `gui/src/index.css` if the moved controls need hover/focus rules

- [ ] **Step 1: Read both blocks and their styles** — `topbarStyle:634-637`, `iconBtnStyle:638-642`,
  `menuBtnStyle:661-670`, `menuDropStyle:671-677`, `menuRowStyle:678-686`.

- [ ] **Step 2: Move, don't rebuild.** The five dropdown rows (Reminder / Connections / Outline /
  History / Metadata) and their `togglePin` handlers move unchanged. **Preserve the `ponytail:` comment
  at `:911-915`** explaining that Connections and Outline deliberately open the same `"conn"` drawer.

- [ ] **Step 3: Final order, right-aligned:** `[pencil/eye toggle] [open external] [⋯]`. Delete the
  `position:relative` corner column wrapper. `menuDropStyle`'s `top:56, right:0` anchors against the
  old corner position and must be re-anchored to the top bar.

- [ ] **Step 4: Verify**

```bash
cd "Second Thought/gui" && npx vitest run && npm run build
```

---

## Task 10: Format toolbar — clip it, then grow it (E)

**Files:**
- Modify: `gui/src/components/NoteEditor.tsx:701-715, 863-891`

- [ ] **Step 1: Name the constant that is currently written twice**

`46` appears at `:701` (`fmtEdgeStyle.width`) and `:712` (`translate(46px, -50%)`) with no shared
constant. **That duplication is the bug** — the toolbar's edge peeks because the two numbers describe
the same distance and nothing forces them to agree. Introduce one exported constant and use it in both.

- [ ] **Step 2: Clip the hidden toolbar**

Neither `fmtEdgeStyle` nor its parent `bodyRowStyle:652` sets `overflow: hidden`, so only `fw-shell`
at the very top of the tree clips anything. Add `overflow: hidden` to the edge box. Verify the peek
arrow is still reachable — **if clipping the box also hides the arrow that reveals the toolbar, stop
and report**; that would make the toolbar unreachable, which is worse than a visible edge.

- [ ] **Step 3: Grow the icons to 19px, the column to 52px**

`:863-891` — the format icons, `MicIcon`, and `CameraIcon` all pass `size={13}`. Change to `19`. The
lock button at `:891` is a raw inline SVG hardcoded `12×12` with no size prop — bring it up
proportionally so it does not become the odd one out. Set the shared constant from Step 1 to `52`.

- [ ] **Step 4: Verify**

```bash
cd "Second Thought/gui" && npx vitest run && npm run build
```
Expected: PASS, build exit 0. **The real verification is live QA criterion 9** — no unit test can see
a peeking edge.

---

## Task 11: Delete Daily rhythm, then clean up

**Files:**
- Modify: `gui/src/components/FullWindow/HistoryView.tsx:33-63`
- Modify: `gui/src/components/CompactPanels/CompactHistory.tsx:75-80`
- Modify: `gui/src/components/StatsPanel.tsx` (`DaySparkline` definition)
- Modify: `gui/src/components/FullWindow/FullWindow.tsx:52` (rail subtitle)
- Modify: `gui/src/components/FullWindow/HistoryView.test.tsx`

- [ ] **Step 1: Remove both "Daily rhythm" cards**, keeping "By project" in `HistoryView` and "Recent
  activity" in `CompactHistory`.

- [ ] **Step 2: Grep every importer of `DaySparkline` before deleting it.**

```bash
cd "Second Thought/gui" && npx rg "DaySparkline" src/
```
Delete it from `StatsPanel.tsx` **only if zero importers remain**. If `ProjectBar` sits next to it,
leave `ProjectBar` alone — "By project" still uses it.

- [ ] **Step 3: Fix the rail subtitle** at `FullWindow.tsx:52` — it currently reads
  `"daily rhythm · by project"` and half of that is about to be a lie.

- [ ] **Step 4: Update `HistoryView.test.tsx`**, which asserts the "Daily rhythm" text exists.
  **Do not delete the whole file** — its `_loose` → `"loose"` project-name assertion is unrelated and
  still valuable.

- [ ] **Step 5: Collapse `ALL_TARGETS` / `NAV_TARGETS`**

Task 2 left both exports identical. Count importers of each and keep the one with more; delete the
other and update its importers. **`ALL_TARGETS` is the name used in `compactPanel.test.ts`'s derived
assertion — if you delete it, update that test too.**

- [ ] **Step 6: Verify no trace remains**

```bash
cd "Second Thought/gui" && npx rg -i "daily rhythm|\"today\"|'today'|\"hide\"" src/
```
Expected: zero hits for "daily rhythm". Any surviving `today`/`hide` hit must be justified in your
report (a note's *date* is not a menu target; `HistoryView`'s day data is not "daily rhythm").

- [ ] **Step 7: Verify**

```bash
cd "Second Thought/gui" && npx vitest run && npm run build
```

---

## Task 12: Gates and live QA (orchestrator, not an agent)

- [ ] **Step 1: Gate on a quiet tree, twice.** No agent may be mid-write.

```bash
cd "Second Thought/gui" && npm test && npm run build
cd "Second Thought/omni_capture" && python -m pytest -q
```
Run the gui gate **at least twice**. s134 saw two unidentified flakes, both from a run started
immediately after a subagent finished in the same tree; ~20 quiet-tree runs were green. If a flake
reproduces, pipe `--reporter=verbose` **to a file** — the previous two captures were lost to
tail-only output.

- [ ] **Step 2: Itemise the test-count delta.** Additions need no argument; the fall from deleting
`TodayView.test.tsx` does. State: previous total − TodayView's count + new tests = new total.

- [ ] **Step 3: Build a real release exe and check its mtime.**

```bash
cd "Second Thought/gui" && npx tauri build --no-bundle
```
**Never `cargo build --release`** — that yields a dev-configured exe showing a WebView2 error page.
Put `cargo` on PATH first. Check the exe's mtime before trusting any QA result; it goes stale
silently. A stale instance can block the build and resist `taskkill` — use
`Invoke-CimMethod Win32_Process.Terminate`.

- [ ] **Step 4: Live QA — one Sonnet agent, low/medium, screenshots stay in the subagent.**

Driver: `scratchpad/flow-review/2026-08-02-1500/cdp.mjs`. Walk success criteria 1, 2, 4, 5, 6, 7, 8,
9, 11 from the spec, **in both themes**. `document.styleSheets` is the only reliable detector for a
dead stylesheet — the console will look clean either way.

- [ ] **Step 5: Commit scoped paths.** Gates green, staged diff reviewed, no `--no-verify`, no
`git add -A`. **Pushing needs a fresh go from the user.**

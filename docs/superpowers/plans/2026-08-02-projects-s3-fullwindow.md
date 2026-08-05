# Sub-project 3 — desktop full-window projects UI (PLAN)

**Spec:** `../specs/2026-08-02-projects-s3-fullwindow-design.md` (design gate CLOSED 2026-08-02).
**Board / visual source of truth:** `gui/mocks/2026-08-01-projects-fullwindow-v3.html`.
**Gates to beat:** gui **545** + `npm run build` exit 0 · desktop **1262 · 4 skipped** · phone **1834**/6skip.

## Standing rules for every task in this plan

1. **`gui/` ONLY. No Python.** Every route already exists (spec §2). `git diff --stat` must show `gui/`
   only. **A task that wants to edit a `.py` file is wrong — STOP and report, do not bend it.**
   **★ ONE exception was granted by the user and is already spent (s129):** `/search` publishes
   `modified` so the *recently edited* sort has a field to sort on (`DECISIONS.md` §5 s129 item 1).
   **The exception is closed — it does not license a second one.**
2. **The four design skills load before the first edit of any task that touches a UI surface** —
   `impeccable-pbakaus`, `taste-skill`, `uiux-pro-max`, `animotion`. **A delegated agent's prompt must
   carry this instruction explicitly**; a subagent does not inherit the orchestrator's loaded skills.
3. **No new easing curve or duration may be invented.** Spec §8 is the complete motion inventory.
   Anything not in it goes back to the user as a mock.
4. **Never render `_loose`.** The UI says *loose*.
5. **Derive a displayed count from the rows you hold** (spec §5.6). Never a count from one source beside
   a list from another.
6. **Pass an explicit `limit`** on every `/search` call (spec §5.5). The default is 25.
7. Component tests are **opt-in per file** via `// @vitest-environment happy-dom`. **Do not add a global
   `test.environment` to `vite.config.ts`** or the 534 Node-env tests move underneath us.
8. Orchestrator re-runs the gates between tasks, in the main thread, on a quiet tree.

---

## ★ TASK 0 — ANSWERED 2026-08-02. Both branches resolved; Task 1 is unblocked.

**Answer 1 — the tag question: OPTION A.** The old `TagsView` page is **deleted**; the projects rail's
Tags list is the only tags browser, and it is **flat** — slash-named tags (`work/urgent`) will render as
plain rows, not indented under a parent.

**The evidence that made this cheap, and it should be re-checked before anyone calls it a regression:**
the real vault (`C:\Users\biloh\second-thought-storage`) holds **24 `.md` files and exactly two tags,
`#intentions` and `#log`, neither containing a slash** (VERIFIED by grep, 2026-08-02). The two-level
grouping being removed therefore renders **nothing at all** on today's vault. **If the user ever adopts
slash-named tags, grouping is a small addition to the rail — not a rebuild.**

**Answer 2 — the stats panels: DROP THEM ENTIRELY.** `ProjectBar` and `DaySparkline`'s "By project" and
"Daily rhythm" panels in the vault section's right column are **removed, not relocated.**

> **★ BOTH OF THESE ARE AUTHORIZED FEATURE SUBTRACTIONS, given explicitly by the user on 2026-08-02.**
> They are the only deletions this sub-project may make. **Anything else that would remove a feature is
> STOPPED and reported, per the standing constraint.**
> **Deletion hygiene:** `ProjectBar` / `DaySparkline` are **exported from `StatsPanel.tsx` and may have
> other callers** — grep every importer before deleting either symbol, and delete only what becomes
> genuinely unreachable. Same for `TagsView.tsx` + `TagsView.test.ts` and the `tags` arm of
> `LibraryView`'s section switch, `FullWindow`'s topbar toggle, and any `RailView`/section type that
> names it. **A green gate proves neither that the new code ran nor that nothing else was deleted.**

### Original framing (kept for the reasoning, superseded by the answers above)

**The tag IA collides, and one branch silently subtracts a feature.**

Today `LibraryView.tsx` has three sections — `vault | tags | trash` — toggled from the FullWindow
topbar. `TagsView.tsx` (175 lines, plus `TagsView.test.ts`) renders a **two-level tag tree**: namespace
rows with indented children, `sys/` machine tags filtered out, and the legacy `project/` namespace
pinned as a separate list.

The approved board puts a **flat, single-level** tag list inside the projects screen's rail toggle.
Parent spec §6 makes that toggle the one control shared across all three shells, so the two cannot both
be the tags browser without duplicating tags in two places on the same screen.

**Three branches, and they produce different plans:**

- **A — rail Tags replaces the `tags` section.** Cleanest IA, matches the board and parent spec §6.
  **Cost: two-level namespace nesting is lost** unless it is rebuilt in the rail. That is a feature
  subtraction and needs the user's explicit word.
- **B — rail Tags replaces the section AND inherits nesting.** No subtraction. Costs a rail redesign the
  board does not cover, so it needs a mock round before code.
- **C — both survive.** No subtraction, no new design. Tags appear twice on one screen, which is the
  duplication the rework exists to remove.

**Also to confirm while deciding:** `TagsView`'s `isProjectNamespace` pinning treats `project/` as a tag
namespace. That is the **pre-rework** scheme — contract v3.1 uses the `#project@name` body tag — so that
branch is likely already dead code after S1. **Verify by grep before deleting anything;** do not assume.

**Recommendation: B**, with the nesting question mocked first. It is the only branch that both matches
the approved design and subtracts nothing. If the user wants speed, **A** is defensible *only* if they
say out loud that flat tags are acceptable.

---

## Task 1 — the pure modules, with their tests (no UI)

**Files:** new `gui/src/lib/projectsView.ts` + `projectsView.test.ts`.

Pure, side-effect-free, Node-env tests (no happy-dom needed):

- `sortNotes(rows, mode)` — the three arrangements, **stable**: original index is the tiebreak so equal
  timestamps never shuffle between cycles. Exports the label and the meta verb (`added` / `edited`) so
  the row's meta column reports the field actually sorted on.
- `displayProject(value)` — `_loose` → `loose`; everything else unchanged. **This is the sentinel
  guard**; one test asserts `_loose` never survives to a caller.
- `pageOf(total, page, size = 200)` — page count, slice bounds, and **`needsPager(total)` false below
  200** (spec §5.5.1). Tests pin 199 / 200 / 201.

**Verify:** `npm test` green, +N tests, and each function's failure mode has a case.

## Task 2 — the API layer

**File:** `gui/src/lib/api.ts` (extend; do not restructure).

Typed wrappers for the routes in spec §2: `listProjects`, `createProject`, `renameProject`,
`setProjectDescription`, `deleteProject`, `notesForProject`, `notesForTag`. `getTagTree` and
`searchCaptures` already exist — **reuse, do not duplicate.**

Every note-listing call **passes an explicit `limit`**. Sibling tests mock `fetch` and assert the URL,
including that the limit is present.

**Verify:** `npm test`, `npm run build`.

## Task 3 — tokens

**File:** `gui/src/index.css`.

Add `--ctl-face` / `--ctl-face-hover` for **both** themes (spec §4.4). Light-theme values are **not in
the board** — the board is dark-only — so derive them to hold the same relationship (control face
raised above the surface it sits on) and **check contrast at both**, per §4.4's measured floors.

**Verify:** `npm run build`; existing 545 unchanged (CSS only).

## Task 4 — the rail

Segmented toggle (the real `SegmentedToggle`, not a lookalike) · project tiles with counts and the
no-description warning · the loose tile spanning the row when alone · the suggestion **box** in the 8px
gutter with the §4.2 button geometry · New project welded to the rail foot.

**Shape depends on Task 0's answer.**

## Task 5 — the pane

Head (name, rename, delete, description editor with the honest one-line note and its empty variant) ·
the notes-head count + sort instrument · note rows · the delete-confirm strip with its true consequence.

## Task 6 — motion

FLIP re-order, sort-button icon swap and cycle spin, suggestion collapse, segmented pill, view swap.
**Every value comes from spec §8.** `prefers-reduced-motion` collapses each one.

## Task 7 — the tag view

Per spec §5, shaped by Task 0. Per-row project chip (or dashed `loose`), no editor/rename/delete on a
tag, first tag auto-selected on switch.

## Task 8 — wire into `LibraryView` / `FullWindow`

Replace the `vault` section's folders-panel layout. **`ProjectBar` / `DaySparkline` and the Daily-rhythm
panel are existing features — do not delete them as a side effect.** Where they land is a layout
question the board does not answer: **raise it rather than guessing.**

## Task 9 — the pager

Only if Task 0 and the note volumes make it reachable. **Its visual has no mock** (spec §5.5.1) — mock
it for the user before it ships. Deliberately last: on today's real vault (17 notes, largest tag 11) it
never renders.

## Task 10 — `today_view.create_daily_note(folder="Daily")`

The user decided a real registered `Daily` project (`DECISIONS.md` §5, s127 item 1). **Carried since
s127 and still not built.** **★ Check first whether this is genuinely `gui/`-side** — if it needs
Python, it is **out of this sub-project's scope** under standing rule 1 and gets its own task with the
user's go, rather than being smuggled in.

## Task 11 — gates + live QA

Full gate set, then live QA — **which has never been run on this rework**. Check the release exe's mtime
first; it is stale (2026-07-31 18:12). happy-dom has no layout engine, so geometry is **CDP-only**:
measure rects and computed styles, do not screenshot.

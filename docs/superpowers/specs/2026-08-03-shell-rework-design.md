# Spec: Desktop shell rework — six-item menus, the quick pad, and the full-window fix

**Session s135 · 2026-08-03 · desktop repo (`Second Thought/`)**
Design board (user-approved, all five recommendations taken):
`gui/mocks/2026-08-03-shell-rework-decisions.html`.
Binding decisions: `BUILD-STATE/PROGRESS/DECISIONS.md` §5 s135 — **do not relitigate them here.**

> This file is `*.md` inside the desktop repo, which `.gitignore:22` excludes. **It lives on disk only
> and cannot be committed.** Do not read a clean `git status` as evidence it vanished.

---

## 1. Objective

The desktop shell has three shells (minimal, capsule, full window) that have drifted into contradicting
each other. This rework makes each one internally coherent:

- **Menus cap at six items.** Seven spokes is one too many to aim at, and one of them (`hide`) is not a
  destination.
- **Compact never escapes to full.** Minimal and capsule share their own panel designs and sizes. Today
  is the single target that violates this, by hard special-case.
- **A quick pad replaces hide.** A Sticky-Notes-style scratch surface for three-second thoughts, distinct
  from the full note editor.
- **The full window stops fighting itself.** The left rail currently goes dead behind an editor overlay
  that never closes, the format toolbar's edge peeks out of its hiding place, and Settings sits
  mid-rail above a Hide button that is about to be deleted.

**Success is behavioural, not structural:** a user can reach every destination in six aims, can jot a
throwaway note without leaving the pill, and can never get stranded on a screen whose navigation has
stopped responding.

## 2. Tech stack (unchanged — this rework adds nothing)

- `gui/`: React 18 hooks-only, Vite 8, Tauri v2, TailwindCSS **3**, Vitest. **No state/router/UI-component
  library, no animation library.** `animotion`'s framer-motion recommendation is refused here; motion is
  pure CSS transitions against `index.css`.
- `omni_capture/`: FastAPI, Pydantic v2, pytest.
- Icons: inline SVG from `gui/src/components/PillMenu/icons.tsx` only. Never emoji. `taste-skill`'s
  "use an icon library, never hand-roll SVG" rule is refused for the same reason.

## 3. Commands

```bash
# gui — from Second Thought/gui/
npm test                      # vitest run
npm run build                 # tsc typecheck + vite build; MUST pass before any gui commit
npx tauri build --no-bundle   # the RELEASE exe. Never `cargo build --release` (yields a dev exe)

# desktop python — from Second Thought/omni_capture/
python -m pytest -q
python -m pytest test_server.py -k daily_note

# live QA driver
node scratchpad/flow-review/2026-08-02-1500/cdp.mjs
```

## 4. Project structure touched

```
gui/src/
  components/PillMenu/icons.tsx        MenuTarget union, MENU_LABELS, NAV_TARGETS/ALL_TARGETS, MenuIcon
  components/PillMenu/RadialMenu.tsx   minimal-mode fan; consumes ALL_TARGETS
  components/PillMenu/CapsuleMenu.tsx  capsule bar; consumes ALL_TARGETS + CAPSULE_OPEN_W
  components/PillOverlay.tsx           renderPanelBody switch — gains a quick-pad case
  components/CompactPanels/
    CompactShell.tsx                   shared shell; headerActions slot the pad reuses
    CompactQuickNote.tsx               NEW — the quick pad
  components/InboxPanel.tsx            gains the daily-note strip (full window only)
  components/FullWindow/
    FullWindow.tsx                     rail order, RailView union, note-as-a-view
    TodayView.tsx                      DELETED
    HistoryView.tsx                    Daily rhythm section removed
  components/CompactPanels/CompactHistory.tsx   Daily rhythm section removed
  components/StatsPanel.tsx            DaySparkline removed if it loses every importer
  components/NoteEditor.tsx            top bar consolidation, toolbar clip + 19px, view-not-overlay
  lib/compactPanel.ts                  PANEL_W re-derived
  lib/fanLayout.ts                     the "hide" opposite-"search" pin is removed
  lib/viewRouting.ts                   LegacyView/RailDestination maps
  lib/tauri.ts                         NEW: runtime always-on-top setter
  lib/api.ts                           NEW: createNote()
  src-tauri/src/lib.rs                 NEW: set_always_on_top command
omni_capture/
  server.py                            NEW: POST /note
  today_view.py                        create-note write path, shared with the daily note
```

## 5. Decisions already locked (context, not open questions)

| # | Decision |
|---|---|
| A1 | `today` merges into `inbox`. Inbox is the one surface for everything waiting on you. |
| B2 | Quick pad is one band of chrome, in-shell, reusing `CompactShell`'s `headerActions`. |
| C1 | Note-editor top bar: `[pencil/eye] [external] [⋯]` right-aligned. Corner column retired. |
| D1 | Rail ends `… divider · New Note · Settings`. Settings bottom-left. |
| E | Format toolbar icons 13px → **19px**; column 46px → 52px. |
| — | Hide leaves all menus; tray + a new **Esc-to-hide** keep it reachable. |
| — | New Note is deliberately asymmetric: full window opens the real editor, compact opens the pad. |
| — | Notes are created **on first keystroke**, never on click. |
| — | The daily-note entry renders in **full window only** — hidden in compact, gated on `compactHeader`. |
| — | `POST /note` is added as a second desktop note-origination path. |

## 6. Assumptions (revised after two recon passes — correct these, not the mock)

1. **The Today→Inbox merge carries exactly one thing: the daily-note card.** Inbox already has a
   Reminders tab (`InboxPanel.tsx:592-628`) that shows a superset of what Today showed, and Today's
   scratchpad count is provably the same number Inbox already prints in its header — `today_view.py:146`
   and `server.py:1695` both call `list_scratchpad()`. **The other two cards are deleted, not moved.**
   The mock's three-section Inbox over-promised; this is the honest version.
2. **`newnote` must be a real `MenuTarget`**, because the user wants it on the radial and capsule menus.
   It is therefore NOT the cheap FullWindow-only rail addition that `RailView`'s existing
   `dashboard`/`library` precedent would allow.
3. **`ALL_TARGETS` collapses into `NAV_TARGETS` once `hide` is gone** — the two differ only by `hide`.
   Which name survives is a mechanical call made at implementation time by importer count; the union
   itself is the contract.
4. **`PANEL_W` is re-derived, not hand-picked.** `lib/compactPanel.ts:22` hardcodes `332` = 7 × 44 + 24.
   Six items give **288** = 6 × 44 + 24, which happens to match `index.css`'s existing
   `.compact-panel { width: 288px }`. The equality lock `PANEL_W === CAPSULE_OPEN_W`
   (`compactPanel.test.ts:26-27`) is deliberate and is **kept**, not loosened.
   **Consequence to watch: the compact panel gets 44px narrower, and the quick pad lives in it.** If
   live QA shows the pad cramped at 288×320, that is a question for the user, not a silent unlock.
5. **`POST /note` emits the same frontmatter shape as `create_daily_note`** — `origin: note`, `id`,
   `created`, device — into the vault root rather than `Daily/`. Same shape, new caller. **No contract
   doc changes.** If the implementation cannot reuse that shape exactly, work STOPS and the user is
   asked, because note frontmatter is a contract owned by `data-model-and-contracts.md`.
6. **`server.py:1872`'s docstring — "The ONLY action by which the desktop originates a note" — becomes
   false and must be rewritten in the same commit.** Leaving a lie in a docstring that documents a
   doctrine boundary is worse than the feature being missing.
7. **The note editor becomes a real `view`, dropping its self-mounting overlay.** `everOpened`
   (`NoteEditor.tsx:288-296`), `position:absolute`, and `zIndex:20` all go; it joins the
   `<ErrorBoundary key={view}>` switch as a `fw-view-panel` like every sibling. Its ~15-field load-reset
   effect keyed on `[open, path]` must still fire on a new path.
8. **Esc-to-hide binds on the pill and compact panels only.** Not full window — Escape already has
   precedence semantics inside `NoteEditor`, and FR-09 (Escape drifting the background rail) is an open
   finding there. Do not add a second Escape meaning to a surface that already has a buggy one.
9. **`HistoryView` needs no change beyond deleting its Daily rhythm card.** Recon found zero coupling
   between Today/Inbox and History/`DaySparkline`.
10. **`TodayView.test.tsx` dies with `TodayView.tsx`, so the gui test count will FALL.** That is
    acceptable only if itemised: count the file's tests before deleting and record the exact delta,
    the way s130's −11 was accounted for. **An unitemised falling count is a regression until proven
    otherwise.**

## 7. Code style

Matches the repo exactly; no new conventions.

```tsx
// pure geometry/logic in lib/*.ts with a sibling *.test.ts, no side effects
export function quickPadWindowBox(corner: PillCorner, zone: PanelExtrudeZone): Rect { … }

// stateful orchestration in the component; compact hosting gated on compactHeader, never embedded
{!compactHeader && dailyNote && <DailyNoteStrip note={dailyNote} onStart={handleStartDaily} />}

// ponytail: pad holds one note id in localStorage; a real recents list if the pad ever grows tabs
```

- TS `strict` + `noUnusedLocals`/`noUnusedParameters`/`noFallthroughCasesInSwitch` are ON. Satisfy them,
  never suppress.
- Python: snake_case, `_`-prefixed module helpers, type hints on signatures, no class-based DI.
- No linter/formatter exists in either repo. Match surrounding style; do not add one.

## 8. Testing strategy

- **gui:** Vitest. Pure modules get a sibling `*.test.ts`. Component tests are opt-in per file via a
  `// @vitest-environment happy-dom` docblock — **happy-dom has no layout engine, so no rect
  assertions**; extract geometry as a pure function and test that instead.
- **desktop:** pytest, one file per concern, no conftest. `POST /note` gets a test that asserts the
  created file's frontmatter matches the daily-note shape and that a second call does not clobber the
  first.
- **New coverage this batch is mandatory in two places that have none today:**
  1. `FullWindow.tsx` has **zero tests** — the rail/view switch, `MAIN_VIEWS`, `TITLES`, and the editor
     mount are entirely unguarded, and every change here touches them.
  2. The quick pad's create/discard/reopen state machine.
- **`FUZZ=1` is not required** — nothing in this batch touches the op-queue, sync, or reconcile surface.
- **A green suite is not the gate.** s131 and s134 both shipped a feature that was dead in the release
  build while every test passed, because production CSP is `style-src 'self'` and `devCsp` is not.
  Every surface in this batch is interactive. **`document.styleSheets` on a built exe is the detector;
  WebView2 emits no CSP-violation event.**

## 9. Boundaries

**Always**
- Run `npm test` + `npm run build` **on a quiet tree** (no subagent mid-write) before any commit, more
  than once — s134 saw two unexplained flakes, both immediately after an agent finished in the tree.
- Put every `:hover`/`:focus-visible` rule in `index.css`. **Never a component-local `<style>` block.**
- Grep every importer/caller before deleting, moving, or concluding.
- Itemise any falling test count against the file that lost the tests.

**Ask first**
- Anything that would change note frontmatter, the Drive schema, or `data-model-and-contracts.md`.
- Unlocking `PANEL_W === CAPSULE_OPEN_W`.
- Pushing. Committing is granted; pushing needs a fresh go every time.

**Never**
- Weaken the production CSP to make a feature work.
- Add a compact→full-window escape hatch back.
- Write below a note's frontmatter from anything but the user's editor.
- `git add -A` — agents share one worktree.
- Run two TS agents concurrently; one tsc/vitest project, they poison each other's gates.

## 10. Success criteria (specific and testable)

| # | Criterion | How it's verified |
|---|---|---|
| 1 | Radial and capsule render exactly 6 items, no `hide`, with `newnote` present | `npm test` + live QA on a built exe |
| 2 | No menu target sets `displayMode` to `"full"` | grep `setDisplayMode("full")` in `handleMenuSelect` returns nothing |
| 3 | `PANEL_W === CAPSULE_OPEN_W` still holds at the new count | `compactPanel.test.ts` green without editing the assertion's shape |
| 4 | Esc hides the window from pill and compact panels; tray still restores | live QA, both paths |
| 5 | The pad creates a note only after a keystroke; discard on an untouched pad writes nothing | unit test on the state machine + a vault file count check |
| 6 | Pin toggles always-on-top and the window actually sinks behind another app | live QA — cannot be unit-tested |
| 7 | Full-window rail tabs switch views **while the note editor is open** | live QA; this is the bug that motivated the change |
| 8 | Rail order ends New Note → Settings, Settings bottom-most | live QA, both themes |
| 9 | The format toolbar's edge is not visible when hidden, at 19px icons | live QA on a built exe at 100% and 125% scale |
| 10 | "Daily rhythm" returns zero hits in `gui/src` | grep |
| 11 | The daily-note strip appears in full-window Inbox and NOT in compact Inbox | live QA, both shells |
| 12 | `POST /note` creates a note whose frontmatter matches `create_daily_note`'s shape | pytest |
| 13 | Desktop pytest ≥ 1270 + the new tests; gui green with the `TodayView.test.tsx` delta itemised | gates on a quiet tree |

## 11. Open questions

1. **Is 288×320 enough for the quick pad?** Deferred to live QA by design (assumption 6.4). The answer
   is not guessable from source and the equality lock should not be broken speculatively.
2. **Does `ALL_TARGETS` or `NAV_TARGETS` survive the collapse?** Mechanical, decided by importer count
   at implementation time. Not a user question.

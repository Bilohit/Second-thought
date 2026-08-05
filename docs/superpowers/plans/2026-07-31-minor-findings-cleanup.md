# Plan: s119 Minor findings + ponytail-audit cleanup (safety-gated)

**Date:** 2026-07-31 · **Scope rule (user-set, binding):** only fixes that are *guaranteed* not to
change any build's functional behavior beyond the reported defect itself. Anything that cannot meet
that bar is EXCLUDED below, with reason. Plan only — nothing executed yet.

**Verification baseline to beat (must match or exceed after every task batch):**
gui `npm test` **538 passed / 55 files / 0 failed** + `npm run build` clean ·
desktop `python -m pytest -q` **1152 passed / 4 skipped** · phone untouched by this plan.

All 13 findings re-verified in current code 2026-07-31 (`master` = `7976dba`, tree clean) by a
read-only investigator + orchestrator spot-reads. All 13 CONFIRMED present. `NoteEditor.tsx` is
1293 lines; no dedicated NoteEditor test file exists (toolbar logic is only covered indirectly via
`noteFormat.test.ts`) — hence heavy reliance on live-CDP verification (see Task 9).

---

## Part A — Assessment (affect · benefit · safety class)

### Group 1: Chevron (peek arrow) — findings 1–4, all in `peekArrowStyle` / the arrow `<button>`

| # | Finding | Anchor | Affect (today) | Benefit of fix | Safety |
|---|---|---|---|---|---|
| 1 | Never brightens on hover | `NoteEditor.tsx:707` (inline `opacity: 0.4` beats any class rule) | Affordance feels dead; users may not realize it's interactive | Discoverability of the whole strip | SAFE (visual only) |
| 2 | No click handler | `:852-860` (opens only via parent `onMouseEnter`/focus) | Click on the arrow does nothing — violates universal button expectation; touch/pen users have NO path to the strip | Real accessibility + input-modality gap closed | SAFE (purely additive handler) |
| 3 | Opacity gated on wrong flag | `:707` `opacity: toolbarLocked ? 0 : 0.4` — arrow stays visible at 0.4 while strip is already out (`toolbarOut`) | Redundant arrow floats next to the open strip; cosmetic confusion | Cleaner open-state | SAFE (visual only) |
| 4 | `:active` beaten by inline transform | `:705` inline `transform: translateY(-50%)` always overrides `.ne-toolbar-btn:active { transform: scale(0.88) }` (`index.css:1064`) | No press feedback on the arrow | Consistent press feedback | SAFE (visual only) |

All four share one root cause: **positioning/opacity live inline, so no CSS state rule can ever
win.** Fix once at the root (Task 1), not per-symptom — one dedicated CSS class, states via data
attribute.

### Group 2: Overflow menu — findings 5, 6, 7, 12

| # | Finding | Anchor | Affect | Benefit | Safety |
|---|---|---|---|---|---|
| 5 | Escape doesn't close menu | `:407-417` handler checks `toolbarLocked` → `pinnedDrawer` → `onClose()`; `menuOpen` absent | Escape with menu open **closes the whole editor** instead — mildly destructive surprise (autosave means no data loss, but jarring) | Correct dismissal layering; highest-affect finding of the 13 | SAFE (adds one earlier guard; all existing paths preserved) |
| 6 | `menuOpen` not reset on note-switch | note-load effect `:306-350` resets 14+ states, omits `setMenuOpen(false)` | Narrow: doc-click closer (`:300-303`) masks it for mouse note-switches; keyboard-driven switches leave a stale open menu | Consistency with every sibling state | SAFE (one added reset line, matches established pattern) |
| 7 | Connections + Outline both `togglePin("conn")` | `:921` + `:924`; **`ponytail:` comment `:912-916` marks the shared drawer as deliberate** | Opening Outline while Connections is open (or vice-versa) *closes* the drawer instead of showing it — menu rows behave as toggles when users expect "open" | Menu behaves like a menu | SAFE with the minimal fix (open-idempotent for the two conn rows only). Splitting the drawer is OUT — the ponytail ceiling ("split if Outline needs its own scroll position") has not been hit; doctrine forbids silently fixing past it |
| 12 | Open dropdown overlaps external-editor button | `menuDropStyle` `:673-679` `top: 34` vs the stacked 26px buttons (More at ~0, external at ~30) | Dropdown covers the external-editor button while open; it's unclickable (dropdown `zIndex: 20`) though pointer-events return when closed | Both controls visible/reachable with menu open | SAFE (constant change `top: 34` → `top: 64`, clearing both 26px buttons + gaps; verify exact stack height live in Task 9) |

### Group 3: Internal hygiene — findings 8, 9, 10, plus dead exports

| # | Finding | Anchor | Affect | Benefit | Safety |
|---|---|---|---|---|---|
| 8 | Dead `hoverDrawer` state | declared `:241`, set to `null` at `:315`, `:515`, read `:623` — **never set to a non-null value** | Zero runtime effect; pure reader confusion + a dead branch at `:623` | −4 lines, one less lie in the file | SAFE (provably always `null`; delete state + all four sites, simplify `:623` accordingly) |
| 9 | `setMode` inside `setToolbarLocked` functional updater | `:433-447` | Works today (React batches), but updaters must be pure — a purity smell that will bite under StrictMode double-invoke or future React | Future-proof correctness | SAFE (mechanical hoist: compute `next` from current state var outside the updater, call the three setters sequentially; identical observable behavior) |
| 10 | Bold/link tests dropped caret assertions | `noteFormat.test.ts:39-48` (checklist/tag tests at `:4-19` DO assert `selStart`/`selEnd`) | Test-only gap: a caret regression in bold/link formatting would pass CI | Restored regression net | SAFE (test-only; zero runtime code) |
| A1 | Dead `traceCapsuleMorph()` | `gui/src/lib/geoLog.ts:157`; only ref is a *comment* at `App.tsx:2062` | Dead diagnostic export | −~15 lines | SAFE (zero callers; also update the pointing comment) |
| A2 | Unused `railSliderRect()` | `gui/src/lib/railSelection.ts:8`; only importer is its own test | Dead geometry fn + tests testing nothing used | −~20 lines | SAFE (delete fn + its test cases only; rest of module untouched). Note: gui test count will drop by however many cases cover it — record new expected total |
| A3 | `_notify_windows` 2-line pass-through | `omni_capture/notifier.py:69`, caller `:105`, mocked in `test_notifier.py:31,43` | Pure indirection | −4 lines | SAFE but LOW value: inlining forces rewriting 2 test mocks. Included as optional Task 8; skip freely |

### EXCLUDED — first-pass classification (superseded in part by Part C, which re-investigated all three; Part C rulings win)

- **Finding 11 (`measureStyle` 70px right padding applies in view mode, `:656`).** Assessment says
  the "deviation" is now **load-bearing**: s119's fix (b) made the peek+lock zone always-rendered
  *including view mode*, so the 46px strip footprint exists in view mode too — gating the padding
  on edit mode would reintroduce the exact text/strip overlap s119's fix (a) killed, at 640px min
  width. Correct action: **no fix.** Recommend recording in `DECISIONS.md` §5 as
  "spec's 'no padding ever changes' line superseded by always-rendered lock zone" so it stops being
  carried as a defect.
- **Phone: collapse ~10 AsyncStorage flag-store modules into one factory (ponytail-audit).**
  Multi-module refactor across the sync-adjacent phone codebase; cannot be guaranteed
  behavior-preserving by inspection. Out of scope; stays on the ponytail-audit backlog.
- **Splitting the combined "conn" drawer into Connections/Outline components.** `ponytail:`-gated,
  ceiling not hit (see finding 7).
- **Adjacent latent issue (observed, NOT in the 13, NOT planned):** Escape-unlock (`:411`) calls
  `setToolbarLocked(false)` directly, bypassing `toggleToolbarLock` — so Escape after
  lock-from-view leaves the user in edit mode (no prior-mode restore) and leaves a stale
  `lockPriorModeRef`. Routing Escape through `toggleToolbarLock` is a *behavior change*
  (arguably spec-correct per requirement #3, but it needs a user call). Flagged for the user;
  Task 4's refactor makes the later fix one-line if approved.

---

## Part B — Tasks (order chosen so each is independently commit-able; gates run once per batch)

Model tiering: Tasks 1–7 are single-file mechanical edits → `cavecrew-builder` or Sonnet-low, one
task per subagent, orchestrator reviews every diff (s119 lesson: review even literal plan code).
Task 9 (live-CDP) → Sonnet subagent, rect-math not screenshots.

### Task 1 — Chevron root fix (findings 1, 2, 3, 4) — `NoteEditor.tsx` + `index.css`

1. `index.css`: add a dedicated class (next to the `:1061-1065` block):
   ```css
   .ne-peek-arrow { transform: translateY(-50%); opacity: 0.4; }
   .ne-peek-arrow:hover, .ne-peek-arrow:focus-visible { opacity: 0.85; }
   .ne-peek-arrow:active { transform: translateY(-50%) scale(0.88); }
   .ne-peek-arrow[data-hidden="true"] { opacity: 0; pointer-events: none; }
   ```
2. `peekArrowStyle` (`:704-711`): DELETE the inline `transform`, `opacity`, and `pointerEvents`
   entries (keep position/size/color/background/border/padding/transition — drop `opacity` from the
   transition shorthand is NOT needed; transition stays valid).
3. Arrow `<button>` (`:852-860`): add `className="ne-peek-arrow"`,
   `data-hidden={toolbarLocked || toolbarOut}` (fixes finding 3: hide when strip is out, not only
   when locked), and `onClick={() => setToolbarPeeking(true)}` (fixes finding 2 — additive; hover
   path untouched). Confirm the exact peek-state setter name at the anchor before editing
   (`setToolbarPeeking` per `:316`).
4. Hidden-state note: `data-hidden` must include `toolbarLocked` so current locked behavior
   (`opacity 0` + `pointerEvents none`, `:707,:710`) is preserved exactly.

*Risk: none functional — CSS-state migration + one additive handler. The one behavior delta is the
intended fix itself (click opens strip; arrow hides when strip out).*

### Task 2 — Escape closes menu first (finding 5) — `NoteEditor.tsx:407-417`

In `onKeyDown`, insert as the FIRST guard:
```ts
if (menuOpen) { setMenuOpen(false); return; }
```
Add `menuOpen` to the effect dep array (`:417`). Existing lock/drawer/close ordering untouched.

### Task 3 — `menuOpen` reset on note-switch (finding 6) — `NoteEditor.tsx:306-350`

Add `setMenuOpen(false);` alongside the sibling resets (with `setPinnedDrawer(null)` at `:314`).

### Task 4 — `toggleToolbarLock` purity (finding 9) — `NoteEditor.tsx:433-447`

Hoist the decision out of the updater; behavior byte-identical:
```ts
const toggleToolbarLock = useCallback(() => {
  const next = !toolbarLocked;
  if (next) {
    lockPriorModeRef.current = mode === "view" ? "view" : null;
    if (mode === "view") setMode("edit");
  } else if (lockPriorModeRef.current === "view") {
    setMode("view");
    lockPriorModeRef.current = null;
  }
  setToolbarLocked(next);
}, [toolbarLocked, mode]);
```
Note the dep change (`toolbarLocked` added). Keep the existing `:437-438` comment.

### Task 5 — Menu rows open, not toggle, for the two conn rows (finding 7) — `NoteEditor.tsx:921,924`

Both Connections and Outline rows: `togglePin("conn")` → open-idempotent:
```ts
onClick={() => { setMenuOpen(false); if (pinnedDrawer !== "conn") togglePin("conn"); }}
```
(Or a tiny `openPin("conn")` helper if `togglePin`'s shape makes that cleaner — implementer's
choice, single file.) Reminder/History/Metadata rows keep toggle semantics — same-item toggle is
correct; only the two-rows-one-key pair exhibits the bug. **Keep the `ponytail:` comment
`:912-916` verbatim.**

### Task 6 — Dropdown clears the external-editor button (finding 12) — `NoteEditor.tsx:674`

`menuDropStyle`: `top: 34` → `top: 64` (two stacked 26px buttons + gaps; MEASURE the real stack
height via CDP `getBoundingClientRect()` in Task 9 and adjust ±px to sit 4px below the
external-editor button — do not trust the arithmetic here, per s119's CORNER_MENU_WIDTH lesson).

### Task 7 — Dead code (findings 8, A1, A2)

- `NoteEditor.tsx`: delete `hoverDrawer` state (`:241`), the two `setHoverDrawer(null)` calls
  (`:315`, `:515`), and simplify the read at `:623` (it can only ever see `null` — reduce the
  expression accordingly and confirm no visual change falls out of the simplification; if `:623`
  turns out to feed a style, the simplification must produce the exact always-`null` branch
  result).
- Delete `traceCapsuleMorph` from `gui/src/lib/geoLog.ts:157`; rewrite the `App.tsx:2062` comment
  so it stops pointing at a deleted symbol.
- Delete `railSliderRect` from `gui/src/lib/railSelection.ts:8` + its cases in
  `railSelection.test.ts`. Record the new expected gui test total (will drop below 538 by the
  deleted case count; that delta is expected and must be explained in the session ledger, not
  papered over).

### Task 8 (OPTIONAL — skip by default) — inline `_notify_windows` (A3) — `omni_capture/notifier.py`

Inline the 2-line body into `send_notification` (`:105`); update the two mocks in
`test_notifier.py:31,43` to patch the inlined target (`plyer.notification.notify` or equivalent).
Only do this if a session is already touching `notifier.py`; benefit is 4 lines.

### Task 9 — Test + verification batch (once, after Tasks 1–7)

1. **Add caret assertions** (finding 10): extend the bold + link cases in
   `gui/src/lib/noteFormat.test.ts:39-48` with `selStart`/`selEnd` expectations, mirroring the
   checklist/tag pattern at `:4-19`. Derive expected values from `noteFormat.ts`'s actual return —
   if an assertion fails, that's a REAL pre-existing caret bug: stop, report, do not adjust the
   assertion to pass.
2. `npm test` + `npm run build` — must be 0 failed; total = 538 − (railSliderRect cases) + (new
   caret assertions' case delta, likely 0 new cases just stronger existing ones).
3. Desktop pytest only if Task 8 ran.
4. **Live-CDP pass** (Sonnet subagent, rect-math): chevron hover brighten / click opens strip /
   arrow hidden while strip out and while locked / press feedback; Escape priority chain
   (menu → lock → drawer → editor-close) exercised in that order; menu closed after keyboard
   note-switch; Outline click with Connections open shows (not closes) the drawer; dropdown open →
   external-editor button rect non-overlapping and clickable; 640px-min-width no-overlap
   re-checked (Task 1 touched nothing in the padding path, but it's cheap insurance); 0 console
   errors.
5. Human GUI-QA pass (Minimal→Capsule→Full, 100% + 125/150%) is ALREADY owed for the s119 rework
   and now covers these deltas too — one combined pass, no extra human work created.

### Commit strategy

One commit per task (Tasks 1–7), gates batched at Task 9 before any commit is pushed; standing
direct-commit permission applies when green; push needs the user's go. Ledger updates
(`CURRENT.md` §4, `HANDOVER.md`, finding-11 entry in `DECISIONS.md` §5) at session wrap.

### What could still go wrong (named residual risks)

- `:623` `hoverDrawer` read simplification is the only Task-7 step with any inferential distance —
  the implementer must paste the surrounding expression in the diff and the orchestrator must
  verify the always-`null` reduction by eye.
- Task 6's `top: 64` is arithmetic until CDP measures it (explicitly flagged; Task 9 verifies).
- gui test-count drop from A2 must be recorded, or the next session's "gate to beat" comparison
  will read as a regression.

---

## Part C — Excluded-items re-investigation (2026-07-31, second pass; systematic-debugging discipline: evidence first, ruling second)

### C1. Finding 11 (view-mode padding) — RESOLVED: not a code defect at all. New Task 10 (docs/ledger only).

**Evidence.** s119's fix (b) made the peek-arrow + lock zone always-rendered — *including view mode*
(spec requirement #3 demands lock be reachable from view mode, so this is mandatory). Therefore the
46px right-edge footprint exists identically in BOTH modes, and the constant
`padding: "24px 70px 96px 24px"` (`NoteEditor.tsx:656`) **never changes between modes** — which is
precisely what the spec's "no padding ever changes" line asks for. The "deviation" the s119 review
flagged assumed the toolbar zone was edit-only; that assumption died with fix (b). Gating the
padding on `mode === "edit"` is not merely risky — it is *wrong*: view mode would regain the exact
text-under-lock-button overlap at `FULL_WIN_MIN_W` (640px, `App.tsx:1058`) that fix (a) killed.

**Numeric cross-check (why no "smarter" padding is attempted):** the 62ch measure column
(~502px at 13.5px Geist Mono) + symmetric 70px padding ≈ 642px > the 640px window minimum —
symmetric padding fails at min width by arithmetic alone; and s119's own CORNER_MENU_WIDTH lesson
says this file's layout arithmetic must be CDP-measured, not derived. No padding change clears the
guarantee bar.

**Task 10 (no code, zero build risk):**
1. `DECISIONS.md` §5 entry: *"Finding 11 closed as invalid — constant 24/70/96/24 padding is
   spec-conformant ('no padding ever changes') given the always-rendered lock zone (s119 fix b);
   do not gate padding on edit mode; do not re-carry as a defect."*
2. Spec doc (`2026-07-31-note-editor-toolbar-rework-design.md`): one-line amendment noting the
   toolbar zone (chevron + lock) renders in both modes per requirement #3, so the reflow/padding
   promise applies to both modes uniformly. (Spec is gitignored; edit is safe and purely textual.)
3. Drop finding 11 from every carried-findings list at session wrap.

### C2. Escape-unlock mode restore — PROMOTED to Task 4b: spec-authorized, guarantee bar MET.

**Evidence.** Spec `:45-46`: *"Locking forces edit mode … **Unlocking restores whatever mode the
note was in before.**"* — stated unconditionally, not scoped to the lock button. The Escape path
(`NoteEditor.tsx:411`) calls `setToolbarLocked(false)` directly, skipping the restore logic in
`toggleToolbarLock` (`:433-447`) — so Escape-unlock strands a view-mode user in edit mode and
leaves a stale `lockPriorModeRef` (self-healing only on next note load, `:318`). This is therefore
a **spec-conformance fix**, not a design change; no user ruling needed.

**Task 4b — depends on Task 4 (must land after it):** in the Escape handler (`:407-417`) replace
```ts
if (toolbarLocked) { setToolbarLocked(false); return; }
```
with
```ts
if (toolbarLocked) { toggleToolbarLock(); return; }
```
and add `toggleToolbarLock` to the effect deps (`:417`). Post-Task-4, `toggleToolbarLock` reads
`toolbarLocked === true` in this branch, so it always unlocks — byte-identical to the old call
*plus* the spec's restore. **Ordering note for the implementer:** Task 2 puts `menuOpen` FIRST in
this handler; 4b edits the second guard. Escape chain after both: menu → unlock(restore) →
drawer → editor-close.

**Verification (extends Task 9.4):** CDP — open note in view mode → lock (mode flips to edit) →
Escape once → toolbar unlocked AND mode back to `view`; Escape again → drawer/editor chain
unchanged. Also lock-from-edit → Escape → stays edit (null prior-mode path).

### C3. Phone AsyncStorage flag-store collapse — INVESTIGATED, verdict: audit claim overstated; only a partial collapse is safe, and it stays OPTIONAL (Task 11, default SKIP this session).

**Evidence (full read-only survey of `phone/src/lib`, 2026-07-31).** The audit's "~10 near-identical
modules" is really **17 AsyncStorage-backed modules, 848–907 lines, in 8 distinct shapes** — most
are NOT interchangeable:

| Shape | Modules | Lines | Collapse-safe? |
|---|---|---|---|
| 1. Scalar boolean get/set | chatModelConfig, chatConfig, semanticConfig, syncDotConfig | 85 | YES (near-identical) |
| 2. Enum get/set + cache | syncPlacementStore, tagsViewModeStore | 61 | YES (near-identical) |
| 3. Set + listeners/notify | pinStore, syncIgnoreStore | 133 | Maybe — but syncIgnoreStore feeds the opqueue check (`noteStore.ts:280`) |
| 4. Record map + JSON | noteModeStore | 40 | No pair to collapse with |
| 5. Dual-key complex config | syncConfig | 126 | NO — sync-core (`noteStore` pull/drain, `backgroundSync`, `hubDiscovery`) |
| 6. Business-logic gates | batteryExemptionPrompt, dailyDigestShown, sttModelConfig | 165 | NO — each has unique logic (shouldPrompt gate, date-key invalidation, tri-state + probe) |
| 7. Validated snapshot | widgetSnapshot | 117 | NO — field-by-field validation |
| 8. Theme + derivation | theme (23 importers) | 46 | NO — schemeOf luma calc, widest blast radius |

All 16 non-onboarding modules have sibling tests. Three modules sit on sync/reconcile paths
(syncIgnoreStore, syncConfig, semanticConfig) — the workspace's highest-protected code.

**Ruling.** Realistic safe collapse = shapes 1–2 only: 6 modules, ~146 lines → a ~40-line factory
+ 6 thin re-export shims ≈ **net −80 lines**, far below the audit's implied win. One of the six
(semanticConfig) gates `noteStore.backfillAll`; one (syncDotConfig) hydrates at app startup
(`_layout.tsx:265-270`). Benefit is small; blast radius is not zero; and this plan's session is
desktop-gated (phone suite would need its own full re-run: 1816 tests + both typechecks + fuzz
6/6). **Default: SKIP.** Shapes 3–8 are PERMANENTLY out of a "guaranteed-safe" plan — divergent
logic means a factory changes real behavior or forces per-module escape hatches (complexity moved,
not removed).

**Task 11 (OPTIONAL — only if a future session is already gate-running the phone repo):**
1. Scope: shapes 1–2 ONLY (chatModelConfig, chatConfig, semanticConfig, syncDotConfig,
   syncPlacementStore, tagsViewModeStore).
2. Safety-by-construction constraints, all mandatory: (a) every module's public API (names,
   signatures, storage keys, defaults) frozen — each file becomes a thin instantiation of the
   factory and re-exports the exact same symbols; (b) **existing sibling tests are NOT edited** —
   they must pass verbatim against the shimmed modules (the whole guarantee rests on this);
   (c) factory itself gets ONE new sibling test; (d) full phone gate re-run (1816/6skip + both
   typechecks + fuzz 6/6) before commit.
3. If any frozen-API or untouched-test constraint can't be met for a module, drop THAT module from
   the collapse rather than bending the constraint.
4. Correct the ponytail-audit backlog entry at session wrap: "~10 near-identical modules" →
   "6 collapse-safe of 17 surveyed; ~−80 lines ceiling" so the overstated claim stops being carried.

### Part C effect on Part B

- Task list is now: 1, 2, 3, 4, **4b (new)**, 5, 6, 7, [8 optional], 9, **10 (new, docs-only)**,
  [11 optional, phone, default-skip].
- Task 9.4's CDP checklist gains C2's lock/unlock-restore scenarios.
- Excluded list shrinks to: shapes 3–8 of the phone survey (permanent), drawer split
  (`ponytail:`-gated, unchanged), padding gating (closed as invalid, Task 10).

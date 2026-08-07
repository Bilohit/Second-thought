# V2 Redesign Port — Program Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the user-approved V2 design mock into both shipping apps without altering a single hand-tuned morph, and without a settings surface changing shape.

**Architecture:** Eight phases. Evidence is captured before anything moves, motion is made drift-proof before anything is restyled, the one missing data layer is built before the UI that renders it, and the two app shells then proceed in parallel (one TypeScript agent per repo) with the pill last because it inherits every decision the others make.

**Tech Stack:** Desktop — Python 3 / FastAPI / pytest; React 18 + Vite + Tauri v2, TypeScript strict, Tailwind 3, Vitest. Phone — Expo SDK 54 / RN 0.81, expo-router, TypeScript strict, Vitest. No UI-component library on either side; every surface is hand-written against the repo's own tokens.

**Status:** Phase 0 is task-complete below and executable now. Phases 1–7 carry goals, acceptance criteria, model tiers and checkpoints; each earns its own detailed plan at open, written against evidence that exists then.

---

## Global Constraints

Every task's requirements implicitly include this section. Values are verbatim.

**From the workspace locks (never violate, never relitigate):**
- Files are the source of truth. Every SQLite table, index, vector store, manifest and dedup ledger is a derived, rebuildable cache.
- A note's body is sacred (`origin: note`). Only the user's editor writes below the frontmatter, with the single provenance-gated trailing-`tags:` exception. Body-byte-identity above that line is asserted on every non-editor op, both sides.
- Google Drive is the shared hub; the version token is `headRevisionId`, never `modifiedTime`/mtime.
- Notes are not captures. Note enrichment never runs the capture pipeline.
- Field-aware, non-destructive conflicts. Enrichment is provenance-gated — each device enriches only content it authored.
- Drive is the only reachability plane, batched. LAN file-sync is an accelerator, never a dependency.
- `X-Omni-Secret` is localhost API auth and is never removed. No CSP weakening.
- Identity: 0-radius surfaces, border-based elevation, grayscale accent, semantic green/yellow/red only, inline SVG icons only — **never emoji**.
- `ponytail:` comments mark deliberate ceilings with a named upgrade path. Never silently "fix" one.

**From the user, binding on this program (s142 close + s143 open):**
1. **Desktop Settings keeps the current app's visuals and ordering** (Form/Function/Sync as shipped). Functional additions only where §4.12's inventory shows a real gap. The mock's settings tab is a functionality inventory, not a visual target.
2. **Android Settings likewise** — current visual setup and ordering stand; functional changes only where genuinely warranted.
3. **Minimal mode: the central orb itself grows into the open tab panel and closes back into it.**
4. **★ PRESERVE the current morphing mechanics, animations and easing points EVERYWHERE.** The V2 reskin changes what panels CONTAIN, never how they MOVE. An agent that "cleans up" `compactPanel.ts`, the capsule CSS transitions or the island sequencing has broken the brief even if every gate is green.
5. **Android "Today" tab is dropped entirely** (s143, explicit). The daily-digest logic behind it goes with it.
6. **Android FAB radial ships four satellites: Photo · Voice · Template · Quick-Sync**, with Quick-Sync keeping its current further-out position. **Existing arc mechanics and measurements are untouched.** Search relocates into BROWSE.
7. **Desktop SYNC is built to the plan, gaps filled for real** — no stubbed panels, no invented rows.
8. **A shared type scale is introduced** in both repos.

**Gate values to match (★ REFRESHED — last measured s145, 2026-08-06, on a quiet tree. The s141 numbers this table used to carry are two phases stale; every delta since has been additive):**
- desktop `python -m pytest -q` → **1411 passed · 4 skipped**
- gui `npm test` → **841 passed · 77 files**; `npm run build` → **exit 0** (the >500kB chunk warning is pre-existing, not a failure)
- phone `npm test` → **1844 passed · 6 skipped**; `npm run typecheck` + `npm run typecheck:app` → exit 0
- ★ **Noise, not a red row:** the gui suite prints an `ECONNREFUSED 127.0.0.1:7070` stack to stderr on every run, passing or not — a test probes the local server.
- `FUZZ=1 pytest test_fuzz_races.py -q` → **4 passed** — required only if a phase touches the op-queue/sync/reconcile path. **Phase 3 does.**

**Frozen constants — changing any of these is a plan violation, not a judgment call:**

| Constant | Value | Where | Why frozen |
|---|---|---|---|
| `CAPSULE_CLOSED_W` | 154 | `CapsuleMenu.tsx:42` | Start width of the hand-tuned 154→288 morph |
| `CAPSULE_OPEN_W` / `PANEL_W` | 288 | `CapsuleMenu.tsx:47-49`, `compactPanel.ts:22` | Derived `6 × 44 + 12×2`; the 6-target count must not change |
| `PANEL_H` | 320 | `compactPanel.ts:23` | Fused panel + island height |
| `PANEL_GAP` | 0 | `compactPanel.ts:24` | The "fused border" seam |
| `CAPSULE_ANIM_MS` | 260 | `CapsuleMenu.tsx:56` | Bar width transition |
| `CAPSULE_ITEM_PLAY_MS` | 180 | `CapsuleMenu.tsx:57` | Icon reveal |
| `PANEL_ANIM_MS` | 300 | `compactPanel.ts:25` | Clip-path wipe + island rect morph |
| `PANEL_EXIT_MS` | 360 | `compactPanel.ts:26` | `= ANIM + 60`; paired with the 100ms close-lag in `index.css:1264-1266` |
| Content lift delay | 140ms | `index.css:1684-1701` | Capsule stage-2 |
| Island content delay | 300ms | `index.css:1613-1615` | Waits for rect settle |
| Icon stagger | 16ms/icon | `menuTiming.ts:16-22` | Capsule reveal cadence |
| Swipe geometry (phone) | panel 100px, arm 70px, zone 0.25, activate −12px | `app/(tabs)/index.tsx:163-192` | Already matches the mock exactly |
| Toolbar cell (phone) | 46×44 | `app/note/[id].tsx:1396-1402` | Already matches the mock exactly |
| Arc geometry (phone) | `ARC_SLOT_SIZE=42`, `FAB_CENTER=28`, `ARC_LONG_PRESS_MS=300` | `app/(tabs)/index.tsx:118-133` | User instruction 6: mechanics untouched |

---

## Council verdict (2026-08-06) — why this order

Four voices; three launched with no conversation history as an anti-anchoring measure.

- **Consensus (all four):** the SYNC backing data is not UI work and must not ride inside a UI phase; Phase 1 must shrink to a typeface swap plus token *definition*, with type-scale *migration* riding along with each surface rewrite; desktop and Android share zero files and separate test runners, so they run concurrently.
- **Strongest dissent — Critic vs. Pragmatist on lint timing.** Pragmatist: a raw-px lint at closeout. Critic: define the token's allowed values before Phase 4 or you get 25 dialects set by whoever went first. **Resolved toward the Critic** — the scale is defined in Phase 2 and enforced at review from Phase 4 onward, because a convention that arrives at closeout arrives after the damage.
- **Premise check — yes, the Skeptic rejected the framing.** The proposed list was "a schedule, not a decomposition." Accepted; the phase count grew from six to eight as a result.
- **Two independent voices, then code, converged on the same unseen risk:** Geist Mono and IBM Plex Mono have different advance widths, so every width derived from a character count moves. `CAPSULE_TEXT_W = 98` at `CapsuleMenu.tsx:39` is a hardcoded measurement of "Second Thought" in Geist Mono 12px, and `CAPSULE_CLOSED_W = 154` derives from it. **The typeface change is a motion change.** This was verified at source, not taken on the council's word.
  - **★ s144 CORRECTION — the premise was never measured, and it is false.** What was verified at source was that `CAPSULE_TEXT_W` is a hardcoded Geist measurement (true, and it is stale by 2.8px). What was *assumed* is that IBM Plex Mono's advances differ — nobody opened the font binaries. They do not differ: both faces are 1000 upem with a uniform 600-unit advance on every rendering glyph. **A council consensus and a source-verified adjacent fact combined into a conclusion neither of them supported.** Worth remembering as a failure mode: "verified at source" attached to the wrong half of the claim.
- **The Critic's time-sensitive catch, which sets Phase 0:** the 4,027 currently-green tests touch almost no pixels. The only real regression evidence for this program is a measured baseline of the current UI, and **that door closes permanently the moment the first commit lands.**

---

## Phase order

| # | Phase | Repo | Tier | Gate before exit |
|---|---|---|---|---|
| 0 | Baseline evidence + motion single-sourcing | desktop `gui/` | **Opus** (motion), Sonnet (capture) | gui suite green; measured values byte-identical to baseline |
| 1 | SYNC data layer | desktop `omni_capture/` | **Opus** | pytest green + `FUZZ=1` if the sync path is touched |
| 2 | Typeface + token definition | both + design-system doc | Sonnet, Opus review | all three suites green; DPI sweep clean |
| 3 | Desktop full window | desktop `gui/` | Sonnet build, Opus review | gui green; live CDP round |
| 4 | Android shell | phone `phone/` | Sonnet build, Opus review | phone green + both typechecks; emulator round |
| 5 | Pill modes | desktop `gui/` | **Opus** | gui green; motion diff vs Phase 0 baseline |
| 6 | Closeout | both | Opus | full gates + device round + DPI QA |

Phases 3 and 4 run concurrently — different repos, different test runners, zero shared files. Phase 1 runs concurrently with Phase 0 (Python vs TypeScript, no shared gate).

---

## PHASE 0 — Baseline evidence + motion single-sourcing

**Why first:** every later phase claims "motion unchanged." Without a measured baseline captured before the first commit, that claim is unfalsifiable. And the CSS/TS duration literals are currently kept in sync by a code comment — the drift is silent and a green suite cannot see it.

**Agent brief must carry verbatim:** *"You are protecting hand-tuned motion. Every duration, easing and stagger in this code was set by the user by feel. Your job is to make drift impossible, not to improve anything. If you find yourself simplifying, renaming, or tidying, stop — that is the failure mode this task exists to prevent."*

### Task 0.1: Capture the measured motion baseline

**Files:**
- Create: `<scratchpad>/baseline-2026-08-06/measure.mjs`
- Create: `<scratchpad>/baseline-2026-08-06/baseline.json`

**Interfaces:**
- Produces: `baseline.json` — `{ capsule: {closedW, openW, barH, radius}, panel: {w, h, radius}, island: {startRect, endRect, radius}, durations: {...}, labelWidth }`. Phase 5 diffs against this file.

- [ ] **Step 1: Confirm the release exe is current before measuring a stale binary**

```powershell
Get-Item "gui\src-tauri\target\release\second-thought.exe" | Select-Object LastWriteTime
```
If older than the newest file under `gui/src/`, rebuild first with `npm run tauri build --no-bundle` (never plain `cargo build` — that yields a dev binary).

- [ ] **Step 2: Launch with CDP enabled**

Port 9222 binds **only** via the env var; exe arguments do not work:
```powershell
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9222"
.\launch.ps1
```

- [ ] **Step 3: Measure — do not screenshot for numbers**

Connect with `suppress_origin=True` (WebView2 rejects the default Origin header). For each of: capsule closed, capsule open, capsule panel open (top zone and bottom zone), minimal orb, minimal island open — record `getBoundingClientRect()` and `getComputedStyle()` for `border-radius` and every `transition-duration`. Record the rendered width of `.capsule-label` explicitly; that is the number the typeface swap will move.

- [ ] **Step 4: Capture the pixel corpus at three DPI scales**

At 100%, 125% and 150% display scale, capture: full window on each of the 4 current rail views, capsule closed/open/panel, minimal orb/island. **Screenshots stay in the subagent** — the main thread reads at most one failing image. Store under `baseline-2026-08-06/`.

- [ ] **Step 5: Commit the measured values only**

The JSON is committed to the repo as the motion contract; the PNG corpus stays in the scratchpad (binary, not repo content).
```bash
git add gui/src/lib/__baseline__/motion-baseline.json
git commit -m "test(pill): freeze the measured motion baseline before the V2 port"
```

### Task 0.2: Make CSS/TS duration drift unrepresentable

**Files:**
- Modify: `gui/src/lib/compactPanel.ts` (export a duration map)
- Modify: `gui/src/App.tsx` (apply the map as custom properties, next to the existing theme-property application)
- Modify: `gui/src/index.css` (consume the custom properties)
- Test: `gui/src/lib/compactPanel.test.ts`

**Interfaces:**
- Produces: `export const MOTION_VARS: Record<string, string>` mapping CSS custom-property name → `"<n>ms"`, derived from the existing constants. Phase 5 relies on these names.

- [ ] **Step 1: Verify today's values match before rewiring anything**

Grep every duration literal in the capsule/panel/island CSS blocks and assert by eye against the frozen-constants table above. **If any pair already disagrees, STOP and report** — that is a pre-existing defect and single-sourcing it would silently change motion while claiming to preserve it.

- [ ] **Step 2: Write the failing test**

```ts
import { MOTION_VARS, PANEL_ANIM_MS, PANEL_EXIT_MS } from "./compactPanel";
import { CAPSULE_ANIM_MS, CAPSULE_ITEM_PLAY_MS } from "../components/PillMenu/CapsuleMenu";

test("motion custom properties carry the TS constants verbatim", () => {
  expect(MOTION_VARS["--panel-anim-ms"]).toBe(`${PANEL_ANIM_MS}ms`);
  expect(MOTION_VARS["--panel-exit-ms"]).toBe(`${PANEL_EXIT_MS}ms`);
  expect(MOTION_VARS["--capsule-bar-ms"]).toBe(`${CAPSULE_ANIM_MS}ms`);
  expect(MOTION_VARS["--capsule-item-ms"]).toBe(`${CAPSULE_ITEM_PLAY_MS}ms`);
});

test("the frozen motion constants still hold their tuned values", () => {
  expect(PANEL_ANIM_MS).toBe(300);
  expect(PANEL_EXIT_MS).toBe(360);
  expect(CAPSULE_ANIM_MS).toBe(260);
  expect(CAPSULE_ITEM_PLAY_MS).toBe(180);
});
```

- [ ] **Step 3: Run it and watch it fail**

Run: `npm test -- compactPanel`
Expected: FAIL — `MOTION_VARS` is not exported.

- [ ] **Step 4: Implement the map**

```ts
export const MOTION_VARS: Record<string, string> = {
  "--panel-anim-ms": `${PANEL_ANIM_MS}ms`,
  "--panel-exit-ms": `${PANEL_EXIT_MS}ms`,
  "--capsule-bar-ms": `${CAPSULE_ANIM_MS}ms`,
  "--capsule-item-ms": `${CAPSULE_ITEM_PLAY_MS}ms`,
};
```

- [ ] **Step 5: Apply the properties where theme properties are already applied**

`App.tsx` already writes theme custom properties onto `documentElement` inline, because production CSP blocks `<style>` tags. Use that same mechanism — do not introduce a new one, and do not add a `<style>` tag.

- [ ] **Step 6: Replace the CSS literals with `var()` — one block at a time**

Each replacement keeps a fallback equal to the current literal, e.g. `transition: clip-path var(--panel-anim-ms, 300ms) cubic-bezier(0.16,1,0.3,1)`. **Easing curves are not parameterized** — only durations. The 100ms close-lag at `index.css:1264-1266` keeps its comment explaining that it plus `CAPSULE_ANIM_MS` equals `PANEL_EXIT_MS`.

- [ ] **Step 7: Run the suite and re-measure against the baseline**

Run: `npm test` → expect **808+ passed** (new assertions are additive).
Then re-run Task 0.1's measurement and diff against `motion-baseline.json`. **Any non-zero diff means this task changed motion and must be reverted.**

- [ ] **Step 8: Commit**

```bash
git add gui/src/lib/compactPanel.ts gui/src/App.tsx gui/src/index.css gui/src/lib/compactPanel.test.ts
git commit -m "refactor(pill): single-source the morph durations so CSS cannot drift from TS"
```

### Task 0.3: Mount the pill DOM once, so a class change can fail a test

**Files:**
- Create: `gui/src/components/CompactPanels/CompactShell.test.tsx`

The Critic's point stands: a duration assertion catches nothing in the "dead or blank window until restart" class, because that class is lifecycle, not geometry, and no existing test ever mounts this DOM.

- [ ] **Step 1: Write the failing test** — mount `CompactShell` and assert the structural contract only: the outer `.compact-panel` element exists, carries `data-zone`, gains `.open` when `open` is true, and renders `headerActions` into the header slot. **Assert classes and data attributes, not pixels** — happy-dom has no layout engine.
- [ ] **Step 2: Run it and watch it fail.**
- [ ] **Step 3: Make it pass without touching component internals.** If it cannot pass without an edit to `CompactShell`, STOP and report — the structural contract has drifted from what Phase 5 expects to rely on.
- [ ] **Step 4: Run `npm test`; commit.**

**Phase 0 exit criteria:** `motion-baseline.json` committed · PNG corpus at 3 DPI scales in the scratchpad · gui suite green with additive tests only · re-measurement byte-identical to baseline.

---

## PHASE 1 — SYNC data layer (concurrent with Phase 0)

**Goal:** the desktop SYNC tab's four regions have real sources before any UI renders them. **No mock is in scope for this phase.** Contract-first: if any wire shape changes, `data-model-and-contracts.md` is edited and user-approved *before* code.

**Task 1.1 is CLOSED (2026-08-06, investigation VERIFIED at source). Findings, binding on 1.2/1.3:**

| Region | Real source | Status |
|---|---|---|
| Activity feed | `capture_log.read_log(n)` — `capture_log.py:95` | ✅ real per-event source |
| Pass strip | `sync_scheduler.status().history` — `sync_scheduler.py:113-122` | ⚠️ **pass-level counts ONLY** (`uploaded/reconciled/conflicts/pulled/…`), no note ids. Backs a "last N passes" strip, **NOT** an activity feed. The baton's claim that it could was wrong |
| Conflicts | `GET /vault/conflicts` — **`vault_admin.py:1099`**, not `server.py` | ✅ moves to SYNC unchanged |
| Deletes pending | `delete_prompts.json` — `delete_detect.py:144-165` | ✅ durable, user-actionable, currently unrendered |
| Queue | `.omni_capture/mobile_sync_state.json` — `mobile_sync_agent.py:1933` | ✅ **exists**, see below |

**Corrections to the brief the investigation issued:** `vault_sync.py` does not exist (the Drive engine is `mobile_sync_agent.py`, 2020 lines). Desktop has no op-queue *table* but DOES have a durable per-note last-synced sidecar. `lan_sync.py:92-95`'s `_outbound` list is mtime-based and **self-declared non-authoritative — never use it as the queue source.**

**The pending-upload set is the negation of the skip at `mobile_sync_agent.py:1135`:** a note is pending when the sidecar has no row, no `drive_file_id`, or `local_hash != sha256(file bytes)` — then filtered through `sync_ignore.filter_ignored_notes`. Local-only, zero Drive calls, zero new state. `mobile_sync_agent.py:1109` states the rule in-source: *"NEVER modifiedTime"* — the `headRevisionId` lock is already honored. Precedent for a read-only API path reading this sidecar without writing it: `note_history.py:41-42`.

**★ USER DECISION (s143): HYBRID.** Two hub-side filters (`:1144` F-1 skip, `:1151` advanced-head guard) and the entire inbound set require a live Drive listing, so local-only can honestly say *"changed since last sync"* but **never** *"will upload next pass"*.
- **At rest:** local hash-vs-sidecar diff + `delete_prompts.json`, labelled **"Changed since last sync"**. Zero network — safe at `/sync/status` poll cadence.
- **On explicit user action only** (expand / Sync now): one Drive listing upgrades the panel to exact *will upload · blocked · to pull*. Needs the three-state posture `note_history.py:29-31` already established (`ok` / `offline` / `not_synced`).
- **The word "queue" is banned from the resting label** — it promises drain semantics the local source cannot honor.

**★ USER DECISION (s143): the refusal state never shows a count.** If `sync_ignore` fails to load it returns `{}` (`sync_ignore.py:114`) — the panel would show **zero pending at the exact moment `run_pass` refuses the whole sync** (`mobile_sync_agent.py:1941-1942` raises). Empty-reads-as-all-synced is the most dangerous failure in this surface. Render an explicit red **"Sync blocked — ignore list unreadable"** state carrying the underlying error. Never a number.

- [ ] **Task 1.2 — Activity endpoint** over `capture_log.read_log`, newest-first, bounded. Sibling `test_*.py`. Do **not** fold pass-history rows in as if they were events.
- [ ] **Task 1.3 — Pending endpoint**, hybrid per the decision above. **Must reuse `read_vault_notes`** — a second vault walk is a second definition of "what a note is" (`lan_sync.py:95` states this rule).

**Seven ways a naive panel lies (all verified; the implementer must handle each):** F-1 notes pending forever · direction inverted on advanced-head · sidecar loss reads as mass-pending when real behavior is quiet adoption (`:959-974`) · ignore-set corruption reads as all-synced · captures invisible unless `mirror_captures` flips, then +hundreds · `enrich_notes` makes notes pending with no user edit (`:1780-1781`) · attachments structurally invisible (presence-is-state, no sidecar row).

**Acceptance:** every SYNC region maps to a named real source · the resting panel never issues a network call · the refusal state is asserted by a test · body-sacred and provenance-gating assertions unchanged and green. **`FUZZ=1` required — this phase reads the sync path.**

**Trap:** this is the phase where a UI-minded agent can silently violate enrichment provenance-gating. Opus tier, no exceptions.

---

## PHASE 2 — Typeface + token definition

**Goal:** Geist Mono → IBM Plex Mono, and the type scale *defined*. **No call-site migration in this phase.**

> **★★★ PHASE 2 IS COMPLETE (s144 typeface, s145 scale). THE SCALE IS DEFINED — do not treat it as an open question.**
>
> **`micro 9 · label 10 · body 11 · read 12 · lead 13 | title 16 · display 20 · hero 22`. Half-steps are banned.**
> Desktop carries it twice — `gui/src/lib/type.ts` for the 350 inline TSX sizings and `--fs-*` at `:root` for the 8
> CSS ones, with `type.test.ts` parsing `index.css` off disk to assert the two agree. The phone vendors it as
> **`font.scale`, a NEW key** — `font.size` collides at two names with different numbers (`label` 11 vs 10,
> `body` 14 vs 11), so redefining in place would have silently re-rendered 97 call sites. **`font.size` keeps its
> exact values and a test guards them; Phase 4 migrates the last call site, then deletes it. Not before.**
>
> **Migration is what remains: 99 call sites (desktop 58, phone 41) + the phone's `font.size.body 14 → font.scale.lead 13`
> across 25 uses. It rides per-surface with Phases 3/4 — never as a big-bang sweep. A raw px in a touched file is
> rejected at review from Phase 4 onward.**

**Checkpoint before any code:** a side-by-side type-specimen mock — both fonts, real surfaces, rendered — for the user to approve the flip. The user approves the specimen, not the idea. Decision recorded in `DECISIONS.md` §5. **DONE s144 — the user picked option B.**

**Lands together, one commit per repo:** `gui/src/index.css` · `phone/src/lib/tokens.ts` · `Second Thought - Android App/design-system.md`.

**The phone needs five font touchpoints, not one:** the 4 weight `.ttf` files in `phone/assets/fonts/`, the `useFonts` call at `app/_layout.tsx:134-139`, the `font` object in `tokens.ts:136-142`, **and the separate un-weighted widget font declared in `app.json:87-92`** for home-screen `RemoteViews`. Miss the last and the widgets silently keep the old typeface.

**RN weight trap:** Android does not map `fontWeight` onto custom font files. Each weight is its own `fontFamily`. Never pair `font.mono` with `fontWeight`.

**The geometry check — downgraded from make-or-break to confirmation (s144, measured).** The two faces are metrically identical (Open Risk 1, now closed), so the face itself moves nothing. Still re-measure `.capsule-label` against Phase 0's baseline as a confirmation, because the *tracking* option does move it: `+0.01em` adds 1.68px, taking the label from 100.80px to 102.48px and the in-bar slack from 18.2px to 16.52px. Both fit. `CAPSULE_CLOSED_W` stays **154** — frozen. If any label ever stops fitting, solve it as a *fit* problem (tracking, size) inside the frozen width. **Updating `CAPSULE_TEXT_W` moves the morph and is forbidden.**

**Acceptance:** all three suites green · DPI sweep at 100/125/150% shows no clipping or reflow · capsule label fits within the frozen budget · widget font swapped · no call sites migrated.

---

## PHASE 3 — Desktop full window (concurrent with Phase 4)

**This is an IA rewrite, not a reskin.** 4 rail views become 5 tabs; SYNC leaves Settings; conflicts leave Dashboard; CHAT separates from Search.

| Surface | Today | Acceptance |
|---|---|---|
| Rail | Dashboard·Look·Vault·History + footer New Note/Settings | 5 tabs NOTES·BROWSE·CHAT·SYNC·SET, sliding indicator, screen slide. Existing `railSelection.ts` measured-geometry indicator reused, not reinvented |
| NOTES | `LibraryView → ProjectsView → ProjectsPane` | List + 280px morphing capture pane; radial → blank/voice/clip/screenshot; hotkey → live StepIndicator over the real `STEP_DEFS` |
| Editor | `NoteEditor.tsx`, keyed sibling view | Window-level slide-over from the right. 3-dot becomes Reminder·Set as template·Outline·History·Delete(danger, last) |
| BROWSE | ProjectsRail + ProjectsPane, unpaged | Sectioned search + paged 4×2 project rects + tag list + LIST/STARS toggle. **All net-new: no pager and no LIST/STARS exists today** |
| CHAT | a *mode* of `LookPanel.tsx` | Own tab. Note `--swap-dir` is coupled to Search=0/Chat=1 ordering — reordering flips slide direction silently |
| SYNC | Settings tab 3 | Own tab: hub strip + queue + conflicts + activity, over Phase 1's real sources |
| SET | Form/Function/Sync | **VISUAL NO-FLY ZONE.** Layout and ordering unchanged. Functional deltas only |

**Preserve:** the FLIP reorder animation in `ProjectsPane.tsx:314-387` reads rects and mutates `style.transform` outside React — it must stay `path`-keyed. `FluidVisualizer` is **shared with the pill**; editing it touches Phase 5's surface. Both `ponytail:` 2000-note ceilings stand.

**Type-scale migration rides along here** — each rewritten file adopts the tokens defined in Phase 2. Raw px in a touched file is rejected at review.

**Acceptance:** gui green · `npm run build` exit 0 · **`FUZZ=1 pytest test_fuzz_races.py -q`** (Phase 3 touches the sync path) · live CDP round on a fresh exe · settings pixel-diffed against Phase 0's corpus to prove the no-fly zone held.

### Phase 3 task breakdown (s146) — five sequential runners, then a live round

**Why sequential:** TS agents cannot be parallelised *within one repo*. Phone Phase 4 runs concurrently throughout — different repo, zero shared files, separate runners.

**Every runner inherits:** the Global Constraints above · **the cardinal rule — reskin the CONTENTS, never the MOTION** · **SET is a VISUAL NO-FLY ZONE** · agents never commit and never run the full gate.

**Frozen across all five — an agent that "cleans up" any of these has broken the brief even with a green gate:**
- `compactPanel.ts`, `reconcileEdges.ts`, `reconcileApply.ts`, `CapsuleMenu.tsx`, `App.tsx`'s reconcile effect.
- **`ProjectsPane.tsx:314-387`'s FLIP reorder** — it reads rects and mutates `style.transform` **outside React** and **must stay `path`-keyed**.
- **`FluidVisualizer` is SHARED WITH THE PILL** — editing it reaches into Phase 5's frozen surface.
- **`CAPSULE_TEXT_W = 98` is stale by 2.8px ON PURPOSE. Do not "fix" it.** The real label is 100.80px; the constant is **not load-bearing** (`CapsuleMenu` sets the bar width explicitly). Changing it moves the morph. Comments at all four sites say so.
- Both `ponytail:` 2000-note ceilings stand.

- [x] **P3-A — the rail: 4 views → 5 tabs. DONE s146 `ecbe8ab`.** Dashboard·Look·Vault·History + footer becomes **NOTES·BROWSE·CHAT·SYNC·SET**, evenly split, with a sliding indicator and a screen slide. **Reuse `railSelection.ts`'s measured-geometry indicator — do not reinvent it.**
- [x] **P3-B — NOTES + the editor. DONE s147 `e74a432`.** List + a **280px morphing capture pane** (radial → purpose-built blank-note / voice / clip / screenshot views; hotkey → a live StepIndicator over the **real `STEP_DEFS`**, not a mock sequence). Note that **the radial is pill-only today and has never mounted in the full window.** The editor becomes a **window-level slide-over from the right** with a view/edit icon toggle, an open-in-OS-editor button and a 3-dot menu (**Reminder · Set as template · Outline · History · Delete (danger, last)**). **★ s145 override of the mock: the editor closes on EVERY tab switch, BROWSE included.** The mock leaves it open over BROWSE; that was a mock bug.
- [x] **P3-C — BROWSE, entirely net-new. DONE s148 in three runners: `4e9ebb5` (shell + STARS) + `5facb60` (drill-in management).** Sectioned search (notes + tags + projects) + **paged 4×2 project rects** (**★ CORRECTED s148: the mock's DESKTOP tile is `aspect-ratio:1` — square — at `SecondThoughtV2.html:518`; the 74px non-square rect is the PHONE variant at `:590`. "Phone tile ratio" was wrong**) + tag list + a **LIST/STARS toggle in the titlebar**.
  **★★ SHIPPED BEYOND THIS BULLET, user-ruled from a board (`DECISIONS.md` §5 s148):** the drill-in also carries a **3-dot menu (Rename · Set description · Delete, danger last)** plus the description editor, tidy-preview and folder-import — because the mock draws no management strip and P3-C had otherwise left `ProjectsPane`'s capabilities unreachable from the full window.
  **★★★ KNOWN CEILING, `ponytail:`-MARKED: desktop STARS has NO wikilink edges.** No `/links`, `/backlinks` or `/graph` route exists; `link_resolver.py` builds its index in-process at capture-write time and never persists it. Desktop draws **shared-tag edges only**, so wikilink degree is always 0 and cores never reach the 8/10px buckets. **The phone's port does NOT have this limitation — the asymmetry is real and NOT yet ruled.** **No pager and no LIST/STARS exists anywhere in the app today.** **★ s145 ruling: the desktop pager gets dots AND clickable arrows; the pill keeps dots only.** **★ Fold in FR-36 here** (`CURRENT.md` §4.2h): today the projects tile list is stale until you navigate away and back — two independent live-QA agents saw it, in two different flows, while `.projects.toml` was already correct. **★★ FR-36 IS CLOSED s148 (`5facb60`, mutation-proved) — AND THIS SENTENCE WAS WRONG.** It used to say the tile list must refetch on *project-create AND* folder-import-applied. **Project-create ALREADY refetched correctly** (`ProjectsRail.tsx:184-192` → `ProjectsView.tsx:199-209`'s `refresh({select})`); **only the folder-import path was ever broken.** It could not be fixed until s148's ruling moved folder-import INTO the drill-in, because while import lived only in the pill's `VaultManager`, BROWSE had **no `onApplied` seam to wire at all** — a missing seam, not a missing task. One `refetchProjects` is now called from rename, delete and `onApplied`. **★★ AND fold in FR-34's read-only folder surfacing** (`DECISIONS.md` §5 s146, binding): **a folder the user created by hand appears in the tags/projects panel.** Display only — **read from the filesystem, writing nothing**: no registry entry, no `#project@` tag, no body or frontmatter edit, no file move. **Do NOT offer it as an import candidate and do NOT recurse `plan_import`.** Android BROWSE gets the identical row in Phase 4 — the two panels mirror each other, and a folder visible on the phone but not the desktop reads as a bug.
  **★★★ AND STARS HERE IS THE REAL CONSTELLATION** (`DECISIONS.md` §5 s146, binding): **movement · wire connections · drag-around physics · quick peek at the dots.** `class Sky` in `SecondThoughtV2.html` is the spec and the desktop is the platform it was written for — **`skyD` is directly portable, so port the constants verbatim rather than re-deriving them.** Every force gated `if (!node.drag)`; wires wikilink solid `.30` / shared-tag dashed `3 5` at `.10`; core size encodes degree 5/8/10px; **a tap PEEKS into the ~230px card and must NOT navigate to the note** — only its OPEN NOTE button does. **Reduced motion disables the drift and the twinkle ONLY.** Phone P4-F is the sibling; **a constellation on one platform and a grid on the other is the same asymmetry FR-34's folder row was ruled against.**
- [x] **P3-D — CHAT splits from Search into its own tab. DONE s155 `e51583b`.** **`--swap-dir` is coupled to the Search=0 / Chat=1 ordering — reordering the tabs flips the slide direction SILENTLY, with no test failure.** Assert the direction after the split.
- [x] **P3-E — SYNC becomes its own tab. DONE s155 `1aa07c2`** (SYNC's real interior; Settings ▸ Sync deliberately LEFT, duplication owed a ruling; ★ the plan's "conflicts leave Dashboard" is stale — DashboardView has been dead since P3-A, so SyncFeed is the FIRST full-window-reachable conflict list), leaving Settings, rendering over **Phase 1's real endpoints** (`GET /sync/activity`, `GET /sync/pending`). Conflicts leave Dashboard. **Gaps are filled for real — no stubbed panels, no invented rows** (user decision, s143). **Binding copy rules:** at rest the panel is the local diff labelled ***"Changed since last sync"*** — **the word "queue" is BANNED there**, because it promises drain semantics only a live Drive listing can honour; it upgrades to exact *will upload · blocked · to pull* **only on an explicit user gesture** (`hub=true`, which spends one Drive listing). **The refusal state NEVER shows a count** — a corrupt ignore set returns `{}` and would render *zero pending* at the exact moment `run_pass` refuses the entire sync, and empty-reads-as-all-synced is the most dangerous failure this surface has. It renders a red ***"Sync blocked — ignore list unreadable"*** instead.
- [ ] **P3-F — glyphs + scale sweep over what Phases 3A–E touched.** Replace `→` with `»` in the 8 shipping strings and the block caret `▌` with a **blinking `_`**. Confirm every file touched by A–E adopted the scale: **a raw px in a touched file is rejected at review.** Desktop has **47** half-step sites and **58** migration sites — and note the census instrument itself: **`grep -r` reports "Binary file matches" and silently drops every hit in `NoteEditor.tsx`** (it holds a literal `\x00`), which is how an earlier count came out at 22 instead of 47. **Use Python for any census; `Grep -a` fixes the tool, a `grep -rho | sort | uniq -c` pipeline silently does not.**

---

## PHASE 4 — Android shell (concurrent with Phase 3)

| Surface | Today | Acceptance |
|---|---|---|
| Tabs | Notes·Today·Chat | **NOTES·BROWSE·CHAT. Today deleted** with its digest logic (user instruction 5). Pager indicator math updated for 3 cells |
| FAB radial | Search·Voice·Photo·Quick-Sync | **Photo·Voice·Template·Quick-Sync**, Quick-Sync in its current outer position. **Arc mechanics and measurements untouched** (instruction 6) |
| BROWSE | `search.tsx` + `tags.tsx` | Absorbs Search. Sectioned search + swipe-paged project rects + tags + LIST/STARS |
| Editor | `app/note/[id].tsx` (**not** `editor/[id].tsx`) | 3-dot becomes Reminder·Set as template·Outline·History·Delete. **Connections is replaced** — it survives on the row long-press menu |
| Templates | 3 hardcoded skeletons, `ponytail:`-marked | "Set as template" — net-new. Respect the marked ceiling |
| Toolbar / swipe | Bold·Checklist·Link·Tag·Mic·Camera, 46×44; swipe 100/70/0.25 | **Already match the mock exactly. Do not touch.** |
| Settings | 6 sections | **VISUAL NO-FLY ZONE.** Already carries Activity and Sync-status rows |

**Doc fix owed:** repo-root `CLAUDE.md` calls `chat.tsx` a placeholder. It is a real on-device Qwen2.5-1.5B engine with real RAG. Correct the doctrine. — **★ DONE s146, in the main thread, before any agent read it.**

**Acceptance:** phone green + both typechecks · emulator round (Sonnet subagent, screenshots stay there) · device burn-in per `FACTS.md` §6 before "device-done".

### Phase 4 task breakdown (s146) — three sequential runners, then an emulator round

**Why sequential:** TS agents cannot be parallelised *within one repo* — they share one worktree and collide. Desktop Phase 3 runs concurrently with all of these because it is a different repo with zero shared files.

**Every runner inherits:** the Global Constraints above · Settings is a **visual no-fly zone** · toolbar (46×44) and swipe (100/70/0.25) **already match the mock — do not touch** · no hover states on phone · inline SVG only, never emoji · `ponytail:` ceilings preserved · agents never commit and never run the full gate (the main thread does both, on a quiet tree).

- [x] **P4-A — IA restructure. DONE s146 `765a7b4`.** Delete the **Today** tab and its daily-digest logic entirely (user instruction 5, a sanctioned subtraction). Tabs become **NOTES·BROWSE·CHAT**; the pager indicator math is updated for **3 cells, not 4**. BROWSE absorbs `search.tsx` and `tags.tsx` into a sectioned search + swipe-paged project rects + tags + LIST/STARS.
  **Check:** phone `npm test` + both typechecks · **and a grep proving no importer of the deleted digest module survives** — a green gate proves neither that new code ran nor that nothing was orphaned.
- [x] **P4-B — FAB radial + editor menu + templates. DONE s146 `ac8048a`.** Radial becomes **Photo·Voice·Template·Quick-Sync**, Quick-Sync keeping its current further-out position. **Arc mechanics and measurements are FROZEN** — assert the arc constants are byte-identical before and after. Editor (`app/note/[id].tsx`, **not** `editor/[id].tsx`) 3-dot becomes **Reminder · Set as template · Outline · History · Delete (danger, last)**; **Connections is replaced there and survives on the row long-press menu** — it is moved, not deleted. "Set as template" is net-new and must respect the existing `ponytail:`-marked 3-hardcoded-skeletons ceiling rather than silently lifting it.
  **Check:** phone green + typechecks · one new runnable assertion per net-new branch.
- [x] **P4-C — type-scale migration + the two glyph swaps. DONE s147 `c6bb57c`.** Migrate the **41** raw-px sites to `font.scale`, and `font.size.body 14 → font.scale.lead 13` across its **25** call sites. **Delete `font.size` only when the last call site has moved**, and remove its value-guard test in the same commit — not before, and never by merging the two objects. Replace `→` with `»` in the shipping strings and the block caret `▌` with a **blinking `_`** (both are in the 229-glyph subset; the full 930-glyph face was offered and declined).
  **Check:** phone green + typechecks · **a raw-px sweep over every touched file — a raw px in a touched file is rejected at review.**
- [x] **★★★ P4-F — STARS is the REAL constellation. DONE s146 `12843da`. REPLACES what P4-A shipped** (`DECISIONS.md` §5 s146, binding). P4-A shipped a physics-free grid of chips **with no edges at all**; the user rejected it. **Its `ponytail:` marker understated the gap and is NOT a valid ceiling.** Required, in the user's own terms: **movement · wire connections · drag-around physics · quick peek at the dots.** `class Sky` in `SecondThoughtV2.html` is the spec and drives both platforms — **port its constants verbatim** (repulsion `2600/d²` floored at `d²≥40` · springs wikilink `k=0.015 rest=105` and shared-tag `k=0.003 rest=170` · centering `*0.0016` · drift `sin(t/1700+ph)*0.012` with `ph=i*1.7` · damping `*0.90` · clamp `x∈[26,W−26] y∈[20,H−34]` · release momentum `*1.6` · tap ≤6px). **Every force is gated `if (!node.drag)` — that anchoring IS the drag physics.** Wires: wikilink solid `.30`, shared-tag dashed `3 5` at `.10`. Core size encodes degree (5/8/10px). **A tap PEEKS into the ~230px card and must NOT navigate to the note** — only the card's OPEN NOTE button does. **Reduced motion disables the drift and the twinkle ONLY** — springs, drag and wires keep working. **No new dependency:** `react-native-svg` and `react-native-gesture-handler` are installed, **`react-native-reanimated` is NOT and must not be added** — run the sim on the JS thread via `requestAnimationFrame` + `Animated.ValueXY.setValue()`, cap the node count, and `ponytail:` the cap with reanimated + spatial partitioning as the upgrade path *if a device measurement shows dropped frames*. Force model goes in a **pure tested module**, per `graphLayout.ts`'s precedent.
- [ ] **P4-E — FR-34's read-only folder surfacing, Android half** (`DECISIONS.md` §5 s146, binding). A folder the user created by hand appears in `app/(tabs)/browse.tsx`'s tags/projects panel. **Display only — reads the filesystem, writes nothing:** no registry entry, no `#project@` tag, no body or frontmatter edit, no file move. **The desktop's P3-C row is the reference — the two panels must mirror each other**, because a folder visible on the phone but not the desktop reads as a bug. Can ride with P4-C.
- [ ] **P4-D — emulator round.** Sonnet subagent, low/medium effort. **Screenshots stay in the subagent**; the main thread reads a short verdict plus at most one failing image. Device burn-in per `FACTS.md` §6 before anything is called "device-done".

---

## CAL — the reminders calendar (net-new scope, s147, user-ruled)

**Not part of the original port.** Added by the user mid-s147; every design question is already answered in
`DECISIONS.md` §5 s147 — **read it before touching this, and do not re-open any of it.** Board:
`https://claude.ai/code/artifact/5ad97fab-d8e7-4060-a65e-9b64e8734e38`.

**The lock:** `remind_at` in a note's **frontmatter** is the truth on both platforms and is LWW-merged, so a
reminder already crosses devices. **No new store may be created.** Desktop's `sync_reminders_from_notes` runs
one way only — notes → SQLite, never back.

- [ ] **CAL-D — desktop.** (a) `omni_capture/`: a way to **create a note with `remind_at` already set** —
  today `today_view.py:130` hardcodes `remind_at=None` and `POST /reminders` writes the SQLite row only.
  Frontmatter only, never the body; do not touch `reminders.py`'s table logic or the sync pass.
  (b) `gui/`: a **fifth satellite in the NOTES capture-pane fan** (`captureRadial.ts`, shipped `e74a432`) —
  widen the angle span, never hand-place arms — and the pane morphs to **month grid above, selected day
  below**, with an inline composer (title · optional body · time · optional `#project@`).
- [ ] **CAL-P — phone.** A **calendar icon next to the gear** in the NOTES header (`app/(tabs)/index.tsx:945`)
  opening a screen — **not a tab.** Same shape and same composer. `app/reminders.tsx` under Settings stays.
- [ ] **CAL-5 — the pill, in Phase 5 and not before.** Capsule and minimal are **identical: grid only, and
  the day list REPLACES the grid on tap.** Motion stays frozen — a calendar changes what a panel contains,
  never how it moves.

**Binding across all three:** time is **never required, defaults to 08:00, and the default must be VISIBLE**
(not a hidden all-day chip) · day cell = number + ≤3 density dots then `+n` · red overdue, dim fired, plain
upcoming · **no date library on either platform** · marking a reminder done, recurring reminders, and reading
the OS calendar are **out of scope by ruling, not by omission**.

**★ OPEN, deferred by the user to a later session:** `NoteEditor.tsx:1153`'s Reminder row writes SQLite only,
so a **desktop-set reminder never reaches the phone** and is invisible to the calendar. Pre-existing. Do not
fix it inside CAL-D.

---

## PHASE 5 — Pill modes (motion frozen)

Panel targets: Look·Vault·Settings·Inbox·History·NewNote → Notes·Browse·Chat·Sync·Set·NewNote. **Count stays 6, so `PANEL_W` holds at 288.**

**The only file an agent edits for content:** `PillOverlay.tsx:244-273` (`renderPanelBody`'s switch body) plus the individual `CompactPanels/Compact*.tsx`.

**Files that must not be opened:** `compactPanel.ts` · `reconcileEdges.ts` · `reconcileApply.ts` · `App.tsx`'s reconcile effect · `CapsuleMenu.tsx` · `capsuleSlider.ts` · `CompactShell.tsx`'s structural JSX · every CSS block listed in the frozen-constants table.

**Naive-edit traps that reproduce the dead-window class:** gating `leavingPill` on `pillModeActive` · making any `setPanelReady(false)` site async · wrapping `App`'s geometry-owning shell in an ErrorBoundary · dropping the two-rAF wait before `setPanelReady(true)` in minimal mode.

**Acceptance:** gui green · re-measure and diff against `motion-baseline.json` — **zero delta** · manual cycle Minimal→Capsule→Full and back at 100/125/150%. Absorbs parked SP3-4.

---

## PHASE 6 — Closeout

Full gates both repos · `FUZZ=1` if Phase 1 touched the sync path · live CDP round on a fresh exe · device round · raw-px sweep over touched files · `PROGRESS/` §-files updated as facts land · ask the user about the push hold.

---

## Checkpoint questions — ★★★ ALL FIVE ARE ANSWERED. DO NOT RE-RAISE ANY OF THEM.

Each was returned as a rendered mock, never prose. Rulings are binding; `DECISIONS.md` §5 is authoritative.

1. **Type specimen** (Phase 2, was blocking) — **ANSWERED s144: option B, IBM Plex Mono at `+0.01em`.** Both faces are metrically identical (every glyph 600/1000 upem), so the swap moves no width. `DECISIONS.md` §5 s144.
2. **BROWSE project pager** (Phase 3) — **ANSWERED s145: desktop gets dots AND clickable arrows; the pill keeps dots only.** `DECISIONS.md` §5 s145.
3. **Editor over BROWSE** (Phase 3) — **ANSWERED s145: mock bug. The editor closes on EVERY tab switch, BROWSE included.** This overrides `SecondThoughtV2.html`. `DECISIONS.md` §5 s145.
4. **Android settings vs the mock** (Phase 4) — **ANSWERED: constraint 2 wins, the mock loses.** Settings is a visual no-fly zone on both platforms.
5. **Queue region** (Phase 1) — **ANSWERED s143 and BUILT s144.** An honest source exists (`.omni_capture/mobile_sync_state.json`); the panel is hybrid, labelled *"changed since last sync"* at rest, and the refusal state shows no count. `GET /sync/pending` ships.

**Two further s145 rulings ride with Phases 3/4 and are not on this list because they were never checkpoint questions:** `→` becomes `»` in the 8 shipping strings, and the block caret `▌` becomes a blinking `_`.

---

## Open risks

1. ~~**The typeface is a geometry change.**~~ **CLOSED — FALSE, measured 2026-08-06 (s144).** Geist Mono and IBM Plex Mono are **metrically identical**: both are 1000 upem and **every rendering glyph in both is exactly 600 units**, checked across the full character set of all three bundled weights of each face with fontTools, read straight out of the `.woff2` binaries. `"Second Thought"` is **100.80px in either face** at 12px. No width derived from a character count moves, so the swap cannot move the morph. Calibration: the same method computes 100.80px for Geist against the **100.8125px** `motion-baseline.json` recorded on the running binary — a 0.0125px delta, i.e. sub-pixel rounding. Script kept at `gui/mocks/2026-08-06-measure_fonts.py`. **The residual — and it is real — is that the V2 mock also applies a global `+0.01em` tracking, which adds 1.68px to the label. That is a tracking decision, not a font consequence, and it is one of the specimen's three options.** `CAPSULE_TEXT_W = 98` remains stale by 2.8px, but it was already stale in Geist and the swap does not worsen it.
2. **Cross-repo token equality is asserted by nothing.** Both repos define tokens independently; `phone/src/lib/tokens.ts` is a vendored copy that must track `gui/src/index.css` by hand. Deferring migration widens the window. Mitigation: Phase 2 lands all three docs in one round.
3. **Pixels are untested by 4,027 green tests.** Phase 0's corpus is the only counter-evidence, and it cannot be captured after the fact.
4. **`FluidVisualizer` and the capture types are shared between full window and pill** — a Phase 3 edit can reach Phase 5's surface.
5. **This plan can be wrong.** Five consecutive sessions have found the baton mistaken about its own state. Every phase re-verifies at source before acting.

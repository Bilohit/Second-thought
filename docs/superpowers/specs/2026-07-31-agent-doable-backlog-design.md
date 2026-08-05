# Design — the agent-doable backlog milestone (s123)

**Date:** 2026-07-31 · **Session:** s123 · **Status:** user-approved (design sections 1–3 approved in
conversation; ride-along set and scope calls answered via interview).

This spec covers the milestone the user scoped as "all" of the agent-doable backlog, minus the ship
path. Five packages, each independently shippable. Where investigation contradicted the ledger, the
source finding wins and the ledger row is corrected as part of P5.

---

## 0. What changed during investigation (read before planning)

Three ledger rows were wrong. Verified at source this session by the orchestrator, not taken from a
subagent report:

1. **O-16's "dead Stop waiting button" (P1 from s109) is ALREADY FIXED at source.** `SyncWizard.tsx:186-193`
   replaced the button with a single `Cancel` wired to `onSkipDrive`, and `SyncPanel.tsx:234-247` adds a
   60s `CONSENT_TIMEOUT_MS` auto-escape. The in-file comment names the exact original defect (the old
   button flipped local `connecting` false and the next 4s status poll read `drive.connecting` still
   true from the server and put the screen back). **The s109 QA observation reflects a stale release
   exe, not this source state.** No code is owed — only a ledger correction.

2. **OF-6 is anchored on the wrong line and is one trigger of a larger hole.** The ledger cites
   `models.py:100-104`, but that guard never fires: `llm_engine.py:322-326` raises first, because
   `build_category_descriptions()` returns `{}` for an empty vault. More importantly, the empty-vault
   case is only one of four triggers routing into `route_failed_llm` (the others: Ollama unreachable,
   request timeout, structured-output parse failure).

3. **`needs_llm_retry` is a promise the code never keeps.** `scratchpad.py:154` writes the flag; the
   only non-test reader is `scratchpad.py:185`, which merely *displays* "enrichment unavailable" in the
   Inbox row. No pass, job, or action re-runs enrichment. Inbox Approve (`server.py:1639-1693`) moves
   the file and computes an embedding but never regenerates title/tags/summary — the placeholder body
   is permanent unless hand-edited. Separately, `log_capture` runs only on the success path
   (`main.py:526`), so `--log` shows a clean history while captures silently degrade.

**The gui has no component-test infrastructure at all** — no `@testing-library/react`, no jsdom or
happy-dom, no `test.environment` in `vite.config.ts`, and `render(` appears in zero of 55 test files.
All existing coverage is indirect, via pure `lib/*` modules.

---

## 1. Scope

**In:** P1 gui component-testing infra + NoteEditor coverage · P2 enrichment retry engine + first-run
empty state · P3 panel-geometry watchdog · P4 phone store factory + `expo-system-ui` dead key · P5
desktop ride-alongs (`_notify_windows` inline, graphify refresh) + ledger truth corrections.

**Out, explicitly (user calls this session):**

- The `.aab` and **all** release signing — "no aab yet, only when product is fully ready and tested".
- Tauri `signCommand` / updater (updater already decided OFF), PS-9 store-side work.
- Every human-only QA row: O-6 DPI geometry, the s114 Inbox-row/Dashboard-REVIEW box, O-14 widget
  drag-placement, O-15 arc haptics.
- The collection-valued phone stores (`pinStore`, `syncIgnoreStore`, `noteModeStore`) — different
  shape from the scalar/enum factory.

---

## 2. P1 — gui component testing + NoteEditor coverage

**User decision:** full component-testing setup (chosen over pure-extraction-only and over the
minimal happy-dom mount test).

**Infra, surgical:** add `@testing-library/react`, `@testing-library/user-event`, `happy-dom` as
devDeps. **Do not flip vitest's global environment** — component tests opt in per file with a
`// @vitest-environment happy-dom` docblock, so the existing 534 Node-environment tests are unrisked
and unchanged. `lib/api` is mocked at the module seam with `vi.mock`, mirroring how the phone repo
mocks device APIs.

**Tests written — NoteEditor only.** The infrastructure is repo-level; the test surface is not.

| Behavior | Anchor | Failure it catches |
|---|---|---|
| Mount smoke | whole component | The s122 TDZ-`ReferenceError` class — no existing gate can see it |
| Escape precedence chain | `NoteEditor.tsx:420-432` | menu → unlock → drawer → close, in order |
| `toggleToolbarLock` mode restore | `:406-418` | unlock returns to prior mode; lock-from-edit does not |
| Menu resets on note switch | `:297-302` + `menuOpen` | the s122 fix, currently CDP-only |
| Chevron `data-hidden` + click | `.ne-peek-arrow` | the s122 fix, currently CDP-only |
| Autosave debounce + backoff | `:352-389` | retry/backoff state machine, via fake timers |

**Stated ceiling — carry as a `ponytail:` comment.** happy-dom has no layout engine;
`getBoundingClientRect` returns zeros. Every geometry assertion (dropdown `top: 56` non-overlap, the
640px no-overlap check, button hit-testability) **stays CDP-only**. P1 retires the logic half of the
live QA pass, not the geometry half. The ledger must not imply otherwise.

---

## 3. P2 — enrichment retry engine + first-run empty state

**User decision:** retry engine **and** first-run GUI prompt (chosen over retry-only and over
empty-vault-legibility-only).

### 3.1 Python core

New pure module with a sibling test, plus wiring into both duplicated pipelines.

- **`is_retryable(text)` / `placeholder_matches(text)`** — pure predicates, no I/O. A capture is
  repaired only when `needs_llm_retry: true` **and** its body still matches the `route_failed_llm`
  signature byte-for-byte. A capture the user has hand-edited is skipped permanently, never
  overwritten. This is the safety gate; it is asserted in tests.
- **`retry_pending(vault, deps)`** — scans `_scratchpad`, checks preconditions (≥1 category folder
  **and** Ollama reachable, reusing the existing `--self-check` health path), re-runs enrichment,
  regenerates title/tags/summary/embedding, and re-files the note out of `_scratchpad`. Failures are
  contained per-note: one unrepairable capture never aborts the pass.
- **Triggers:** server startup · after any successful capture · a manual **Retry** action on the
  Inbox row. A degraded capture must not wait on the user noticing.
- **Audit-log fix:** `log_capture` is extended to the failure path so `--log` stops reporting a clean
  history while captures degrade.

**Hard-rule compliance.** `main.py:run_pipeline()` and `server.py:_run_pipeline_blocking()` are
hand-duplicated *by design* (desktop `CLAUDE.md`). The retry hook lands in **both, mirrored by hand**.
No shared generator, no `on_step` callback — that inversion is explicitly forbidden.

**Lock compliance.** Captures are not notes (`origin: note`), so the body-sacred lock does not apply.
The placeholder-signature gate is nonetheless enforced, so no user-authored bytes are ever rewritten.
Vault categories stay non-hardcoded — the first-run prompt asks the *user* to create the folder.

### 3.2 GUI

Two surfaces:

1. **Retry action** on the existing "enrichment unavailable" Inbox row (`scratchpad.py:185` already
   supplies the state; `GET /inbox` already carries it).
2. **First-run empty state** for a zero-category vault, prompting the user to create their first
   category folder.

**The empty state is a design gate, not an implementation detail.** Before building it: load
`impeccable-pbakaus`, `uiux-pro-max`, `taste-skill`, `animotion`. Then produce **HTML mock options**
for the user to pick from — per workspace doctrine, design questions are never asked in prose. The
placement question (Inbox vs Vault Manager vs dashboard-level first-run banner) goes **into the
mocks** as options rather than being guessed or asked in text.

Void identity binds the mocks: Geist Mono, 0-radius, grayscale accent, border-based elevation,
semantic color only, inline SVG icons from `PillMenu/icons.tsx`, **never emoji**.

### 3.3 Why this shape

All four failure triggers route through `route_failed_llm`. Fixing that one junction repairs empty
vault, Ollama-down, timeout and parse-failure alike. Fixing OF-6 alone would have repaired one of four
and left the promised-but-absent retry in place — symptom, not root cause.

---

## 4. P3 — panel-geometry watchdog

`App.tsx` already watchdogs `panelReady` and `renderPill` at 1000ms. Nothing watchdogs `panelGeom`
itself — the "blank-but-grown panel" bug class named in s114 and never built.

Same pattern, same interval, same discipline the pill-lifecycle hard rule demands: **the watchdog only
ever forces the safe state, never the unsafe one**, and every setter site stays synchronous
(edge-detection only, never behind an `await`). Geometry math stays in the pure `lib/` modules with
their sibling tests — the watchdog is an effect, not new geometry.

Small, self-contained diff, reviewed on its own because it lands in the DPI/geometry hard-rule zone.

---

## 5. P4 — phone ride-alongs

**Store factory** over the five scalar/enum stores, all confirmed near-identical at source:
`chatModelConfig.ts` (16 lines), `chatConfig.ts` (16), `semanticConfig.ts` (26), `syncDotConfig.ts`
(28), `tagsViewModeStore.ts` (31). Each store keeps its **frozen public API**, so no call site changes.
Collection-valued stores stay out.

Recorded honestly: the orchestrator's ponytail read was that a factory over five working 20-line files
is a new abstraction bought for ~60 lines. **The user included it anyway — that is the decision, and
it is not to be relitigated.** It is built with the frozen-API constraint so the risk stays near zero.

**`expo-system-ui`:** `app.json:12` sets `"userInterfaceStyle": "dark"` while the package is not a
dependency, making the native hint a confirmed no-op. **Delete the dead key** rather than add the
dependency — the app already forces its own dark theme in JS, so adding a dep would buy nothing.

---

## 6. P5 — desktop ride-alongs + ledger truth

- **Task 8:** inline `_notify_windows` (`notifier.py:69-70`, 2-line body, exactly one caller at `:105`).
  Rewrites the two `monkeypatch.setattr` mocks in `test_notifier.py:31,43`. Net ≈ −4 lines.
- **graphify refresh:** frozen at `2026-07-21`, missing s84→s122 entirely. Invoke via
  `python -m graphify` — **not** the bare CLI (BOM trap, `FACTS.md` §6).
- **Ledger corrections** (doc-only, land in the owning §-file, never in the baton):
  - O-16's dead-button half → closed as fixed-at-source, with the stale-exe explanation.
  - OF-6 → re-anchored to `llm_engine.py:322-326`, reclassified as one trigger of the retry hole,
    pointed at P2.
  - A new `DECISIONS.md` §5 entry recording the interview calls: full component-testing setup, retry
    engine + first-run prompt, ship path deferred, ride-along set including the factory.

---

## 7. Gates and verification

| Repo | Command | Floor |
|---|---|---|
| desktop | `python -m pytest -q` (from `omni_capture/`) | ≥ **1152** passed / 4 skipped / 0 failed |
| gui | `npm test` + `npm run build` (from `gui/`) | ≥ **534** passed, build clean, exit 0 |
| phone | `npm test` + `typecheck` + `typecheck:app` | ≥ **1816** passed / 6 skipped, both clean |

`FUZZ=1` is **not required** on either side — no package touches the op-queue, sync, or reconcile
surface. If any task drifts into one, the fuzz gate becomes mandatory and the drift is reported first.

P1 and P2 add tests, so gui and desktop numbers must **rise**. Actuals get reported, never targets.
Every gate is run by the orchestrator in the main thread — never taken from a subagent's report
([[verify-subagent-claims-independently]]).

**Live QA:** P2's GUI surfaces and P3's watchdog need a CDP pass against a **freshly built** release
exe (`npm run tauri -- build --no-bundle`; the exe goes stale silently — check its mtime first, and
`cargo` needs `export PATH="$HOME/.cargo/bin:$PATH"` in Git Bash). Raw CDP mouse dispatch is unreliable
on this WebView2 app — use DOM `element.click()`.

---

## 8. Execution model

One task per `cavecrew-builder` subagent at Sonnet tier; the orchestrator reviews **every** diff
against the file, even when the plan carries literal code (s119 lesson). Perceive-act QA goes to a
Sonnet subagent with screenshots staying inside it.

**The one high-tier exception:** P2's Python core rewrites capture bodies. It stays on the orchestrator
or a high-tier agent, and its placeholder-signature gate is reviewed line by line.

A task that cannot stay behavior-preserving in execution is **stopped and reported, not bent** (s121).

---

## 9. Open risks

1. **P1 is a repo-wide convention change.** The infra invites 55 existing test files to eventually
   follow a pattern this milestone only applies to one file. Accepted deliberately; the per-file
   `@vitest-environment` docblock keeps the blast radius at zero for existing tests.
2. **P2's retry rewrites machine-authored bodies.** The placeholder-signature gate is the whole safety
   argument. If that predicate is wrong, user edits are lost — hence pure, tested, and reviewed by hand.
3. **P2's trigger set could thrash.** A permanently-failing precondition (Ollama down for days) must
   not produce a retry loop — the s104 unbounded-defer regression is the precedent. The retry pass is
   bounded per run and preconditions are checked before work, not after.
4. **P4's factory is a net-new abstraction** the orchestrator argued against. Frozen APIs keep the risk
   low, but if it grows past a thin seam in execution, it stops and reports rather than expanding.

# STARS navigation — adaptive density, SKY panel, zoom/pan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Make the STARS sky's connection density adapt to the vault, give the user a control to
fine-tune it, and make the sky navigable by zoom and pan — on **both** platforms.

**Architecture:** Three separable pieces. (1) The **shared edge model** gains a hybrid semantic floor
`max(absolute, pNN)` plus a five-step density table that moves the percentile and the per-node edge
budget together; this lives inside the marked shared block of both `starsSim.ts` files and must be
**code-identical** across repos. (2) A new pure module **`skyViewport.ts`**, mirrored in both repos,
owns all zoom/pan/label math — the force simulation keeps running in unchanged world coordinates and
a viewport transform maps world → screen. (3) Per-platform UI: a collapsible **SKY panel** holding the
density rail, the Smart-connections toggle and zoom controls, plus the gesture wiring.

**Tech Stack:** TypeScript strict. Desktop: React 18 + Vite + inline-style components (no UI library,
no Tailwind classes for this surface). Phone: React Native + `react-native-gesture-handler` +
`react-native-svg`. Vitest both sides.

## Global Constraints

- **Decisions already ruled by the user (2026-08-07, s156). Do not relitigate, do not re-ask.**
  - **D1 = hybrid floor.** `max(absolute_safety_floor, percentile)`. A pure percentile is rejected: on a
    vault of unrelated notes it draws a constellation at cosines ~0.18.
  - **D2 = a collapsible SKY panel**, **open on first visit, then it remembers** the user's last state.
  - **D3 = labels are constant size and fade out when zoomed out.**
  - **The density control is `B` — a tick rail with a square thumb.** Not a segmented control, not a
    native `<input type=range>`, not a stepper. Board:
    `https://claude.ai/code/artifact/c812b64b-c320-481d-85cd-103e7405cde4`
  - **Scope is both platforms, everything.**
- **`SEMANTIC_FLOOR = 0.62` keeps its name and value.** Its meaning is reframed: it is the absolute
  **floor**, never a ceiling. The adaptive rule may raise the effective floor above it and must never
  lower it below it. This is the entire safety argument for adaptivity — preserve it.
- **The shared block is guarded byte-for-byte by `tools/parity_edge_model.py`.** Everything between
  `THE EDGE MODEL (s152)` and `END OF THE SHARED EDGE MODEL` must be code-identical in both repos
  (comments may differ; executable lines may not). **The canonical text is in Task 1 of this plan —
  paste it, do not retype it.**
- **`CLAMP_X`/`CLAMP_Y` sit OUTSIDE the marker block.** `parity_edge_model.py` covers them via its
  `SHARED_CONSTS` list, not via the block. Do not move them.
- **Identity, non-negotiable:** IBM Plex Mono via `--mono`/`--track` (desktop) and `font.mono` (phone)
  — never a literal font stack. Type only from the s145 scale (`lib/type.ts` / `--fs-*` on desktop,
  `font.scale` on phone) — **a raw px font size is rejected at review; half-steps are banned.**
  0-radius surfaces, border-based elevation, grayscale accent, semantic colour for state only.
  **Icons are inline SVG only (`stroke=currentColor`, ~1.7 weight, 24-grid) — never emoji.**
- **`_loose` and `uncategorized` are the ABSENCE of a grouping.** They can never source an edge and
  `_loose` must never be rendered.
- **Non-trivial logic ships one runnable check, and that check must have been SEEN RED** before you
  trust it. Break the implementation deliberately, watch the test fail, restore, watch it pass. State
  in your report what you broke and what the red output was. A test that has never failed is not a test.
- **Run `python check.py 0` from the workspace root after every edit, and `python check.py 1` before
  reporting done.** Never run tier 2 or tier 3. **Never commit.** Never pipe `check.py` into `tail` or
  any pager — it reports the pager's exit code. Redirect to a file and echo `$?`.
- **A shell census over either repo is unreliable** — NUL bytes in some files make ripgrep skip them
  silently. Count with Python when a number becomes evidence.
- **If this plan is wrong, say so and stop.** It has been wrong before. Correcting the brief is a
  success, not a deviation.

---

## File Structure

| File | Repo | Responsibility |
|---|---|---|
| `gui/src/lib/starsSim.ts` | desktop | shared edge model (density table, hybrid floor) — **block is canonical** |
| `phone/src/lib/starsSim.ts` | phone | the same block, code-identical |
| `gui/src/lib/skyViewport.ts` | desktop | **new** — pure zoom/pan/label math |
| `phone/src/lib/skyViewport.ts` | phone | **new** — the same module, same text |
| `gui/src/lib/skyViewport.test.ts` | desktop | **new** — sibling test |
| `phone/src/lib/skyViewport.test.ts` | phone | **new** — sibling test |
| `gui/src/lib/starsSim.test.ts` | desktop | extended — density + hybrid floor cases |
| `phone/src/lib/starsSim.test.ts` | phone | extended — the same cases |
| `gui/src/lib/skyPrefs.ts` | desktop | **new** — persisted density index + panel-open, following `smartConnectionsPref.ts` |
| `phone/src/lib/starsConfig.ts` | phone | extended — two more `createAsyncScalarStore` entries |
| `gui/src/components/FullWindow/SkyPanel.tsx` | desktop | **new** — the collapsible panel + the tick rail |
| `gui/src/components/FullWindow/BrowseStarsView.tsx` | desktop | modified — viewport state, gestures, transform layer, labels |
| `phone/src/components/StarsSky.tsx` | phone | modified — the same, RN-flavoured (panel may be a sibling file if it grows past ~120 lines) |
| `tools/parity_edge_model.py` | workspace root | extended by the MAIN THREAD, not by an agent — do not touch |

---

## Task 1: The shared edge model — density table + hybrid floor

**Files:**
- Modify: `Second Thought/gui/src/lib/starsSim.ts` (inside the marker block, ~:254-427)
- Modify: `Second Thought - Android App/phone/src/lib/starsSim.ts` (the same block)
- Test: `gui/src/lib/starsSim.test.ts` · `phone/src/lib/starsSim.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `DensityStep`, `DENSITY_STEPS`, `DENSITY_DEFAULT_INDEX`, `densityStep(i: number): DensityStep`,
  `percentileOf(sortedAsc: readonly number[], p: number): number`,
  `adaptiveSemanticFloor(sortedAsc: readonly number[], p: number): number`,
  `pairWeight(a, b, semantic: boolean, floor?: number)`,
  `buildStarEdges(notes, allowedIds, opts: EdgeOptions)` where
  `EdgeOptions = { semantic?: boolean; densityIndex?: number }`.
  `EDGE_TOP_K` and `SEMANTIC_FLOOR` keep their names, values and exports.

- [ ] **Step 1: Write the failing tests** (identical text in both repos' `starsSim.test.ts`)

```ts
describe("density + adaptive floor (s156)", () => {
  it("percentileOf uses nearest-rank on an ascending array", () => {
    const xs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0];
    expect(percentileOf(xs, 0)).toBeCloseTo(0.1, 6);
    expect(percentileOf(xs, 100)).toBeCloseTo(1.0, 6);
    expect(percentileOf(xs, 50)).toBeCloseTo(0.5, 6);
    expect(percentileOf([], 83)).toBe(0);
    expect(percentileOf([0.42], 83)).toBeCloseTo(0.42, 6);
  });

  it("the absolute floor is a FLOOR, never a ceiling", () => {
    // A vault of unrelated notes: every cosine is low. The percentile would draw a
    // constellation over nothing; the absolute floor must win and the sky stays honestly empty.
    const unrelated = Array.from({ length: 100 }, (_, i) => 0.05 + i * 0.001).sort((a, b) => a - b);
    expect(adaptiveSemanticFloor(unrelated, 83)).toBeCloseTo(SEMANTIC_FLOOR, 6);
    // A one-topic vault: every cosine is high. Here the percentile must win, or the sky saturates.
    const oneTopic = Array.from({ length: 100 }, (_, i) => 0.8 + i * 0.001).sort((a, b) => a - b);
    expect(adaptiveSemanticFloor(oneTopic, 83)).toBeGreaterThan(SEMANTIC_FLOOR);
  });

  it("the default step still equals the shipped constants", () => {
    expect(DENSITY_STEPS[DENSITY_DEFAULT_INDEX].topK).toBe(EDGE_TOP_K);
    expect(DENSITY_STEPS).toHaveLength(5);
    // Percentile falls and budget rises monotonically as density goes up — a step that did
    // neither would be a control cell that does nothing when pressed.
    for (let i = 1; i < DENSITY_STEPS.length; i++) {
      expect(DENSITY_STEPS[i].percentile).toBeLessThan(DENSITY_STEPS[i - 1].percentile);
      expect(DENSITY_STEPS[i].topK).toBeGreaterThan(DENSITY_STEPS[i - 1].topK);
    }
  });

  it("densityStep clamps out-of-range indices instead of returning undefined", () => {
    expect(densityStep(-3)).toBe(DENSITY_STEPS[0]);
    expect(densityStep(99)).toBe(DENSITY_STEPS[DENSITY_STEPS.length - 1]);
    expect(densityStep(Number.NaN)).toBe(DENSITY_STEPS[DENSITY_DEFAULT_INDEX]);
  });

  it("raising density reveals real edges and never invents one below the absolute floor", () => {
    // Six notes, no tags, no project — the semantic pass is the ONLY signal, so edge count is a
    // pure readout of floor + budget.
    const vec = (seed: number): number[] =>
      Array.from({ length: 8 }, (_, d) => Math.sin(seed * 3.1 + d * 0.7));
    const notes = Array.from({ length: 6 }, (_, i) => ({ id: `n${i}`, tags: [], vec: vec(i) }));
    const ids = new Set(notes.map((n) => n.id));
    const at = (densityIndex: number) =>
      buildStarEdges(notes, ids, { semantic: true, densityIndex }).length;
    expect(at(4)).toBeGreaterThanOrEqual(at(DENSITY_DEFAULT_INDEX));
    expect(at(0)).toBeLessThanOrEqual(at(DENSITY_DEFAULT_INDEX));
    // Every drawn semantic edge, at every density, cleared the absolute floor.
    for (let i = 0; i < DENSITY_STEPS.length; i++) {
      for (const e of buildStarEdges(notes, ids, { semantic: true, densityIndex: i })) {
        if (e.kind !== "semantic") continue;
        const a = notes.find((n) => n.id === e.a)!;
        const b = notes.find((n) => n.id === e.b)!;
        expect(cosine(a.vec, b.vec)).toBeGreaterThanOrEqual(SEMANTIC_FLOOR);
      }
    }
  });

  it("density leaves a non-semantic sky reachable — the budget still applies", () => {
    // Tag edges never touch the floor, so this proves topK is wired, not just the percentile.
    const notes = Array.from({ length: 6 }, (_, i) => ({ id: `t${i}`, tags: ["shared"] }));
    const ids = new Set(notes.map((n) => n.id));
    const few = buildStarEdges(notes, ids, { densityIndex: 0 }).length;
    const many = buildStarEdges(notes, ids, { densityIndex: 4 }).length;
    expect(many).toBeGreaterThan(few);
  });

  it("omitting densityIndex reproduces the sky that shipped before s156", () => {
    const notes = Array.from({ length: 8 }, (_, i) => ({
      id: `d${i}`, tags: i % 2 === 0 ? ["even"] : ["odd"], project: i < 4 ? "p" : "q",
    }));
    const ids = new Set(notes.map((n) => n.id));
    expect(buildStarEdges(notes, ids, {})).toEqual(
      buildStarEdges(notes, ids, { densityIndex: DENSITY_DEFAULT_INDEX })
    );
  });
});
```

Add `cosine`, `percentileOf`, `adaptiveSemanticFloor`, `DENSITY_STEPS`, `DENSITY_DEFAULT_INDEX`,
`densityStep` to the file's existing import from `./starsSim`.

- [ ] **Step 2: Run the tests, confirm they fail for the right reason**

Workspace root:
```
python check.py 0 > /tmp/t0.log 2>&1; echo "EXIT=$?"; cat /tmp/t0.log
```
Expected: FAIL — `percentileOf is not exported` / `DENSITY_STEPS is not defined`. If it fails for any
other reason, stop and read the log; a compile error elsewhere is not this test failing.

- [ ] **Step 3: Add the canonical block text**

**This exact text goes into BOTH `starsSim.ts` files, inside the marker block, immediately after the
`SEMANTIC_FLOOR` declaration. Paste it; do not paraphrase — `parity:edge-model` compares executable
lines and any divergence fails the gate.**

```ts
/** ★ s156 (D1, user-ruled): CONNECTION DENSITY. One index moves two knobs at once — the percentile
 *  the semantic floor tracks, and the per-node edge budget. Both are needed, and for different
 *  reasons. The percentile is what makes the floor adapt to a vault's own similarity distribution.
 *  The budget is what makes the control do anything at all on a vault whose distribution the
 *  absolute floor already dominates: on the user's real vault 74 of 435 pairs clear 0.62 but only 39
 *  edges are drawn, so 35 REAL pairs are pruned by the budget alone. Raising density un-prunes those;
 *  it can never invent one, because the floor below is a max(), not a replacement. */
export interface DensityStep {
  readonly name: string;
  /** Percentile of the observed cosine distribution the semantic floor tracks. */
  readonly percentile: number;
  /** Max edges any one star may SOURCE at this step (see EDGE_TOP_K). */
  readonly topK: number;
}
export const DENSITY_STEPS: readonly DensityStep[] = [
  { name: "Minimal", percentile: 92, topK: 1 },
  { name: "Sparse", percentile: 88, topK: 2 },
  { name: "Balanced", percentile: 83, topK: 3 },
  { name: "Dense", percentile: 78, topK: 4 },
  { name: "Maximal", percentile: 70, topK: 5 },
];
/** Index of the shipped default. Measured s155 on the real vault: the fixed 0.62 floor sits at ~p83,
 *  so this step reproduces the pre-s156 sky to within one edge. Adaptivity cannot regress the one
 *  case anybody can actually see — that is why p83 is the default and not a rounder number. */
export const DENSITY_DEFAULT_INDEX = 2;

/** Clamped lookup. A persisted preference can be anything — an out-of-range index must resolve to a
 *  real step, never to `undefined` that then reads as a missing topK deep inside the budget loop. */
export function densityStep(i: number): DensityStep {
  if (!Number.isFinite(i)) return DENSITY_STEPS[DENSITY_DEFAULT_INDEX];
  const k = Math.min(Math.max(Math.round(i), 0), DENSITY_STEPS.length - 1);
  return DENSITY_STEPS[k];
}

/** Nearest-rank percentile over an array sorted ASCENDING. `p` is 0..100. An empty distribution
 *  scores 0, which makes the max() below fall back to the absolute floor — the safe direction. */
export function percentileOf(sortedAsc: readonly number[], p: number): number {
  if (sortedAsc.length === 0) return 0;
  const q = Math.min(Math.max(p, 0), 100) / 100;
  const idx = Math.min(sortedAsc.length - 1, Math.max(0, Math.ceil(q * sortedAsc.length) - 1));
  return sortedAsc[idx];
}

/** THE HYBRID RULE (D1-C). `SEMANTIC_FLOOR` is the FLOOR, never a ceiling: the percentile may raise
 *  the bar on a vault whose notes are all alike, and may never lower it on a vault whose notes are
 *  all unrelated. Measured across three vault shapes — real / one-topic / unrelated — this is the
 *  only rule that stays honest in all three: a pure percentile keeps the top 17% of an unrelated
 *  vault at cosines around 0.18 and draws a constellation over nothing. */
export function adaptiveSemanticFloor(sortedAsc: readonly number[], p: number): number {
  return Math.max(SEMANTIC_FLOOR, percentileOf(sortedAsc, p));
}
```

Then change `pairWeight`'s signature and its semantic bid:

```ts
export function pairWeight(
  a: StarSourceNote,
  b: StarSourceNote,
  semantic: boolean,
  floor: number = SEMANTIC_FLOOR
): { weight: number; kind: SimEdgeKind } | null {
```

and inside it replace the semantic block with:

```ts
  if (semantic && a.vec && b.vec) {
    const s = cosine(a.vec, b.vec);
    if (s >= floor) {
      // Normalised against the EFFECTIVE floor, so a just-passing edge is weight 0.5 at every
      // density rather than drifting as the floor moves. `span` guards a degenerate floor of 1.
      const span = Math.max(1 - floor, 1e-6);
      bid(W_SEMANTIC_BASE + W_SEMANTIC_SPAN * ((s - floor) / span), "semantic");
    }
  }
```

Extend `EdgeOptions`:

```ts
export interface EdgeOptions {
  /** The opt-in semantic pass (DECISIONS §5 s152). Default OFF — the user's own call. */
  semantic?: boolean;
  /** Index into DENSITY_STEPS. Omitted = the shipped default (s156). */
  densityIndex?: number;
}
```

and rewrite `buildStarEdges`'s body opening and its budget line:

```ts
export function buildStarEdges(
  notes: readonly StarSourceNote[],
  allowedIds: ReadonlySet<string>,
  opts: EdgeOptions = {}
): SimEdge[] {
  const semantic = opts.semantic ?? false;
  const step = densityStep(opts.densityIndex ?? DENSITY_DEFAULT_INDEX);
  const included = notes.filter((n) => allowedIds.has(n.id));

  // Pass 1: the observed cosine distribution, needed before ANY pair can be judged — the floor is a
  // property of the whole vault, not of a pair. Only runs when the semantic bid is on.
  // ponytail: cosine is computed twice per pair (here, then again in pairWeight). At NODE_CAP=100
  // that is 2 x 4,950 x 384 multiplies, run once per data change behind a useMemo, not per frame —
  // measured negligible. Cache pass 1 into a Map keyed by edgeKey if a profile ever shows it.
  let floor = SEMANTIC_FLOOR;
  if (semantic) {
    const cosines: number[] = [];
    for (let i = 0; i < included.length; i++) {
      for (let j = i + 1; j < included.length; j++) {
        const a = included[i];
        const b = included[j];
        if (a.vec && b.vec) cosines.push(cosine(a.vec, b.vec));
      }
    }
    cosines.sort((x, y) => x - y);
    floor = adaptiveSemanticFloor(cosines, step.percentile);
  }

  const scored = new Map<string, SimEdge>();
  const candidates = new Map<string, string[]>();
```

Inside the scoring loop, `pairWeight(a, b, semantic)` becomes `pairWeight(a, b, semantic, floor)`.
In the budget loop, `keys.slice(0, EDGE_TOP_K)` becomes `keys.slice(0, step.topK)`.

Leave `EDGE_TOP_K`'s declaration and its doc comment exactly where they are — it is still the default
step's budget, it is still exported, and `parity_edge_model.py` and existing tests both reference it.

- [ ] **Step 4: Run the tests, confirm they pass in BOTH repos**

```
python check.py 0 > /tmp/t0.log 2>&1; echo "EXIT=$?"; cat /tmp/t0.log
```
Expected: PASS.

- [ ] **Step 5: PROVE the parity guard is live**

```
python tools/parity_edge_model.py; echo "EXIT=$?"
```
Expected: `parity:edge-model OK - <N> identical code lines, 10 shared constants identical`, exit 0.
**Then deliberately change one digit in ONE repo's `DENSITY_STEPS` (e.g. `percentile: 83` → `84`),
re-run, and confirm it prints `FAILED` with that line as the first divergence. Restore it.** Report
both outputs. A parity check you did not watch fail is not evidence the block is guarded.

- [ ] **Step 6: Probe the new tests RED**

Break `adaptiveSemanticFloor` to `return percentileOf(sortedAsc, p);` (drop the `max`). Re-run. The
"absolute floor is a FLOOR, never a ceiling" test must fail. Restore. Report the red output verbatim.

- [ ] **Step 7: Report — do not commit.** State: both repos edited, parity output before/after the
deliberate break, the red output from Step 6, and `check.py 0` exit codes.

---

## Task 2: `skyViewport.ts` — the pure zoom/pan/label math

**Files:**
- Create: `gui/src/lib/skyViewport.ts` and `phone/src/lib/skyViewport.ts` — **same text in both**
- Create: `gui/src/lib/skyViewport.test.ts` and `phone/src/lib/skyViewport.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `Viewport`, `IDENTITY_VIEWPORT`, `ZOOM_MIN`, `ZOOM_MAX`, `ZOOM_DEFAULT`, `ZOOM_STEP`,
  `LABEL_FADE_START`, `LABEL_FADE_END`, `clampScale`, `zoomAt`, `panBy`, `clampPan`, `worldToScreen`,
  `screenToWorld`, `labelCounterScale`, `labelOpacity`, `zoomPercent`.

- [ ] **Step 1: Write the failing test** (same text both repos)

```ts
import { describe, expect, it } from "vitest";
import {
  clampPan, clampScale, IDENTITY_VIEWPORT, labelOpacity, labelCounterScale, panBy,
  screenToWorld, worldToScreen, ZOOM_MAX, ZOOM_MIN, zoomAt, zoomPercent,
} from "./skyViewport";

describe("skyViewport", () => {
  it("clamps scale to the documented range", () => {
    expect(clampScale(0.001)).toBe(ZOOM_MIN);
    expect(clampScale(99)).toBe(ZOOM_MAX);
    expect(clampScale(1)).toBe(1);
    expect(clampScale(Number.NaN)).toBe(1);
  });

  it("zoomAt keeps the point under the cursor fixed — the whole reason it exists", () => {
    const vp = { scale: 1, panX: 0, panY: 0 };
    const anchor = { x: 300, y: 180 };
    const before = screenToWorld(vp, anchor.x, anchor.y);
    const zoomed = zoomAt(vp, 1.25, anchor.x, anchor.y);
    const after = worldToScreen(zoomed, before.x, before.y);
    expect(after.x).toBeCloseTo(anchor.x, 6);
    expect(after.y).toBeCloseTo(anchor.y, 6);
  });

  it("zoomAt cannot escape the scale range, and stops panning once clamped", () => {
    let vp = { scale: ZOOM_MAX, panX: -40, panY: -20 };
    const same = zoomAt(vp, 2, 100, 100);
    expect(same.scale).toBe(ZOOM_MAX);
    expect(same.panX).toBeCloseTo(-40, 6);
    expect(same.panY).toBeCloseTo(-20, 6);
  });

  it("worldToScreen and screenToWorld round-trip", () => {
    const vp = { scale: 1.7, panX: -120, panY: 35 };
    const w = screenToWorld(vp, 410, 260);
    const s = worldToScreen(vp, w.x, w.y);
    expect(s.x).toBeCloseTo(410, 6);
    expect(s.y).toBeCloseTo(260, 6);
  });

  it("clampPan centres content smaller than the viewport and bounds it when larger", () => {
    // At 1x the world is exactly the viewport: there is nothing to pan to, so pan pins to 0.
    const at1 = clampPan({ scale: 1, panX: 90, panY: -40 }, 800, 500, 800, 500);
    expect(at1.panX).toBeCloseTo(0, 6);
    expect(at1.panY).toBeCloseTo(0, 6);
    // Zoomed in, pan is bounded so the sky's edge can never be dragged inside the viewport.
    const at2 = clampPan({ scale: 2, panX: 500, panY: 500 }, 800, 500, 800, 500);
    expect(at2.panX).toBeCloseTo(0, 6);
    const far = clampPan({ scale: 2, panX: -5000, panY: 0 }, 800, 500, 800, 500);
    expect(far.panX).toBeCloseTo(800 - 1600, 6);
  });

  it("labels fade out below the start and are solid at the end", () => {
    expect(labelOpacity(0.4)).toBe(0);
    expect(labelOpacity(0.5)).toBe(0);
    expect(labelOpacity(0.85)).toBe(1);
    expect(labelOpacity(2.5)).toBe(1);
    expect(labelOpacity(0.675)).toBeCloseTo(0.5, 2);
  });

  it("labels counter-scale so they render at a constant pixel size", () => {
    expect(labelCounterScale({ ...IDENTITY_VIEWPORT, scale: 2 })).toBeCloseTo(0.5, 6);
    expect(labelCounterScale({ ...IDENTITY_VIEWPORT, scale: 0.5 })).toBeCloseTo(2, 6);
  });

  it("panBy is relative and zoomPercent is a whole number", () => {
    expect(panBy({ scale: 1, panX: 10, panY: 10 }, -4, 6)).toEqual({ scale: 1, panX: 6, panY: 16 });
    expect(zoomPercent(1.234)).toBe(123);
  });
});
```

- [ ] **Step 2: Run it, confirm it fails**

```
python check.py 0 > /tmp/t0.log 2>&1; echo "EXIT=$?"; cat /tmp/t0.log
```
Expected: FAIL — cannot resolve `./skyViewport`.

- [ ] **Step 3: Create the module** (same text in both repos)

```ts
/**
 * skyViewport.ts — the STARS sky's zoom/pan viewport (s156, D3 user-ruled). Pure math, no platform
 * types, so the desktop copy and `phone/src/lib/skyViewport.ts` are the SAME TEXT. Kept in lockstep
 * by hand and by `tools/parity_edge_model.py`, which compares this file's marked block across repos
 * — the same guard the edge model uses, added after `CLAMP_X` drifted 26-vs-66 between the two
 * `starsSim.ts` files with every gate green.
 *
 * The force simulation is NOT viewport-aware and must stay that way: `stepSimulation` keeps running
 * in world coordinates over the host's own width/height, and this module only maps world -> screen
 * for rendering. That separation is what keeps zoom from changing the physics — a sky that settles
 * differently at 2x than at 1x would be a different sky, not a magnified one.
 */

// ══ THE SKY VIEWPORT (s156) — THIS BLOCK IS KEPT IDENTICAL IN THE SIBLING REPO. ═════════════════
export interface Viewport {
  /** Screen pixels per world pixel. */
  scale: number;
  /** Screen offset applied AFTER the scale: screen = world * scale + pan. */
  panX: number;
  panY: number;
}

export const ZOOM_MIN = 0.4;
export const ZOOM_MAX = 2.5;
export const ZOOM_DEFAULT = 1;
/** One button press or one wheel notch. Multiplicative, so zooming out then in returns exactly. */
export const ZOOM_STEP = 1.25;
/** Below this scale a label is fully gone; at or above LABEL_FADE_END it is fully opaque. Labels
 *  render at a CONSTANT pixel size (D3-C), so without this ramp a zoomed-out sky becomes an
 *  unreadable mat of overlapping text rather than a shape. */
export const LABEL_FADE_START = 0.5;
export const LABEL_FADE_END = 0.85;

export const IDENTITY_VIEWPORT: Viewport = { scale: ZOOM_DEFAULT, panX: 0, panY: 0 };

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/** A persisted or gesture-derived scale can be anything, including NaN from a divide-by-zero in a
 *  pinch handler. NaN resolves to the default rather than propagating into every transform. */
export function clampScale(s: number): number {
  if (!Number.isFinite(s)) return ZOOM_DEFAULT;
  return Math.min(Math.max(s, ZOOM_MIN), ZOOM_MAX);
}

export function worldToScreen(vp: Viewport, x: number, y: number): { x: number; y: number } {
  return { x: x * vp.scale + vp.panX, y: y * vp.scale + vp.panY };
}

export function screenToWorld(vp: Viewport, x: number, y: number): { x: number; y: number } {
  return { x: (x - vp.panX) / vp.scale, y: (y - vp.panY) / vp.scale };
}

/** Zoom by `factor`, keeping whatever world point currently sits under (screenX, screenY) exactly
 *  there. Anchoring on the cursor is the difference between zooming and teleporting. */
export function zoomAt(vp: Viewport, factor: number, screenX: number, screenY: number): Viewport {
  const scale = clampScale(vp.scale * factor);
  if (scale === vp.scale) return vp;
  const world = screenToWorld(vp, screenX, screenY);
  return { scale, panX: screenX - world.x * scale, panY: screenY - world.y * scale };
}

export function panBy(vp: Viewport, dx: number, dy: number): Viewport {
  return { scale: vp.scale, panX: vp.panX + dx, panY: vp.panY + dy };
}

/** Keep the sky on screen. When the scaled world is smaller than the viewport it is centred and pan
 *  is not a user-controllable axis at all; when it is larger, pan is bounded so an edge of the sky
 *  can never be dragged inside the viewport. At 1x the world IS the viewport, so panning does
 *  nothing — which is correct: there is nothing outside it to reach. */
export function clampPan(vp: Viewport, worldW: number, worldH: number, viewW: number, viewH: number): Viewport {
  const axis = (pan: number, world: number, view: number): number => {
    const content = world * vp.scale;
    if (content <= view) return (view - content) / 2;
    return Math.min(Math.max(pan, view - content), 0);
  };
  return { scale: vp.scale, panX: axis(vp.panX, worldW, viewW), panY: axis(vp.panY, worldH, viewH) };
}

/** Labels are drawn inside the scaled layer, so they need the inverse to render at constant px. */
export function labelCounterScale(vp: Viewport): number {
  return 1 / vp.scale;
}

export function labelOpacity(scale: number): number {
  return clamp01((scale - LABEL_FADE_START) / (LABEL_FADE_END - LABEL_FADE_START));
}

export function zoomPercent(scale: number): number {
  return Math.round(scale * 100);
}
// ══ END OF THE SHARED SKY VIEWPORT ═══════════════════════════════════════════════════════════════
```

**Note on the marker comments:** `THE SKY VIEWPORT (s156)` and `END OF THE SHARED SKY VIEWPORT` are
the exact strings the MAIN THREAD wires into `tools/parity_edge_model.py` as this file's marker pair.
Reword either one and the guard silently stops covering the file. Do not touch them.

- [ ] **Step 4: Run the tests, both repos** — `python check.py 0`, expect PASS.

- [ ] **Step 5: Probe RED.** Change `zoomAt` to ignore the anchor (`return { scale, panX: vp.panX,
panY: vp.panY }`). The "keeps the point under the cursor fixed" test must fail. Restore. Report the
red output.

- [ ] **Step 6: Report — do not commit.**

---

## Task 3 (DESKTOP): the SKY panel, the tick rail, and zoom/pan in `BrowseStarsView`

**Files:**
- Create: `gui/src/components/FullWindow/SkyPanel.tsx`
- Create: `gui/src/components/FullWindow/SkyPanel.test.tsx`
- Create: `gui/src/lib/skyPrefs.ts`
- Modify: `gui/src/components/FullWindow/BrowseStarsView.tsx`

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces: `SkyPanel` (default export) with props
  `{ open, onOpenChange, densityIndex, onDensityChange, smartConnections, onSmartConnectionsChange,
  scale, onZoomIn, onZoomOut, onZoomReset, edgeCount }`;
  `useSkyPrefs()` from `lib/skyPrefs.ts` returning
  `{ densityIndex, setDensityIndex, panelOpen, setPanelOpen }`.

- [ ] **Step 1: Read the two files you are copying patterns from, before writing anything.**
  `gui/src/lib/smartConnectionsPref.ts` — `skyPrefs.ts` must follow its persistence + cross-surface
  live-update shape exactly, not a new one. `gui/src/components/ui/Toggle.tsx` — the panel reuses it.

- [ ] **Step 2: Write the failing test** `SkyPanel.test.tsx`

The rail is `role="slider"`. **This test is the reason option B was chosen over a native input — a
hand-rolled slider owns its own keyboard contract, and an untested one is an inaccessible one.**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SkyPanel from "./SkyPanel";
import { DENSITY_STEPS } from "../../lib/starsSim";

const base = {
  open: true, onOpenChange: () => {}, densityIndex: 2, onDensityChange: () => {},
  smartConnections: false, onSmartConnectionsChange: () => {}, scale: 1,
  onZoomIn: () => {}, onZoomOut: () => {}, onZoomReset: () => {}, edgeCount: 39,
};

describe("SkyPanel", () => {
  it("exposes the rail as a slider with the real ARIA range", () => {
    render(<SkyPanel {...base} />);
    const rail = screen.getByRole("slider", { name: /density/i });
    expect(rail).toHaveAttribute("aria-valuemin", "1");
    expect(rail).toHaveAttribute("aria-valuemax", String(DENSITY_STEPS.length));
    expect(rail).toHaveAttribute("aria-valuenow", "3");
    expect(rail).toHaveAttribute("aria-valuetext", "Balanced");
  });

  it("drives density from the keyboard in both directions and to both ends", () => {
    const onDensityChange = vi.fn();
    render(<SkyPanel {...base} onDensityChange={onDensityChange} />);
    const rail = screen.getByRole("slider", { name: /density/i });
    fireEvent.keyDown(rail, { key: "ArrowRight" });
    expect(onDensityChange).toHaveBeenLastCalledWith(3);
    fireEvent.keyDown(rail, { key: "ArrowLeft" });
    expect(onDensityChange).toHaveBeenLastCalledWith(1);
    fireEvent.keyDown(rail, { key: "Home" });
    expect(onDensityChange).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(rail, { key: "End" });
    expect(onDensityChange).toHaveBeenLastCalledWith(DENSITY_STEPS.length - 1);
  });

  it("cannot step past either end", () => {
    const onDensityChange = vi.fn();
    const { rerender } = render(<SkyPanel {...base} densityIndex={0} onDensityChange={onDensityChange} />);
    fireEvent.keyDown(screen.getByRole("slider", { name: /density/i }), { key: "ArrowLeft" });
    expect(onDensityChange).toHaveBeenLastCalledWith(0);
    rerender(<SkyPanel {...base} densityIndex={DENSITY_STEPS.length - 1} onDensityChange={onDensityChange} />);
    fireEvent.keyDown(screen.getByRole("slider", { name: /density/i }), { key: "ArrowRight" });
    expect(onDensityChange).toHaveBeenLastCalledWith(DENSITY_STEPS.length - 1);
  });

  it("names the current step and the resulting connection count", () => {
    render(<SkyPanel {...base} />);
    expect(screen.getByText(/Balanced/)).toBeInTheDocument();
    expect(screen.getByText(/39/)).toBeInTheDocument();
  });

  it("collapses to a single control that reopens it", () => {
    const onOpenChange = vi.fn();
    render(<SkyPanel {...base} open={false} onOpenChange={onOpenChange} />);
    expect(screen.queryByRole("slider")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /sky/i }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });
});
```

- [ ] **Step 3: Run it, confirm it fails** — `python check.py 0`, expect "Cannot find module './SkyPanel'".

- [ ] **Step 4: Build `lib/skyPrefs.ts`**

Two persisted values, following `smartConnectionsPref.ts`'s existing shape (same storage mechanism,
same cross-surface live update, same test seam):
- `omni-stars-density` → the density index, default `DENSITY_DEFAULT_INDEX`. A stored value that is
  not a valid index must resolve through `densityStep`, never crash.
- `omni-stars-panel-open` → the SKY panel's open state. **Default `true` when the key is ABSENT
  (D2: open on first visit), `false` only when the user has actually collapsed it.** Do not use a
  `"1"`-means-on decode that makes a missing key read as closed — that is the opposite of the ruling.

- [ ] **Step 5: Build `SkyPanel.tsx`**

Structure, top to bottom. All sizes come from `lib/type.ts` (`micro`, `label`) and all colours from
`var(--*)` tokens — **no raw px font size, no invented colour, no emoji, no border radius.**

- **Collapsed:** one bordered button, label `SKY`, `aria-expanded={false}`. Sits where today's
  Smart-connections row sits (`position: absolute; top: 12; right: 14`).
- **Open:** a 186px-wide panel, `background: var(--glass-bg)`, `border: 1px solid var(--border)`.
  - Header row: `SKY` + a chevron button (`aria-expanded`, `aria-label="Collapse sky controls"`).
    The chevron is an **inline SVG**, `stroke="currentColor"`, `strokeWidth={1.7}`, 24-grid.
  - `DENSITY` group: the tick rail, then a hint line reading `{step.name} · {edgeCount} connections`.
  - The Smart-connections `Toggle` row, moved here verbatim from `BrowseStarsView` — keep its
    existing `title={SMART_CONNECTIONS_EXPLANATION}` tooltip.
  - `ZOOM` group: `−` / `{zoomPercent(scale)}%` / `+` buttons plus a `RESET` button.
    Disable `−` at `ZOOM_MIN` and `+` at `ZOOM_MAX` — a control that silently does nothing reads as
    broken. Use `font-variant-numeric: tabular-nums` on the percentage so it does not jitter.

**The tick rail (D-B), exact contract:**
- Container `role="slider"`, `tabIndex={0}`, `aria-label="Connection density"`, `aria-valuemin={1}`,
  `aria-valuemax={DENSITY_STEPS.length}`, `aria-valuenow={densityIndex + 1}`,
  `aria-valuetext={step.name}`.
- Visual: a 1px full-width track in `var(--border)`; a 1px fill in `var(--text-3)` from the left to
  the thumb; five 1px ticks; a **square** thumb (7×11, `var(--text-1)`, **no border radius**).
- Keyboard: `ArrowRight`/`ArrowUp` → `+1`, `ArrowLeft`/`ArrowDown` → `−1`, `Home` → `0`,
  `End` → last. Clamp at both ends. `e.preventDefault()` on each.
- Pointer: `onPointerDown` captures the pointer, and both down and move map the x offset within the
  track to the nearest step index — `Math.round((x / trackWidth) * (DENSITY_STEPS.length - 1))`,
  clamped. Read the track width from the event target's `getBoundingClientRect()`, not from a
  hardcoded 186. Emit `onDensityChange` only when the index actually changes, or every mouse move
  refetches the sky.
- `:focus-visible` must show a visible ring (`outline: 1px solid var(--text-1)`). Do not remove it.

- [ ] **Step 6: Run the tests, expect PASS** — `python check.py 0`.

- [ ] **Step 7: Wire `BrowseStarsView.tsx`**

1. `const [vp, setVp] = useState<Viewport>(IDENTITY_VIEWPORT);` and `useSkyPrefs()`.
2. Pass `densityIndex` into the existing `buildStarEdges` memo:
   `{ semantic: smartConnections, densityIndex }`, and add `densityIndex` to its dep array.
3. **Wrap the SVG and the stars — and nothing else — in a transform layer:**
   ```tsx
   <div style={{ position: "absolute", inset: 0, transform: `translate(${vp.panX}px, ${vp.panY}px) scale(${vp.scale})`, transformOrigin: "0 0" }}>
   ```
   The SKY panel, the empty-state notices, the legend and the peek card stay **outside** it.
4. **Edge strokes:** add `vectorEffect="non-scaling-stroke"` to each `<line>` so wires stay 1px at
   every zoom. Do not divide `strokeWidth` by scale by hand — the SVG attribute is the native answer.
5. **Labels (D3-C):** on the `.bs-lbl` div add
   `transform: scale(${labelCounterScale(vp)})`, `transformOrigin: "top center"`,
   `opacity: labelOpacity(vp.scale)`, `pointerEvents: "none"`. Star **cores** keep scaling with the
   sky — only labels are counter-scaled.
6. **Wheel zoom:** `onWheel` on the host. `e.preventDefault()`; factor is `ZOOM_STEP` when
   `e.deltaY < 0`, `1 / ZOOM_STEP` otherwise; anchor at the pointer **relative to the host rect**;
   then `clampPan(..., size.w, size.h, size.w, size.h)`.
   ★ React attaches wheel listeners passively — call `preventDefault` from a **non-passive**
   `addEventListener("wheel", handler, { passive: false })` in an effect, not from the JSX `onWheel`
   prop, or the browser logs "Unable to preventDefault inside passive event listener" and the page
   scroll fights the zoom.
7. **Background pan:** `onPointerDown` on the host. **Ignore the event when it originated on a star**
   — check `(e.target as HTMLElement).closest(".bs-star")` and bail. Otherwise capture the pointer,
   `panBy` on move, `clampPan` after. Cursor `grab`/`grabbing` on the host only while panning.
8. **Star drag must divide by scale.** In `onPointerMove`, `node.x += dx / vp.scale` (same for `y`),
   or a dragged star runs away from the cursor at any zoom other than 1. Read the scale from a ref,
   not from the closure, so the handler is not stale.
9. **Peek card:** it lives outside the transform, so position it with
   `worldToScreen(vp, node.x, node.y)` before the existing clamp arithmetic.
10. **Reset:** `onZoomReset` sets `IDENTITY_VIEWPORT`. Also reset the viewport whenever the star id
    set changes (the existing `idsKey` effect) — a vault that changed under a 2.5× zoom leaves the
    user staring at empty space.
11. **Delete the old `smartRowStyle` block and its JSX** — the toggle now lives in the panel. Removing
    it is required by this task, not scope creep; leaving both would render the control twice.

- [ ] **Step 8: Add one mount-census row** for `SkyPanel.tsx` in `gui/src/__census__/` if that census
enumerates components explicitly — read the census file first and follow whatever it already does.
**A component with passing tests and no import path from `src/main.tsx` fails `check.py 1`.**

- [ ] **Step 9: `python check.py 1 > /tmp/t1.log 2>&1; echo "EXIT=$?"; cat /tmp/t1.log`** — expect all
checks PASS, including `reachability` (the baseline file is EMPTY; a new unreachable component fails
it) and `parity:identity` (**64 known** — a new entry means you wrote a literal font stack or a raw
px size; fix the code, **never** add a line to `tools/identity-baseline.txt`).

- [ ] **Step 10: Probe RED.** Break the rail's `ArrowLeft` branch. Confirm the keyboard test fails.
Restore. Report the red output.

- [ ] **Step 11: Report — do not commit.**

---

## Task 4 (PHONE): the SKY panel, the tick rail, and pinch/pan in `StarsSky`

**Files:**
- Create: `phone/src/components/SkyPanel.tsx` (+ `SkyPanel.test.tsx` if the repo's component tests
  can render it — **check first**; this repo has no render-level automated coverage, so if RN
  components are not renderable under vitest here, put the rail's index math in a pure helper in
  `lib/skyViewport.ts`-style module and test THAT instead of faking a render test)
- Modify: `phone/src/lib/starsConfig.ts`
- Modify: `phone/src/components/StarsSky.tsx`

**Interfaces:** identical props to the desktop `SkyPanel` (Task 3), RN primitives instead of DOM.

- [ ] **Step 1: Read `phone/src/lib/starsConfig.ts` and `phone/src/lib/tokens.ts` first.** The two new
prefs follow `createAsyncScalarStore` exactly; every size comes from `font.scale` and `space`, the
typeface from `font.mono`. **Never a literal font stack, never a raw px font size.**

- [ ] **Step 2: Extend `starsConfig.ts`** with two stores:
- `st.stars.density` → number, default `DENSITY_DEFAULT_INDEX`, decoded through `densityStep`'s
  clamping so a corrupt value cannot produce `undefined`.
- `st.stars.panelOpen` → boolean, **default `true` when the key is absent** (D2), `false` only once
  the user has collapsed it. Note that `starsConfig.ts`'s existing `decode: (raw) => raw === "1"`
  gives the OPPOSITE default — do not copy that line for this key.

- [ ] **Step 3: Build the panel + rail.** Same contract as Task 3 visually, RN accessibility instead
of ARIA: `accessibilityRole="adjustable"`, `accessibilityValue={{ min: 1, max: 5, now: i + 1,
text: step.name }}`, and `onAccessibilityAction` handling `increment`/`decrement` — that is RN's
equivalent of the desktop arrow-key contract and a screen-reader user has no other way to move it.
Rail drag is an RNGH `Gesture.Pan()` on the rail, mapping `x` within the measured track to the
nearest step; measure with `onLayout`, never a hardcoded width.

- [ ] **Step 4: Wire `StarsSky.tsx`.**
1. Load both prefs; pass `densityIndex` into the existing `buildStarEdges` memo and its deps.
2. Wrap the `<Svg>` and the star `<View>`s in a transformed container:
   `transform: [{ translateX: vp.panX }, { translateY: vp.panY }, { scale: vp.scale }]`.
   ★ **RN scales about the view's CENTRE unless `transformOrigin: "0 0"` is set** (RN 0.74+).
   **Verify this repo's RN version supports `transformOrigin` before relying on it.** If it does not,
   say so and stop — do not silently compensate with hand-tuned translate offsets, because that
   arithmetic is exactly what drifts from the desktop copy.
3. **Gestures, chosen so nothing races:** the sky's pan is `Gesture.Pan().minPointers(2)` and the
   pinch is `Gesture.Pinch()`, composed with `Gesture.Simultaneous`. **A star's own drag stays
   one-finger**, so it can never conflict with a two-finger sky pan. Do not try to arbitrate a
   one-finger sky pan against the star drag — that is the race this design avoids.
   Note the existing trap: **RNGH's `onEnd` is ACTIVE-gated, `onFinalize` is not.** Release/cleanup
   logic belongs in `onFinalize`.
4. Pinch anchors at the gesture's `focalX`/`focalY`; then `clampPan` with the measured sky size.
5. **Star drag divides its delta by `vp.scale`.**
6. Labels: `transform: [{ scale: labelCounterScale(vp) }]`, `opacity: labelOpacity(vp.scale)`.
   Star cores keep scaling with the sky.
7. **Reduced motion:** `reduceMotionActive` is already imported. Under it, zoom and pan apply
   instantly — no animated transition. Do not disable zoom itself; reduced motion is not reduced
   function.
8. Remove the old inline Smart-connections offer row **only if** it is now duplicated by the panel;
   the three empty-sky notices (`offer-smart` / `needs-embeddings` / `sparse`) **stay exactly as they
   are** — they are a shipped, user-ruled affordance, not chrome.

- [ ] **Step 5: `python check.py 0`** after every edit; **`python check.py 1`** before reporting.
Expect `phone:census` **25 passed** and `parity:identity` **64 known** — a new identity entry means a
raw px size or a literal font stack in what you wrote.

- [ ] **Step 6: Probe RED** — break the rail's index math (drop the clamp) and confirm your test
fails. Restore. Report the red output.

- [ ] **Step 7: Report — do not commit.**

---

## Verification (MAIN THREAD only — agents never run these)

- `python check.py 2` on a quiet tree, exit code **captured, never piped**. Baselines that must
  reproduce: desktop **1453 passed · 4 skipped**, gui **917 + the new tests**, phone
  **1924 passed · 6 skipped**.
- `python tools/parity_edge_model.py` — must cover **both** `starsSim.ts` and `skyViewport.ts` after
  the main thread extends it.
- Rebuild the exe (`npm run tauri -- build --no-bundle` from `gui/`) and run a live CDP round: zoom
  to both limits, pan at 2×, drag a star at 2×, watch labels fade, drive the rail by keyboard.
- Commit per repo, scoped pathspec, no `Co-Authored-By`, never `--no-verify`.

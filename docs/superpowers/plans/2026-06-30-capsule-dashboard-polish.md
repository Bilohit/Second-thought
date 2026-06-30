# Capsule & Dashboard Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Run each task's check before moving on, and close with superpowers:verification-before-completion.

**Goal:** Fix five capsule-menu / dashboard regressions (center-zone open jerk, horizontal scroll, hover-shading edge gap, asymmetric right-side easing, sharp→rounded corner clip) without touching the now-shipped directional-morph base.

**Architecture:** All changes are presentation-layer: TS style props in two React components, CSS rules in one stylesheet, and one timing module. The directional-morph zone machine (`capsuleZone` → window x / justify / stagger / transform-origin) from `CAPSULE_DIRECTIONAL_MORPH_PLAN.md` is **already complete and load-bearing** — extend its CSS/physics, never re-architect it. Each visual fix is first reproduced and tuned in a standalone HTML mock under `docs/archive/`, then ported to the live CSS.

**Tech Stack:** React 18 (hooks only), TailwindCSS 3 + hand-written `index.css`, TypeScript strict, Vitest. No new dependencies.

## Skill Matrix (verified installed)

| Plan label | Installed skill | Role |
|---|---|---|
| `caveman` | `caveman` ✓ | Terse compressed execution; surgical 1-2 file edits via `caveman:cavecrew-builder` subagent |
| `animotion` | `animotion` ✓ | Easing curves, transform-origin, asymmetric-physics normalization (absorbs the requested `gpt-taste`/GSAP role — GSAP is **not** in this stack, so motion stays CSS-only) |
| `uiux-pro-max` | `uiux-pro-max` ✓ | Layout-bounds vs paint-bounds, hover padding boundaries |
| `impeccable` | `impeccable` ✓ | Quality pass, edge-pixel correctness |
| `taste-skill` | `taste-skill` ✓ | Visual judgment (substitutes the requested `design-taste-frontend`, which is **not installed**) |
| `accesslint` | `accesslint` ✓ | Scroll/overflow & focus correctness on the dashboard card |
| `rtk` | `rtk` ✓ | Token-proxied git/build commands (transparent via hook) |

> Requested-but-absent skills `gpt-taste` and `design-taste-frontend` are remapped above. Do not attempt to invoke them.

## Global Constraints

Copied verbatim from project rules — every task inherits these:

- **GUARDRAIL (from `CAPSULE_DIRECTIONAL_MORPH_PLAN.md`):** Clicking the pill (capsule **and** minimal) must NOT make it jump or clip the bar/fan into a corner. `capsuleZone` is the single source feeding window x + justify + stagger + transform-origin — never let them disagree.
- **Tauri geometry:** only `LogicalPosition`/`LogicalSize`; every monitor read goes through `gui/src/lib/monitor.ts`. (No task here touches window geometry — these are pure CSS/paint fixes. If you reach for a geometry edit, you have the wrong root cause.)
- **`npm run build` (tsc strict + vite) MUST pass before any GUI commit.** `noUnusedLocals`/`noUnusedParameters`/`noFallthroughCasesInSwitch` are on — satisfy, never suppress.
- **One runnable check per non-trivial change** — sibling `*.test.ts` or `__main__`/assert smoke; trivial one-liners exempt.
- No new linter/formatter config. Match surrounding file style exactly.
- Pure geometry/logic in `lib/*.ts` with a sibling `*.test.ts`; stateful orchestration in components/hooks.

---

## Architectural Overview — why each issue occurs

**Issue 1 — center-zone open "jerk."** The close-side "jerks from the middle" glitch was already fixed by ungating `margin-left:auto` from `.open` (index.css:904-910). The remaining *open* jerk is the **center zone**: `[data-near="center"]` carries `margin-left:auto; margin-right:auto` (index.css:910). During the `width` transition both auto-margins re-solve every frame as the box widens, so the bar's center drifts a sub-pixel per frame instead of growing symmetrically about a fixed point — a twitch visible only in the center third. `transform-origin: center center` is correct; the auto-margin pair is the offender.

**Issue 2 — dashboard horizontal scroll.** `renderRecentCard` wraps rows in `overflow: "auto"` (DashboardView.tsx:139) — that's auto on **both** axes. Each row is `width:100%` flex with a `whiteSpace:nowrap` category chip + timestamp column (lines 159-160) that cannot shrink; when filename + chips exceed card width the row overflows horizontally and `overflow:auto` grows a horizontal scrollbar. The card only ever wants vertical scroll.

**Issue 4 — hover shading stops short of the capsule edge.** `.capsule-menu` has `padding: 0 var(--space-3)` (12px, index.css:881). The `.capsule-slider` highlight is sized to the hovered item's `offsetLeft`/`offsetWidth` (CapsuleMenu.tsx:91-97). The first and last items (first = `look`, last = `hide`) sit *inside* that 12px pad, so the slider's edge lands 12px shy of the capsule's physical rounded edge — the shading gap. Independent of `data-corner` because the pad is on `.capsule-menu` unconditionally. Layout-bounds (item box) vs paint-intent (capsule edge) mismatch.

**Issue 5 — asymmetric open physics (left smooth, right uneven).** Left/right zones use mirror transforms (`translateX(-10px)` vs `translateX(10px)`, index.css:916-917) and mirror anchors. They *look* symmetric but aren't perceptually: the right zone grows the box leftward from a right-pinned origin while the OS window repositions, so the item entrance translate (+x, toward the pinned edge) fights the box's leftward growth, reading as a stutter. The left zone's translate (-x) moves *with* the growth, so it reads smooth. The entrance translate **sign**, not the easing curve, is the asymmetry source.

**Issue 6 — corner clipped after sharp→rounded toggle.** `.capsule-menu` is `overflow:hidden` + animated `transform` + a `border-radius` swap between 0 (sharp, index.css:894-896) and 18px (rounded, :885), with **no transition** on radius while a GPU compositing layer (from the persistent `transform`/`transform-origin`) is live. Chromium/WebKit caches the rounded-rect clip mask on the layer and does not always re-rasterize when only `border-radius` changes — so the freshly-rounded corner paints with the stale square clip, cutting the corner. Paint-bounds vs layout-bounds desync: layout knows it's round, the cached layer mask is still square.

---

## File Structure

| File | Responsibility | Touched by |
|---|---|---|
| `docs/archive/capsule-polish-mock.html` | **New.** Standalone, no-build interactive mock: capsule in all three zones, sharp/rounded toggle, hover slider, open/close replay. Repro + tuning sandbox for issues 1, 4, 5, 6. | Task 1 |
| `gui/src/components/FullWindow/DashboardView.tsx` | Recent-activity card overflow | Task 2 |
| `gui/src/index.css` | Capsule morph CSS: center-zone margins, slider edge bleed, entrance transform, corner repaint | Tasks 3, 5, 6, 7 |
| `gui/src/components/PillMenu/CapsuleMenu.tsx` | Slider sizing for edge items (issue 4) | Task 5 |
| `gui/src/components/PillMenu/capsuleSlider.ts` + `.test.ts` | **New.** Pure edge-bleed slider math + check | Task 5 |
| `gui/src/lib/menuTiming.ts` + `menuTiming.test.ts` | Stagger timing (only if issue 5 residual is timing, not transform — confirm before editing) | Task 6 (conditional) |

---

## Task 1: Build the standalone HTML mock

**Files:**
- Create: `docs/archive/capsule-polish-mock.html`

**Interfaces:**
- Produces: a browser-openable repro that demonstrates issues 1, 4, 5, 6 *before* fixes and *after*. Not imported by the app (matches the repo's existing `docs/archive/*-mock.html` convention — zero build step).

**Skill:** `taste-skill` + `animotion` (motion fidelity), `uiux-pro-max` (edge geometry).

- [ ] **Step 1: Create the mock file**

Mirror the live capsule CSS so the mock is faithful. Copy the real rules from `index.css:877-1042` (`.capsule-menu`, `[data-near=*]`, `.capsule-item`, `.capsule-slider`) into a `<style>` block, hardcode the 6 items, add controls (zone selector, corner toggle, open/close replay) and a 1px crosshair at each capsule's physical left/right edge so the issue-4 gap is measurable.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Capsule polish mock — issues 1/4/5/6</title>
<style>
  :root {
    --surface:#1b1d22; --border:#33363d; --text-1:#e6e7ea; --text-3:#8b8f98;
    --hover-bg:rgba(255,255,255,.08); --accent:#6ea8fe; --space-3:12px; --space-2:8px;
    --menu-travel-ease:cubic-bezier(0.16,1,0.3,1);
    --menu-overshoot-ease:cubic-bezier(0.34,1.56,0.64,1);
    --hover-dur:140ms; --hover-ease:cubic-bezier(0.16,1,0.3,1); --hover-ease-out:ease-out;
  }
  body { background:#0f1013; display:flex; flex-direction:column; gap:40px;
         align-items:center; padding:60px; font-family:system-ui; color:var(--text-1); }
  .stage { position:relative; width:520px; height:60px; display:flex; align-items:center; }
  .edge { position:absolute; top:0; bottom:0; width:1px; background:#e0427d; opacity:.5; }
  /* paste .capsule-menu / [data-near] / .capsule-item / .capsule-slider rules here.
     keep CANDIDATE FIXES commented under each original rule so reviewers can A/B. */
</style>
</head>
<body>
  <div class="controls">
    <label>Zone:
      <select id="zone"><option>left</option><option>center</option><option>right</option></select></label>
    <label>Corner:
      <select id="corner"><option value="">rounded</option><option value="sharp">sharp</option></select></label>
    <button id="replay">Open / Close</button>
  </div>
  <div class="stage" id="stage"></div>
  <script>
    const ITEMS = ["look","capture","inbox","stats","vault","hide"];
    // build capsule DOM; wire zone/corner/replay; position .edge crosshairs at the
    // capsule's getBoundingClientRect() left/right so the issue-4 gap is visible.
    // ~40 lines; sandbox, not production.
  </script>
</body>
</html>
```

- [ ] **Step 2: Open it and confirm all four visual bugs reproduce**

Open `docs/archive/capsule-polish-mock.html` in a browser.
Expected (bugs present, pre-fix): center-zone open twitches (issue 1); hovering `look`/`hide` leaves a ~12px unshaded strip to the crosshair (issue 4); right-zone open stutters vs left (issue 5); sharp→rounded toggle clips a corner (issue 6).

- [ ] **Step 3: Commit the mock**

```bash
git add docs/archive/capsule-polish-mock.html
git commit -m "docs: add capsule polish repro mock for issues 1/4/5/6"
```

---

## Task 2: Kill dashboard horizontal scroll (Issue 2)

**Files:**
- Modify: `gui/src/components/FullWindow/DashboardView.tsx:139`

**Interfaces:**
- Produces: recent-activity card that scrolls vertically only; never grows a horizontal scrollbar regardless of filename/category length.

**Skill:** `uiux-pro-max` + `accesslint` (overflow + focus-scroll correctness).

- [ ] **Step 1: Constrain the axis**

In `renderRecentCard`, change the scroll container (DashboardView.tsx:139):

```tsx
// before
<div style={{ overflow: "auto", flex: 1 }}>
// after
<div style={{ overflowY: "auto", overflowX: "hidden", flex: 1, minWidth: 0 }}>
```

`overflowX:"hidden"` removes the horizontal bar; `minWidth:0` lets the flex column shrink so the `wordBreak:"break-word"` filename (line 154) wraps instead of forcing width. The right-hand chip column is already `flexShrink:0` + `whiteSpace:nowrap` (lines 158-160) and stays intact.

> Check whether `renderQueueCard` (DashboardView.tsx:202) shares the same `overflow:"auto"` risk. If its rows can also exceed width, apply the identical fix there. Root-cause once across both cards, not just the ticket's named one.

- [ ] **Step 2: Verify in dev**

```bash
cd gui && npm run dev:vite
```
Expected: open Full Window dashboard, shrink window narrow, seed a long filename + long category — recent-activity card shows **no** horizontal scrollbar; text wraps, chips stay right-aligned, vertical scroll still works.

- [ ] **Step 3: Build gate + commit**

```bash
cd gui && npm run build
git add gui/src/components/FullWindow/DashboardView.tsx
git commit -m "fix: lock recent-activity card to vertical scroll only"
```

> No unit test: one-line style constraint, no logic branch (trivial-change exemption). The dev-mode visual check is the runnable check.

---

## Task 3: Fix center-zone open jerk (Issue 1)

**Files:**
- Modify: `gui/src/index.css:910`

**Interfaces:**
- Produces: center-zone open/close that grows symmetrically about a fixed point, no per-frame center drift. `capsuleZone` machine untouched.

**Skill:** `animotion` (transform-origin vs margin-flow), `impeccable`.

- [ ] **Step 1: Reproduce in the mock, then remove the auto-margin drift**

In the mock select zone=center, hit replay — confirm the twitch. The center bar must hold position via the already-correct `transform-origin: center center` driving the width animation, not by re-solving auto-margins each frame. Try the smaller fix first:

```css
/* before (index.css:910) */
.capsule-menu[data-near="center"] { margin-left: auto; margin-right: auto; }
/* after — center once, let transform-origin own the morph */
.capsule-menu[data-near="center"] { margin-left: auto; margin-right: auto; align-self: center; }
```

If the mock still drifts with auto-margins present, switch the center case to parent-justify centering instead (the box is a flex child of a known-width window whose `justify-content` already resolves to `center` for this zone — App.tsx `capsuleOpenJustify` ~1473):

```css
.capsule-menu[data-near="center"] { margin-left: 0; margin-right: 0; }
```
Then confirm the parent's justify centers the box (single layout solve, not a per-frame margin re-solve).

> **Pick the smaller diff that holds in the mock.** Prefer the `align-self` tweak; fall to margin-zero + parent-justify only if drift persists. Do not touch `capsuleZone`, window x, or the justify gate logic — CSS-only.

- [ ] **Step 2: Port to live app and verify**

```bash
cd gui && npm run dev
```
Expected (capsule mode): drag pill into the **center third**, click open — bar grows smoothly both directions, no frame-1 twitch. Left/right thirds unchanged.

- [ ] **Step 3: GUARDRAIL re-check + commit**

Open/close in all three zones on the primary monitor and a second DPI monitor: bar paints fully at the correct anchor, no corner clip, no close snap toward center. (If the center fix changed the box's flex behavior, left/right share the same parent flex — re-confirm their close still collapses to the pinned edge.)

```bash
git add gui/src/index.css
git commit -m "fix: stop center-zone capsule open from twitching mid-morph"
```

---

## Task 4: Extend hover shading to the capsule edge (Issue 4)

**Files:**
- Modify: `gui/src/components/PillMenu/CapsuleMenu.tsx:91-97` (`showSliderAt`)
- Create: `gui/src/components/PillMenu/capsuleSlider.ts` + `capsuleSlider.test.ts`
- Modify: `gui/src/index.css` (slider border-radius for rounded mode, after :1042)

**Interfaces:**
- Consumes: `.capsule-slider` (index.css:1029), `.capsule-item` layout, exported `CAPSULE_PAD_X` (CapsuleMenu.tsx:31).
- Produces: hovering the first (`look`) or last (`hide`) item shades flush to the capsule's physical edge in **both** sharp and rounded modes; interior items unchanged. `sliderRect(offsetLeft, offsetWidth, idx, count) → { left, width }`.

**Skill:** `uiux-pro-max` (layout-bounds vs paint-bounds), `impeccable` (edge pixels).

- [ ] **Step 1: Decide where the 12px pad goes (use the mock)**

The gap = `.capsule-menu`'s `padding: 0 var(--space-3)` (12px) that the slider doesn't cover for edge items. A/B two candidates in the mock with the crosshair overlay:

- **Candidate A (preferred): bleed the slider for edge items only.** Keep the capsule pad; in `showSliderAt`, when the hovered item is first/last, extend the slider over the pad to the capsule inner edge. JS-side geometry only — no width-constant changes.
- **Candidate B: move the 12px from `.capsule-menu` into the first/last item's outer padding.** Eliminates the inset but changes `CAPSULE_OPEN_W`/`CAPSULE_PAD_X` math (CapsuleMenu.tsx:42-44) — larger blast radius. Only if A looks wrong.

**Prefer A.**

- [ ] **Step 2: Write the failing test**

Create `gui/src/components/PillMenu/capsuleSlider.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { sliderRect } from "./capsuleSlider";
import { CAPSULE_PAD_X } from "./CapsuleMenu";

describe("sliderRect", () => {
  it("bleeds left over the pad for the first item", () => {
    const r = sliderRect(12, 44, 0, 6);
    expect(r.left).toBe(12 - CAPSULE_PAD_X);
    expect(r.width).toBe(44 + CAPSULE_PAD_X);
  });
  it("bleeds right over the pad for the last item", () => {
    const r = sliderRect(232, 44, 5, 6);
    expect(r.left).toBe(232);
    expect(r.width).toBe(44 + CAPSULE_PAD_X);
  });
  it("leaves interior items untouched", () => {
    const r = sliderRect(100, 44, 2, 6);
    expect(r.left).toBe(100);
    expect(r.width).toBe(44);
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

```bash
cd gui && npm test -- capsuleSlider
```
Expected: FAIL — `sliderRect` not found.

- [ ] **Step 4: Implement the helper**

Create `gui/src/components/PillMenu/capsuleSlider.ts`:
```ts
import { CAPSULE_PAD_X } from "./CapsuleMenu";

/** Slider rect for the hovered item, bleeding over the capsule pad at the ends. */
export function sliderRect(offsetLeft: number, offsetWidth: number, idx: number, count: number) {
  const isFirst = idx === 0;
  const isLast = idx === count - 1;
  return {
    left: offsetLeft - (isFirst ? CAPSULE_PAD_X : 0),
    width: offsetWidth + (isFirst ? CAPSULE_PAD_X : 0) + (isLast ? CAPSULE_PAD_X : 0),
  };
}
```

- [ ] **Step 5: Run it to verify it passes**

```bash
cd gui && npm test -- capsuleSlider
```
Expected: PASS (3 tests).

- [ ] **Step 6: Wire the helper into the component**

In `CapsuleMenu.tsx`, replace `showSliderAt` (lines 91-97):
```tsx
import { sliderRect } from "./capsuleSlider";
// ...
const showSliderAt = (el: HTMLButtonElement | null) => {
  const slider = sliderRef.current;
  if (!el || !slider) return;
  const idx = itemRefs.current.indexOf(el);
  const { left, width } = sliderRect(el.offsetLeft, el.offsetWidth, idx, itemRefs.current.length);
  slider.style.transform = `translateX(${left}px)`;
  slider.style.width = `${width}px`;
  slider.style.opacity = "1";
};
```

Then in `index.css` after the `.capsule-slider` block (~:1042) give the bled highlight matching corner radius for rounded mode so it follows the capsule curve:
```css
.capsule-menu:not([data-corner="sharp"]) .capsule-slider { border-radius: 17px; }
```
(17px = capsule 18px − 1px border, so the highlight's rounded edge sits just inside the capsule's.)

- [ ] **Step 7: Build gate + commit**

```bash
cd gui && npm run build && npm test -- capsuleSlider
git add gui/src/components/PillMenu/CapsuleMenu.tsx gui/src/components/PillMenu/capsuleSlider.ts gui/src/components/PillMenu/capsuleSlider.test.ts gui/src/index.css
git commit -m "fix: bleed capsule hover highlight to the physical edge for end items"
```

---

## Task 5: Normalize right-zone open physics (Issue 5)

**Files:**
- Modify: `gui/src/index.css:916-918`
- Conditionally Modify: `gui/src/lib/menuTiming.ts` + `menuTiming.test.ts` (only if residual is timing, not transform)

**Interfaces:**
- Consumes: `[data-near]` entrance transforms; `staggerDelays` (lib/menuTiming.ts).
- Produces: right-zone open reads as smooth as left-zone; both grow with the same perceived velocity and direction. Center bloom untouched.

**Skill:** `animotion` (asymmetric-physics normalization — the headline motion task, executed in CSS).

- [ ] **Step 1: Reproduce left vs right in the mock, isolate the sign**

In the mock, replay left then right. Root cause (Overview): right items enter `translateX(10px)` (toward the pinned right edge, index.css:917) while the box grows leftward — entrance and growth oppose. Left items enter `translateX(-10px)` *with* the leftward growth. Flip the right entrance to move **with** its growth:

```css
/* before (index.css:916-917) */
.capsule-menu[data-near="left"]   .capsule-item { transform: translateX(-10px) scale(0.7); }
.capsule-menu[data-near="right"]  .capsule-item { transform: translateX(10px)  scale(0.7); }
/* after — both icons enter trailing their growth edge */
.capsule-menu[data-near="left"]   .capsule-item { transform: translateX(-10px) scale(0.7); }
.capsule-menu[data-near="right"]  .capsule-item { transform: translateX(-10px) scale(0.7); }
```

> Validate the sign in the mock before porting — correct sign is the one where the icon entrance visually *trails* the bar's growth edge in both zones. Tune the 10px magnitude only if right still lags; keep left/right magnitudes equal. Leave `[data-near="center"]` (pure scale) as-is.

- [ ] **Step 2: If sign-match alone doesn't equalize, check the stagger (conditional)**

Only if the mock still shows uneven *timing* (not direction): the right zone reverses the stagger (`[...base].reverse()`, CapsuleMenu.tsx:111). Add a test pinning reversed and forward to the same finish time; fix the helper only if it fails:

```ts
// gui/src/lib/menuTiming.test.ts — add
it("reverse preserves total animation window", () => {
  const f = staggerDelays(6, 260, 180);
  const r = [...f].reverse();
  expect(Math.max(...f) + 180).toBe(Math.max(...r) + 180);
});
```
Run: `cd gui && npm test -- menuTiming`. If it passes, timing is already symmetric — **skip the helper edit** (YAGNI); the fix is purely Step 1's transform sign.

- [ ] **Step 3: Port to live, A/B left vs right**

```bash
cd gui && npm run dev
```
Expected: open from left third (smooth baseline), then right third — identical smoothness, same direction-of-travel, no stutter. Screen-capture both and compare frame pacing if uncertain.

- [ ] **Step 4: Build gate + commit**

```bash
cd gui && npm run build
git add gui/src/index.css
# add menuTiming files only if Step 2 fired:
git add gui/src/lib/menuTiming.ts gui/src/lib/menuTiming.test.ts 2>/dev/null
git commit -m "fix: normalize right-zone capsule open to match left-zone physics"
```

---

## Task 6: Fix sharp→rounded corner clip (Issue 6)

**Files:**
- Modify: `gui/src/index.css:877-896` (`.capsule-menu` / `[data-corner="sharp"]`)

**Interfaces:**
- Consumes: `.capsule-menu` compositing layer (from its persistent `transform`).
- Produces: toggling `data-corner` sharp→rounded repaints the rounded corner immediately — no stale square clip.

**Skill:** `uiux-pro-max` (paint-bounds vs layout-bounds), `taste-skill` (final visual), `impeccable`.

- [ ] **Step 1: Reproduce + force layer re-raster in the mock**

In the mock, toggle sharp→rounded repeatedly — confirm the clipped corner. The cached rounded-rect clip mask isn't invalidated on a bare `border-radius` change while a transform layer is live. Force re-raster by transitioning `border-radius` (a change the compositor must re-raster) and hinting the layer (index.css:877-892):

```css
.capsule-menu {
  /* ...existing... */
  border-radius: 18px;
  overflow: hidden;
  will-change: width, border-radius;          /* hint compositor to re-raster on radius change */
  transition: width 260ms cubic-bezier(0.16, 1, 0.3, 1),
              transform 0.12s cubic-bezier(0.16, 1, 0.3, 1),
              border-radius 120ms linear;       /* animate the swap → forces corner re-raster */
}
```

`[data-corner="sharp"] { border-radius: 0 }` stays as-is — now the transition animates 0↔18px, fixing the clip and reading as small polish.

> If `will-change` + transition still caches in the mock (some Chromium versions), fall back to a guaranteed invalidation (transform nudge on corner change, or `mask` instead of `overflow:hidden`). Prefer the one-rule `will-change`+transition combo. Confirm `taste-skill` is OK with the 120ms radius morph; shorten toward 0ms (instant) if laggy while still repainting — test both in the mock.

- [ ] **Step 2: Port + verify the toggle**

```bash
cd gui && npm run dev
```
Expected (capsule mode): toggle corner setting sharp→rounded→sharp several times — every rounded state paints all four corners cleanly. Re-open the menu in the rounded state and confirm no corner clip during the width morph either.

- [ ] **Step 3: Build gate + commit**

```bash
cd gui && npm run build
git add gui/src/index.css
git commit -m "fix: force corner re-raster on capsule sharp->rounded toggle"
```

---

## Verification Protocol (superpowers:verification-before-completion)

Run after all tasks. Do **not** declare done until every box passes — report any failure with its output, never paper over it.

- [ ] **Build & unit gate:**
  ```bash
  cd gui && npm run build && npm test
  ```
  Expected: tsc strict clean, vite build OK, all vitest green (incl. new `capsuleSlider.test.ts`, and `menuTiming.test.ts` if Task 5 Step 2 fired).

- [ ] **Issue 2 — scroll:** Dashboard recent-activity (and queue card if it shared the bug) with a long filename + long category → no horizontal scrollbar at any window width; vertical scroll works; chips stay right-aligned. (`accesslint`: keyboard focus on a row still scrolls it into view, no focus trap.)

- [ ] **Issue 1 — center jerk:** Capsule open in the center third → grows symmetrically, no frame-1 twitch. Left/right thirds unchanged.

- [ ] **Issue 4 — hover edge:** Hover `look` (first) and `hide` (last) in capsule open state → highlight reaches the physical capsule edge in **both** sharp and rounded modes (verify against the mock crosshair). Interior items unchanged.

- [ ] **Issue 5 — symmetry:** Open from left third and right third back-to-back → identical smoothness and direction-of-travel; no right-side stutter.

- [ ] **Issue 6 — corner clip:** Toggle sharp→rounded→sharp ≥3× → every rounded state shows all four corners intact; no stale square clip; no clip during the subsequent open morph.

- [ ] **GUARDRAIL (regression gate — mandatory):** All three zones × {primary monitor, second DPI monitor} × {capsule, minimal}:
  - Click pill → bar morphs open fully visible, correct anchor, **no corner clip, no jump into a corner**.
  - Close from each zone → collapses straight back to its anchor, no center drift, no terminal snap.
  - Reduced-motion OS setting on → no stuck off-anchor bar in any zone (`@media (prefers-reduced-motion)` ~index.css:926).
  - If any zone clips, snaps, or jumps → **STOP, revert the offending task, re-check that `capsuleZone` still solely drives window x + justify + stagger + transform-origin.**

- [ ] **Mock parity:** `docs/archive/capsule-polish-mock.html` shows all four visual bugs **fixed** when its `<style>` carries the final live rules — mock and app agree.

---

## Out of scope / explicitly NOT doing

- **Global cross-window morph (executive issue 3) — dropped by decision.** No window-resize morph engine, no full/capsule/minimal squash-stretch. Do not add it.
- No edits to the `capsuleZone` zone machine, window geometry (`computeCapsuleMenuGeometry`, App.tsx openingMenu branch), or `lib/monitor.ts` — these fixes are CSS/paint only.
- No new dependency (no GSAP — `animotion` work stays CSS), no linter/formatter config.
- No Python / Rust / Tauri capability changes.

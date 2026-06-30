# Capsule Directional Morph Expansion — Implementation Plan

Three-zone, direction-aware capsule expansion. Plan only. Implement exactly as
written. Build on the existing edge-aware capsule path (`computeCapsuleMenuGeometry`,
`capsuleNearEdge`, `data-near` / `transform-origin`).

---

## ⚠️ GUARDRAIL — DO NOT BREAK THIS

Clicking the pill (capsule **and** minimal) must NOT make it jump or clip the
bar/fan into a corner. The open path is correct today.

- Capsule open justify stays edge/center-pinned while `menuOpen` (App.tsx ~1473).
  Only EXTEND it for the new `center` zone — never loosen the existing gate.
- `capsuleExiting` still holds the anchor through the whole exit (prior fix). New
  `center` zone must be held the same way.
- After every change: open capsule at LEFT edge, RIGHT edge, and CENTER of one
  monitor + a second DPI monitor. Bar must paint fully at correct anchor, no clip,
  no terminal snap on close.

---

## Decisions (locked)

- **Zones:** viewport split in equal vertical thirds by the **capsule center x**.
  Left third → anchor left, grow right. Right third → anchor right, grow left.
  Middle third → anchor center, grow both ways equally.
- **Middle stagger:** center-out (icons reveal from middle outward both directions).
- **Middle collision:** if symmetric grow would overflow the monitor work area,
  **demote** to the nearer edge zone (reuse existing left/right path). No new clamp.

---

## Architecture change at a glance

`nearEdge: "left" | "right"` becomes a tri-state **zone** `"left" | "right" | "center"`
threaded through the same 4 seams that already carry `nearEdge`:
`menuGeometry.ts` (window x), `App.tsx` (zone detection + justify), `CapsuleMenu.tsx`
(stagger + `data-near`), `index.css` (`transform-origin`). No new component, no new
state machine — widen the existing one.

---

## Phase 1 — Zone Detection

### Step 1.1 — Replace the binary edge calc with a thirds-based zone
**[uiuix-pro-max] -> App.tsx (capsule openingMenu branch ~1288):**
Replace the `monitorMidX` / binary `nearEdge` lines with a thirds split on the
pill center x relative to `monitorBounds`. Compute `oneThird = monitorBounds.w / 3`,
derive `zone`:
- `pillCenterLogical.x < monitorBounds.x + oneThird` → `"left"`
- `pillCenterLogical.x > monitorBounds.x + 2*oneThird` → `"right"`
- else → `"center"`

> Keep the existing `getActiveMonitorBounds(pillCenterPhysical)` read — do not add a
> second monitor query.

### Step 1.2 — Widen the state type
**[uiuix-pro-max] -> App.tsx (~339):**
`const [capsuleNearEdge, setCapsuleNearEdge] = useState<"left"|"right">("left")`
becomes `useState<"left"|"right"|"center">("left")`. Rename to `capsuleZone` for
clarity (mechanical rename across its ~4 uses). Set it from Step 1.1's `zone`.

### Step 1.3 — Propagate the type through the seams
**[impeccable] -> menuGeometry.ts (~235), PillOverlay.tsx (~55), CapsuleMenu.tsx (~78):**
Change every `nearEdge: "left" | "right"` prop/field to include `"center"`. TS strict
will flag every unhandled site — that list IS the change surface. Don't suppress.

---

## Phase 2 — Anchor & Transform Swapping (geometry)

### Step 2.1 — Symmetric-grow branch in window geometry
**[uiuix-pro-max] -> menuGeometry.ts `computeCapsuleMenuGeometry` (~257):**
Add a `center` case to the `x` calc. Today: right pins right edge, left keeps idle x.
Add: `center` → window centered on the pill center →
`x = idleTopLeftLogical.x + idlePillBoxW/2 - windowW/2`.
Keep `windowW`/`windowH` unchanged. Round x as the existing code does.

### Step 2.2 — Collision check → demote to edge
**[uiuix-pro-max] -> menuGeometry.ts (same function) + App.tsx (Step 1.1):**
After computing the `center` x, clamp-test against `monitorBounds` work area. If
`x < monitorBounds.x` or `x + windowW > monitorBounds.x + monitorBounds.w`, the
center grow doesn't fit → return the nearer edge's geometry instead AND signal the
demotion so `capsuleZone` is set to that edge (so justify/stagger/CSS all agree).
Lazy option: do the fit-test in App.tsx (it already has `monitorBounds`), pick the
final zone there, then call `computeCapsuleMenuGeometry` once with the resolved zone.
**Prefer this** — one call, no return-shape change.

> Demotion must happen BEFORE `setCapsuleZone` so a single source of truth drives
> window x, justify, stagger, and transform-origin. Never let them disagree.

### Step 2.3 — Extend the justify gate for center
**[animotion] -> App.tsx `capsuleOpenJustify` (~1473):**
Add the center arm. When zone is `center` (and `menuOpen || capsuleExiting`), justify
is `"center"` (which is already the default-else) — so the change is: the edge arms
fire for `left`/`right`, center falls through to `"center"`. Verify the existing
`capsuleExiting` hold also covers center (it should — it's zone-agnostic).

### Step 2.4 — Center transform-origin
**[animotion] -> CapsuleMenu.tsx (~121) + index.css (~769):**
`data-near={zone}` already emits the value once renamed. Add CSS:
```css
.capsule-menu[data-near="center"] { transform-origin: center center; }
```
Left/right rules from the prior fix stay. This anchors the width morph so center
collapses to/from its middle, edges to/from their pinned side.

---

## Phase 3 — Stagger & Micro-interaction Polish

### Step 3.1 — Center-out stagger
**[animotion] -> CapsuleMenu.tsx `delays` useMemo (~106):**
Today: base array, reversed when `nearEdge==="right"`. Add `center` case: build a
center-out delay order — smallest delay at the middle index(es), increasing toward
both ends. For N icons: `delay[i] = step * abs(i - (N-1)/2)` scaled into the existing
`CAPSULE_ANIM_MS` / `CAPSULE_ITEM_PLAY_MS` budget so the outermost icons still finish
by `CAPSULE_ANIM_MS` (mirror `staggerDelays`' total-window contract). Keep DOM order
fixed (`ALL_TARGETS`).

### Step 3.2 — Seamless directional switching
**[taste-skill] -> CapsuleMenu.tsx + index.css:**
Confirm a drag from left zone → center → right zone re-derives zone only on the next
OPEN (geometry is computed in the openingMenu branch, not live) — so mid-open the
direction never thrashes. No code if true; if a live flip is observed, gate zone
re-eval to `openingMenu` edge only. Visually verify the three open directions read as
one consistent morph language, not three different animations.

### Step 3.3 — Balance pass
**[taste-skill] [impeccable] -> CapsuleMenu.tsx, index.css:**
Eyeball center-zone symmetry: the bar should grow visually equally left/right from the
pill, icons blooming from the middle. Tune the center-out `step` only if the outer
icons feel late vs the edge zones. No new constants unless a value is reused ≥2×.

---

## Phase 4 — QA & Polish

### Step 4.1 — Build + test gate (must pass before commit)
```bash
cd gui
npm run build      # tsc strict + vite — MUST pass (catches every un-migrated nearEdge)
npm test           # vitest
```

### Step 4.2 — Extend geometry unit test
**[impeccable] -> menuGeometry.test.ts (~349):**
Add a `center` case to the `computeCapsuleMenuGeometry` describe: assert window is
centered on the pill center, and assert the demotion path returns the nearer-edge
geometry when a center grow overflows a narrow monitor. One assert each — this is the
runnable check the repo rule requires for the new branch.

### Step 4.3 — Manual zone check
- Drag capsule into LEFT third → open: anchors left, grows right.
- CENTER third → open: grows both ways, symmetric.
- RIGHT third → open: anchors right, grows left.
- Center third but pill near a monitor edge (forces overflow) → demotes cleanly to
  that edge, no clip.
- Repeat on second monitor (DPI scaling).

### Step 4.4 — GUARDRAIL re-check (mandatory)
- All three zones, both monitors: bar morphs open fully visible, no corner clip.
- Close from each zone: collapses straight back to its anchor, no center drift / snap.
- If any zone clips or snaps → STOP, revert, re-check that `capsuleZone` is the single
  source feeding window x + justify + stagger + transform-origin.

### Step 4.5 — Reduced motion
- OS "reduce motion" on: no stuck off-anchor bar in any zone
  (`@media (prefers-reduced-motion)` ~926 in index.css).

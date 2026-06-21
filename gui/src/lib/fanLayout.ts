/**
 * fanLayout.ts
 * ------------
 * Pure geometry for the minimal-mode (radial) pill menu. ONE law for every
 * pill position — a pinned anchor is just a known screen-space pill center
 * (cx, cy) fed into the same math as a dragged/custom position. See
 * for_sonnet.md "Problem 2 + 3" for the full spec; this is the formalized
 * reference implementation of gui/mockups/radial-unified.html's
 * unifiedFan()/availableArc().
 */

/** Spread-mode partial-arc cap (deg) — the menu never opens wider than this
 *  unless a whole circle actually fits (full 360° wheel). */
export const SPREAD_MAX_ARC = 300;

export interface FanParams {
  cx: number;
  cy: number;
  sw: number;
  sh: number;
  radius: number;
  chipMax: number;
  chipMin: number;
  pad: number;
  /** Canonical-order item ids (Search...Hide). Count = n. */
  ids: string[];
  minSpacingDeg: number;
  fanStyle: "spread" | "capped";
  /** Overrides SPREAD_MAX_ARC — the dev tuner's escape hatch; production
   *  code omits this and gets the constant. */
  spreadMaxArc?: number;
}

export interface FanItemPosition {
  id: string;
  angleDeg: number;
  x: number;
  y: number;
}

export interface FanResult {
  items: FanItemPosition[];
  chip: number;
  span: number;
  fullFits: boolean;
}

export interface ArcResult {
  fullFits: boolean;
  availSpan: number;
  availCenter: number;
  isValid(deg: number): boolean;
}

const COARSE_STEP = 0.5;
/** Inward inset (deg) applied to each refined arc endpoint — erring inward
 *  is required, erring outward is forbidden (see for_sonnet.md "off-by-a-
 *  step warning"). */
export const SAFETY_EPSILON = 0.3;

/** Largest contiguous in-bounds arc (chip-aware) containing the inward
 *  direction, refined to ~0.01deg accuracy then inset by a safety epsilon —
 *  erring inward only, never outward (see for_sonnet.md "off-by-a-step
 *  warning"). */
export function availableArc(cx: number, cy: number, sw: number, sh: number, R: number, chip: number, pad: number): ArcResult {
  const m = chip / 2 + pad;
  const isValid = (deg: number) => {
    const a = (deg * Math.PI) / 180;
    const x = cx + Math.cos(a) * R;
    const y = cy + Math.sin(a) * R;
    return x >= m && x <= sw - m && y >= m && y <= sh - m;
  };

  const N = Math.round(360 / COARSE_STEP);
  const samples: boolean[] = [];
  for (let i = 0; i < N; i++) samples.push(isValid(i * COARSE_STEP));

  if (samples.every(Boolean)) return { fullFits: true, availSpan: 360, availCenter: 0, isValid };

  let best = { len: 0, start: 0 };
  let len = 0;
  let start = 0;
  for (let i = 0; i < N * 2; i++) {
    if (samples[i % N]) {
      if (len === 0) start = i;
      len++;
      if (len > best.len) best = { len, start };
    } else {
      len = 0;
    }
  }

  if (best.len === 0) return { fullFits: false, availSpan: 0, availCenter: 0, isValid };

  // Coarse run endpoints (the run is maximal, so one step beyond each end is
  // invalid) — refine each via bisection to ~0.01deg.
  const refine = (validDeg: number, invalidDeg: number) => {
    let lo = validDeg;
    let hi = invalidDeg;
    for (let i = 0; i < 30; i++) {
      const mid = (lo + hi) / 2;
      if (isValid(mid)) lo = mid;
      else hi = mid;
    }
    return lo;
  };

  const coarseLo = best.start * COARSE_STEP;
  const coarseHi = (best.start + best.len - 1) * COARSE_STEP;
  let lo = refine(coarseLo, coarseLo - COARSE_STEP);
  let hi = refine(coarseHi, coarseHi + COARSE_STEP);

  // Inset both ends inward by the safety epsilon — never outward.
  lo += SAFETY_EPSILON;
  hi -= SAFETY_EPSILON;

  const availSpan = Math.max(0, hi - lo);
  const availCenter = lo + availSpan / 2;
  return { fullFits: false, availSpan, availCenter, isValid };
}

function selectSpanAndCenter(arc: ArcResult, n: number, minSpacingDeg: number, fanStyle: "spread" | "capped", spreadMaxArc: number) {
  if (arc.fullFits) return { span: 360, center: 0 };
  const span =
    fanStyle === "capped"
      ? Math.min(arc.availSpan, minSpacingDeg * Math.max(n - 1, 0))
      : Math.min(arc.availSpan, spreadMaxArc);
  return { span, center: arc.availCenter };
}

/** THE unified fan geometry — same call for a pinned anchor (known cx, cy)
 *  and a dragged custom position. See for_sonnet.md "Problem 2 + 3". */
export function unifiedFan(p: FanParams): FanResult {
  const { cx, cy, sw, sh, radius: R, chipMax, chipMin, pad, ids, minSpacingDeg, fanStyle, spreadMaxArc = SPREAD_MAX_ARC } = p;
  const n = ids.length;

  let chip = chipMax;
  let arc = availableArc(cx, cy, sw, sh, R, chip, pad);
  let { span, center } = selectSpanAndCenter(arc, n, minSpacingDeg, fanStyle, spreadMaxArc);

  for (let pass = 0; pass < 4; pass++) {
    const gapDeg = span >= 360 ? 360 / n : n > 1 ? span / (n - 1) : 0;
    const chord = n > 1 ? 2 * R * Math.sin(((gapDeg * Math.PI) / 180) / 2) : chipMax;
    const want = Math.max(chipMin, Math.min(chipMax, chord));
    if (Math.abs(want - chip) < 0.5) {
      chip = want;
      break;
    }
    chip = want;
    arc = availableArc(cx, cy, sw, sh, R, chip, pad);
    ({ span, center } = selectSpanAndCenter(arc, n, minSpacingDeg, fanStyle, spreadMaxArc));
  }

  // Ordering guarantee (G1): the arc/span used for placement must match the
  // chip actually rendered — recompute once more with the settled chip.
  arc = availableArc(cx, cy, sw, sh, R, chip, pad);
  ({ span, center } = selectSpanAndCenter(arc, n, minSpacingDeg, fanStyle, spreadMaxArc));

  const isFullWheel = span >= 360;
  const slotAngle = (i: number) => {
    if (n <= 1) return isFullWheel ? -90 : center;
    return isFullWheel ? -90 + (360 / n) * i : center - span / 2 + (span / (n - 1)) * i;
  };

  const slotAngles = ids.map((_, i) => slotAngle(i));
  // Reading order (preserve existing rule): canonical Search...Hide order
  // always reads top-to-bottom. A full wheel keeps canonical clockwise order
  // (Search pinned to 12 o'clock); a partial arc reverses the walk if the
  // raw assignment would put the last item above the first.
  const yOf = (deg: number) => Math.sin((deg * Math.PI) / 180);
  const orderedIds = isFullWheel || n <= 1 || yOf(slotAngles[0]) <= yOf(slotAngles[n - 1]) ? ids : [...ids].reverse();

  const items: FanItemPosition[] = orderedIds.map((id, i) => {
    const angleDeg = slotAngles[i];
    const rad = (angleDeg * Math.PI) / 180;
    return { id, angleDeg, x: Math.cos(rad) * R, y: Math.sin(rad) * R };
  });

  return { items, chip, span, fullFits: arc.fullFits };
}

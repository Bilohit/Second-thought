import { describe, it, expect } from "vitest";
import {
  adaptiveSemanticFloor,
  CONFLICT_OPACITY_MAX,
  CONFLICT_OPACITY_MIN,
  CONFLICT_PULSE_PERIOD_SEC,
  CONFLICT_RADIUS_MAX,
  CONFLICT_RADIUS_MIN,
  conflictPulseOpacity,
  conflictPulseRadius,
  densityStep,
  DENSITY_DEFAULT_INDEX,
  DENSITY_STEPS,
  driftEnvelope,
  percentileOf,
  buildStarEdges,
  coreVisual,
  cosine,
  EDGE_TOP_K,
  edgeOpacity,
  hashPosition,
  initNodes,
  isTap,
  pairWeight,
  parseTagsField,
  QUEUED_PULSE_MAX,
  QUEUED_PULSE_MIN,
  QUEUED_PULSE_PERIOD_SEC,
  queuedPulseOpacity,
  QUIESCENCE_DELTA_PX,
  QUIESCENCE_FRAMES,
  quiescenceStep,
  releaseMomentum,
  selectRecentIds,
  SEMANTIC_FLOOR,
  SETTLE_SEC,
  springK,
  springRest,
  stepSimulation,
  TAP_THRESHOLD_PX,
  computeDegrees,
  type SimEdge,
  type SimNode,
} from "./starsSim";

describe("stepSimulation — drag anchoring", () => {
  it("a dragged node's velocity is untouched by repulsion, springs and centering, but position IS clamped", () => {
    const dragged: SimNode = { id: "a", x: -50, y: -50, vx: 0, vy: 0, ph: 0, drag: true };
    // A close neighbour to force a large repulsion push, plus a wikilink edge to `a` so the spring
    // pass also has a chance to touch it, plus far-off-center so the centering pull is non-trivial.
    const neighbour: SimNode = { id: "b", x: -45, y: -45, vx: 0, vy: 0, ph: 1.7, drag: false };
    // weight 1 == bit-for-bit the old wikilink spring (springK(1)/springRest(1) below).
    const edges: SimEdge[] = [{ a: "a", b: "b", kind: "wikilink", weight: 1 }];

    const [resA] = stepSimulation([dragged, neighbour], edges, 0, 800, 600);

    expect(resA.vx).toBe(0);
    expect(resA.vy).toBe(0);
    // clamp: x in [66, W-66], y in [20, H-34] — a's raw (-50,-50) is out of bounds on both axes,
    // so ONLY the clamp (unconditional) can be what moved it.
    // ★ s154: x was 26 until FR-40 raised CLAMP_X to 66 so an 80px centred label stops being
    // clipped at the sky edge. This assertion pinning the exact value is what caught the change —
    // keep it exact, not a range: a `>=` bound here would have let the constant drift silently.
    expect(resA.x).toBe(66);
    expect(resA.y).toBe(20);
  });

  it("an undragged node in-bounds is free to move under centering + drift", () => {
    const n: SimNode = { id: "a", x: 100, y: 100, vx: 0, vy: 0, ph: 0, drag: false };
    const [res] = stepSimulation([n], [], 0, 800, 600, { reducedMotion: true });
    // off-center (400,300) pulls it toward the center — some nonzero velocity/movement.
    expect(res.vx).not.toBe(0);
    expect(res.x).not.toBe(100);
  });
});

describe("stepSimulation — reduced motion", () => {
  it("kills ONLY the idle-drift term: a centered, edgeless, undragged node is fully still", () => {
    const n: SimNode = { id: "a", x: 400, y: 300, vx: 0, vy: 0, ph: 0.5, drag: false };
    const [res] = stepSimulation([n], [], 12345, 800, 600, { reducedMotion: true });
    // centering force is ~0 (already at center), no edges, no repulsion (single node) — with drift
    // off, velocity must stay exactly 0 and position must not move.
    expect(res.vx).toBe(0);
    expect(res.vy).toBe(0);
    expect(res.x).toBe(400);
    expect(res.y).toBe(300);
  });

  it("does NOT touch drift when reducedMotion is false — the same node now moves", () => {
    const n: SimNode = { id: "a", x: 400, y: 300, vx: 0, vy: 0, ph: 0.5, drag: false };
    const [res] = stepSimulation([n], [], 12345, 800, 600, { reducedMotion: false });
    expect(res.vx).not.toBe(0);
    expect(res.vy).not.toBe(0);
  });

  it("does NOT disable centering — an off-center node still moves under reducedMotion", () => {
    const n: SimNode = { id: "a", x: 100, y: 100, vx: 0, vy: 0, ph: 0, drag: false };
    const [res] = stepSimulation([n], [], 0, 800, 600, { reducedMotion: true });
    expect(res.vx).not.toBe(0);
    expect(res.vy).not.toBe(0);
  });

  it("does NOT disable springs — a wikilink pair still pulls together under reducedMotion", () => {
    const a: SimNode = { id: "a", x: 400, y: 300, vx: 0, vy: 0, ph: 0, drag: false };
    const b: SimNode = { id: "b", x: 700, y: 300, vx: 0, vy: 0, ph: 0, drag: false };
    const edges: SimEdge[] = [{ a: "a", b: "b", kind: "wikilink", weight: 1 }];
    const [resA] = stepSimulation([a, b], edges, 0, 1000, 800, { reducedMotion: true });
    // rest length 105, current distance 300 — spring must pull a toward b (positive vx).
    expect(resA.vx).toBeGreaterThan(0);
  });
});

describe("isTap", () => {
  it(`is a tap at exactly the ${TAP_THRESHOLD_PX}px threshold`, () => {
    expect(isTap(6, 0)).toBe(true);
    expect(isTap(3, 3)).toBe(true);
    expect(isTap(-6, 0)).toBe(true);
  });
  it("is NOT a tap one unit past the threshold", () => {
    expect(isTap(7, 0)).toBe(false);
    expect(isTap(4, 3)).toBe(false);
  });
});

describe("coreVisual", () => {
  it("degree 0 -> smallest, dimmer core", () => {
    expect(coreVisual(0)).toEqual({ size: 5, opacity: 0.75 });
  });
  it("degree 1 -> mid core, full opacity", () => {
    expect(coreVisual(1)).toEqual({ size: 8, opacity: 1 });
  });
  it("degree 2+ -> largest core, full opacity", () => {
    expect(coreVisual(2)).toEqual({ size: 10, opacity: 1 });
    expect(coreVisual(7)).toEqual({ size: 10, opacity: 1 });
  });
});

describe("releaseMomentum", () => {
  it("scales the last drag-frame delta by 1.6", () => {
    const r = releaseMomentum(2, -3);
    expect(r.vx).toBeCloseTo(3.2);
    expect(r.vy).toBeCloseTo(-4.8);
  });
});

describe("hashPosition / initNodes", () => {
  it("is deterministic — same index always yields the same position", () => {
    expect(hashPosition(3, 800, 600)).toEqual(hashPosition(3, 800, 600));
  });
  it("stays inside the host bounds", () => {
    const nodes = initNodes(["a", "b", "c"], 800, 600);
    for (const n of nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(800);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeLessThanOrEqual(600);
      expect(n.drag).toBe(false);
    }
  });
});

describe("buildStarEdges — no wikilink source, shared-tag edges only", () => {
  it("an empty note list produces no edges", () => {
    expect(buildStarEdges([], new Set())).toEqual([]);
  });

  it("notes with no shared tags produce no edges, even with undefined-ish (empty) tag arrays", () => {
    const notes = [
      { id: "a", tags: [] },
      { id: "b", tags: [] },
    ];
    expect(buildStarEdges(notes, new Set(["a", "b"]))).toEqual([]);
  });

  it("a shared tag produces exactly one deduped, order-independent 'tag' edge", () => {
    const notes = [
      { id: "b", tags: ["x", "y"] },
      { id: "a", tags: ["y"] },
    ];
    const edges = buildStarEdges(notes, new Set(["a", "b"]));
    // inter=1 ("y"), union={x,y} size 2 -> 0.35 + 0.4*(1/2) = 0.55
    expect(edges).toEqual([{ a: "a", b: "b", kind: "tag", weight: 0.55 }]);
  });

  it("drops an edge whose endpoint isn't in allowedIds (the capped node set)", () => {
    const notes = [
      { id: "a", tags: ["x"] },
      { id: "b", tags: ["x"] },
    ];
    expect(buildStarEdges(notes, new Set(["a"]))).toEqual([]);
  });

  it("never produces a wikilink-kind edge (the documented ceiling)", () => {
    const notes = [
      { id: "a", tags: ["x"] },
      { id: "b", tags: ["x"] },
    ];
    const edges = buildStarEdges(notes, new Set(["a", "b"]));
    expect(edges.every((e) => e.kind === "tag")).toBe(true);
  });
});

describe("pairWeight — Jaccard ordering (s152)", () => {
  it("three shared tags outrank one, even though both are non-empty overlaps", () => {
    const hub = { id: "hub", tags: ["t1", "t2", "t3", "t4"] };
    // 3 shared (t1,t2,t3), union = hub's 4 tags -> 0.35 + 0.4*(3/4) = 0.65
    const strong = { id: "strong", tags: ["t1", "t2", "t3"] };
    // 1 shared (t1), union = {t1,t2,t3,t4,t5} size 5 -> 0.35 + 0.4*(1/5) = 0.43
    const weak = { id: "weak", tags: ["t1", "t5"] };

    const strongBid = pairWeight(hub, strong, false);
    const weakBid = pairWeight(hub, weak, false);

    expect(strongBid?.kind).toBe("tag");
    expect(weakBid?.kind).toBe("tag");
    expect(strongBid!.weight).toBeCloseTo(0.65);
    expect(weakBid!.weight).toBeCloseTo(0.43);
    expect(strongBid!.weight).toBeGreaterThan(weakBid!.weight);
  });

  it("returns null when tag sets share nothing", () => {
    expect(pairWeight({ id: "a", tags: ["x"] }, { id: "b", tags: ["y"] }, false)).toBeNull();
  });
});

describe("pairWeight — project grouping excludes _loose/uncategorized (s152)", () => {
  it("never sources a project edge from two '_loose' notes", () => {
    const a = { id: "a", tags: [], project: "_loose" };
    const b = { id: "b", tags: [], project: "_loose" };
    expect(pairWeight(a, b, false)).toBeNull();
  });

  it("never sources a project edge from two 'uncategorized' notes", () => {
    const a = { id: "a", tags: [], project: "uncategorized" };
    const b = { id: "b", tags: [], project: "uncategorized" };
    expect(pairWeight(a, b, false)).toBeNull();
  });

  it("DOES source a project edge from a real shared project", () => {
    const a = { id: "a", tags: [], project: "acme" };
    const b = { id: "b", tags: [], project: "acme" };
    expect(pairWeight(a, b, false)).toEqual({ weight: 0.3, kind: "project" });
  });
});

describe("pairWeight — semantic floor (s152, opt-in)", () => {
  // 2D unit vectors so cosine(a, b) is exactly the first component of b.
  const unitAt = (cos: number): number[] => [cos, Math.sqrt(1 - cos * cos)];
  const a = { id: "a", tags: [], vec: [1, 0] };

  it("does not bid below the floor", () => {
    const below = { id: "b", tags: [], vec: unitAt(SEMANTIC_FLOOR - 0.12) };
    expect(pairWeight(a, below, true)).toBeNull();
  });

  it("bids once similarity clears the floor, scaled toward 1 as similarity -> 1", () => {
    const above = { id: "b", tags: [], vec: unitAt(0.7) };
    const bid = pairWeight(a, above, true);
    expect(bid?.kind).toBe("semantic");
    // 0.5 + 0.5 * ((0.7 - 0.62) / (1 - 0.62))
    expect(bid!.weight).toBeCloseTo(0.60526, 4);
  });

  it("never bids when semantic is off, no matter how similar the vectors", () => {
    const identical = { id: "b", tags: [], vec: [1, 0] };
    expect(pairWeight(a, identical, false)).toBeNull();
  });
});

describe("cosine", () => {
  it("is 1 for identical vectors, 0 for orthogonal ones", () => {
    expect(cosine([1, 0], [1, 0])).toBeCloseTo(1);
    expect(cosine([1, 0], [0, 1])).toBeCloseTo(0);
  });
  it("is 0 (never NaN) for a zero-length vector", () => {
    expect(cosine([0, 0], [1, 2])).toBe(0);
  });
});

describe("buildStarEdges — EDGE_TOP_K budget bounds sourcing (s152)", () => {
  it("a 6-note clique sharing one real project draws fewer than the full 15 pairs", () => {
    // The documented historical bug (DECISIONS §5 s151): "same project" alone drew ALL pairs on a
    // real vault. This reproduces that shape with 6 nodes (C(6,2) = 15 possible edges) and asserts
    // the per-node top-EDGE_TOP_K budget actually bounds it. Math below assumes EDGE_TOP_K === 3 —
    // canary first so a constant change fails loudly instead of silently miscounting.
    expect(EDGE_TOP_K).toBe(3);
    const ids = ["a", "b", "c", "d", "e", "f"];
    const notes = ids.map((id) => ({ id, tags: [], project: "acme" }));
    const allowed = new Set(ids);

    const edges = buildStarEdges(notes, allowed);
    const keys = new Set(edges.map((e) => `${e.a}-${e.b}`));

    // Every edge is the constant project weight, tie-broken by lexicographic key — worked out by
    // hand: each node keeps its own top-3 (smallest keys first), unioned across all 6 nodes.
    expect(keys.size).toBe(12);
    expect(keys.size).toBeLessThan(15); // the bug this budget fixes: NOT the full clique
    for (const missing of ["d-e", "d-f", "e-f"]) expect(keys.has(missing)).toBe(false);
    expect(keys.has("a-b")).toBe(true);
    expect(edges.every((e) => e.kind === "project" && e.weight === 0.3)).toBe(true);
  });
});

describe("edgeOpacity / springK / springRest — weight-continuum endpoints (s152)", () => {
  it("springK/springRest at weight 0 are exactly the old tag spring", () => {
    expect(springK(0)).toBeCloseTo(0.003);
    expect(springRest(0)).toBe(170);
  });
  it("springK/springRest at weight 1 are exactly the old wikilink spring", () => {
    expect(springK(1)).toBeCloseTo(0.015);
    expect(springRest(1)).toBe(105);
  });
  it("edgeOpacity is the old tag-line opacity at weight 0", () => {
    expect(edgeOpacity(0)).toBeCloseTo(0.1);
  });
  it("edgeOpacity at weight 1 (NOTE: not the old 0.3 wikilink-line opacity — that inline ternary lived in BrowseStarsView.tsx, not this module's own continuum)", () => {
    expect(edgeOpacity(1)).toBeCloseTo(0.48);
  });
});

describe("computeDegrees", () => {
  it("counts only wikilink-kind edges, ignoring tag edges entirely", () => {
    const edges: SimEdge[] = [
      { a: "a", b: "b", kind: "wikilink", weight: 1 },
      { a: "a", b: "c", kind: "tag", weight: 0.5 },
    ];
    const degrees = computeDegrees(["a", "b", "c"], edges);
    expect(degrees.get("a")).toBe(1);
    expect(degrees.get("b")).toBe(1);
    expect(degrees.get("c")).toBe(0);
  });
});

describe("selectRecentIds", () => {
  it("sorts most-recently-modified first and caps at the given count", () => {
    const items = [
      { id: "old", modified: 100 },
      { id: "new", modified: 300 },
      { id: "mid", modified: 200 },
    ];
    expect(selectRecentIds(items, 2)).toEqual(["new", "mid"]);
  });
  it("sorts a null modified last", () => {
    const items = [
      { id: "unknown", modified: null },
      { id: "known", modified: 1 },
    ];
    expect(selectRecentIds(items)).toEqual(["known", "unknown"]);
  });
});

describe("parseTagsField", () => {
  it("parses a JSON array-of-strings", () => {
    expect(parseTagsField('["a","b"]')).toEqual(["a", "b"]);
  });
  it("returns [] for null/undefined/empty/malformed input", () => {
    expect(parseTagsField(null)).toEqual([]);
    expect(parseTagsField(undefined)).toEqual([]);
    expect(parseTagsField("")).toEqual([]);
    expect(parseTagsField("not json")).toEqual([]);
    expect(parseTagsField("42")).toEqual([]);
  });
});

// ── s156: connection density + the hybrid adaptive floor (D1-C, user-ruled) ──────────────────────
// A unit-circle vector, so the cosine between two of these is exactly cos(theta_i - theta_j) and
// every expectation below can be reasoned about by hand rather than trusted from a run.
function ringVec(i: number, spread: number): number[] {
  return [Math.cos(i * spread), Math.sin(i * spread)];
}

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
    // A vault of unrelated notes: every cosine is low. A pure percentile would keep the top slice
    // anyway and draw a constellation over nothing; the absolute floor must win instead.
    const unrelated = Array.from({ length: 100 }, (_, i) => 0.05 + i * 0.001).sort((a, b) => a - b);
    expect(adaptiveSemanticFloor(unrelated, 83)).toBeCloseTo(SEMANTIC_FLOOR, 6);
    // A one-topic vault: every cosine is high. Here the percentile must win, or the sky saturates.
    const oneTopic = Array.from({ length: 100 }, (_, i) => 0.8 + i * 0.001).sort((a, b) => a - b);
    expect(adaptiveSemanticFloor(oneTopic, 83)).toBeGreaterThan(SEMANTIC_FLOOR);
  });

  it("the default step still equals the shipped constants", () => {
    expect(DENSITY_STEPS).toHaveLength(5);
    expect(DENSITY_STEPS[DENSITY_DEFAULT_INDEX].topK).toBe(EDGE_TOP_K);
    // Percentile falls and budget rises monotonically as density goes up — a step that did neither
    // would be a rail position that does nothing when you drag onto it.
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

  it("a vault of unrelated notes draws NO semantic edge at ANY density", () => {
    // theta step 1.3 rad over four notes: cosines are 0.267, -0.857, -0.726 — every one below the
    // absolute floor. This is the case a pure percentile gets wrong, and the only reason the rule
    // is a max() rather than a replacement.
    const notes = Array.from({ length: 4 }, (_, i) => ({ id: `u${i}`, tags: [], vec: ringVec(i, 1.3) }));
    const ids = new Set(notes.map((n) => n.id));
    for (let i = 0; i < DENSITY_STEPS.length; i++) {
      expect(buildStarEdges(notes, ids, { semantic: true, densityIndex: i })).toEqual([]);
    }
  });

  it("raising density never draws an edge below the absolute floor", () => {
    // theta step 0.25 rad over six notes: 12 of the 15 pairs clear 0.62, three do not.
    const notes = Array.from({ length: 6 }, (_, i) => ({ id: `n${i}`, tags: [], vec: ringVec(i, 0.25) }));
    const ids = new Set(notes.map((n) => n.id));
    const at = (densityIndex: number) => buildStarEdges(notes, ids, { semantic: true, densityIndex });

    // Non-vacuity guard FIRST. Without it the invariant loop below passes over an empty array and
    // reports perfect health for a scorer that draws nothing at all.
    expect(at(DENSITY_DEFAULT_INDEX).length).toBeGreaterThan(0);
    expect(at(0).length).toBeLessThanOrEqual(at(DENSITY_DEFAULT_INDEX).length);
    expect(at(DENSITY_STEPS.length - 1).length).toBeGreaterThanOrEqual(at(DENSITY_DEFAULT_INDEX).length);

    const byId = new Map(notes.map((n) => [n.id, n]));
    for (let i = 0; i < DENSITY_STEPS.length; i++) {
      for (const e of at(i)) {
        if (e.kind !== "semantic") continue;
        const a = byId.get(e.a);
        const b = byId.get(e.b);
        expect(a && b).toBeTruthy();
        expect(cosine(a!.vec, b!.vec)).toBeGreaterThanOrEqual(SEMANTIC_FLOOR);
      }
    }
  });

  it("density moves a NON-semantic sky too — the budget is wired, not just the percentile", () => {
    // Tag edges never touch the floor, so this isolates topK. Six notes sharing one tag = 15 pairs
    // that all bid identically; only the per-node budget decides how many survive.
    const notes = Array.from({ length: 6 }, (_, i) => ({ id: `t${i}`, tags: ["shared"] }));
    const ids = new Set(notes.map((n) => n.id));
    const few = buildStarEdges(notes, ids, { densityIndex: 0 }).length;
    const many = buildStarEdges(notes, ids, { densityIndex: DENSITY_STEPS.length - 1 }).length;
    expect(few).toBeGreaterThan(0);
    expect(many).toBeGreaterThan(few);
  });

  it("omitting densityIndex reproduces the sky that shipped before s156", () => {
    const notes = Array.from({ length: 8 }, (_, i) => ({
      id: `d${i}`,
      tags: i % 2 === 0 ? ["even"] : ["odd"],
      project: i < 4 ? "p" : "q",
    }));
    const ids = new Set(notes.map((n) => n.id));
    expect(buildStarEdges(notes, ids, {})).toEqual(
      buildStarEdges(notes, ids, { densityIndex: DENSITY_DEFAULT_INDEX })
    );
  });

  it("pairWeight normalises against the EFFECTIVE floor, so a just-passing edge is always 0.5", () => {
    const a = { id: "a", tags: [], vec: [1, 0] };
    const b = { id: "b", tags: [], vec: ringVec(1, Math.acos(0.8)) };
    const w = pairWeight(a, b, true, 0.8);
    expect(w?.kind).toBe("semantic");
    expect(w?.weight).toBeCloseTo(0.5, 5);
  });
});

// ── FR-44: the settle envelope, mirrored from the phone port ─────────────────────────────────────
describe("driftEnvelope", () => {
  it("starts at 1 (full drift) and decays linearly to 0 by SETTLE_SEC", () => {
    expect(driftEnvelope(0)).toBe(1);
    expect(driftEnvelope(SETTLE_SEC / 2)).toBeCloseTo(0.5, 10);
    expect(driftEnvelope(SETTLE_SEC)).toBe(0);
  });

  it("never goes negative past SETTLE_SEC", () => {
    expect(driftEnvelope(SETTLE_SEC + 100)).toBe(0);
  });

  it("SETTLE_SEC is 7", () => {
    expect(SETTLE_SEC).toBe(7);
  });

  it("wired into stepSimulation: envelope 0 reproduces reducedMotion's drift-free vx/vy exactly", () => {
    const centred: SimNode = { id: "a", x: 400, y: 300, vx: 0, vy: 0, ph: 0.5, drag: false };
    const t = 500;
    const noEnvelope = stepSimulation([centred], [], t, 800, 600, { driftEnvelope: 0 })[0];
    const reducedMotionOff = stepSimulation([centred], [], t, 800, 600, { reducedMotion: true })[0];
    expect(noEnvelope.vx).toBe(reducedMotionOff.vx);
    expect(noEnvelope.vy).toBe(reducedMotionOff.vy);
  });

  it("omitting driftEnvelope defaults to 1 — every pre-existing caller is behaviour-identical", () => {
    const centred: SimNode = { id: "a", x: 400, y: 300, vx: 0, vy: 0, ph: 0.5, drag: false };
    const t = 500;
    const noOpt = stepSimulation([centred], [], t, 800, 600)[0];
    const explicit1 = stepSimulation([centred], [], t, 800, 600, { driftEnvelope: 1 })[0];
    expect(noOpt).toEqual(explicit1);
  });
});

// ── FR-44: stepSimulation exposes its own max per-node displacement ────────────────────────────────
describe("stepSimulation maxDelta", () => {
  it("is attached to the returned array and is 0 for a frozen (all-dragged) scene", () => {
    // x/y well inside the clamp bounds (CLAMP_X=[66,66], CLAMP_Y=[20,34]) — a dragged node still
    // runs the unconditional clamp every step, so a starting position OUTSIDE it would move on
    // frame one for a reason that has nothing to do with maxDelta itself.
    const nodes: SimNode[] = [{ id: "a", x: 100, y: 100, vx: 0, vy: 0, ph: 0, drag: true }];
    const out = stepSimulation(nodes, [], 0, 800, 600) as SimNode[] & { maxDelta: number };
    expect(out.maxDelta).toBe(0);
  });

  it("is positive when a node actually moves", () => {
    const nodes: SimNode[] = [
      { id: "a", x: 150, y: 240, vx: 0, vy: 0, ph: 0, drag: false },
      { id: "b", x: 400, y: 240, vx: 0, vy: 0, ph: 1.7, drag: false },
    ];
    const edges: SimEdge[] = [{ a: "a", b: "b", kind: "wikilink", weight: 1 }];
    const out = stepSimulation(nodes, edges, 0, 2000, 2000) as SimNode[] & { maxDelta: number };
    expect(out.maxDelta).toBeGreaterThan(0);
  });
});

// ── FR-44: the quiescence guard ──────────────────────────────────────────────────────────────────
describe("quiescenceStep", () => {
  it("QUIESCENCE_DELTA_PX is 0.01 and QUIESCENCE_FRAMES is 30", () => {
    expect(QUIESCENCE_DELTA_PX).toBe(0.01);
    expect(QUIESCENCE_FRAMES).toBe(30);
  });

  it("counts consecutive quiet frames and settles at exactly QUIESCENCE_FRAMES", () => {
    let consecutive = 0;
    let settled = false;
    for (let i = 0; i < QUIESCENCE_FRAMES; i++) {
      const step = quiescenceStep(0.005, consecutive);
      consecutive = step.consecutive;
      settled = step.settled;
      if (i < QUIESCENCE_FRAMES - 1) expect(settled).toBe(false);
    }
    expect(consecutive).toBe(QUIESCENCE_FRAMES);
    expect(settled).toBe(true);
  });

  it("a single frame at/above the threshold resets the counter to 0", () => {
    let step = quiescenceStep(0.005, 20);
    expect(step.consecutive).toBe(21);
    step = quiescenceStep(0.01, step.consecutive); // AT the threshold does not count as quiet
    expect(step.consecutive).toBe(0);
    expect(step.settled).toBe(false);
  });
});

// ── FR-44 pt.4: semantic pulse curves — the SPEC for the CSS-driven animation on BrowseStarsView's
// side (not sampled per frame there; see the comment beside these exports in starsSim.ts) ──────────
describe("semantic pulse curves", () => {
  it("queuedPulseOpacity stays within [QUEUED_PULSE_MIN, QUEUED_PULSE_MAX] and hits both bounds", () => {
    let min = Infinity;
    let max = -Infinity;
    for (let i = 0; i <= 1000; i++) {
      const v = queuedPulseOpacity((i / 1000) * QUEUED_PULSE_PERIOD_SEC, 0);
      expect(v).toBeGreaterThanOrEqual(QUEUED_PULSE_MIN - 1e-9);
      expect(v).toBeLessThanOrEqual(QUEUED_PULSE_MAX + 1e-9);
      min = Math.min(min, v);
      max = Math.max(max, v);
    }
    expect(min).toBeCloseTo(QUEUED_PULSE_MIN, 3);
    expect(max).toBeCloseTo(QUEUED_PULSE_MAX, 3);
  });

  it("conflictPulseOpacity/Radius stay within their own bounds and are in phase (both peak together)", () => {
    let minO = Infinity;
    let maxO = -Infinity;
    let minR = Infinity;
    let maxR = -Infinity;
    for (let i = 0; i <= 1000; i++) {
      const tSec = (i / 1000) * CONFLICT_PULSE_PERIOD_SEC;
      const o = conflictPulseOpacity(tSec, 0);
      const r = conflictPulseRadius(tSec, 0);
      minO = Math.min(minO, o);
      maxO = Math.max(maxO, o);
      minR = Math.min(minR, r);
      maxR = Math.max(maxR, r);
    }
    expect(minO).toBeCloseTo(CONFLICT_OPACITY_MIN, 3);
    expect(maxO).toBeCloseTo(CONFLICT_OPACITY_MAX, 3);
    expect(minR).toBeCloseTo(CONFLICT_RADIUS_MIN, 3);
    expect(maxR).toBeCloseTo(CONFLICT_RADIUS_MAX, 3);
  });

  it("per-node phase actually desyncs two nodes — they are not always equal", () => {
    const a: number[] = [];
    const b: number[] = [];
    for (let i = 0; i <= 20; i++) {
      const tSec = (i / 20) * QUEUED_PULSE_PERIOD_SEC;
      a.push(queuedPulseOpacity(tSec, 0));
      b.push(queuedPulseOpacity(tSec, Math.PI / 2));
    }
    expect(a).not.toEqual(b);
  });
});

// ── FR-44 integration: the settle envelope + quiescence guard actually stop the loop on a
// realistically-sized sky — the three pieces above tested in isolation, this is the end-to-end
// regression guard that they compose correctly (mirrors the phone's own integration test). ────────
describe("FR-44 integration — settle envelope + quiescence guard actually stop the loop", () => {
  const FRAME_MS = 16;
  const MEASURED_WINDOW_FRAMES = 3000;

  function runToSettle(nodeCount: number, useEnvelope: boolean): number {
    let nodes = initNodes(
      Array.from({ length: nodeCount }, (_, i) => `n${i}`),
      800,
      600
    );
    let consecutive = 0;
    for (let frame = 0; frame < MEASURED_WINDOW_FRAMES; frame++) {
      const t = frame * FRAME_MS;
      const opts = useEnvelope ? { driftEnvelope: driftEnvelope(t / 1000) } : {};
      const out = stepSimulation(nodes, [], t, 800, 600, opts) as SimNode[] & { maxDelta: number };
      nodes = out;
      const q = quiescenceStep(out.maxDelta, consecutive);
      consecutive = q.consecutive;
      if (q.settled) return frame;
    }
    return -1; // never settled inside the window
  }

  it("WITHOUT driftEnvelope, a 30-node sky does not settle inside the measured window — this IS FR-44", () => {
    expect(runToSettle(30, false)).toBe(-1);
  });

  it("WITH driftEnvelope wired in, the same 30-node sky settles well inside the same window", () => {
    const frame = runToSettle(30, true);
    expect(frame).toBeGreaterThan(0);
    expect(frame).toBeLessThan(MEASURED_WINDOW_FRAMES);
  });
});

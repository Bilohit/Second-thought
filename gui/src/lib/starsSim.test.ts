import { describe, it, expect } from "vitest";
import {
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
  releaseMomentum,
  selectRecentIds,
  SEMANTIC_FLOOR,
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

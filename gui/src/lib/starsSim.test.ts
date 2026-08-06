import { describe, it, expect } from "vitest";
import {
  buildStarEdges,
  coreVisual,
  hashPosition,
  initNodes,
  isTap,
  parseTagsField,
  releaseMomentum,
  selectRecentIds,
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
    const edges: SimEdge[] = [{ a: "a", b: "b", kind: "wikilink" }];

    const [resA] = stepSimulation([dragged, neighbour], edges, 0, 800, 600);

    expect(resA.vx).toBe(0);
    expect(resA.vy).toBe(0);
    // clamp: x in [26, W-26], y in [20, H-34] — a's raw (-50,-50) is out of bounds on both axes,
    // so ONLY the clamp (unconditional) can be what moved it.
    expect(resA.x).toBe(26);
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
    const edges: SimEdge[] = [{ a: "a", b: "b", kind: "wikilink" }];
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
    expect(edges).toEqual([{ a: "a", b: "b", kind: "tag" }]);
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

describe("computeDegrees", () => {
  it("counts only wikilink-kind edges, ignoring tag edges entirely", () => {
    const edges: SimEdge[] = [
      { a: "a", b: "b", kind: "wikilink" },
      { a: "a", b: "c", kind: "tag" },
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

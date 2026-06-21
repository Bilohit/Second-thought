import { describe, expect, it } from "vitest";
import { availableArc, SAFETY_EPSILON, SPREAD_MAX_ARC, unifiedFan, type FanParams } from "./fanLayout";

const SIX = ["search", "vault", "settings", "inbox", "stats", "hide"];
const SCREENS = [
  { sw: 1440, sh: 900 },
  { sw: 800, sh: 600 },
];

function baseParams(overrides: Partial<FanParams>): FanParams {
  return {
    cx: 0, cy: 0, sw: 1440, sh: 900,
    radius: 100, chipMax: 36, chipMin: 33, pad: 0,
    ids: SIX, minSpacingDeg: 34, fanStyle: "spread",
    ...overrides,
  };
}

function chipSquareInBounds(x: number, y: number, chip: number, sw: number, sh: number) {
  return x - chip / 2 >= -1e-6 && x + chip / 2 <= sw + 1e-6 && y - chip / 2 >= -1e-6 && y + chip / 2 <= sh + 1e-6;
}

describe("availableArc", () => {
  it("reports fullFits=true far from every edge", () => {
    const arc = availableArc(500, 450, 1000, 900, 100, 36, 0);
    expect(arc.fullFits).toBe(true);
    expect(arc.availSpan).toBe(360);
  });

  it("reports a tight ~90deg arc in a corner", () => {
    const arc = availableArc(20, 20, 1000, 900, 100, 36, 0);
    expect(arc.fullFits).toBe(false);
    expect(arc.availSpan).toBeGreaterThan(80);
    expect(arc.availSpan).toBeLessThan(100);
  });

  it("endpoints are valid and just past each endpoint is invalid (tightness)", () => {
    const arc = availableArc(20, 450, 1000, 900, 100, 36, 0);
    expect(arc.fullFits).toBe(false);
    const lo = arc.availCenter - arc.availSpan / 2;
    const hi = arc.availCenter + arc.availSpan / 2;
    expect(arc.isValid(lo)).toBe(true);
    expect(arc.isValid(hi)).toBe(true);
    // The returned endpoints already carry the deliberate inward safety
    // epsilon (erring inward is required); going *another* full epsilon
    // past them must cross into the truly invalid (off-screen) zone, proving
    // the underlying binary-search refinement is tight rather than the old
    // mockup's one-step overshoot.
    expect(arc.isValid(lo - SAFETY_EPSILON - 0.05)).toBe(false);
    expect(arc.isValid(hi + SAFETY_EPSILON + 0.05)).toBe(false);
  });
});

describe("unifiedFan — G1 no chip off-screen (zero tolerance)", () => {
  const positionsToCheck: Array<{ cx: number; cy: number }> = [];
  for (const { sw, sh } of SCREENS) {
    for (let x = 0; x <= sw; x += 80) {
      for (let y = 0; y <= sh; y += 80) {
        positionsToCheck.push({ cx: x, cy: y });
      }
    }
  }

  it.each(SCREENS)("every chip stays fully on-screen across a dense position grid ($sw x $sh)", ({ sw, sh }) => {
    for (let cx = 0; cx <= sw; cx += 80) {
      for (let cy = 0; cy <= sh; cy += 80) {
        for (const n of [2, 3, 4, 5, 6, 7, 8]) {
          for (const fanStyle of ["spread", "capped"] as const) {
            const ids = SIX.concat(["x7", "x8"]).slice(0, n);
            const result = unifiedFan(baseParams({ cx, cy, sw, sh, ids, fanStyle }));
            for (const item of result.items) {
              const screenX = cx + item.x;
              const screenY = cy + item.y;
              expect(
                chipSquareInBounds(screenX, screenY, result.chip, sw, sh),
                `n=${n} fanStyle=${fanStyle} cx=${cx} cy=${cy} id=${item.id} chip=${result.chip} pos=(${screenX},${screenY})`,
              ).toBe(true);
            }
          }
        }
      }
    }
  });
});

describe("unifiedFan — G3 span bounded by geometry", () => {
  it("used span never exceeds availableArc's availSpan when not a full wheel", () => {
    const sw = 1440, sh = 900;
    for (let cx = 0; cx <= sw; cx += 100) {
      for (let cy = 0; cy <= sh; cy += 100) {
        const result = unifiedFan(baseParams({ cx, cy, sw, sh }));
        if (!result.fullFits) {
          const arc = availableArc(cx, cy, sw, sh, 100, result.chip, 0);
          expect(result.span).toBeLessThanOrEqual(arc.availSpan + 0.5);
        }
      }
    }
  });

  it("caps at <=180 deg on a flat edge", () => {
    const result = unifiedFan(baseParams({ cx: 700, cy: 0, sw: 1440, sh: 900, fanStyle: "spread" }));
    expect(result.fullFits).toBe(false);
    expect(result.span).toBeLessThanOrEqual(180.5);
  });

  it("caps at <=90 deg in a corner", () => {
    const result = unifiedFan(baseParams({ cx: 0, cy: 0, sw: 1440, sh: 900, fanStyle: "spread" }));
    expect(result.fullFits).toBe(false);
    expect(result.span).toBeLessThanOrEqual(90.5);
  });
});

describe("unifiedFan — spread cap", () => {
  it("never exceeds SPREAD_MAX_ARC in spread mode when not a full wheel", () => {
    const sw = 1440, sh = 900;
    for (let cx = 0; cx <= sw; cx += 60) {
      const result = unifiedFan(baseParams({ cx, cy: 450, sw, sh, fanStyle: "spread" }));
      if (!result.fullFits) expect(result.span).toBeLessThanOrEqual(SPREAD_MAX_ARC + 0.5);
    }
  });
});

describe("unifiedFan — full wheel", () => {
  it("a center far from all edges yields fullFits, span=360, equal 360/n gaps", () => {
    const result = unifiedFan(baseParams({ cx: 720, cy: 450, sw: 1440, sh: 900 }));
    expect(result.fullFits).toBe(true);
    expect(result.span).toBe(360);
    const angles = result.items.map((i) => i.angleDeg).sort((a, b) => a - b);
    const gaps = angles.slice(1).map((a, i) => a - angles[i]);
    for (const g of gaps) expect(g).toBeCloseTo(360 / SIX.length, 4);
  });

  it("pins the first canonical item (search) to 12 o'clock", () => {
    const result = unifiedFan(baseParams({ cx: 720, cy: 450, sw: 1440, sh: 900 }));
    const search = result.items.find((i) => i.id === "search")!;
    expect(search.angleDeg).toBeCloseTo(-90, 4);
  });
});

describe("unifiedFan — dynamic chip size", () => {
  it("chip stays within [chipMin, chipMax]", () => {
    const sw = 1440, sh = 900;
    for (let cx = 0; cx <= sw; cx += 100) {
      for (let cy = 0; cy <= sh; cy += 100) {
        const result = unifiedFan(baseParams({ cx, cy, sw, sh }));
        expect(result.chip).toBeGreaterThanOrEqual(33 - 1e-6);
        expect(result.chip).toBeLessThanOrEqual(36 + 1e-6);
      }
    }
  });

  it("uses chipMax when there's plenty of room (full wheel, few items)", () => {
    const result = unifiedFan(baseParams({ cx: 720, cy: 450, sw: 1440, sh: 900, ids: ["a", "b", "c"] }));
    expect(result.chip).toBeCloseTo(36, 4);
  });
});

describe("unifiedFan — determinism (G4)", () => {
  it("identical inputs produce identical outputs", () => {
    const params = baseParams({ cx: 300, cy: 200, sw: 1440, sh: 900 });
    const a = unifiedFan(params);
    const b = unifiedFan(params);
    expect(a).toEqual(b);
  });

  it("a pinned-equivalent center and a custom position at the same point match", () => {
    const pinnedLikeCenter = { cx: 12 + 18, cy: 12 + 18 }; // e.g. "tl" pill center
    const a = unifiedFan(baseParams({ cx: pinnedLikeCenter.cx, cy: pinnedLikeCenter.cy, sw: 1440, sh: 900 }));
    const b = unifiedFan(baseParams({ cx: pinnedLikeCenter.cx, cy: pinnedLikeCenter.cy, sw: 1440, sh: 900 }));
    expect(a.items).toEqual(b.items);
  });
});

describe("unifiedFan — reading order", () => {
  it("Search...Hide stays top-to-bottom for every tested anchor/position", () => {
    const sw = 1440, sh = 900;
    const positions = [
      { cx: 18, cy: 18 }, { cx: 720, cy: 18 }, { cx: 1422, cy: 18 },
      { cx: 18, cy: 450 }, { cx: 720, cy: 450 }, { cx: 1422, cy: 450 },
      { cx: 18, cy: 882 }, { cx: 720, cy: 882 }, { cx: 1422, cy: 882 },
    ];
    for (const { cx, cy } of positions) {
      const result = unifiedFan(baseParams({ cx, cy, sw, sh }));
      const search = result.items.find((i) => i.id === "search")!;
      const hide = result.items.find((i) => i.id === "hide")!;
      expect(search.y).toBeLessThanOrEqual(hide.y + 1e-6);
    }
  });
});

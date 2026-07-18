import { describe, it, expect } from "vitest";
import { contrast, checkPalette, hardFails, snapToPass, type Palette } from "./themeContrast";

// Void (dark) — the shipping default, vendored from index.css [data-theme="dark"] with the OF-27
// text-3 bump (#7a7a7a). Inlined here (gui keeps palettes in CSS, not a TS record); the phone side
// verifies the whole preset family from its THEMES record (values match by the vendoring lock).
const VOID: Palette = {
  bg: "#0a0a0a", surface: "#262626", surface2: "#404040", border: "#383838", border2: "#262626",
  text1: "#fafafa", text2: "#a1a1a1", text3: "#7a7a7a",
  accent: "#737373", accentDim: "rgba(115,115,115,0.18)", accentGlow: "rgba(115,115,115,0.30)",
  onAccent: "#fafafa", paletteBg: "#262626",
  recording: "#c25b52", green: "#4ade80", yellow: "#facc15", red: "#ff6467",
  glassBg: "#191919", glassBorder: "#383838", scrim: "rgba(0,0,0,0.55)",
};

describe("WCAG contrast", () => {
  it("computes known ratios (black/white = 21)", () => {
    expect(Math.round(contrast("#000000", "#ffffff"))).toBe(21);
    expect(contrast("#000000", "#000000")).toBe(1);
  });
  it("is symmetric (order-independent)", () => {
    expect(contrast("#7a7a7a", "#0a0a0a")).toBeCloseTo(contrast("#0a0a0a", "#7a7a7a"), 10);
  });
  it("text3 #7a7a7a on #0a0a0a passes the 4.5 bar (OF-27 post-fix)", () => {
    expect(contrast("#7a7a7a", "#0a0a0a")).toBeGreaterThanOrEqual(4.5);
  });
  it("text3 #737373 on #0a0a0a FAILS the 4.5 bar (OF-27 pre-fix)", () => {
    expect(contrast("#737373", "#0a0a0a")).toBeLessThan(4.5);
  });
});

describe("checkPalette / hardFails", () => {
  it("Void passes every hard check (zero hard fails)", () => {
    expect(hardFails(VOID)).toHaveLength(0);
  });
  it("runs all five guardrails, border marked soft", () => {
    const checks = checkPalette(VOID);
    expect(checks.map((c) => c.key)).toEqual(["text1", "text2", "text3", "accent", "border"]);
    expect(checks.find((c) => c.key === "border")!.soft).toBe(true);
    expect(checks.filter((c) => !c.soft)).toHaveLength(4);
  });
  it("a low-contrast text-1 registers as a hard fail", () => {
    expect(hardFails({ ...VOID, text1: "#111111" }).some((c) => c.key === "text1")).toBe(true);
  });
});

describe("snapToPass", () => {
  it("returns the input unchanged when it already passes", () => {
    expect(snapToPass("#fafafa", "#0a0a0a", 7)).toBe("#fafafa");
  });
  it("returns a shade meeting the min for a failing pair (dark bg → lighter fg)", () => {
    const snapped = snapToPass("#3a3a3a", "#0a0a0a", 4.5);
    expect(contrast(snapped, "#0a0a0a")).toBeGreaterThanOrEqual(4.5);
  });
  it("darkens the fg on a light bg", () => {
    const snapped = snapToPass("#cccccc", "#ffffff", 4.5);
    expect(contrast(snapped, "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });
});

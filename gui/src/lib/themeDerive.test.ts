import { describe, it, expect } from "vitest";
import { deriveCustom } from "./themeDerive";
import type { EditableSlot } from "./themeCode";

const voidEditable: Record<EditableSlot, string> = {
  bg: "#0a0a0a", surface: "#262626", surface2: "#404040", border: "#383838",
  text1: "#fafafa", text2: "#a1a1a1", text3: "#7a7a7a", accent: "#737373", glassBg: "#191919",
};

describe("deriveCustom", () => {
  it("passes the 9 editable slots through unchanged", () => {
    const p = deriveCustom(voidEditable);
    expect(p.bg).toBe("#0a0a0a");
    expect(p.surface).toBe("#262626");
    expect(p.text3).toBe("#7a7a7a");
    expect(p.accent).toBe("#737373");
    expect(p.glassBg).toBe("#191919");
  });
  it("derives the scheme-locked semantic colors for a DARK bg", () => {
    const p = deriveCustom(voidEditable);
    expect(p.green).toBe("#4ade80");
    expect(p.yellow).toBe("#facc15");
    expect(p.red).toBe("#ff6467");
    expect(p.scrim).toBe("rgba(0,0,0,0.55)");
    expect(p.accentDim).toBe("rgba(115, 115, 115, 0.18)");
  });
  it("switches to LIGHT scheme colors when bg is light", () => {
    const p = deriveCustom({ ...voidEditable, bg: "#ffffff", text1: "#0a0a0a" });
    expect(p.green).toBe("#16a34a");
    expect(p.red).toBe("#e7000b");
    expect(p.scrim).toBe("rgba(0,0,0,0.25)");
    expect(p.accentDim).toContain("0.1"); // light hover-dim alpha
  });
  it("on-accent flips by accent luminance (dark accent → light text, light accent → dark text)", () => {
    expect(deriveCustom({ ...voidEditable, accent: "#333333" }).onAccent).toBe("#fafafa");
    expect(deriveCustom({ ...voidEditable, accent: "#e0c060" }).onAccent).toBe("#0a0a0a");
  });
  it("border-2 sits between border and bg (a fainter divider)", () => {
    const p = deriveCustom(voidEditable);
    // mix(#383838, #0a0a0a, 0.35) → darker than border, lighter than bg
    expect(p.border2).toBe("#282828");
  });
});

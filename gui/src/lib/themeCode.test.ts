import { describe, it, expect } from "vitest";
import { encodeTheme, decodeTheme, EDITABLE_ORDER } from "./themeCode";

const slots = {
  bg: "#0a0a0a", surface: "#262626", surface2: "#404040", border: "#383838",
  text1: "#fafafa", text2: "#a1a1a1", text3: "#7a7a7a", accent: "#737373", glassBg: "#191919",
};

describe("st1 theme code", () => {
  it("round-trips", () => {
    expect(decodeTheme(encodeTheme(slots))).toEqual(slots);
  });
  it("starts with st1: and is exactly 54 hex after the prefix", () => {
    const code = encodeTheme(slots);
    expect(code.startsWith("st1:")).toBe(true);
    expect(code.slice(4)).toMatch(/^[0-9a-f]{54}$/);
  });
  it("encodes the 9 editable slots in the fixed order", () => {
    expect(EDITABLE_ORDER).toHaveLength(9);
    expect(encodeTheme(slots)).toBe("st1:0a0a0a262626404040383838fafafaa1a1a17a7a7a737373191919");
  });
  it("normalizes case (uppercase in → lowercase round-trip)", () => {
    const up = { ...slots, bg: "#0A0A0A", accent: "#737373" };
    expect(decodeTheme(encodeTheme(up))!.bg).toBe("#0a0a0a");
  });
  it("tolerates surrounding whitespace on decode", () => {
    expect(decodeTheme("  " + encodeTheme(slots) + "  ")).toEqual(slots);
  });
  it("rejects a bad prefix", () => expect(decodeTheme("xx:" + "0".repeat(54))).toBeNull());
  it("rejects wrong length", () => expect(decodeTheme("st1:0a0a0a")).toBeNull());
  it("rejects non-hex", () => expect(decodeTheme("st1:" + "zz".repeat(27))).toBeNull());
  it("rejects an empty / garbage string", () => {
    expect(decodeTheme("")).toBeNull();
    expect(decodeTheme("st1:")).toBeNull();
  });
});

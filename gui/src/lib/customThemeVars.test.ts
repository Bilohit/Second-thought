// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from "vitest";
import { applyCustomThemeVars, removeCustomThemeVars, CUSTOM_THEME_VAR_NAMES } from "./customThemeVars";
import { deriveCustom } from "./themeDerive";
import type { EditableSlot } from "./themeCode";

const voidEditable: Record<EditableSlot, string> = {
  bg: "#0a0a0a", surface: "#262626", surface2: "#404040", border: "#383838",
  text1: "#fafafa", text2: "#a1a1a1", text3: "#7a7a7a", accent: "#737373", glassBg: "#191919",
};

const customEditable: Record<EditableSlot, string> = {
  ...voidEditable,
  accent: "#3fae6b",
};

// FR-03: production CSP (style-src 'self', no unsafe-inline/nonce) silently
// drops an injected <style> tag, so the fix writes inline custom properties
// on the target element instead. These tests exercise that DOM contract
// directly (happy-dom supports style.setProperty/removeProperty/getPropertyValue
// without a layout engine, so no geometry assertions are needed here).
describe("applyCustomThemeVars / removeCustomThemeVars", () => {
  let el: HTMLElement;
  beforeEach(() => {
    el = document.createElement("div");
  });

  it("writes every derived palette value as an inline custom property", () => {
    const p = deriveCustom(customEditable);
    applyCustomThemeVars(p, el);
    expect(el.style.getPropertyValue("--accent")).toBe("#3fae6b");
    expect(el.style.getPropertyValue("--bg")).toBe("#0a0a0a");
    expect(el.style.getPropertyValue("--glass-bg")).toBe("#191919");
    expect(el.style.getPropertyValue("--scrim")).toBe(p.scrim);
  });

  it("removeCustomThemeVars clears every property applyCustomThemeVars can set", () => {
    applyCustomThemeVars(deriveCustom(customEditable), el);
    // Sanity: something was actually set before we assert it's gone.
    expect(el.style.getPropertyValue("--accent")).not.toBe("");
    removeCustomThemeVars(el);
    for (const name of CUSTOM_THEME_VAR_NAMES) {
      expect(el.style.getPropertyValue(name)).toBe("");
    }
    expect(el.getAttribute("style") ?? "").toBe("");
  });

  it("round-trips custom -> preset -> custom -> preset without residue", () => {
    // custom
    applyCustomThemeVars(deriveCustom(customEditable), el);
    expect(el.style.getPropertyValue("--accent")).toBe("#3fae6b");

    // -> preset (theme switch away from "custom")
    removeCustomThemeVars(el);
    expect(el.style.getPropertyValue("--accent")).toBe("");

    // -> custom again
    applyCustomThemeVars(deriveCustom(customEditable), el);
    expect(el.style.getPropertyValue("--accent")).toBe("#3fae6b");

    // -> preset again: must be fully clean, not just re-overwritten
    removeCustomThemeVars(el);
    for (const name of CUSTOM_THEME_VAR_NAMES) {
      expect(el.style.getPropertyValue(name)).toBe("");
    }
  });

  it("defaults to document.documentElement when no target is passed", () => {
    applyCustomThemeVars(deriveCustom(customEditable));
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#3fae6b");
    removeCustomThemeVars();
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("");
  });
});

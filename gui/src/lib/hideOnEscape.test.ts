import { describe, it, expect } from "vitest";
import { shouldHideOnEscape } from "./hideOnEscape";

describe("shouldHideOnEscape", () => {
  it("hides from the bare pill", () => {
    expect(shouldHideOnEscape({ displayMode: "minimal", menuOpen: false, compactPanel: null })).toBe(true);
  });

  it("closes the menu instead of hiding when the menu is open", () => {
    expect(shouldHideOnEscape({ displayMode: "capsule", menuOpen: true, compactPanel: null })).toBe(false);
  });

  it("closes the panel instead of hiding when a compact panel is open", () => {
    expect(shouldHideOnEscape({ displayMode: "capsule", menuOpen: false, compactPanel: "vault" })).toBe(false);
  });

  it("never hides from full window", () => {
    expect(shouldHideOnEscape({ displayMode: "full", menuOpen: false, compactPanel: null })).toBe(false);
  });
});

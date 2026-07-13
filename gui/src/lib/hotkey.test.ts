import { describe, it, expect } from "vitest";
import { canParseHotkey } from "./hotkey";

// A-2: canParseHotkey mirrors src-tauri/src/lib.rs's parse_shortcut — a
// hotkey must be rejected client-side (before patchConfig/setHotkeyRust)
// whenever parse_shortcut would return None, i.e. no segment resolves to
// an actual key code.
describe("canParseHotkey", () => {
  it("accepts the default hotkey", () => {
    expect(canParseHotkey("ctrl+shift+space")).toBe(true);
  });

  it("accepts a single letter with modifiers", () => {
    expect(canParseHotkey("ctrl+alt+k")).toBe(true);
  });

  it("accepts a single digit", () => {
    expect(canParseHotkey("ctrl+5")).toBe(true);
  });

  it("accepts named keys: space/enter/return/tab/backspace", () => {
    expect(canParseHotkey("ctrl+space")).toBe(true);
    expect(canParseHotkey("ctrl+enter")).toBe(true);
    expect(canParseHotkey("ctrl+return")).toBe(true);
    expect(canParseHotkey("ctrl+tab")).toBe(true);
    expect(canParseHotkey("ctrl+backspace")).toBe(true);
  });

  it("rejects modifiers-only combos", () => {
    expect(canParseHotkey("ctrl+shift")).toBe(false);
    expect(canParseHotkey("ctrl")).toBe(false);
  });

  it("rejects unmapped keys Rust's parser can't resolve (F-keys/arrows/escape)", () => {
    expect(canParseHotkey("ctrl+f1")).toBe(false);
    expect(canParseHotkey("ctrl+arrowup")).toBe(false);
    expect(canParseHotkey("ctrl+escape")).toBe(false);
  });

  it("is case-insensitive and trims whitespace, matching the Rust side", () => {
    expect(canParseHotkey("CTRL+ K")).toBe(true);
    expect(canParseHotkey("Ctrl+Shift+Space")).toBe(true);
  });
});

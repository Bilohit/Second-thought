import { describe, it, expect } from "vitest";
import { SENSITIVE_KEY_RE } from "./logger";

/** GUI-20: the redaction key pattern. The regression that motivated the last
 *  alternative is the LAN secretbox key, whose field is literally named `key`
 *  — the original pattern matched `api_key` but not `key`, so the one
 *  credential that can decrypt LAN traffic was logged in the clear. */
describe("SENSITIVE_KEY_RE", () => {
  it("still matches everything it matched before", () => {
    for (const k of [
      "secret", "gui_secret", "token", "accessToken", "password",
      "authorization", "api_key", "api-key", "apiKey", "cookie",
    ]) {
      expect(SENSITIVE_KEY_RE.test(k), k).toBe(true);
    }
  });

  it("matches a field named exactly `key`, and its qualified forms", () => {
    for (const k of ["key", "Key", "lan_key", "lan-key", "key.id", "shared key"]) {
      expect(SENSITIVE_KEY_RE.test(k), k).toBe(true);
    }
  });

  it("does not over-match unrelated words containing 'key'", () => {
    for (const k of ["monkey", "keyboard", "keywords", "hotkey", "turkey"]) {
      expect(SENSITIVE_KEY_RE.test(k), k).toBe(false);
    }
  });

  it("leaves ordinary field names alone", () => {
    for (const k of ["path", "count", "status", "category", "bytes"]) {
      expect(SENSITIVE_KEY_RE.test(k), k).toBe(false);
    }
  });

  it("is stateless across calls (no /g flag)", () => {
    expect(SENSITIVE_KEY_RE.test("key")).toBe(true);
    expect(SENSITIVE_KEY_RE.test("key")).toBe(true);
  });
});

import { describe, it, expect } from "vitest";
import { isInsideRoot } from "./pathGuard";

const ROOT = "C:/Users/me/second-thought-storage";

describe("isInsideRoot", () => {
  it("accepts a file directly under the root", () => {
    expect(isInsideRoot(ROOT, `${ROOT}/ideas/note.md`)).toBe(true);
  });

  it("accepts the root itself", () => {
    expect(isInsideRoot(ROOT, ROOT)).toBe(true);
  });

  it("ignores separator style — the server may return either", () => {
    expect(isInsideRoot(ROOT, "C:\\Users\\me\\second-thought-storage\\ideas\\note.md")).toBe(true);
    expect(isInsideRoot("C:\\Users\\me\\second-thought-storage", `${ROOT}/a.md`)).toBe(true);
  });

  it("ignores case (Windows is the shipping target)", () => {
    expect(isInsideRoot(ROOT, "c:/users/ME/Second-Thought-Storage/a.md")).toBe(true);
  });

  it("tolerates a trailing separator on the root", () => {
    expect(isInsideRoot(`${ROOT}/`, `${ROOT}/a.md`)).toBe(true);
  });

  it("rejects a sibling directory sharing the root's prefix", () => {
    expect(isInsideRoot(ROOT, `${ROOT}-backup/a.md`)).toBe(false);
  });

  it("rejects a path outside the vault", () => {
    expect(isInsideRoot(ROOT, "C:/Users/me/.ssh/id_rsa")).toBe(false);
    expect(isInsideRoot(ROOT, "C:/Windows/System32/calc.exe")).toBe(false);
  });

  it("rejects traversal segments outright", () => {
    expect(isInsideRoot(ROOT, `${ROOT}/../.ssh/id_rsa`)).toBe(false);
  });

  it("rejects empty inputs rather than opening everything", () => {
    expect(isInsideRoot("", `${ROOT}/a.md`)).toBe(false);
    expect(isInsideRoot(ROOT, "")).toBe(false);
  });
});

import { describe, it, expect } from "vitest";
import { middleEllipsis } from "./middleEllipsis";

describe("middleEllipsis", () => {
  it("returns short strings unchanged", () => {
    expect(middleEllipsis("short", 20)).toBe("short");
  });

  it("returns a string exactly at the limit unchanged", () => {
    expect(middleEllipsis("exactly10c", 10)).toBe("exactly10c");
  });

  it("truncates the middle, not the start or end, of a long path", () => {
    const path = "C:/Users/biloh/Documents/SecondThoughtVault/STORAGE";
    const out = middleEllipsis(path, 20);
    expect(out.length).toBe(20);
    expect(out).toContain("…");
    expect(out.startsWith("C:/Users")).toBe(true);
    expect(out.endsWith("STORAGE")).toBe(true);
  });

  it("keeps output length at or under maxChars", () => {
    const out = middleEllipsis("a".repeat(100), 15);
    expect(out.length).toBeLessThanOrEqual(15);
  });

  it("degrades gracefully when maxChars is too small to be useful", () => {
    expect(middleEllipsis("hello world", 1)).toBe("hello world");
    expect(middleEllipsis("hello world", 0)).toBe("hello world");
  });

  it("handles an empty string", () => {
    expect(middleEllipsis("", 10)).toBe("");
  });

  it("favors one extra character on the head when the remainder is odd", () => {
    // maxChars=5 -> keep=4 -> head=2, tail=2 (even split)
    expect(middleEllipsis("abcdefgh", 5)).toBe("ab…gh");
    // maxChars=6 -> keep=5 -> head=3, tail=2 (head gets the extra char)
    expect(middleEllipsis("abcdefgh", 6)).toBe("abc…gh");
  });
});

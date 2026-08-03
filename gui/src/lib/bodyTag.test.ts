import { describe, expect, it } from "vitest";
import { BODY_TAG_HINT, isValidBodyTag, normalizeBodyTag } from "./bodyTag";

// Same vectors as omni_capture/test_body_tags.py's is_valid_body_tag block. If one side changes,
// the other must change with it — a GUI that accepts what the server rejects re-creates FR-01.

describe("isValidBodyTag", () => {
  it("accepts ordinary tag shapes", () => {
    for (const t of ["daily", "work", "area/health", "@work", "project:work", "a-b", "x_1", "abcd", "D"]) {
      expect(isValidBodyTag(t), t).toBe(true);
    }
  });

  it("rejects what the scanner would mangle", () => {
    for (const t of ["", "my tag", "two words", "#daily", "-lead", "/lead", "tag!", "tag.md"]) {
      expect(isValidBodyTag(t), t).toBe(false);
    }
  });

  it("rejects the hex-colour silent drop", () => {
    for (const t of ["abc", "fff", "a1b2c3", "DEADBE"]) {
      expect(isValidBodyTag(t), t).toBe(false);
    }
    expect(isValidBodyTag("abcd")).toBe(true); // 4 digits is not a colour shape
  });

  it("rejects structural tags, so the field is not a back door into projects", () => {
    for (const t of ["sys", "sys/llm-failed", "project@work", "project@_loose"]) {
      expect(isValidBodyTag(t), t).toBe(false);
    }
  });
});

describe("normalizeBodyTag", () => {
  it("forgives a leading # and surrounding space", () => {
    expect(normalizeBodyTag("  #daily ")).toBe("daily");
    expect(normalizeBodyTag("##daily")).toBe("daily");
    expect(normalizeBodyTag("daily")).toBe("daily");
  });

  it("does not invent validity", () => {
    expect(isValidBodyTag(normalizeBodyTag("#my tag"))).toBe(false);
  });
});

describe("BODY_TAG_HINT", () => {
  it("names the grammar it enforces", () => {
    expect(BODY_TAG_HINT).toMatch(/no spaces/);
  });
});

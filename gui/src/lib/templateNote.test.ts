// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from "vitest";
import { getTemplateNotePath, setTemplateNotePath, isTemplateNote } from "./templateNote";

describe("templateNote", () => {
  beforeEach(() => localStorage.clear());

  it("starts with no template set", () => {
    expect(getTemplateNotePath()).toBeNull();
    expect(isTemplateNote("Notes/a.md")).toBe(false);
  });

  it("setTemplateNotePath persists and isTemplateNote reflects it", () => {
    setTemplateNotePath("Notes/a.md");
    expect(getTemplateNotePath()).toBe("Notes/a.md");
    expect(isTemplateNote("Notes/a.md")).toBe(true);
    expect(isTemplateNote("Notes/b.md")).toBe(false);
  });

  it("setting a new template replaces the old one (one slot)", () => {
    setTemplateNotePath("Notes/a.md");
    setTemplateNotePath("Notes/b.md");
    expect(getTemplateNotePath()).toBe("Notes/b.md");
    expect(isTemplateNote("Notes/a.md")).toBe(false);
  });
});

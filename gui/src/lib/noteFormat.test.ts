import { describe, it, expect } from "vitest";
import { applyMarkdownFormat, parseOutline, parseWikilinks } from "./noteFormat";

describe("applyMarkdownFormat — checklist", () => {
  it("prefixes the current line with '- [ ] ' when selection is collapsed", () => {
    const value = "buy milk";
    const r = applyMarkdownFormat(value, 0, 0, "checklist");
    expect(r.value).toBe("- [ ] buy milk");
    expect(r.selStart).toBe(6);
    expect(r.selEnd).toBe(6);
  });

  it("prefixes the line the selection starts on, not the document start", () => {
    const value = "first line\nsecond line";
    const secondLineStart = value.indexOf("second");
    const r = applyMarkdownFormat(value, secondLineStart, secondLineStart, "checklist");
    expect(r.value).toBe("first line\n- [ ] second line");
  });
});

describe("applyMarkdownFormat — tag", () => {
  it("inserts a bare '#' at the caret when selection is collapsed", () => {
    const value = "meeting notes";
    const r = applyMarkdownFormat(value, 8, 8, "tag");
    expect(r.value).toBe("meeting #notes");
    expect(r.selStart).toBe(9);
    expect(r.selEnd).toBe(9);
  });

  it("wraps a non-empty selection between '#' and nothing (selection becomes the tag name)", () => {
    const value = "meeting project";
    const start = value.indexOf("project");
    const end = start + "project".length;
    const r = applyMarkdownFormat(value, start, end, "tag");
    expect(r.value).toBe("meeting #project");
  });
});

describe("applyMarkdownFormat — bold and link still work (regression guard)", () => {
  it("bold wraps the selection in '**'", () => {
    const r = applyMarkdownFormat("hello world", 6, 11, "bold");
    expect(r.value).toBe("hello **world**");
  });

  it("link wraps the selection in '[' and '](url)'", () => {
    const r = applyMarkdownFormat("see docs", 4, 8, "link");
    expect(r.value).toBe("see [docs](url)");
  });
});

describe("parseOutline", () => {
  it("collects ATX headings in document order with their line index", () => {
    const body = "# Title\n\nintro text\n\n## Section one\n\nbody\n\n### Sub\n";
    expect(parseOutline(body)).toEqual([
      { level: 1, text: "Title", line: 0 },
      { level: 2, text: "Section one", line: 4 },
      { level: 3, text: "Sub", line: 8 },
    ]);
  });

  it("ignores non-heading lines that merely start with #", () => {
    expect(parseOutline("#no-space-heading\n# Real heading")).toEqual([
      { level: 1, text: "Real heading", line: 1 },
    ]);
  });

  it("returns an empty array for a body with no headings", () => {
    expect(parseOutline("just prose, no headings here")).toEqual([]);
  });
});

describe("parseWikilinks", () => {
  it("extracts wikilink targets, de-duplicated and in first-seen order", () => {
    const body = "See [[capture-pipeline-design]] and also [[capture-pipeline-design]] again, then [[obsidian-workflow|workflow]].";
    expect(parseWikilinks(body)).toEqual(["capture-pipeline-design", "obsidian-workflow"]);
  });

  it("returns an empty array when there are no wikilinks", () => {
    expect(parseWikilinks("no links in this note")).toEqual([]);
  });
});

describe("parseOutline", () => {
  it("collects ATX headings in document order with their line index", () => {
    const body = "# Title\n\nintro text\n\n## Section one\n\nbody\n\n### Sub\n";
    expect(parseOutline(body)).toEqual([
      { level: 1, text: "Title", line: 0 },
      { level: 2, text: "Section one", line: 4 },
      { level: 3, text: "Sub", line: 8 },
    ]);
  });

  it("ignores non-heading lines that merely start with #", () => {
    expect(parseOutline("#no-space-heading\n# Real heading")).toEqual([
      { level: 1, text: "Real heading", line: 1 },
    ]);
  });

  it("returns an empty array for a body with no headings", () => {
    expect(parseOutline("just prose, no headings here")).toEqual([]);
  });
});

describe("parseWikilinks", () => {
  it("extracts wikilink targets, de-duplicated and in first-seen order", () => {
    const body = "See [[capture-pipeline-design]] and also [[capture-pipeline-design]] again, then [[obsidian-workflow|workflow]].";
    expect(parseWikilinks(body)).toEqual(["capture-pipeline-design", "obsidian-workflow"]);
  });

  it("returns an empty array when there are no wikilinks", () => {
    expect(parseWikilinks("no links in this note")).toEqual([]);
  });
});

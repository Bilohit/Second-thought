import { describe, it, expect } from "vitest";
import { applyMarkdownFormat, parseOutline, parseWikilinks } from "./noteFormat";

describe("applyMarkdownFormat", () => {
  it("wraps a selection in bold markers", () => {
    const r = applyMarkdownFormat("hello world", 6, 11, "bold");
    expect(r.value).toBe("hello **world**");
    expect(r.selStart).toBe(r.selEnd);
  });

  it("wraps a selection in italic markers", () => {
    const r = applyMarkdownFormat("hello world", 0, 5, "italic");
    expect(r.value).toBe("_hello_ world");
  });

  it("wraps a link selection with a placeholder url", () => {
    const r = applyMarkdownFormat("see docs", 4, 8, "link");
    expect(r.value).toBe("see [docs](url)");
  });

  it("inserts a heading prefix at the start of the current line, not the caret", () => {
    const value = "first line\nsecond line";
    const caret = value.indexOf("second") + 3; // mid-word in "second"
    const r = applyMarkdownFormat(value, caret, caret, "heading");
    expect(r.value).toBe("first line\n## second line");
  });

  it("inserts a list prefix at the start of the current line", () => {
    const value = "only line";
    const r = applyMarkdownFormat(value, 3, 3, "list");
    expect(r.value).toBe("- only line");
  });

  it("wraps a selection in a fenced code block", () => {
    const r = applyMarkdownFormat("const x = 1;", 0, 12, "code");
    expect(r.value).toBe("```\nconst x = 1;\n```");
  });

  it("collapses caret to the end of the inserted/wrapped range", () => {
    const r = applyMarkdownFormat("ab", 0, 0, "bold");
    expect(r.value).toBe("****ab");
    expect(r.selStart).toBe(2);
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

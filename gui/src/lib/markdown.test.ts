import { describe, it, expect } from "vitest";
import { parseBlocks, parseInline } from "./markdown";

describe("parseInline", () => {
  it("parses plain text with no markers", () => {
    expect(parseInline("hello world")).toEqual([{ kind: "text", value: "hello world" }]);
  });

  it("parses bold", () => {
    expect(parseInline("a **b** c")).toEqual([
      { kind: "text", value: "a " },
      { kind: "bold", value: "b" },
      { kind: "text", value: " c" },
    ]);
  });

  it("parses wikilinks", () => {
    expect(parseInline("see [[Some Note]] now")).toEqual([
      { kind: "text", value: "see " },
      { kind: "wikilink", target: "Some Note" },
      { kind: "text", value: " now" },
    ]);
  });
});

describe("parseBlocks", () => {
  it("parses a heading", () => {
    expect(parseBlocks("## Title")).toEqual([
      { kind: "heading", level: 2, spans: [{ kind: "text", value: "Title" }] },
    ]);
  });

  it("parses a checked and unchecked checklist item", () => {
    expect(parseBlocks("- [x] done\n- [ ] todo")).toEqual([
      { kind: "check", checked: true, spans: [{ kind: "text", value: "done" }] },
      { kind: "check", checked: false, spans: [{ kind: "text", value: "todo" }] },
    ]);
  });

  it("parses a bullet", () => {
    expect(parseBlocks("- an item")).toEqual([
      { kind: "bullet", spans: [{ kind: "text", value: "an item" }] },
    ]);
  });

  it("parses an attachment line", () => {
    expect(parseBlocks("[attachment: voice.wav]")).toEqual([
      { kind: "attachment", filename: "voice.wav" },
    ]);
  });

  it("collapses consecutive non-blank lines into one paragraph, joined by spaces", () => {
    expect(parseBlocks("line one\nline two")).toEqual([
      { kind: "paragraph", spans: [{ kind: "text", value: "line one line two" }] },
    ]);
  });

  it("splits paragraphs on a blank line", () => {
    expect(parseBlocks("first\n\nsecond")).toEqual([
      { kind: "paragraph", spans: [{ kind: "text", value: "first" }] },
      { kind: "paragraph", spans: [{ kind: "text", value: "second" }] },
    ]);
  });

  it("renders an attachment line in place between paragraphs", () => {
    expect(parseBlocks("before\n[attachment: photo.png]\nafter")).toEqual([
      { kind: "paragraph", spans: [{ kind: "text", value: "before" }] },
      { kind: "attachment", filename: "photo.png" },
      { kind: "paragraph", spans: [{ kind: "text", value: "after" }] },
    ]);
  });
});

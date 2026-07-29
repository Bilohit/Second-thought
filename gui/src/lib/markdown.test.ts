import { describe, it, expect } from "vitest";
import { parseBlocks, parseInline, blockKey } from "./markdown";

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

  it("parses an inline-ref attachment whole line", () => {
    expect(parseBlocks("![voice memo](../_attachments/note-1/memo.m4a)")).toEqual([
      { kind: "attachment", filename: "memo.m4a", alt: "voice memo" },
    ]);
  });

  it("parses both attachment forms in one body", () => {
    expect(
      parseBlocks("before\n[attachment: a.jpg]\nmiddle\n![photo](../_attachments/note-1/b.png)\nafter")
    ).toEqual([
      { kind: "paragraph", spans: [{ kind: "text", value: "before" }] },
      { kind: "attachment", filename: "a.jpg" },
      { kind: "paragraph", spans: [{ kind: "text", value: "middle" }] },
      { kind: "attachment", filename: "b.png", alt: "photo" },
      { kind: "paragraph", spans: [{ kind: "text", value: "after" }] },
    ]);
  });

  it("an inline ref that is not alone on its line stays ordinary markdown", () => {
    expect(parseBlocks("see ![photo](../_attachments/note-1/b.png) here")).toEqual([
      { kind: "paragraph", spans: [{ kind: "text", value: "see ![photo](../_attachments/note-1/b.png) here" }] },
    ]);
  });

  it("a ref pointing outside _attachments/ is not an attachment block", () => {
    expect(parseBlocks("![elsewhere](../other/place.png)")).toEqual([
      { kind: "paragraph", spans: [{ kind: "text", value: "![elsewhere](../other/place.png)" }] },
    ]);
  });
});

describe("blockKey", () => {
  it("is stable for a block when unrelated blocks are inserted above it", () => {
    const target = parseBlocks("- [ ] todo")[0];
    const before = blockKey(target);
    const shifted = parseBlocks("new paragraph\n\nanother one\n\n- [ ] todo");
    const after = blockKey(shifted[shifted.length - 1]);
    expect(after).toBe(before);
  });

  it("differs across block kinds and content", () => {
    const [heading, bullet] = parseBlocks("# Title\n- Title");
    expect(blockKey(heading)).not.toBe(blockKey(bullet));
  });

  it("is stable for an attachment block regardless of surrounding text", () => {
    const a = parseBlocks("[attachment: voice.wav]")[0];
    const b = parseBlocks("intro\n\n[attachment: voice.wav]")[0 + 1];
    expect(blockKey(a)).toBe(blockKey(b));
  });
});

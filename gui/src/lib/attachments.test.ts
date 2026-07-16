import { describe, it, expect } from "vitest";
import { parseAttachments, kindOf } from "./attachments";

describe("kindOf", () => {
  it("classifies images", () => { expect(kindOf("photo.JPG")).toBe("image"); });
  it("classifies audio", () => { expect(kindOf("memo.m4a")).toBe("audio"); });
  it("falls back to file", () => { expect(kindOf("notes.pdf")).toBe("file"); });
  it("no extension -> file", () => { expect(kindOf("README")).toBe("file"); });
});

describe("parseAttachments", () => {
  it("extracts one link", () => {
    const body = "Some prose.\n\n[attachment: memo.m4a]\n";
    expect(parseAttachments(body)).toEqual([{ filename: "memo.m4a", kind: "audio" }]);
  });

  it("extracts multiple links in order", () => {
    const body = "[attachment: a.jpg]\ntext\n[attachment: b.pdf]\n";
    expect(parseAttachments(body)).toEqual([
      { filename: "a.jpg", kind: "image" },
      { filename: "b.pdf", kind: "file" },
    ]);
  });

  it("dedupes repeated references", () => {
    const body = "[attachment: a.jpg] mentioned again: [attachment: a.jpg]";
    expect(parseAttachments(body)).toEqual([{ filename: "a.jpg", kind: "image" }]);
  });

  it("no links -> empty", () => {
    expect(parseAttachments("just prose, nothing here")).toEqual([]);
  });
});

import { describe, it, expect } from "vitest";
import { parseAttachments, kindOf, attachErrorMessage, NO_ATTACH_HINT } from "./attachments";

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

  it("extracts an inline-ref link", () => {
    const body = "Some prose.\n\n![voice memo](../_attachments/note-1/memo.m4a)\n";
    expect(parseAttachments(body)).toEqual([
      { filename: "memo.m4a", kind: "audio", alt: "voice memo" },
    ]);
  });

  it("extracts both forms in one body, in order", () => {
    const body = "[attachment: a.jpg]\ntext\n![photo](../_attachments/note-1/b.png)\n";
    expect(parseAttachments(body)).toEqual([
      { filename: "a.jpg", kind: "image" },
      { filename: "b.png", kind: "image", alt: "photo" },
    ]);
  });

  it("dedupes by filename across forms", () => {
    const body = "[attachment: a.jpg] and also ![photo](../_attachments/note-1/a.jpg)";
    expect(parseAttachments(body)).toEqual([{ filename: "a.jpg", kind: "image" }]);
  });

  it("handles a filename with a space", () => {
    const body = "![scan](../_attachments/note-1/my file.pdf)";
    expect(parseAttachments(body)).toEqual([
      { filename: "my file.pdf", kind: "file", alt: "scan" },
    ]);
  });

  it("a ref pointing outside _attachments/ is not an attachment", () => {
    const body = "![elsewhere](../other/place.png)";
    expect(parseAttachments(body)).toEqual([]);
  });
});

describe("attachErrorMessage", () => {
  it("translates the no-id developer copy to calm user-facing text", () => {
    expect(attachErrorMessage("Note has no id -- cannot attach a file")).toBe(NO_ATTACH_HINT);
  });

  it("passes every other message through unchanged", () => {
    expect(attachErrorMessage("Failed to attach file")).toBe("Failed to attach file");
    expect(attachErrorMessage("")).toBe("");
  });
});

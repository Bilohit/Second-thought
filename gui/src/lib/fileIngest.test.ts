import { describe, expect, it } from "vitest";
import { fileKind } from "./fileIngest";

describe("fileKind", () => {
  it("maps image extensions", () => {
    expect(fileKind("photo.PNG")).toBe("image");
    expect(fileKind("x.jpg")).toBe("image");
    expect(fileKind("a.jpeg")).toBe("image");
    expect(fileKind("b.gif")).toBe("image");
    expect(fileKind("c.webp")).toBe("image");
  });

  it("maps audio extensions", () => {
    expect(fileKind("song.MP3")).toBe("audio");
    expect(fileKind("a.wav")).toBe("audio");
    expect(fileKind("b.m4a")).toBe("audio");
    expect(fileKind("c.ogg")).toBe("audio");
    expect(fileKind("d.flac")).toBe("audio");
  });

  it("maps text extensions", () => {
    expect(fileKind("note.MD")).toBe("text");
    expect(fileKind("a.txt")).toBe("text");
  });

  it("rejects unknown extensions", () => {
    expect(fileKind("archive.zip")).toBeNull();
    expect(fileKind("noext")).toBeNull();
  });
});

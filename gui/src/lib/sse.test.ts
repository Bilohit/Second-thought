import { describe, it, expect } from "vitest";
import { parseSseFrame } from "./sse";

describe("parseSseFrame", () => {
  it("parses an event + data frame", () => {
    expect(parseSseFrame("event: step\ndata: hello")).toEqual({ ev: "step", data: "hello" });
  });

  it("defaults ev to 'message' when only data is present", () => {
    expect(parseSseFrame("data: payload")).toEqual({ ev: "message", data: "payload" });
  });

  it("returns null for a frame with no data line (comment/keep-alive)", () => {
    expect(parseSseFrame(": keep-alive")).toBeNull();
    expect(parseSseFrame("event: ping")).toBeNull();
    expect(parseSseFrame("")).toBeNull();
  });

  it("returns null when data is empty after trim", () => {
    expect(parseSseFrame("data: ")).toBeNull();
  });

  it("trims surrounding whitespace on ev and data", () => {
    expect(parseSseFrame("event: done \ndata: /vault/x.md ")).toEqual({
      ev: "done",
      data: "/vault/x.md",
    });
  });

  it("takes the last event/data line when a frame repeats them", () => {
    expect(parseSseFrame("data: first\ndata: second")).toEqual({ ev: "message", data: "second" });
  });

  it("ignores lines missing the required 'field: ' space prefix", () => {
    // 'data:x' (no space) is not the SSE field form this parser recognizes
    expect(parseSseFrame("data:no-space")).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import { parseStrictPrefix } from "./lookChatCommands";

describe("parseStrictPrefix", () => {
  it("passes through normal questions", () => {
    expect(parseStrictPrefix("what is rust")).toEqual({ question: "what is rust", strict: false });
  });

  it("strips /strict prefix", () => {
    expect(parseStrictPrefix("/strict what is rust")).toEqual({ question: "what is rust", strict: true });
    expect(parseStrictPrefix("/STRICT notes on async")).toEqual({ question: "notes on async", strict: true });
  });

  it("marks strict when prefix is alone", () => {
    expect(parseStrictPrefix("/strict")).toEqual({ question: "", strict: true });
  });
});

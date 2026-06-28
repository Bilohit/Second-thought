import { describe, expect, it } from "vitest";
import { parseLookChatInput } from "./lookChatCommands";

describe("parseLookChatInput", () => {
  it("defaults to vault mode", () => {
    expect(parseLookChatInput("what is rust")).toEqual({ question: "what is rust", mode: "vault" });
    expect(parseLookChatInput("dinosaur")).toEqual({ question: "dinosaur", mode: "vault" });
  });

  it("strips /talk prefix for general knowledge", () => {
    expect(parseLookChatInput("/talk what is rust")).toEqual({ question: "what is rust", mode: "talk" });
    expect(parseLookChatInput("/TALK notes on async")).toEqual({ question: "notes on async", mode: "talk" });
  });

  it("allows empty question after /talk", () => {
    expect(parseLookChatInput("/talk")).toEqual({ question: "", mode: "talk" });
  });
});

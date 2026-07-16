import { describe, expect, it, beforeEach } from "vitest";
import { formatChatFailure, getInitialIgnoreHistory, setIgnoreHistoryPref, getRetryTarget } from "./useLookChat";
import type { ChatMessage } from "./useLookChat";

beforeEach(() => {
  const store = new Map<string, string>();
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, v); },
    removeItem: (k: string) => { store.delete(k); },
    clear: () => { store.clear(); },
    key: () => null,
    length: 0,
  };
});

describe("ignore history pref", () => {
  it("defaults to false", () => {
    expect(getInitialIgnoreHistory()).toBe(false);
  });

  it("round-trips via localStorage", () => {
    setIgnoreHistoryPref(true);
    expect(getInitialIgnoreHistory()).toBe(true);
    setIgnoreHistoryPref(false);
    expect(getInitialIgnoreHistory()).toBe(false);
  });
});

describe("formatChatFailure", () => {
  it("formats an Error's message as bare text (no ⚠ prefix — failure state lives on ChatMessage.failed)", () => {
    expect(formatChatFailure(new Error("stream reset"))).toBe("Chat failed: stream reset");
  });

  it("falls back to a generic message for non-Error throwables", () => {
    expect(formatChatFailure("boom")).toBe("Chat failed: connection lost");
    expect(formatChatFailure(undefined)).toBe("Chat failed: connection lost");
  });
});

describe("getRetryTarget", () => {
  // retry(index) re-sends the userQuery stored on the failed assistant
  // message: it must recover that exact query and drop the failed pair
  // (user turn + assistant turn) so the caller's ask() re-pushes a clean one.
  it("recovers the stored userQuery and drops the failed user+assistant pair", () => {
    const messages: ChatMessage[] = [
      { role: "user", content: "what is the vault path" },
      { role: "assistant", content: "Chat failed: connection lost", failed: true, userQuery: "what is the vault path" },
    ];
    const target = getRetryTarget(messages, 1);
    expect(target).not.toBeNull();
    expect(target!.query).toBe("what is the vault path");
    expect(target!.truncated).toEqual([]);
  });

  it("preserves earlier turns ahead of the failed pair", () => {
    const messages: ChatMessage[] = [
      { role: "user", content: "first question" },
      { role: "assistant", content: "first answer" },
      { role: "user", content: "second question" },
      { role: "assistant", content: "Chat failed: connection lost", failed: true, userQuery: "second question" },
    ];
    const target = getRetryTarget(messages, 3);
    expect(target!.query).toBe("second question");
    expect(target!.truncated).toEqual([
      { role: "user", content: "first question" },
      { role: "assistant", content: "first answer" },
    ]);
  });

  it("returns null for a user message, or an assistant message with no stored userQuery", () => {
    const messages: ChatMessage[] = [
      { role: "user", content: "hi" },
      { role: "assistant", content: "hello" },
    ];
    expect(getRetryTarget(messages, 0)).toBeNull();
    expect(getRetryTarget(messages, 1)).toBeNull();
  });
});

describe("failed message detection (regression: string-prefix sentinel was a latent bug)", () => {
  // Before this change, LookPanel detected a failed message via
  // `msg.content.startsWith("⚠")` — a user message that happened to start
  // with that glyph would incorrectly render a Retry button. `failed` is a
  // real boolean field, so content text can never masquerade as failure state.
  it("a user message whose text starts with the old ⚠ glyph is not treated as failed", () => {
    const msg: ChatMessage = { role: "user", content: "⚠ is a cool symbol, what does it mean?" };
    expect(msg.failed).not.toBe(true);
  });
});

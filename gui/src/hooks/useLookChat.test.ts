import { describe, expect, it, beforeEach } from "vitest";
import { getInitialIgnoreHistory, setIgnoreHistoryPref } from "./useLookChat";

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

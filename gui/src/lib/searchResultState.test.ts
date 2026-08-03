import { it, expect } from "vitest";
import { classifySearchResults } from "./searchResultState";
import type { SearchResult } from "./api";

function row(overrides: Partial<SearchResult> = {}): SearchResult {
  return { project: null, path: "vault/note.md", filename: "note.md", ...overrides };
}

it("classifies zero results as empty", () => {
  expect(classifySearchResults([])).toEqual({ kind: "empty" });
});

it("classifies a single rescued row as rescued, carrying the row", () => {
  const rescuedRow = row({ tier: "semantic", score: 0.41, rescued: true });
  expect(classifySearchResults([rescuedRow])).toEqual({ kind: "rescued", result: rescuedRow });
});

it("classifies ordinary keyword/semantic hits as results", () => {
  const results = [row({ tier: "exact", score: 1 }), row({ tier: "semantic", score: 0.9 })];
  expect(classifySearchResults(results)).toEqual({ kind: "results", results });
});

it("never treats an ordinary row missing `rescued` as rescued", () => {
  // Contract: absent means "not rescued" -- undefined, not false.
  const ordinary = row({ tier: "semantic", score: 0.9 });
  expect(ordinary.rescued).toBeUndefined();
  expect(classifySearchResults([ordinary])).toEqual({ kind: "results", results: [ordinary] });
});

it("picks out the rescued row even if it weren't first (defensive; server sends it alone)", () => {
  const other = row({ tier: "substring", path: "a.md" });
  const rescuedRow = row({ tier: "semantic", score: 0.3, rescued: true, path: "b.md" });
  expect(classifySearchResults([other, rescuedRow])).toEqual({ kind: "rescued", result: rescuedRow });
});

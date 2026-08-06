import { describe, it, expect } from "vitest";
import { sectionSearch, isSearchActive, NOTE_HIT_CAP, type SearchableProject } from "./browseSearch";
import type { FlatTag } from "./projectsView";

const projects: SearchableProject[] = [
  { name: "research", count: 12 },
  { name: "focus-ritual", count: 4 },
  { name: "garden", count: 1 },
];

const tags: FlatTag[] = [
  { tag: "research-notes", count: 8 },
  { tag: "sync", count: 3 },
];

describe("isSearchActive", () => {
  it("is false for an empty or whitespace-only query", () => {
    expect(isSearchActive("")).toBe(false);
    expect(isSearchActive("   ")).toBe(false);
  });
  it("is true once a query has real content", () => {
    expect(isSearchActive("sync")).toBe(true);
  });
});

describe("sectionSearch", () => {
  it("returns empty sections for a blank query", () => {
    const r = sectionSearch("", { noteResults: [{ id: 1 }], projects, tags });
    expect(r.noteHits).toEqual([]);
    expect(r.projectHits).toEqual([]);
    expect(r.tagHits).toEqual([]);
  });

  it("sections a query that matches all three kinds", () => {
    const noteResults = [{ id: 1 }, { id: 2 }];
    const r = sectionSearch("research", { noteResults, projects, tags });
    expect(r.noteHits).toEqual(noteResults);
    expect(r.projectHits).toEqual([{ name: "research", count: 12 }]);
    expect(r.tagHits).toEqual([{ tag: "research-notes", count: 8 }]);
  });

  it("returns empty sections for a query matching nothing", () => {
    const r = sectionSearch("zzz-nonexistent", { noteResults: [], projects, tags });
    expect(r.noteHits).toEqual([]);
    expect(r.projectHits).toEqual([]);
    expect(r.tagHits).toEqual([]);
  });

  it("matches case-insensitively", () => {
    const r = sectionSearch("RESEARCH", { noteResults: [], projects, tags });
    expect(r.projectHits.map((p) => p.name)).toEqual(["research"]);
    expect(r.tagHits.map((t) => t.tag)).toEqual(["research-notes"]);
  });

  it("caps note hits at NOTE_HIT_CAP", () => {
    const noteResults = Array.from({ length: 10 }, (_, i) => ({ id: i }));
    const r = sectionSearch("x", { noteResults, projects: [], tags: [] });
    expect(r.noteHits.length).toBe(NOTE_HIT_CAP);
    expect(r.noteHits).toEqual(noteResults.slice(0, NOTE_HIT_CAP));
  });
});

import { describe, it, expect } from "vitest";
import {
  sortNotes,
  displayProject,
  needsPager,
  pageOf,
  nextSortMode,
  SORT_MODE_CYCLE,
  SORT_MODE_META_VERB,
  type SortableNote,
} from "./projectsView";

function note(timestamp: string | null | undefined, modified?: number | null): SortableNote {
  return { timestamp, modified };
}

describe("sortNotes", () => {
  it("newest orders by timestamp descending", () => {
    const rows = [note("2026-01-01T00:00:00"), note("2026-03-01T00:00:00"), note("2026-02-01T00:00:00")];
    expect(sortNotes(rows, "newest").map((r) => r.timestamp)).toEqual([
      "2026-03-01T00:00:00",
      "2026-02-01T00:00:00",
      "2026-01-01T00:00:00",
    ]);
  });

  it("oldest orders by timestamp ascending", () => {
    const rows = [note("2026-01-01T00:00:00"), note("2026-03-01T00:00:00"), note("2026-02-01T00:00:00")];
    expect(sortNotes(rows, "oldest").map((r) => r.timestamp)).toEqual([
      "2026-01-01T00:00:00",
      "2026-02-01T00:00:00",
      "2026-03-01T00:00:00",
    ]);
  });

  it("edited orders by modified descending", () => {
    const rows = [note(null, 100), note(null, 300), note(null, 200)];
    expect(sortNotes(rows, "edited").map((r) => r.modified)).toEqual([300, 200, 100]);
  });

  it("stable tiebreak: equal timestamps keep original order across two consecutive sorts", () => {
    const rows = [
      { ...note("2026-01-01T00:00:00"), id: 1 },
      { ...note("2026-01-01T00:00:00"), id: 2 },
      { ...note("2026-01-01T00:00:00"), id: 3 },
    ];
    const first = sortNotes(rows, "newest").map((r) => r.id);
    const second = sortNotes(first.map((id) => rows.find((r) => r.id === id)!), "newest").map((r) => r.id);
    expect(first).toEqual([1, 2, 3]);
    expect(second).toEqual([1, 2, 3]);
  });

  it("null/missing timestamp sorts to the end in newest mode", () => {
    const rows = [note(null), note("2026-01-01T00:00:00"), note(undefined)];
    const result = sortNotes(rows, "newest");
    expect(result[0].timestamp).toBe("2026-01-01T00:00:00");
    expect(result[1].timestamp == null).toBe(true);
    expect(result[2].timestamp == null).toBe(true);
  });

  it("null/missing timestamp sorts to the end in oldest mode", () => {
    const rows = [note(null), note("2026-01-01T00:00:00"), note(undefined)];
    const result = sortNotes(rows, "oldest");
    expect(result[0].timestamp).toBe("2026-01-01T00:00:00");
    expect(result[1].timestamp == null).toBe(true);
    expect(result[2].timestamp == null).toBe(true);
  });

  it("unparseable timestamp sorts to the end like a null one", () => {
    const rows = [note("not-a-date"), note("2026-01-01T00:00:00")];
    const result = sortNotes(rows, "newest");
    expect(result[0].timestamp).toBe("2026-01-01T00:00:00");
    expect(result[1].timestamp).toBe("not-a-date");
  });

  it("null/missing modified sorts to the end in edited mode", () => {
    const rows = [note(null, null), note(null, 100), note(null, undefined)];
    const result = sortNotes(rows, "edited");
    expect(result[0].modified).toBe(100);
    expect(result[1].modified == null).toBe(true);
    expect(result[2].modified == null).toBe(true);
  });

  it("does not mutate the input array", () => {
    const rows = [note("2026-01-01T00:00:00"), note("2026-03-01T00:00:00")];
    const snapshot = [...rows];
    sortNotes(rows, "newest");
    expect(rows).toEqual(snapshot);
    expect(rows[0]).toBe(snapshot[0]);
    expect(rows[1]).toBe(snapshot[1]);
  });

  it("returns a new array reference", () => {
    const rows = [note("2026-01-01T00:00:00")];
    expect(sortNotes(rows, "newest")).not.toBe(rows);
  });
});

describe("sort mode cycle / labels / meta verb", () => {
  it("cycles newest -> oldest -> edited -> newest", () => {
    expect(nextSortMode("newest")).toBe("oldest");
    expect(nextSortMode("oldest")).toBe("edited");
    expect(nextSortMode("edited")).toBe("newest");
  });

  it("SORT_MODE_CYCLE matches the documented order", () => {
    expect(SORT_MODE_CYCLE).toEqual(["newest", "oldest", "edited"]);
  });

  it("meta verb matches the field actually sorted on: added for timestamp modes", () => {
    expect(SORT_MODE_META_VERB.newest).toBe("added");
    expect(SORT_MODE_META_VERB.oldest).toBe("added");
  });

  it("meta verb matches the field actually sorted on: edited for the modified mode", () => {
    expect(SORT_MODE_META_VERB.edited).toBe("edited");
  });
});

describe("displayProject", () => {
  it("maps the _loose sentinel to loose", () => {
    expect(displayProject("_loose")).toBe("loose");
  });

  it("never lets _loose survive to a caller", () => {
    expect(displayProject("_loose")).not.toBe("_loose");
  });

  it("passes through a normal project name unchanged", () => {
    expect(displayProject("my-project")).toBe("my-project");
  });

  it("maps null to loose", () => {
    expect(displayProject(null)).toBe("loose");
  });

  it("maps undefined to loose", () => {
    expect(displayProject(undefined)).toBe("loose");
  });

  it("maps empty string to loose", () => {
    expect(displayProject("")).toBe("loose");
  });
});

describe("needsPager", () => {
  it("false at 199", () => expect(needsPager(199)).toBe(false));
  // Exactly one full page is NOT pageable: spec 5.5.1 bans a "Page 1 of 1",
  // and a 200-row fetch already holds every row.
  it("false at 200 — one full page is still one page", () => expect(needsPager(200)).toBe(false));
  it("true at 201", () => expect(needsPager(201)).toBe(true));

  it("never disagrees with pageOf's page count", () => {
    for (const total of [0, 1, 199, 200, 201, 400, 401]) {
      expect(needsPager(total)).toBe(pageOf(total, 1).pageCount > 1);
    }
  });

  it("respects a custom size", () => {
    expect(needsPager(49, 50)).toBe(false);
    expect(needsPager(50, 50)).toBe(false);
    expect(needsPager(51, 50)).toBe(true);
  });
});

describe("pageOf", () => {
  it("199 items, size 200: one page covering everything", () => {
    const info = pageOf(199, 1, 200);
    expect(info.pageCount).toBe(1);
    expect(info.start).toBe(0);
    expect(info.end).toBe(199);
  });

  it("200 items, size 200: still one page", () => {
    const info = pageOf(200, 1, 200);
    expect(info.pageCount).toBe(1);
    expect(info.start).toBe(0);
    expect(info.end).toBe(200);
  });

  it("201 items, size 200: two pages, page 1 holds the clamp, page 2 holds the remainder", () => {
    const p1 = pageOf(201, 1, 200);
    expect(p1.pageCount).toBe(2);
    expect(p1.start).toBe(0);
    expect(p1.end).toBe(200);

    const p2 = pageOf(201, 2, 200);
    expect(p2.start).toBe(200);
    expect(p2.end).toBe(201);
  });

  it("page 0 clamps up to page 1", () => {
    const info = pageOf(500, 0, 200);
    expect(info.page).toBe(1);
    expect(info.start).toBe(0);
    expect(info.end).toBe(200);
  });

  it("page 1 of a small set", () => {
    const info = pageOf(50, 1, 200);
    expect(info.pageCount).toBe(1);
    expect(info.page).toBe(1);
    expect(info.start).toBe(0);
    expect(info.end).toBe(50);
  });

  it("last page returns the correct partial slice", () => {
    const info = pageOf(450, 3, 200);
    expect(info.pageCount).toBe(3);
    expect(info.start).toBe(400);
    expect(info.end).toBe(450);
  });

  it("last+1 page clamps down to the last page, never out of range", () => {
    const info = pageOf(450, 4, 200);
    expect(info.pageCount).toBe(3);
    expect(info.page).toBe(3);
    expect(info.start).toBe(400);
    expect(info.end).toBe(450);
  });

  it("total 0 never produces negative or NaN bounds", () => {
    const info = pageOf(0, 1, 200);
    expect(info.pageCount).toBe(1);
    expect(info.start).toBe(0);
    expect(info.end).toBe(0);
  });
});

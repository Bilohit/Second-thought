import { describe, it, expect } from "vitest";
import {
  sortNotes,
  displayProject,
  projectTagString,
  needsPager,
  pageOf,
  nextSortMode,
  SORT_MODE_CYCLE,
  SORT_MODE_META_VERB,
  isProvisionalRow,
  excludeProvisional,
  PROVISIONAL_PATH_PREFIX,
  formatAgo,
  metaEpochMs,
  flipStaggerDelayMs,
  isMachineTag,
  filterMachineTags,
  flattenTagTree,
  tagDisplayLabel,
  isValidProjectName,
  describeTidyMove,
  type SortableNote,
} from "./projectsView";
import type { TagNode } from "./api";

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

describe("projectTagString — the copy-the-tag affordance's pure string builder", () => {
  it("builds the #project@<name> tag for a normal name", () => {
    expect(projectTagString("kitchen-remodel")).toBe("#project@kitchen-remodel");
  });

  it("returns null for the _loose sentinel — a loose note has no tag to copy", () => {
    expect(projectTagString("_loose")).toBeNull();
  });

  it("returns null for null", () => {
    expect(projectTagString(null)).toBeNull();
  });

  it("returns null for undefined", () => {
    expect(projectTagString(undefined)).toBeNull();
  });

  it("returns null for an empty string", () => {
    expect(projectTagString("")).toBeNull();
  });
});

describe("isValidProjectName — mirrors omni_capture/projects.py's _VALID_NAME", () => {
  it("accepts a plain lowercase name", () => expect(isValidProjectName("research")).toBe(true));
  it("accepts digits, hyphens and underscores after the first character", () => {
    expect(isValidProjectName("trip-osaka-2026")).toBe(true);
    expect(isValidProjectName("kitchen_remodel")).toBe(true);
  });
  it("accepts a single alphanumeric character", () => {
    expect(isValidProjectName("a")).toBe(true);
    expect(isValidProjectName("9")).toBe(true);
  });
  it("rejects the empty string", () => expect(isValidProjectName("")).toBe(false));
  it("rejects a name starting with - or _ — this is what keeps every reserved _-prefixed hub folder unreachable", () => {
    expect(isValidProjectName("_loose")).toBe(false);
    expect(isValidProjectName("_trash")).toBe(false);
    expect(isValidProjectName("-leading-hyphen")).toBe(false);
  });
  it("rejects embedded whitespace", () => expect(isValidProjectName("trip osaka")).toBe(false));
  it("rejects a name carrying a slash (would escape the vault directory)", () => {
    expect(isValidProjectName("a/b")).toBe(false);
  });
  it("rejects a name carrying an @ (would collide with the #project@name tag grammar)", () => {
    expect(isValidProjectName("a@b")).toBe(false);
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

describe("isProvisionalRow / excludeProvisional (LAN overlay guard, index_writer.py:686-700)", () => {
  it("flags a row keyed by the synthetic provisional path", () => {
    expect(isProvisionalRow({ path: `${PROVISIONAL_PATH_PREFIX}abc123` })).toBe(true);
  });

  it("does not flag a real vault path", () => {
    expect(isProvisionalRow({ path: "research/Q3 lit review.md" })).toBe(false);
  });

  it("does not flag a real path that merely contains the prefix mid-string", () => {
    // Guards against a substring match instead of a prefix match.
    expect(isProvisionalRow({ path: `notes/${PROVISIONAL_PATH_PREFIX}not-actually.md` })).toBe(false);
  });

  it("excludeProvisional drops a provisional row and keeps a real one, feeding both in", () => {
    const rows = [
      { path: `${PROVISIONAL_PATH_PREFIX}op-1`, title: "staged" },
      { path: "research/real-note.md", title: "real" },
    ];
    const kept = excludeProvisional(rows);
    expect(kept.length).toBe(1);
    expect(kept[0].title).toBe("real");
  });

  it("excludeProvisional is a no-op over an all-real list", () => {
    const rows = [{ path: "a.md" }, { path: "b.md" }];
    expect(excludeProvisional(rows)).toEqual(rows);
  });

  it("excludeProvisional does not mutate the input array", () => {
    const rows = [{ path: `${PROVISIONAL_PATH_PREFIX}op-1` }, { path: "a.md" }];
    const snapshot = [...rows];
    excludeProvisional(rows);
    expect(rows).toEqual(snapshot);
  });
});

describe("formatAgo", () => {
  const NOW = Date.parse("2026-08-02T12:00:00Z");
  const DAY = 86_400_000;

  it("today", () => expect(formatAgo(NOW, NOW)).toBe("today"));
  it("yesterday", () => expect(formatAgo(NOW - DAY, NOW)).toBe("yesterday"));
  it("2-6 days ago prints Nd ago", () => {
    expect(formatAgo(NOW - 2 * DAY, NOW)).toBe("2d ago");
    expect(formatAgo(NOW - 6 * DAY, NOW)).toBe("6d ago");
  });
  it("7-13 days ago prints 1w ago", () => {
    expect(formatAgo(NOW - 7 * DAY, NOW)).toBe("1w ago");
    expect(formatAgo(NOW - 13 * DAY, NOW)).toBe("1w ago");
  });
  it("14+ days ago prints the floored week count", () => {
    expect(formatAgo(NOW - 14 * DAY, NOW)).toBe("2w ago");
    expect(formatAgo(NOW - 20 * DAY, NOW)).toBe("2w ago");
    expect(formatAgo(NOW - 21 * DAY, NOW)).toBe("3w ago");
  });
  it("a future timestamp (clock skew) clamps to today rather than a negative count", () => {
    expect(formatAgo(NOW + DAY, NOW)).toBe("today");
  });
});

describe("flipStaggerDelayMs (spec §8: 14ms/row, capped at 110ms)", () => {
  it("row 0 has no delay", () => expect(flipStaggerDelayMs(0)).toBe(0));
  it("scales linearly below the cap", () => {
    expect(flipStaggerDelayMs(1)).toBe(14);
    expect(flipStaggerDelayMs(5)).toBe(70);
  });
  it("the last row below the cap: 7 * 14 = 98, still under 110", () => {
    expect(flipStaggerDelayMs(7)).toBe(98);
  });
  it("the row where the cap actually binds: 8 * 14 = 112, clamped to 110", () => {
    expect(flipStaggerDelayMs(8)).toBe(110);
  });
  it("stays capped at 110 for every row past the binding point", () => {
    expect(flipStaggerDelayMs(9)).toBe(110);
    expect(flipStaggerDelayMs(50)).toBe(110);
  });
  it("a negative index (defensive) never returns a negative delay", () => {
    expect(flipStaggerDelayMs(-3)).toBe(0);
  });
});

describe("isMachineTag / filterMachineTags — moved here verbatim from FullWindow/TagsView.tsx (SP3 Task 7, trap 1)", () => {
  it("flags the sys/ namespace and known bare legacy machine tags", () => {
    expect(isMachineTag("sys/")).toBe(true);
    expect(isMachineTag("sys/llm-failed")).toBe(true);
    expect(isMachineTag("llm-failed")).toBe(true);
    expect(isMachineTag("winerror_2")).toBe(true);
  });

  it("never flags ordinary user content tags", () => {
    expect(isMachineTag("reading")).toBe(false);
    expect(isMachineTag("systems-design")).toBe(false);
  });

  it("filterMachineTags drops the whole sys/ node, including children, and keeps everything else", () => {
    const tags: TagNode[] = [
      { tag: "sys/", count: 2, recent: [], children: [{ tag: "sys/llm-failed", count: 2, recent: [], children: [] }] },
      { tag: "reading", count: 3, recent: [], children: [] },
    ];
    expect(filterMachineTags(tags).map((n) => n.tag)).toEqual(["reading"]);
  });
});

describe("flattenTagTree (spec §5: getTagTree() returns a tree, the tag rail wants a flat list)", () => {
  it("emits a bare top-level tag as a single row", () => {
    const tags: TagNode[] = [{ tag: "reading", count: 4, recent: [], children: [] }];
    expect(flattenTagTree(tags)).toEqual([{ tag: "reading", count: 4 }]);
  });

  it("depth-first: a namespace parent is emitted, immediately followed by its children", () => {
    const tags: TagNode[] = [
      {
        tag: "project/", count: 3, recent: [],
        children: [
          { tag: "project/alpha", count: 2, recent: [], children: [] },
          { tag: "project/beta", count: 1, recent: [], children: [] },
        ],
      },
      { tag: "reading", count: 4, recent: [], children: [] },
    ];
    expect(flattenTagTree(tags)).toEqual([
      { tag: "project/", count: 3 },
      { tag: "project/alpha", count: 2 },
      { tag: "project/beta", count: 1 },
      { tag: "reading", count: 4 },
    ]);
  });

  it("keeps a namespace parent's trailing slash — resolve_paths (tag_index.py) reads it as a prefix marker", () => {
    const tags: TagNode[] = [{ tag: "sys/", count: 1, recent: [], children: [] }];
    expect(flattenTagTree(tags)[0].tag).toBe("sys/");
  });

  it("an empty tree flattens to an empty list", () => {
    expect(flattenTagTree([])).toEqual([]);
  });
});

describe("tagDisplayLabel — trailing slash stripped for display, never for the selection/fetch value", () => {
  it("strips exactly one trailing slash", () => {
    expect(tagDisplayLabel("project/")).toBe("project");
  });

  it("a bare tag is unchanged", () => {
    expect(tagDisplayLabel("reading")).toBe("reading");
  });

  it("a slash in the middle (a real leaf tag) is untouched", () => {
    expect(tagDisplayLabel("project/alpha")).toBe("project/alpha");
  });
});

describe("metaEpochMs", () => {
  it("newest/oldest read the ISO timestamp as ms", () => {
    const row: SortableNote = { timestamp: "2026-01-01T00:00:00Z", modified: 999 };
    expect(metaEpochMs(row, "newest")).toBe(Date.parse("2026-01-01T00:00:00Z"));
    expect(metaEpochMs(row, "oldest")).toBe(Date.parse("2026-01-01T00:00:00Z"));
  });

  it("edited reads modified (epoch SECONDS) converted to ms", () => {
    const row: SortableNote = { timestamp: "2026-01-01T00:00:00Z", modified: 1_700_000_000 };
    expect(metaEpochMs(row, "edited")).toBe(1_700_000_000 * 1000);
  });

  it("null when the mode's field is missing", () => {
    expect(metaEpochMs({ timestamp: null, modified: null }, "newest")).toBeNull();
    expect(metaEpochMs({ timestamp: null, modified: null }, "edited")).toBeNull();
  });

  it("null for an unparseable timestamp", () => {
    expect(metaEpochMs({ timestamp: "not-a-date" }, "newest")).toBeNull();
  });
});

describe("describeTidyMove (FR-23 Option A: preview-strip display mapping)", () => {
  it("splits filename from folder on both sides", () => {
    expect(describeTidyMove({ from: "work/foo.md", to: "_loose/foo.md" })).toEqual({
      file: "foo.md",
      from: "work",
      to: "loose",
    });
  });

  it("never leaks the raw _loose sentinel, on either side", () => {
    const d = describeTidyMove({ from: "_loose/a.md", to: "trip-japan/a.md" });
    expect(d.from).not.toBe("_loose");
    expect(d.from).toBe("loose");
    expect(d.to).toBe("trip-japan");
  });

  it("a vault-root file (no folder) maps to loose, not a raw null/empty string", () => {
    expect(describeTidyMove({ from: "a.md", to: "_loose/a.md" }).from).toBe("loose");
  });
});

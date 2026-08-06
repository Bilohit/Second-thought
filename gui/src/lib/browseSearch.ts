/**
 * browseSearch.ts — P3-C1: pure sectioning for BROWSE's search results
 * (mock: SecondThoughtV2.html:1724-1758 `wireSearch`). Three labelled
 * sections in one list — NOTES, PROJECTS, TAGS — matching the mock's
 * `res-h`/`tag-row`/`res-empty` structure 1:1.
 *
 * Notes are matched SERVER-SIDE: `searchCaptures(q)` (lib/api.ts, GET
 * /search) already does the vault's real full-text + semantic ranking, the
 * same engine CHAT/LOOK uses — re-implementing substring matching over note
 * bodies here (as the mock's client-only `NOTES.filter` does, mock line
 * 1732) would be a second, worse search engine. This module's job is only
 * the part that's genuinely client-side: filtering the already-fetched
 * project/tag lists by name, and capping+shaping the whole section triad —
 * so it stays pure and testable without a network call.
 */
import type { FlatTag } from "./projectsView";

/** A project entry narrowed to the two fields this module reads — avoids
 *  forcing an `api.ts` import just for the sectioning logic. */
export interface SearchableProject {
  name: string;
  count: number;
}

export interface SectionedSearch<TNote> {
  noteHits: TNote[];
  projectHits: SearchableProject[];
  tagHits: FlatTag[];
}

/** Mock's own cap on the NOTES section (line 1732: `.slice(0, 6)`) — a
 *  sectioned search result is a quick jump-to list, not a full result page. */
export const NOTE_HIT_CAP = 6;

/** True once there's anything to section on — the caller uses this to
 *  decide "show search results" vs. "show the home page" (mock's
 *  `main.style.display`/`res.style.display` swap, line 1727/1731). */
export function isSearchActive(query: string): boolean {
  return query.trim().length > 0;
}

/** Sections a query across notes (already-fetched server hits, passed
 *  through and capped), projects, and tags (both filtered here,
 *  case-insensitively, by substring — mock line 1733-1734's
 *  `.toLowerCase().includes(q)`). Returns three empty arrays for a blank
 *  query rather than the full home-page content — sectioning is only
 *  meaningful once there's a query to section by. */
export function sectionSearch<TNote>(
  query: string,
  opts: { noteResults: readonly TNote[]; projects: readonly SearchableProject[]; tags: readonly FlatTag[] },
): SectionedSearch<TNote> {
  const q = query.trim().toLowerCase();
  if (!q) return { noteHits: [], projectHits: [], tagHits: [] };
  return {
    noteHits: opts.noteResults.slice(0, NOTE_HIT_CAP),
    projectHits: opts.projects.filter((p) => p.name.toLowerCase().includes(q)),
    tagHits: opts.tags.filter((t) => t.tag.toLowerCase().includes(q)),
  };
}

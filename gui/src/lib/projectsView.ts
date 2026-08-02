/**
 * projectsView.ts — pure sorting/paging/label helpers for the Projects view
 * (Search results grouped by project). No side effects, no fetch.
 *
 * `SortableNote` is a narrow structural subset of `SearchResult` (api.ts) —
 * defined locally rather than imported so this module never forces an
 * `api.ts` edit just to add a sort mode. Any row shaped like this works,
 * including rows carrying the server's `modified` (filesystem mtime, epoch
 * seconds) field once it lands there.
 */

/** The two fields a row needs to be sortable: `timestamp` is the note's
 *  ADDED time (ISO string); `modified` is filesystem mtime, epoch seconds. */
export interface SortableNote {
  timestamp?: string | null;
  modified?: number | null;
}

export type SortMode = "newest" | "oldest" | "edited";

/** Cycle order for the sort-mode toggle: newest -> oldest -> edited -> newest. */
export const SORT_MODE_CYCLE: readonly SortMode[] = ["newest", "oldest", "edited"];

/** Human label per mode, for the sort control. */
export const SORT_MODE_LABEL: Readonly<Record<SortMode, string>> = {
  newest: "Newest",
  oldest: "Oldest",
  edited: "Recently edited",
};

/** The meta verb the row's right-hand column must print for a given mode.
 *  "added" for the two timestamp modes, "edited" for the modified mode —
 *  a row's meta column may never claim a verb the sort didn't actually use. */
export const SORT_MODE_META_VERB: Readonly<Record<SortMode, "added" | "edited">> = {
  newest: "added",
  oldest: "added",
  edited: "edited",
};

/** Returns the next mode in the cycle. */
export function nextSortMode(mode: SortMode): SortMode {
  const i = SORT_MODE_CYCLE.indexOf(mode);
  return SORT_MODE_CYCLE[(i + 1) % SORT_MODE_CYCLE.length];
}

function fieldFor(mode: SortMode, row: SortableNote): number | null {
  if (mode === "edited") {
    const m = row.modified;
    return typeof m === "number" && isFinite(m) ? m : null;
  }
  const t = row.timestamp;
  if (!t) return null;
  const ms = new Date(t).getTime();
  return isNaN(ms) ? null : ms;
}

/** Sorts `rows` by `mode` without mutating the input. Rows with a null,
 *  missing, or unparseable sort field always sort to the END (in original
 *  relative order among themselves), regardless of mode — never compared
 *  as NaN into a random position. Equal sort values keep their original
 *  relative order (stable tiebreak on index), so re-sorting an unchanged
 *  list never reshuffles ties. */
export function sortNotes<T extends SortableNote>(rows: readonly T[], mode: SortMode): T[] {
  const indexed = rows.map((row, index) => ({ row, index, value: fieldFor(mode, row) }));

  indexed.sort((a, b) => {
    if (a.value === null && b.value === null) return a.index - b.index;
    if (a.value === null) return 1;
    if (b.value === null) return -1;
    if (a.value !== b.value) {
      return mode === "oldest" ? a.value - b.value : b.value - a.value;
    }
    return a.index - b.index;
  });

  return indexed.map((entry) => entry.row);
}

/** Index's internal sentinel for "no project" is the literal string
 *  "_loose" — no surface may ever render that token to the user. Maps it
 *  (and a null/empty project, which means the same thing: an unfiled row)
 *  to the user-facing "loose". Everything else passes through unchanged. */
export function displayProject(value: string | null | undefined): string {
  if (!value || value === "_loose") return "loose";
  return value;
}

/** Server-side hard clamp on GET /search: a result set at or above this
 *  size may be truncated, so the UI needs a pager. Below it, everything
 *  fits in one page and no pager is needed. */
const DEFAULT_PAGE_SIZE = 200;

/** True only once `total` EXCEEDS one page — spec §5.5.1's detection rule is
 *  "the pager exists iff the total exceeds one page", and it bans a
 *  "Page 1 of 1". At exactly `size` the single fetch already holds every
 *  row, so a pager there would be chrome over nothing. `size` defaults to
 *  the server's own clamp (200). */
export function needsPager(total: number, size: number = DEFAULT_PAGE_SIZE): boolean {
  return total > size;
}

export interface PageInfo {
  /** Total number of pages (>= 1, even for `total === 0`). */
  pageCount: number;
  /** The page actually served, clamped to [1, pageCount]. */
  page: number;
  /** Slice bounds into a `total`-length array: `arr.slice(start, end)`. */
  start: number;
  end: number;
}

/** Computes page count and slice bounds for `page` of `size`-sized pages
 *  over `total` items. `page` is clamped to the valid [1, pageCount] range
 *  first, so a page below 1 or past the last page never produces
 *  out-of-range bounds — it clamps to the first or last page instead. */
export function pageOf(total: number, page: number, size: number = DEFAULT_PAGE_SIZE): PageInfo {
  const pageCount = Math.max(1, Math.ceil(total / size));
  const clamped = Math.min(Math.max(1, Math.floor(page)), pageCount);
  const start = (clamped - 1) * size;
  const end = Math.min(start + size, total);
  return { pageCount, page: clamped, start, end };
}

/** The server's synthetic path prefix for LAN-provisional overlay rows
 *  (contract §11). `index_writer._provisional_path` (index_writer.py:699-700)
 *  keys them as `__lan_provisional__/<op_id>` instead of a real vault path.
 *  `GET /search` deliberately does NOT exclude provisional=1 rows
 *  (index_writer.py:686-697's docstring: "Plain index_writer.search()
 *  intentionally does NOT exclude provisional -- that is precisely where the
 *  LAN overlay is meant to surface"), while `GET /stats` DOES exclude them
 *  (same comment: "stats()/reindex_bodies() DO exclude provisional=1").
 *  A project/tag note list built from `/search` without filtering these out
 *  would therefore (a) outnumber the rail tile's stats-derived count (the
 *  "5 of 11" divergence spec §5.6 exists to prevent) and (b) render rows
 *  with no real file behind them, which can never be opened. */
export const PROVISIONAL_PATH_PREFIX = "__lan_provisional__/";

/** True for a row published by the LAN-provisional overlay rather than a
 *  real vault file — see `PROVISIONAL_PATH_PREFIX`'s comment. */
export function isProvisionalRow(row: { path: string }): boolean {
  return row.path.startsWith(PROVISIONAL_PATH_PREFIX);
}

/** Drops every LAN-provisional overlay row. Call this on every `/search`
 *  response used to populate a project or tag note list, before counting or
 *  rendering rows — see `PROVISIONAL_PATH_PREFIX`'s comment for why. */
export function excludeProvisional<T extends { path: string }>(rows: readonly T[]): T[] {
  return rows.filter((row) => !isProvisionalRow(row));
}

/** Formats an elapsed duration from `epochMs` to `now` (default: the real
 *  clock) the way the approved board's mock does: "today" / "yesterday" /
 *  "Nd ago" (2-6 days) / "1w ago" (7-13 days) / "Nw ago" (14+ days, floored).
 *  A negative delta (a future timestamp, e.g. clock skew) clamps to 0 rather
 *  than printing a negative day count. */
export function formatAgo(epochMs: number, now: number = Date.now()): string {
  const days = Math.max(0, Math.floor((now - epochMs) / 86_400_000));
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 14) return "1w ago";
  return `${Math.floor(days / 7)}w ago`;
}

/** FLIP re-order stagger delay for row `index` in the newly-sorted list
 *  (spec §8: "380ms `--ease-travel`, stagger 14ms/row capped at 110ms").
 *  Pure so the cap-binding row (index 8: 8*14=112, clamped to 110) has a
 *  regression test independent of any DOM/geometry work, which happy-dom
 *  cannot perform (no layout engine). */
export function flipStaggerDelayMs(index: number): number {
  return Math.min(Math.max(0, index) * 14, 110);
}

/** The epoch-millisecond value a note row is actually sorted/displayed on
 *  for `mode` — "edited" reads `modified` (filesystem mtime, epoch SECONDS,
 *  converted to ms), the two timestamp modes read `timestamp` (ISO string).
 *  `null` when the row carries no usable value for `mode`, so the row's meta
 *  column can fall back to a plain label instead of "NaN ago". */
export function metaEpochMs(row: SortableNote, mode: SortMode): number | null {
  if (mode === "edited") {
    const m = row.modified;
    return typeof m === "number" && isFinite(m) ? m * 1000 : null;
  }
  const t = row.timestamp;
  if (!t) return null;
  const ms = new Date(t).getTime();
  return isNaN(ms) ? null : ms;
}

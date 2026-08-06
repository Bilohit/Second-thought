/**
 * browsePager.ts — P3-C1: pure paging math for BROWSE's 4x2 project-tile
 * grid (mock: SecondThoughtV2.html:978-985 `#d-proj-pages`/`#d-proj-dots`,
 * `renderProjPages`/`pageBy` at :1669-1705). 8 tiles per page (desktop's
 * `perPage` argument to `renderProjPages`, mock line 1716).
 *
 * The desktop pager gets BOTH dots and clickable arrows (user ruling s145,
 * CLAUDE.md "The pager, ruled by the user") — this module only computes the
 * numbers; BrowseView.tsx renders the dots/arrows off `BrowsePagerInfo`.
 *
 * No side effects, no fetch — mirrors lib/projectsView.ts's `pageOf` shape
 * but chunks a real array (the mock's `chunk()`, line 1620) rather than
 * slicing a total, since the caller needs the actual per-page tile arrays
 * to render.
 */

export const PROJECTS_PER_PAGE = 8;

/** Splits `items` into `perPage`-sized pages, in order. An empty input
 *  produces zero pages (the caller decides how to render "no projects" —
 *  this module only knows about chunking). */
export function chunkProjects<T>(items: readonly T[], perPage: number = PROJECTS_PER_PAGE): T[][] {
  if (perPage <= 0) return items.length === 0 ? [] : [items.slice()];
  const pages: T[][] = [];
  for (let i = 0; i < items.length; i += perPage) pages.push(items.slice(i, i + perPage));
  return pages;
}

export interface BrowsePagerInfo {
  /** Total number of pages, always >= 1 even for zero items (one empty page —
   *  the pager still renders a single (disabled) dot, never zero of them). */
  pageCount: number;
  /** The page actually shown, clamped to [1, pageCount]. */
  page: number;
  /** False on page 1 (or the only page) — drives the prev arrow's `disabled`. */
  canPrev: boolean;
  /** False on the last page (or the only page) — drives the next arrow's `disabled`. */
  canNext: boolean;
}

/** Computes page count + clamped current page + arrow-enable state for
 *  `total` items at `perPage` per page. `page` may be any integer (a stale
 *  value after the project list shrinks, e.g. after a delete) — it always
 *  clamps into range rather than producing an out-of-bounds page. */
export function browsePagerInfo(
  total: number,
  page: number,
  perPage: number = PROJECTS_PER_PAGE,
): BrowsePagerInfo {
  const pageCount = Math.max(1, Math.ceil(total / Math.max(1, perPage)));
  const clamped = Math.min(Math.max(1, Math.floor(page)), pageCount);
  return {
    pageCount,
    page: clamped,
    canPrev: clamped > 1,
    canNext: clamped < pageCount,
  };
}

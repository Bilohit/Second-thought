/**
 * projectsView.ts — pure sorting/paging/label/tag-tree helpers for the
 * Projects view (Search results grouped by project or tag). No side
 * effects, no fetch.
 *
 * `SortableNote` is a narrow structural subset of `SearchResult` (api.ts) —
 * defined locally rather than imported so this module never forces an
 * `api.ts` edit just to add a sort mode. Any row shaped like this works,
 * including rows carrying the server's `modified` (filesystem mtime, epoch
 * seconds) field once it lands there.
 */
import type { TagNode } from "./api";

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

/** Mirrors `omni_capture/projects.py`'s `_VALID_NAME` regex exactly — a
 *  project name is simultaneously a tag suffix, a `.projects.toml` key and a
 *  vault directory name, so it is narrower than the general tag grammar
 *  (contract §1.3's comment on `_VALID_NAME`). The leading-character rule
 *  also makes every reserved `_`-prefixed hub folder (`_loose`, `_trash`,
 *  `_attachments`, `_mobile_inbox`) unreachable as a project name, since none
 *  of them can start with an alphanumeric. This is a client-side pre-check
 *  only — the server (`vault_admin.py`'s create-project route, backed by
 *  this same regex) remains the authority; a name that somehow slips past
 *  this check still gets rejected server-side and surfaces via the normal
 *  `assertOk` error message. */
const VALID_PROJECT_NAME = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;

export function isValidProjectName(name: string): boolean {
  return VALID_PROJECT_NAME.test(name);
}

/** The one wording for a rejected project name, shared by every surface that can produce
 *  one — the rail's inline create field and the folder import's rename rows. It lives
 *  beside the regex it explains so the two can never drift into describing different
 *  rules to the user. */
export const INVALID_NAME_MESSAGE =
  "Letters, numbers, - or _ only, starting with a letter or number.";

/** Index's internal sentinel for "no project" is the literal string
 *  "_loose" — no surface may ever render that token to the user. Maps it
 *  (and a null/empty project, which means the same thing: an unfiled row)
 *  to the user-facing "loose". Everything else passes through unchanged. */
export function displayProject(value: string | null | undefined): string {
  if (!value || value === "_loose") return "loose";
  return value;
}

/** Builds the exact `#project@<name>` tag text a user pastes into a note's
 *  body to file it under `name` (the tag IS the source of truth — see
 *  `displayProject`'s comment above and `omni_capture/projects.py`'s
 *  `_PROJECT_TAG` regex, which this string must stay byte-for-byte
 *  parseable by). Returns `null` for the `_loose` sentinel or an empty/
 *  missing name: a note with no project has no tag to copy, and building
 *  `#project@_loose` would leak an internal sentinel into the clipboard and
 *  claim a "loose" note can be filed by pasting a tag — it can't, loose has
 *  no tag at all. Callers must treat `null` as "render no copy affordance",
 *  never fall back to a placeholder string. */
export function projectTagString(name: string | null | undefined): string | null {
  if (!name || name === "_loose") return null;
  return `#project@${name}`;
}

/** Server-side hard clamp on GET /search: a result set at or above this
 *  size may be truncated, so the UI needs a pager. Below it, everything
 *  fits in one page and no pager is needed. Exported (SP3 Task 9) so the
 *  pager UI shares the exact same constant the fetch's own `{ limit: 200 }`
 *  uses, rather than a second hardcoded 200 that could drift from it. */
export const DEFAULT_PAGE_SIZE = 200;

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

/** The screen-reader sentence a pager's prev/next `aria-label` restates on
 *  every click (spec §7: "the sort button's aria-label restates the current
 *  arrangement after each cycle" — the Task 9 pager applies the identical
 *  rule to its own icon-only steppers, board mock line 445-446). `start`/
 *  `end` are `PageInfo`'s 0-based slice bounds; the sentence prints them
 *  1-based ("notes 1 to 200"), matching the visible range readout below. */
export function pagerPositionSentence(start: number, end: number, total: number): string {
  return `Currently showing notes ${start + 1} to ${end} of ${total}.`;
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

// ── moved verbatim from FullWindow/TagsView.tsx (SP3 Task 7) ───────────────
// TagsView.tsx is deleted in Task 8; this filter has to keep working after
// that, and the new Projects-screen tag rail (ProjectsRail.tsx) needs it
// too, so it lives in the shared lib module both sides already import from
// rather than in the file that is about to disappear. Logic unchanged.

/**
 * ISS-019: machine-written failure markers (scratchpad.py's route_failed_vision
 * /route_failed_llm) are namespaced "sys/..." at the write site so they land
 * in their own "sys/" tree node here -- filter that whole node out rather
 * than showing bookkeeping as if it were the user's tag taxonomy. Also
 * matches bare legacy names (pre-namespacing notes already on disk, or any
 * tag the pipeline never routed through the sys/ prefix) so existing vaults
 * get the same clean view without a migration.
 */
const SYS_TAG_NAMESPACE = "sys";
const LEGACY_MACHINE_TAGS = new Set([
  "llm-failed",
  "vision-failed",
  "transcription_failure",
  "whisper_model_error",
  "winerror_2",
]);

export function isMachineTag(tag: string): boolean {
  const bare = tag.replace(/\/$/, "");
  if (bare === SYS_TAG_NAMESPACE || bare.startsWith(`${SYS_TAG_NAMESPACE}/`)) return true;
  return LEGACY_MACHINE_TAGS.has(bare.toLowerCase());
}

export function filterMachineTags(tags: TagNode[]): TagNode[] {
  return tags
    .filter((node) => !isMachineTag(node.tag))
    .map((node) => ({ ...node, children: node.children.filter((c) => !isMachineTag(c.tag)) }));
}

// ── tag-tree flattening (SP3 Task 7, spec §5) ───────────────────────────────

/** One row of the flat tag rail: the raw tag value (see below for why it
 *  must stay raw) and its note count from GET /tags. */
export interface FlatTag {
  tag: string;
  count: number;
}

/** Flattens the two-level tree `GET /tags` returns (tag_index.py's
 *  `_build_tag_tree`: namespace parents like `"project/"` with leaf children
 *  like `"project/alpha"`; a bare tag with no `/` has no children) into the
 *  single flat list spec §5 wants. Depth-first: each top-level node is
 *  emitted as its own row, immediately followed by its children.
 *
 *  A namespace parent's `tag` field is emitted UNCHANGED, trailing slash and
 *  all — `tag_index.resolve_paths` reads that trailing slash as "match by
 *  prefix, union every child", which is exactly how the parent's own `count`
 *  was built (spec §5.6). Stripping the slash before calling
 *  `notesForTag()`/`GET /search?q=tag:<x>` would turn a namespace click into
 *  an exact-match lookup for a tag that (almost always) has zero notes of
 *  its own, breaking trap 2's rail-vs-pane count agreement. Callers that
 *  render the tag strip a trailing slash for display only, never for the
 *  value used to select/fetch.
 *
 *  The board (gui/mocks/2026-08-01-projects-fullwindow-v3.html) has no
 *  namespaced tags in its TAGS array, so it does not show how a namespace
 *  parent should render — including it in the flat list is a judgment call,
 *  made because spec §5.6 explicitly discusses a namespace parent's unioned
 *  count and its `/search?q=tag:<ns>/` prefix listing as part of the same
 *  agreement rule the rest of this list has to honor. */
export function flattenTagTree(tags: readonly TagNode[]): FlatTag[] {
  const flat: FlatTag[] = [];
  for (const node of tags) {
    flat.push({ tag: node.tag, count: node.count });
    for (const child of node.children) {
      flat.push({ tag: child.tag, count: child.count });
    }
  }
  return flat;
}

/** Strips a namespace parent's trailing slash for DISPLAY ONLY — never use
 *  this on the value passed to `onSelectTag`/`notesForTag`, see
 *  `flattenTagTree`'s comment. */
export function tagDisplayLabel(tag: string): string {
  return tag.replace(/\/$/, "");
}

// ── FR-23 Option A: project-tidy confirm/preview ────────────────────────────

/** One tidy move (GET /vault/tidy/preview -- api.ts's `TidyMove`), reshaped for
 *  display: the bare filename plus its FROM/TO folder, each routed through
 *  `displayProject()` so the internal `_loose` sentinel never reaches the screen
 *  raw (spec lock: no surface may render "_loose"). A vault-root note (no `/` in
 *  its path -- should not occur post-s127, but a hand-placed file is not
 *  impossible) maps to `null`, matching `displayProject`'s own null handling. */
export interface TidyMoveDisplay {
  file: string;
  from: string;
  to: string;
}

function folderOf(relPath: string): string | null {
  const i = relPath.lastIndexOf("/");
  return i === -1 ? null : relPath.slice(0, i);
}

/** Never presents a raw filesystem path as if it were meaningful on its own --
 *  only the folder segment, and only through `displayProject()`. This is the one
 *  place FR-23's preview strip turns a `{from, to}` move into copy; nothing else
 *  in the tidy confirm flow should split a path by hand. */
export function describeTidyMove(move: { from: string; to: string }): TidyMoveDisplay {
  const file = move.to.slice(move.to.lastIndexOf("/") + 1);
  return {
    file,
    from: displayProject(folderOf(move.from)),
    to: displayProject(folderOf(move.to)),
  };
}

/**
 * ProjectsRail.tsx — sub-project 3 Task 4: the projects/tags rail, the left
 * 260px column of the full-window Projects screen (spec §3's A3 split
 * panel). A three-band column: band 1 (the Projects|Tags toggle) and band 3
 * (New project) never scroll or move; only band 2 (tiles, or the tag list)
 * does. New project is always the last thing in the rail (spec §3).
 *
 * Board (visual source of truth): gui/mocks/2026-08-01-projects-fullwindow-v3.html.
 * Spec: docs/superpowers/specs/2026-08-02-projects-s3-fullwindow-design.md §3, §4.1-§4.4.
 *
 * Scope boundaries, binding per the plan's standing rules:
 *  - The toggle is the REAL `ui/SegmentedToggle`, not a lookalike. It only
 *    supports rendering EITHER an option's `icon` OR its `label` (never
 *    both — see its render: `{o.icon ?? o.label}`), so the board's icon+text
 *    look is reproduced by passing a small icon+text fragment AS the `icon`
 *    prop (with `label` still supplying the accessible name/tooltip). This
 *    is the one place this file's visuals diverge from a literal className
 *    port of the board's CSS, in favor of using the unmodified shared
 *    component exactly as its one other real caller (FullWindow.tsx) does.
 *  - The Tags half of the toggle (Task 7) renders the real flat tag list:
 *    role="listbox"/"option", the SAME selected-state visual language as a
 *    project tile (accent wash + 2px accent edge, spec §5.1) — not a second
 *    pattern. Per-row project chips and first-tag-auto-select live in
 *    ProjectsPane.tsx / ProjectsView.tsx respectively (this file only owns
 *    the tag list itself and reporting a click via `onSelectTag`).
 *  - Tile counts are handed in via `projectCounts` (spec §5.6) — this
 *    component does not read `ProjectEntry.file_count` and must not start
 *    (that field is a directory listing, not the index's project column;
 *    see ProjectsView.tsx's file header for why that distinction is load-
 *    bearing). The rail renders the counts it is given, it does not pick
 *    its own source.
 *
 * Task 6 (motion pass, spec §8) added: the Projects|Tags band-2 content
 * swap (`.seg-swap-panel`, direction from `lib/segmentedToggle.ts`'s
 * `slideDirection`). This reuses index.css's existing `--menu-travel-ease` /
 * `--hover-ease-out` tokens — see index.css's "PROJECTS full-window motion
 * pass" comment block for why those are the spec's `--ease-travel` /
 * `--ease-settle` under this repo's own names, not two new tokens on the
 * same curves. The FLIP re-order and sort-icon swap live in ProjectsPane.tsx
 * (they animate note rows and the sort button, not anything in this file).
 */
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";
import { createProject, type ProjectEntry } from "../../lib/api";
import { displayProject, INVALID_NAME_MESSAGE, isValidProjectName, tagDisplayLabel, type FlatTag } from "../../lib/projectsView";
import { slideDirection } from "../../lib/segmentedToggle";
import SegmentedToggle from "../ui/SegmentedToggle";
import { DashboardIcon, ListIcon, PlusIcon, CheckIcon, CloseIcon } from "../PillMenu/icons";

/* INVALID_NAME_MESSAGE moved to lib/projectsView.ts (beside the regex it explains) when the
 * folder import gained rename rows that must show the identical wording. The real authority
 * is still the server (`vault_admin.py`'s create-project route, backed by the identical
 * `_VALID_NAME` regex `isValidProjectName` mirrors); the client check only saves a round trip
 * for the common case (spaces, a leading symbol). A collision ("already exists") is NOT
 * checked client-side — only the server's live registry can know that — so it always surfaces
 * through the catch block's server error message instead. */

/** The rail's own two-position view mode — distinct from any note SortMode.
 *  Exactly two positions on every shell (spec §4.1). */
export type RailMode = "projects" | "tags";

/** Selection sentinel for the loose bucket. Deliberately the SAME literal
 *  the server stores in the index's project column (spec §2.2) so a
 *  selected id can be handed straight to notesForProject(id) with no
 *  translation layer, and `displayProject()` (the one sanctioned sentinel
 *  guard, lib/projectsView.ts) already knows how to turn it into "loose"
 *  for display. */
export const LOOSE_PROJECT_ID = "_loose";

interface ProjectsRailProps {
  mode: RailMode;
  onModeChange: (mode: RailMode) => void;
  /** Registry entries from GET /vault/projects, rendered as-is for identity
   *  (`name`) and `description` — the registry is the authority on what a
   *  project IS. Its `file_count` is NOT read for the tile's number (see
   *  `projectCounts` below): it is a directory listing
   *  (vault_admin._project_file_count), not the index's project column, and
   *  using it would re-introduce the exact directory-vs-tag disagreement
   *  s127 removed from the index (board lines 335/448). */
  projects: ProjectEntry[];
  /** Per-project note counts, keyed by `ProjectEntry.name`, from
   *  getStats().by_project — the SAME index `project` column
   *  GET /search?project=<name> filters on, so a tile's number cannot
   *  disagree with the pane's note-list length (spec §5.6). A project with
   *  no row here (zero captures) renders "0 notes", not "undefined notes". */
  projectCounts: Record<string, number>;
  /** Count of loose notes: the caller's `projectCounts[LOOSE_PROJECT_ID]`
   *  (0 when absent) — kept as its own prop rather than making the rail
   *  re-derive it, since the loose tile is drawn outside the `projects` map. */
  looseCount: number;
  /** A project's `name`, or LOOSE_PROJECT_ID, or null before anything has
   *  loaded / been selected yet. */
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** The flattened tag list (lib/projectsView.ts's `flattenTagTree`, already
   *  run through `filterMachineTags` by the caller — ISS-019, spec's trap 1).
   *  Each `tag` is the RAW value from `GET /tags`, trailing slash and all
   *  for a namespace parent — see `flattenTagTree`'s comment for why that
   *  must survive unstripped into `onSelectTag`. */
  tags: FlatTag[];
  /** The currently selected tag's raw value, or null before the first tag
   *  has auto-selected (spec §5.2) / when there are no tags at all. */
  selectedTag: string | null;
  onSelectTag: (tag: string) => void;
  /** Fired after a successful inline create (spec board: 2026-08-02-flowreview-
   *  decisions.html, Fork 1 Option B) with the newly created name — the
   *  caller is expected to refetch listProjects()/getStats() (the rail's own
   *  tiles/counts go stale) and select the new project, mirroring
   *  ProjectsPane's onRenamed/onDeleted callbacks. This band-3 button used
   *  to be wired to an empty `onNewProject={() => {}}` stub (the FR-04/FR-12
   *  regression) — creation is now owned entirely inside this component, so
   *  there is no longer an external "open a modal" hook to call. */
  onProjectCreated?: (name: string) => void;
}

export default function ProjectsRail({
  mode,
  onModeChange,
  projects,
  projectCounts,
  looseCount,
  selectedId,
  onSelect,
  tags,
  selectedTag,
  onSelectTag,
  onProjectCreated,
}: ProjectsRailProps) {
  // One tile in a two-column grid would leave a hole, so loose spans the
  // row when it is the only thing there (spec §4, mirrored from the board's
  // tileGrid()).
  const looseSpansRow = projects.length === 0;

  // ── view swap (spec §8): entrance-only keyed fade+slide on band 2 when
  // the toggle flips Projects<->Tags. Direction comes from the SAME pure
  // slideDirection() the toggle's own content-swap pattern already uses
  // (lib/segmentedToggle.ts) — 0/1 segment index, not a new concept. The
  // ref holds the PREVIOUS index across renders; it is read (for this
  // render's direction) before being updated (for the next one) below. ──
  const modeIndex = mode === "tags" ? 1 : 0;
  const prevModeIndexRef = useRef(modeIndex);
  const swapDir = slideDirection(prevModeIndexRef.current, modeIndex);
  useEffect(() => {
    prevModeIndexRef.current = modeIndex;
  }, [modeIndex]);

  // ── inline project create (Fork 1 Option B: no modal, a new tile appears
  // in the grid, already editable — see the file header/onProjectCreated's
  // comment for the regression this replaces). All state is local: this
  // component owns the whole flow, start to the API call, and only reports
  // OUTWARD once creation actually succeeds.
  const [creating, setCreating] = useState(false);
  const [createValue, setCreateValue] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  // Guards the classic blur-vs-Escape race: Escape's keydown handler cancels
  // synchronously, but removing the input from the tree (creating -> false)
  // can still let the browser fire a trailing native blur on it first. This
  // ref, set true only inside the Escape handler and consumed by the very
  // next blur, tells that blur "this was a cancel, not a commit" — a commit
  // on blur must never re-fire right after the user explicitly cancelled.
  const cancelledByEscapeRef = useRef(false);

  function startCreate() {
    if (creating) return; // a second click while already editing must not wipe what the user typed
    setCreating(true);
    setCreateValue("");
    setCreateError(null);
  }

  function cancelCreate() {
    setCreating(false);
    setCreateValue("");
    setCreateError(null);
    setCreateSubmitting(false);
  }

  function commitCreate() {
    const trimmed = createValue.trim();
    if (!trimmed) { cancelCreate(); return; } // committing nothing is a cancel, not an error
    if (!isValidProjectName(trimmed)) { setCreateError(INVALID_NAME_MESSAGE); return; }
    setCreateSubmitting(true);
    setCreateError(null);
    createProject(trimmed)
      .then(() => {
        cancelCreate();
        onProjectCreated?.(trimmed);
      })
      .catch((e) => {
        setCreateSubmitting(false);
        setCreateError(e instanceof Error ? e.message : "Failed to create project");
      });
  }

  function handleCreateKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); commitCreate(); }
    else if (e.key === "Escape") {
      e.preventDefault();
      cancelledByEscapeRef.current = true;
      cancelCreate();
    }
  }

  function handleCreateBlur() {
    if (cancelledByEscapeRef.current) { cancelledByEscapeRef.current = false; return; }
    commitCreate();
  }

  return (
    <div style={railStyle}>
      {/* Pseudo-class states (:hover/:focus-visible/:active) for the `pr-`
          prefixed classNames below live in index.css's "PROJECTS full-window
          interaction states" block, not a component-local <style> tag here:
          the production CSP (style-src 'self', no 'unsafe-inline') silently
          drops an inline <style> tag's rules — the FR-03 lesson (see
          index.css's [data-theme="custom"] comment, App.tsx, and
          lib/customThemeVars.ts for the same rule elsewhere). Do not
          reintroduce a <style> block here. */}

      {/* band 1 — the toggle. Never scrolls, never moves. */}
      <div style={railTopStyle}>
        <SegmentedToggle
          ariaLabel="Rail view"
          value={mode}
          onChange={onModeChange}
          options={[
            {
              key: "projects" as const,
              label: "Projects",
              icon: (
                <span style={toggleIconLabelStyle}>
                  <DashboardIcon size={12} />
                  Projects
                </span>
              ),
            },
            {
              key: "tags" as const,
              label: "Tags",
              icon: (
                <span style={toggleIconLabelStyle}>
                  <ListIcon size={12} />
                  Tags
                </span>
              ),
            },
          ]}
        />
      </div>

      {/* band 2 — the ONLY band that scrolls. Each branch is keyed so a
          mode switch REMOUNTS the panel (entrance-only, per the
          .seg-swap-panel/segSwapIn comment in index.css) rather than
          diffing one <div>'s children into the other's — that remount is
          what makes the animation replay on every toggle instead of only
          the first mount. */}
      <div style={railScrollStyle}>
        {mode === "projects" ? (
          // role=listbox/option (not a bare aria-selected button — that
          // combination is invalid ARIA with no containing role, and AT
          // drops it): the same semantics Task 7's tag list uses (spec §7),
          // so the two halves of this toggle read identically to a screen
          // reader instead of two different affordances.
          <div
            key="projects"
            className="seg-swap-panel"
            style={{ ...tilesGridStyle, ["--swap-dir" as unknown as string]: swapDir } as CSSProperties}
            role="listbox"
            aria-label="Projects"
          >
            {projects.map((p) => {
              const on = selectedId === p.name;
              // Guard, per spec §2.2: a tile is one of the three surfaces
              // the `_loose` sentinel must never reach. A real registry
              // entry will never literally be named "_loose", but this
              // keeps the tile from being a silent exception to the rule
              // the other two surfaces (pane head, tag chip) also honor.
              const name = displayProject(p.name);
              const count = projectCounts[p.name] ?? 0;
              const hasDescription = !!(p.description && p.description.trim());
              return (
                <button
                  key={p.name}
                  role="option"
                  className="pr-tile"
                  aria-selected={on}
                  onClick={() => onSelect(p.name)}
                  style={on ? tileSelectedStyle : tileStyle}
                >
                  <span style={tileNameStyle}>{name}</span>
                  {hasDescription
                    ? <span style={tileCountStyle}>{count} notes</span>
                    : <span style={tileWarnStyle}>{count} notes, no description</span>}
                </button>
              );
            })}
            {/* Fork 1 Option B: the inline create row. Full-width regardless
                of how many real tiles precede it (a name is easier to read/
                type in a full row than squeezed into one half of the
                2-column grid) — a judgment call the board doesn't pin down
                for every tile count, flagged in this task's report.
                Background is --accent-d, the SAME wash a selected tile uses
                (tileSelectedStyle below) — never --surface-2, which is
                identical to --ctl-face in both themes (see this screen's own
                ceiling note) and would make the confirm/cancel glyphs below
                nearly invisible. */}
            {creating && (
              <div style={editingTileStyle}>
                <input
                  autoFocus
                  className="pr-create-input"
                  value={createValue}
                  onChange={(e) => { setCreateValue(e.target.value); if (createError) setCreateError(null); }}
                  onKeyDown={handleCreateKeyDown}
                  onBlur={handleCreateBlur}
                  placeholder="project-name"
                  aria-label="New project name"
                  disabled={createSubmitting}
                  style={createInputStyle}
                />
                <div style={editHintRowStyle}>
                  <span style={createError ? editErrorStyle : editHintStyle}>
                    {createError ?? "Enter to create · Esc to cancel"}
                  </span>
                  <span style={editGlyphsStyle}>
                    <button
                      type="button"
                      className="pr-glyph"
                      style={glyphBtnStyle}
                      disabled={createSubmitting}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={commitCreate}
                      title="Create"
                      aria-label="Create project"
                    >
                      <CheckIcon size={10} />
                    </button>
                    <button
                      type="button"
                      className="pr-glyph"
                      style={glyphBtnStyle}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={cancelCreate}
                      title="Cancel"
                      aria-label="Cancel"
                    >
                      <CloseIcon size={10} />
                    </button>
                  </span>
                </div>
              </div>
            )}
            <button
              role="option"
              className="pr-tile"
              aria-selected={selectedId === LOOSE_PROJECT_ID}
              onClick={() => onSelect(LOOSE_PROJECT_ID)}
              style={{
                ...(selectedId === LOOSE_PROJECT_ID ? tileSelectedStyle : tileStyle),
                gridColumn: looseSpansRow ? "1 / -1" : undefined,
              }}
            >
              <span style={tileLooseNameStyle}>
                <span style={looseDotStyle} aria-hidden="true" />
                {displayProject(LOOSE_PROJECT_ID)}
              </span>
              <span style={tileCountStyle}>{looseCount} notes</span>
            </button>
          </div>
        ) : (
          // The flat tag list (spec §5.1): role="listbox"/"option", same
          // selected-state visual language as a project tile (accent wash +
          // 2px accent edge) — "this is what the right side is showing"
          // must not mean two different affordances on the two halves of
          // one toggle. Tags are pre-flattened + pre-filtered by the caller
          // (lib/projectsView.ts's flattenTagTree + filterMachineTags —
          // ISS-019); this component only renders what it is given.
          <div
            key="tags"
            className="seg-swap-panel"
            style={{ ...tagListStyle, ["--swap-dir" as unknown as string]: swapDir } as CSSProperties}
            role="listbox"
            aria-label="Tags"
          >
            {tags.length === 0 ? (
              <div style={tagEmptyStyle}>No tags yet.</div>
            ) : (
              tags.map((t) => {
                const on = selectedTag === t.tag;
                return (
                  <button
                    key={t.tag}
                    role="option"
                    className="pr-tagrow"
                    aria-selected={on}
                    onClick={() => onSelectTag(t.tag)}
                    style={on ? tagRowSelectedStyle : tagRowStyle}
                  >
                    <span style={tagRowLabelStyle}>
                      <span style={tagHashStyle}>#</span>
                      {tagDisplayLabel(t.tag)}
                    </span>
                    <span style={on ? tagRowCountSelectedStyle : tagRowCountStyle}>{t.count}</span>
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>

      {/* band 3 — New project. Never scrolls, never moves, always the last
          thing in the rail regardless of state (spec §3). */}
      <div style={railFootStyle}>
        <button className="pr-newbtn btn-hover" onClick={startCreate} style={newBtnStyle}>
          <PlusIcon size={13} /> New project
        </button>
      </div>
    </div>
  );
}

// ── style objects — one const per element, matching the repo's inline-
// style-object convention (no CSS-in-JS library, see gui/src/components/
// FullWindow/DashboardView.tsx's cardStyle/chipStyle/etc). Values are
// transcribed from the board's CSS 1:1 where the property is static; the
// pseudo-class-only rules live in index.css's "PROJECTS full-window
// interaction states" block instead (moved there from a component-local
// <style> tag — see the comment above; that tag was dead in production). ──

const railStyle: CSSProperties = {
  flex: "0 0 auto", width: 260, borderRight: "1px solid var(--border)",
  display: "flex", flexDirection: "column", minHeight: 0,
};
const railTopStyle: CSSProperties = { flex: "0 0 auto", padding: 8, borderBottom: "1px solid var(--border-2)" };
const railScrollStyle: CSSProperties = { flex: "1 1 auto", minHeight: 0, overflowY: "auto", scrollbarGutter: "stable" };
const railFootStyle: CSSProperties = { flex: "0 0 auto", borderTop: "1px solid var(--border)", padding: 8 };

const toggleIconLabelStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 6 };

const tilesGridStyle: CSSProperties = {
  display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 1,
  background: "var(--border-2)", borderBottom: "1px solid var(--border-2)",
};
const tileStyle: CSSProperties = {
  minWidth: 0, background: "var(--surface)", border: "none", borderLeft: "2px solid transparent",
  padding: "9px 9px", minHeight: 56, display: "flex", flexDirection: "column", justifyContent: "space-between",
  gap: 5, cursor: "pointer", fontFamily: "inherit", textAlign: "left", color: "var(--text-1)",
};
const tileSelectedStyle: CSSProperties = { ...tileStyle, background: "var(--accent-d)", borderLeftColor: "var(--accent)" };
const tileNameStyle: CSSProperties = { fontSize: 10.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const tileLooseNameStyle: CSSProperties = { ...tileNameStyle, color: "var(--text-3)", display: "flex", alignItems: "center", gap: 6 };
const tileCountStyle: CSSProperties = { fontSize: 9, color: "var(--text-3)", fontVariantNumeric: "tabular-nums" };
const tileWarnStyle: CSSProperties = { fontSize: 8.5, color: "var(--yellow)" };
const looseDotStyle: CSSProperties = { width: 5, height: 5, border: "1px dashed currentColor", borderRadius: "50%", flex: "0 0 auto" };

// ── inline create (Fork 1 Option B) ─────────────────────────────────────
const editingTileStyle: CSSProperties = {
  gridColumn: "1 / -1", minWidth: 0, background: "var(--accent-d)", borderLeft: "2px solid var(--accent)",
  padding: "9px 9px", display: "flex", flexDirection: "column", gap: 6,
};
const createInputStyle: CSSProperties = {
  width: "100%", boxSizing: "border-box", background: "var(--bg)", border: "1px solid var(--border)",
  color: "var(--text-1)", fontFamily: "inherit", fontSize: 11, fontWeight: 600, padding: "5px 7px",
};
const editHintRowStyle: CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 };
const editHintStyle: CSSProperties = { fontSize: 9, color: "var(--text-3)" };
const editErrorStyle: CSSProperties = { fontSize: 9, color: "var(--red)" };
const editGlyphsStyle: CSSProperties = { display: "flex", gap: 2, flex: "0 0 auto" };
const glyphBtnStyle: CSSProperties = {
  width: 20, height: 20, display: "flex", alignItems: "center", justifyContent: "center",
  color: "var(--text-2)", background: "var(--ctl-face)", border: "1px solid var(--border)", cursor: "pointer", padding: 0,
};

// ── tag list (spec §5.1) — same selected-state language as a project tile:
// accent wash + 2px accent left edge, board's .tagrow (mock lines 144-154).
const tagListStyle: CSSProperties = { display: "block" };
const tagEmptyStyle: CSSProperties = { padding: "20px 16px", fontSize: 10.5, color: "var(--text-3)", lineHeight: 1.6 };
const tagRowBase: CSSProperties = {
  width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
  padding: "6px 10px 6px 8px", fontSize: 11, textAlign: "left", fontFamily: "inherit",
  color: "var(--text-2)", background: "var(--surface)", border: "none", borderLeft: "2px solid transparent",
  borderBottom: "1px solid var(--border-2)", cursor: "pointer",
};
const tagRowStyle: CSSProperties = tagRowBase;
const tagRowSelectedStyle: CSSProperties = {
  ...tagRowBase, background: "var(--accent-d)", borderLeftColor: "var(--accent)", color: "var(--text-1)",
};
const tagRowLabelStyle: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const tagHashStyle: CSSProperties = { color: "var(--text-3)" };
const tagRowCountStyle: CSSProperties = { fontSize: 9.5, color: "var(--text-3)", fontVariantNumeric: "tabular-nums", flex: "0 0 auto" };
const tagRowCountSelectedStyle: CSSProperties = { ...tagRowCountStyle, color: "var(--text-2)" };

const newBtnStyle: CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 11, color: "var(--text-1)",
  border: "1px solid var(--border)", background: "var(--ctl-face)", padding: 8, cursor: "pointer", fontFamily: "inherit", width: "100%",
};

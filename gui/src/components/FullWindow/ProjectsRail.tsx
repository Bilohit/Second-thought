/**
 * ProjectsRail.tsx — sub-project 3 Task 4: the projects/tags rail, the left
 * 260px column of the full-window Projects screen (spec §3's A3 split
 * panel). A three-band column: band 1 (the Projects|Tags toggle) and band 3
 * (New project) never scroll or move; only band 2 (tiles, or the tag list)
 * does. The suggestion sits directly above band 3 in the same 8px gutter,
 * so New project is always the last thing in the rail (spec §3).
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
 *  - The Tags half of the toggle switches the band correctly; the actual
 *    tag LIST (role=listbox/option, per-row project chip, first-tag-auto-
 *    select) is Task 7 — left as an explicitly commented seam below.
 *  - The suggestion box is presentational only, driven entirely by props.
 *    It is not wired to GET /inbox/{note_id}/suggest-projects here — see
 *    ProjectsView.tsx's file header for why.
 *  - Tile counts are handed in via `projectCounts` (spec §5.6) — this
 *    component does not read `ProjectEntry.file_count` and must not start
 *    (that field is a directory listing, not the index's project column;
 *    see ProjectsView.tsx's file header for why that distinction is load-
 *    bearing). The rail renders the counts it is given, it does not pick
 *    its own source.
 *
 * Task 6 (motion pass, spec §8) added: the Projects|Tags band-2 content
 * swap (`.seg-swap-panel`, direction from `lib/segmentedToggle.ts`'s
 * `slideDirection`) and the suggestion's collapse-on-dismiss (`.pr-disclose`,
 * index.css). Both reuse index.css's existing `--menu-travel-ease` /
 * `--hover-ease-out` tokens — see index.css's "PROJECTS full-window motion
 * pass" comment block for why those are the spec's `--ease-travel` /
 * `--ease-settle` under this repo's own names, not two new tokens on the
 * same curves. The FLIP re-order and sort-icon swap live in ProjectsPane.tsx
 * (they animate note rows and the sort button, not anything in this file).
 */
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { ProjectEntry } from "../../lib/api";
import { displayProject } from "../../lib/projectsView";
import { slideDirection } from "../../lib/segmentedToggle";
import SegmentedToggle from "../ui/SegmentedToggle";
import { DashboardIcon, ListIcon, PlusIcon, MenuIcon, CheckIcon, PencilIcon, CloseIcon } from "../PillMenu/icons";

/** Board xPulse/disclose durations (spec §8), mirrored in JS so the dismiss
 *  handler's cleanup timer agrees with index.css's `.pr-disclose` transition
 *  (grid-template-rows 240ms) without a second hardcoded number to drift. */
const SUGGESTION_COLLAPSE_MS = 240;

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

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

export interface ProjectsRailSuggestion {
  /** The proposed project name. */
  name: string;
  /** The one supporting fact, e.g. "3 loose captures, past 6 days, matching no project". */
  fact: string;
}

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
  /** null/undefined = nothing pending, so the box does not render.
   *  Presentational only — see the file header. */
  suggestion?: ProjectsRailSuggestion | null;
  onSuggestionCreate?: () => void;
  onSuggestionRename?: () => void;
  onSuggestionDismiss?: () => void;
  onNewProject: () => void;
}

export default function ProjectsRail({
  mode,
  onModeChange,
  projects,
  projectCounts,
  looseCount,
  selectedId,
  onSelect,
  suggestion,
  onSuggestionCreate,
  onSuggestionRename,
  onSuggestionDismiss,
  onNewProject,
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

  // ── suggestion collapse-on-dismiss (spec §8): the rail renders the
  // suggestion conditionally ({suggestion && ...}), so once the CALLER
  // nulls `suggestion` there is no node left to collapse. `heldSuggestion`
  // keeps the box's content on screen for exactly the collapse's duration
  // so the disclose wrapper has something to shrink around, then the state
  // clears and the node truly leaves the tree. ──
  const [collapsing, setCollapsing] = useState(false);
  const heldSuggestionRef = useRef<ProjectsRailSuggestion | null>(null);
  const collapseTimerRef = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    if (suggestion) heldSuggestionRef.current = suggestion;
  }, [suggestion]);
  useEffect(() => () => { if (collapseTimerRef.current) clearTimeout(collapseTimerRef.current); }, []);

  function handleDismiss() {
    if (!prefersReducedMotion()) {
      setCollapsing(true);
      collapseTimerRef.current = setTimeout(() => setCollapsing(false), SUGGESTION_COLLAPSE_MS);
    }
    onSuggestionDismiss?.();
  }

  const displaySuggestion = suggestion ?? (collapsing ? heldSuggestionRef.current : null);

  return (
    <div style={railStyle}>
      {/* Pseudo-class states an inline style object cannot express
          (:hover/:focus-visible/:active). Scoped by the `pr-` prefix so
          nothing here can collide with another mounted view's classNames —
          the same pattern TagsView.tsx already uses in this directory.
          Uses var(--hover-ease-out) rather than the equivalent
          cubic-bezier(0.16,1,0.3,1) literal (index.css:79) so this curve's
          value lives in exactly one place. */}
      <style>{`
        .pr-tile { transition: background 160ms var(--hover-ease-out), color 160ms var(--hover-ease-out); }
        .pr-tile:hover { background: var(--surface-2); }
        .pr-tile:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
        .pr-newbtn:focus-visible { outline: 2px solid var(--accent); outline-offset: -1px; }
        .pr-sg-create { transition: background 160ms var(--hover-ease-out), transform 120ms var(--hover-ease-out); }
        .pr-sg-create:hover { background: var(--accent); color: var(--on-accent); }
        .pr-sg-create:active { transform: scale(0.97); }
        .pr-sg-create:focus-visible { outline: 2px solid var(--text-1); outline-offset: 1px; }
        .pr-sg-rename { transition: background 160ms var(--hover-ease-out), border-color 160ms var(--hover-ease-out), transform 120ms var(--hover-ease-out); }
        .pr-sg-rename:hover { background: var(--ctl-face-hover); border-color: var(--accent); }
        .pr-sg-rename:active { transform: scale(0.96); }
        .pr-sg-rename:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
        .pr-sg-dismiss { transition: color 200ms var(--hover-ease-out), border-color 200ms var(--hover-ease-out), background 200ms var(--hover-ease-out), box-shadow 220ms var(--hover-ease-out); }
        .pr-sg-dismiss:hover, .pr-sg-dismiss:focus-visible { color: var(--red); border-color: var(--red); background: rgba(255,100,103,0.12); box-shadow: 0 0 0 3px rgba(255,100,103,0.10); outline: none; }
        .pr-sg-dismiss:hover svg, .pr-sg-dismiss:focus-visible svg { animation: xPulse 340ms var(--hover-ease-out); }
        .pr-sg-dismiss:active { transform: scale(0.92); }
      `}</style>

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
          // Task 7 seam: the flat tag list (role="listbox"/"option", the
          // per-row project chip via displayProject(), first-tag-auto-
          // select on switch — spec §5) is deliberately NOT built here.
          // This placeholder proves the toggle actually switches band 2
          // without inventing tag rows or fake data.
          <div
            key="tags"
            className="seg-swap-panel"
            style={{ ...tagSeamStyle, ["--swap-dir" as unknown as string]: swapDir } as CSSProperties}
          >
            Tags (Task 7)
          </div>
        )}
      </div>

      {/* the suggestion — a box in the SAME 8px gutter band 3 uses, so the
          two are the same width by construction (spec §4.2, §4.3).
          Presentational only: renders iff there is something to show OR the
          collapse-on-dismiss animation is mid-flight (`displaySuggestion`
          covers both — see the state comment above). The `.pr-disclose`
          wrapper is the ONE node the collapse animates: it persists through
          the collapse (spec §8, task brief) and only leaves the tree once
          `collapsing` clears. */}
      {displaySuggestion && (
        <div className={collapsing ? "pr-disclose pr-disclose-shut" : "pr-disclose"}>
          <div>
            <div style={suggWrapStyle}>
              <div style={suggBoxStyle}>
                <div style={suggHeadStyle}>
                  <MenuIcon target="inbox" size={11} /> Inbox suggests
                </div>
                <div style={suggNameStyle}>{displaySuggestion.name}</div>
                <div style={suggFactStyle}>{displaySuggestion.fact}</div>
                <div style={suggActsStyle}>
                  <button className="pr-sg-create" onClick={onSuggestionCreate} style={sgCreateStyle}>
                    <CheckIcon size={12} />
                    <span style={sgLabelStyle}>Create</span>
                  </button>
                  <button className="pr-sg-rename" onClick={onSuggestionRename} style={sgRenameStyle}>
                    <PencilIcon size={12} />
                    <span style={sgLabelStyle}>Rename</span>
                  </button>
                  <button
                    className="pr-sg-dismiss"
                    onClick={handleDismiss}
                    title="Not a project"
                    aria-label="Not a project"
                    style={sgDismissStyle}
                  >
                    <CloseIcon size={13} />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* band 3 — New project. Never scrolls, never moves, always the last
          thing in the rail regardless of state (spec §3). */}
      <div style={railFootStyle}>
        <button className="pr-newbtn btn-hover" onClick={onNewProject} style={newBtnStyle}>
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
// pseudo-class-only rules live in the <style> block above instead. ──────

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

const tagSeamStyle: CSSProperties = { padding: "20px 16px", fontSize: 10.5, color: "var(--text-3)", lineHeight: 1.6 };

const suggWrapStyle: CSSProperties = { flex: "0 0 auto", padding: 8 };
const suggBoxStyle: CSSProperties = {
  ["--ctl" as unknown as string]: "30px",
  border: "1px solid var(--border)", padding: 8, background: "var(--accent-d)",
} as CSSProperties;
const suggHeadStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 6, fontSize: 8.5, letterSpacing: "0.08em",
  textTransform: "uppercase", color: "var(--text-3)",
};
const suggNameStyle: CSSProperties = {
  fontSize: 13, fontWeight: 600, color: "var(--text-1)", margin: "5px 0 2px",
  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
};
const suggFactStyle: CSSProperties = { fontSize: 9, color: "var(--text-3)", marginBottom: 9 };
const suggActsStyle: CSSProperties = { display: "flex", gap: 6, alignItems: "center" };

const sgLabelStyle: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
// One control height declared once (--ctl on the box above), governing all
// three buttons — spec §4.2. Create/Rename share flex:1 1 0 + min-width:0
// so a long label can never make one wider than the other; the dismiss is
// excluded from the flex growth entirely (flex:0 0 auto, width==height==--ctl).
const sgBase: CSSProperties = {
  flex: "1 1 0", minWidth: 0, height: "var(--ctl)", display: "flex", alignItems: "center", justifyContent: "center",
  gap: 6, fontSize: 10.5, fontFamily: "inherit", padding: "0 10px", cursor: "pointer", border: "1px solid var(--border)",
};
// Colour rule (spec §4.4): inputs are RECESSED (--bg), controls are RAISED
// (--ctl-face). Create keeps the accent (the one control that does NOT
// move to --ctl-face) so the primary choice still reads as primary.
const sgCreateStyle: CSSProperties = {
  ...sgBase, fontWeight: 600, background: "var(--accent-glow)", borderColor: "var(--accent)", color: "var(--text-1)",
};
const sgRenameStyle: CSSProperties = { ...sgBase, background: "var(--ctl-face)", color: "var(--text-1)" };
const sgDismissStyle: CSSProperties = {
  flex: "0 0 auto", width: "var(--ctl)", height: "var(--ctl)", display: "flex", alignItems: "center", justifyContent: "center",
  background: "var(--ctl-face)", border: "1px solid var(--border)", color: "var(--text-2)", cursor: "pointer", padding: 0,
};

const newBtnStyle: CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 11, color: "var(--text-1)",
  border: "1px solid var(--border)", background: "var(--ctl-face)", padding: 8, cursor: "pointer", fontFamily: "inherit", width: "100%",
};

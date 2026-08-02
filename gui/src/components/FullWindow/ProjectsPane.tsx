/**
 * ProjectsPane.tsx — sub-project 3 Task 5: the right-hand pane of the
 * full-window Projects screen (spec §3's A3 split panel). Owns the head
 * (name, rename, delete, description editor), the notes-head (count + sort
 * instrument), the note rows, and the delete-confirm strip.
 *
 * Board (visual source of truth): gui/mocks/2026-08-01-projects-fullwindow-v3.html.
 * Spec: docs/superpowers/specs/2026-08-02-projects-s3-fullwindow-design.md
 * §4.5-§4.8, §5.5-§5.6, §6, §7.
 *
 * ★ The two data rules this file exists to get right (task brief, both
 * traced to source):
 *  1. Fetches notes with an EXPLICIT limit (`notesForProject(name, { limit:
 *     200 })`) and drops every LAN-provisional overlay row
 *     (`excludeProvisional`, lib/projectsView.ts) before counting or
 *     rendering — `GET /search` includes provisional=1 rows on purpose
 *     (index_writer.py:686-697), `GET /stats` does not, and a provisional
 *     row is keyed by a synthetic path with no real file behind it
 *     (index_writer.py:699-700), so it can never be opened.
 *  2. The notes-head count is ALWAYS `rows.length` — the same filtered rows
 *     this pane renders (spec §5.6). It never reads the rail's
 *     stats-derived `projectCounts` (that prop does not even reach this
 *     component): a project's tile count and this pane's list length must
 *     never be able to disagree by construction.
 *
 * Scope boundaries (binding, this task's brief):
 *  - Tag-view rendering is Task 7 — this component only ever renders a
 *    project's or the loose bucket's notes, selected via `selectedId`
 *    (a project `name` or `ProjectsRail.LOOSE_PROJECT_ID`).
 *  - FLIP re-order, the sort-icon swap/spin, and the delete-strip/suggestion
 *    motion are Task 6. Rows ARE keyed by `path` (not array index) so a
 *    future FLIP pass can re-parent the existing nodes instead of
 *    recreating them — but no transition/animation is added here.
 *  - No pager (spec §5.5.1 — Task 9's, and unreachable at <=200 notes).
 */
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  notesForProject,
  renameProject,
  deleteProject,
  updateProjectDescription,
  type ProjectEntry,
  type SearchResult,
} from "../../lib/api";
import {
  displayProject,
  excludeProvisional,
  formatAgo,
  metaEpochMs,
  nextSortMode,
  sortNotes,
  SORT_MODE_LABEL,
  SORT_MODE_META_VERB,
  type SortMode,
} from "../../lib/projectsView";
import { LOOSE_PROJECT_ID } from "./ProjectsRail";
import {
  PencilIcon, TrashIcon, CheckIcon, CloseIcon, FileIcon, ChevronRightIcon,
  SortNewestIcon, SortOldestIcon, SortEditedIcon, CycleIcon,
} from "../PillMenu/icons";

/** Debounce for the description editor's "saves as you type" (spec §4.6).
 *  Not part of spec §8's motion inventory — that table covers visual
 *  transitions only, not data-save timing — so this is a plain
 *  implementation constant, not an invented easing/duration. */
const DESC_SAVE_DEBOUNCE_MS = 500;

const SORT_ICON: Record<SortMode, (props: { size?: number }) => JSX.Element> = {
  newest: SortNewestIcon,
  oldest: SortOldestIcon,
  edited: SortEditedIcon,
};

interface ProjectsPaneProps {
  /** Registry entries — used to look up the selected project's identity
   *  (name/description) by `selectedId`. Same array ProjectsRail renders,
   *  so the two surfaces agree on what a project IS. */
  projects: ProjectEntry[];
  /** A project's `name`, `LOOSE_PROJECT_ID`, or null before the first list
   *  has loaded. */
  selectedId: string | null;
  onOpenNote?: (path: string) => void;
  /** Fired after a successful rename. The rail's tiles go stale on a
   *  rename — the caller is expected to refetch `listProjects()` +
   *  `getStats()` and move the selection to `newName`. */
  onRenamed?: (oldName: string, newName: string) => void;
  /** Fired after a successful delete. The rail's tiles/counts go stale on a
   *  delete — the caller is expected to refetch and fall the selection back
   *  to the loose bucket. */
  onDeleted?: (name: string) => void;
  /** Fired after a successful description save, so the caller can patch its
   *  own copy of the registry entry (keeps the rail's "no description"
   *  warning in sync without a full refetch on every keystroke). */
  onDescriptionSaved?: (name: string, description: string) => void;
}

export default function ProjectsPane({
  projects,
  selectedId,
  onOpenNote,
  onRenamed,
  onDeleted,
  onDescriptionSaved,
}: ProjectsPaneProps) {
  const isLoose = selectedId === LOOSE_PROJECT_ID;
  const isEmptyVault = projects.length === 0;
  const selected = selectedId && !isLoose ? projects.find((p) => p.name === selectedId) ?? null : null;

  // ── notes: this pane's OWN fetch (spec §5.5's "the implementation trap") ──
  const [rows, setRows] = useState<SearchResult[]>([]);
  const [notesLoading, setNotesLoading] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>("newest");

  useEffect(() => {
    if (!selectedId) { setRows([]); return; }
    let cancelled = false;
    setNotesLoading(true);
    notesForProject(selectedId, { limit: 200 })
      .then((results) => {
        if (cancelled) return;
        // Rule 1: drop LAN-provisional overlay rows before this pane counts
        // or renders anything — see this file's header comment.
        setRows(excludeProvisional(results));
      })
      .catch(() => { if (!cancelled) setRows([]); })
      .finally(() => { if (!cancelled) setNotesLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId]);

  const sortedRows = sortNotes(rows, sortMode);
  // Rule 2: the ONLY count this pane ever shows — derived from the rows it
  // just fetched and filtered, never from a sibling source (spec §5.6).
  const noteCount = rows.length;

  // ── head interaction state, reset whenever the selection changes ────────
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [descDraft, setDescDraft] = useState("");
  const pendingSaveRef = useRef<{ name: string; value: string; timer: ReturnType<typeof setTimeout> } | null>(null);

  useEffect(() => {
    setRenaming(false);
    setConfirmingDelete(false);
    setMutationError(null);
    setDescDraft(selected?.description ?? "");
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps -- `selected` is derived FROM selectedId; re-running on every `projects` identity change would clobber an in-progress edit on every unrelated refetch.

  // Flush an in-flight debounced description save immediately when the
  // selection moves on (or the pane unmounts), rather than letting a save
  // meant for the PREVIOUS project land silently seconds later.
  useEffect(() => {
    return () => {
      const pending = pendingSaveRef.current;
      if (!pending) return;
      clearTimeout(pending.timer);
      pendingSaveRef.current = null;
      updateProjectDescription(pending.name, pending.value).catch(() => { /* best-effort flush */ });
    };
  }, [selectedId]);

  function handleDescriptionInput(value: string) {
    setDescDraft(value);
    if (!selected) return; // no editor is rendered for loose/empty, so this is unreachable there
    if (pendingSaveRef.current) clearTimeout(pendingSaveRef.current.timer);
    const name = selected.name;
    const timer = setTimeout(() => {
      pendingSaveRef.current = null;
      updateProjectDescription(name, value)
        .then(() => onDescriptionSaved?.(name, value))
        .catch((e) => setMutationError(e instanceof Error ? e.message : "Failed to save description"));
    }, DESC_SAVE_DEBOUNCE_MS);
    pendingSaveRef.current = { name, value, timer };
  }

  function startRename() {
    if (!selected) return;
    setMutationError(null);
    setRenameValue(selected.name);
    setRenaming(true);
  }

  function confirmRename() {
    if (!selected) return;
    const newName = renameValue.trim();
    if (!newName || newName === selected.name) { setRenaming(false); return; }
    const oldName = selected.name;
    setMutationError(null);
    renameProject(oldName, newName)
      .then(() => { setRenaming(false); onRenamed?.(oldName, newName); })
      .catch((e) => setMutationError(e instanceof Error ? e.message : "Failed to rename"));
  }

  function confirmDelete() {
    if (!selected) return;
    const name = selected.name;
    setMutationError(null);
    deleteProject(name)
      .then(() => { setConfirmingDelete(false); onDeleted?.(name); })
      .catch((e) => setMutationError(e instanceof Error ? e.message : "Failed to delete"));
  }

  function handleSortClick() {
    setSortMode((m) => nextSortMode(m));
  }

  if (!selectedId) return <div style={paneStyle} />;

  const SortIcon = SORT_ICON[sortMode];
  const metaVerb = SORT_MODE_META_VERB[sortMode];

  return (
    <div style={paneStyle}>
      {/* Pseudo-class states an inline style object cannot express, same
          scoping pattern as ProjectsRail.tsx's `pr-` prefix. */}
      <style>{`
        .pp-iconbtn { transition: color 160ms cubic-bezier(0.16,1,0.3,1), background 160ms cubic-bezier(0.16,1,0.3,1); }
        .pp-iconbtn:hover { color: var(--text-1); background: var(--surface-2); }
        .pp-iconbtn:focus-visible { outline: 2px solid var(--accent); outline-offset: -1px; }
        .pp-iconbtn.pp-danger { color: var(--red); opacity: 0.82; }
        .pp-iconbtn.pp-danger:hover { opacity: 1; background: rgba(255,100,103,0.12); }
        .pp-desc-area:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
        .pp-sortbtn { transition: color 160ms cubic-bezier(0.16,1,0.3,1), border-color 160ms cubic-bezier(0.16,1,0.3,1), background 160ms cubic-bezier(0.16,1,0.3,1); }
        .pp-sortbtn:hover { border-color: var(--accent); background: var(--ctl-face-hover); }
        .pp-sortbtn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
        .pp-noterow { transition: background 160ms cubic-bezier(0.16,1,0.3,1), color 160ms cubic-bezier(0.16,1,0.3,1); }
        .pp-noterow:hover { background: var(--surface-2); color: var(--text-1); }
        .pp-noterow:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
        .pp-ghost { transition: color 160ms cubic-bezier(0.16,1,0.3,1), border-color 160ms cubic-bezier(0.16,1,0.3,1); }
        .pp-ghost:hover { color: var(--text-1); border-color: var(--accent); }
      `}</style>

      {isEmptyVault ? (
        <div style={calmHeadStyle}>
          <h3 style={calmHeadingStyle}>No projects yet</h3>
          <p style={calmParaStyle}>
            All {noteCount} of your notes are loose, which is a normal and permanent place for a note
            to live. Make a project when you want the phone to file new captures somewhere by itself.
          </p>
        </div>
      ) : isLoose ? (
        <div style={looseHeadStyle}>
          <span style={looseHeadDotStyle} aria-hidden="true" />
          <span style={looseHeadNameStyle}>{displayProject(LOOSE_PROJECT_ID)}</span>
          <span style={looseHeadSubStyle}>no project tag, nothing to set up</span>
        </div>
      ) : selected ? (
        <div style={projectHeadStyle}>
          <div style={projectHeadTopRowStyle}>
            {renaming ? (
              <>
                <input
                  autoFocus
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") confirmRename();
                    if (e.key === "Escape") setRenaming(false);
                  }}
                  aria-label="New project name"
                  style={renameInputStyle}
                />
                <span style={headIconRowStyle}>
                  <button className="pp-iconbtn" style={iconBtnStyle} onClick={confirmRename} title="Confirm rename" aria-label="Confirm rename">
                    <CheckIcon size={13} />
                  </button>
                  <button className="pp-iconbtn" style={iconBtnStyle} onClick={() => setRenaming(false)} title="Cancel rename" aria-label="Cancel rename">
                    <CloseIcon size={13} />
                  </button>
                </span>
              </>
            ) : (
              <>
                <span style={projectNameStyle}>{selected.name}</span>
                <span style={headIconRowStyle}>
                  <button className="pp-iconbtn" style={iconBtnStyle} onClick={startRename} title="Rename" aria-label="Rename project">
                    <PencilIcon size={13} />
                  </button>
                  <button
                    className="pp-iconbtn pp-danger"
                    style={iconBtnStyle}
                    onClick={() => setConfirmingDelete(true)}
                    title="Delete project"
                    aria-label="Delete project"
                  >
                    <TrashIcon size={13} />
                  </button>
                </span>
              </>
            )}
          </div>
          <textarea
            className="pp-desc-area"
            rows={4}
            value={descDraft}
            onChange={(e) => handleDescriptionInput(e.target.value)}
            placeholder="What belongs in this project? One or two sentences."
            aria-label="Project description"
            style={descAreaStyle}
          />
          <div style={descFootStyle}>
            {descDraft.trim() ? (
              <span style={qmeterStyle}>This is what your phone matches new notes against.</span>
            ) : (
              <span style={{ ...qmeterStyle, color: "var(--yellow)" }}>
                Empty. Your phone has nothing to match new notes against yet.
              </span>
            )}
            <span style={savesAsYouTypeStyle}>saves as you type</span>
          </div>
        </div>
      ) : null}

      {mutationError && <div style={mutationErrorStyle}>{mutationError}</div>}

      {confirmingDelete && selected && (
        <div style={confirmStripStyle}>
          <span style={confirmTextStyle}>
            {"Delete "}
            <b style={{ color: "var(--text-1)" }}>{selected.name}</b>
            {`? Its ${noteCount} notes become loose. None is deleted, trashed or edited.`}
          </span>
          <button className="pp-ghost" style={ghostBtnStyle} onClick={() => setConfirmingDelete(false)}>
            Cancel
          </button>
          <button className="pp-ghost" style={ghostDangerBtnStyle} onClick={confirmDelete}>
            Delete project only
          </button>
        </div>
      )}

      <div style={notesHeadStyle}>
        <span style={notesLabelStyle}>{noteCount} notes</span>
        <button
          className="pp-sortbtn"
          style={sortBtnStyle}
          onClick={handleSortClick}
          aria-label={`Arrangement: ${SORT_MODE_LABEL[sortMode]}. Click to change.`}
        >
          <span style={sortIconSlotStyle}><SortIcon size={13} /></span>
          <span style={sortLabelStyle}>{SORT_MODE_LABEL[sortMode]}</span>
          <span style={sortCycleSlotStyle}><CycleIcon size={11} /></span>
        </button>
      </div>

      <div style={notesScrollStyle}>
        {notesLoading && rows.length === 0 && <div style={notesEmptyStyle}>Loading…</div>}
        {!notesLoading && sortedRows.length === 0 && <div style={notesEmptyStyle}>No notes here yet.</div>}
        {sortedRows.map((row) => {
          const epochMs = metaEpochMs(row, sortMode);
          const meta = epochMs === null ? "date unknown" : `${metaVerb} ${formatAgo(epochMs)}`;
          const title = row.filename ?? row.path.split(/[\\/]/).pop() ?? row.path;
          return (
            <div
              key={row.path}
              className="pp-noterow"
              role="button"
              tabIndex={0}
              style={noteRowStyle}
              onClick={() => onOpenNote?.(row.path)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpenNote?.(row.path); }
              }}
            >
              <span style={noteRowFileIconStyle}><FileIcon size={12} /></span>
              <span style={noteRowTitleStyle}>{title}</span>
              <span style={noteRowMetaStyle}>{meta}</span>
              <span style={noteRowChevStyle}><ChevronRightIcon size={11} /></span>
            </div>
          );
        })}
        {isLoose && !isEmptyVault && (
          <div style={moreRowStyle}>Loose is normal and permanent, not a queue.</div>
        )}
      </div>
    </div>
  );
}

// ── style objects — one const per element, matching the repo's inline-
// style-object convention (see ProjectsRail.tsx). Values transcribed from
// the board's CSS 1:1 where the property is static. ──────────────────────

const paneStyle: CSSProperties = { flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0 };

const calmHeadStyle: CSSProperties = {
  flex: "0 0 auto", padding: "24px 26px 22px", borderBottom: "1px solid var(--border)",
  display: "flex", flexDirection: "column", gap: 12, maxWidth: "66ch",
};
const calmHeadingStyle: CSSProperties = { fontSize: 16, fontWeight: 600, margin: 0, color: "var(--text-1)" };
const calmParaStyle: CSSProperties = { fontSize: 11.5, color: "var(--text-2)", lineHeight: 1.7, margin: 0 };

const looseHeadStyle: CSSProperties = {
  flex: "0 0 auto", borderBottom: "1px solid var(--border)", padding: "14px 16px",
  display: "flex", alignItems: "center", gap: 10,
};
const looseHeadDotStyle: CSSProperties = {
  width: 7, height: 7, border: "1px dashed var(--text-3)", borderRadius: "50%", flex: "0 0 auto",
};
const looseHeadNameStyle: CSSProperties = { fontSize: 14, fontWeight: 600, color: "var(--text-1)" };
const looseHeadSubStyle: CSSProperties = { fontSize: 10, color: "var(--text-3)" };

const projectHeadStyle: CSSProperties = {
  flex: "0 0 auto", borderBottom: "1px solid var(--border)", padding: "13px 16px 12px",
  display: "flex", flexDirection: "column", gap: 9,
};
const projectHeadTopRowStyle: CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 };
const projectNameStyle: CSSProperties = {
  fontSize: 15, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-1)",
};
const headIconRowStyle: CSSProperties = { display: "flex", gap: 2, flex: "0 0 auto" };
const iconBtnStyle: CSSProperties = {
  width: 26, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
  color: "var(--text-3)", background: "none", border: "1px solid transparent", cursor: "pointer", padding: 0,
};
const renameInputStyle: CSSProperties = {
  flex: 1, minWidth: 0, background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text-1)",
  fontFamily: "inherit", fontSize: 15, fontWeight: 600, padding: "4px 8px",
};

const descAreaStyle: CSSProperties = {
  width: "100%", background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text-1)",
  fontFamily: "inherit", fontSize: 11.5, lineHeight: 1.6, padding: "9px 11px", resize: "none", boxSizing: "border-box",
};
const descFootStyle: CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14 };
const qmeterStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 7, fontSize: 9.5, color: "var(--text-3)" };
const savesAsYouTypeStyle: CSSProperties = { fontSize: 9, color: "var(--text-3)", flex: "0 0 auto" };

const mutationErrorStyle: CSSProperties = {
  flex: "0 0 auto", padding: "6px 16px", fontSize: 10.5, color: "var(--red)", borderBottom: "1px solid var(--border)",
};

const confirmStripStyle: CSSProperties = {
  flex: "0 0 auto", borderBottom: "1px solid var(--border)", background: "rgba(255,100,103,0.08)",
  padding: "9px 16px", display: "flex", alignItems: "center", gap: 12,
};
const confirmTextStyle: CSSProperties = { fontSize: 10.5, color: "var(--text-2)", flex: "1 1 auto" };
const ghostBtnStyle: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10, color: "var(--text-2)",
  border: "1px solid var(--border)", background: "var(--bg)", padding: "5px 9px", cursor: "pointer", fontFamily: "inherit",
};
const ghostDangerBtnStyle: CSSProperties = { ...ghostBtnStyle, borderColor: "var(--red)", color: "var(--red)" };

const notesHeadStyle: CSSProperties = {
  flex: "0 0 auto", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
  padding: "7px 16px", borderBottom: "1px solid var(--border)",
};
const notesLabelStyle: CSSProperties = { fontSize: 9, letterSpacing: "0.09em", textTransform: "uppercase", color: "var(--text-3)" };

const sortBtnStyle: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 7, fontFamily: "inherit", fontSize: 10,
  color: "var(--text-1)", background: "var(--ctl-face)", border: "1px solid var(--border)", padding: "4px 7px 4px 6px", cursor: "pointer",
};
const sortIconSlotStyle: CSSProperties = { display: "flex", color: "var(--text-1)" };
const sortLabelStyle: CSSProperties = { minWidth: 96, textAlign: "left" };
const sortCycleSlotStyle: CSSProperties = { display: "flex", color: "var(--text-2)" };

const notesScrollStyle: CSSProperties = { flex: "1 1 auto", minHeight: 0, overflowY: "auto", scrollbarGutter: "stable" };
const notesEmptyStyle: CSSProperties = { padding: 14, fontSize: 12, color: "var(--text-3)" };

const noteRowStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderBottom: "1px solid var(--border-2)",
  fontSize: 11.5, color: "var(--text-2)", cursor: "pointer", background: "var(--surface)",
};
const noteRowFileIconStyle: CSSProperties = { color: "var(--text-3)", flex: "0 0 auto", display: "flex" };
const noteRowTitleStyle: CSSProperties = { flex: "1 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const noteRowMetaStyle: CSSProperties = { fontSize: 9.5, color: "var(--text-3)", flex: "0 0 auto", fontVariantNumeric: "tabular-nums" };
const noteRowChevStyle: CSSProperties = { color: "var(--text-3)", flex: "0 0 auto", display: "flex" };

const moreRowStyle: CSSProperties = { padding: "9px 16px", fontSize: 10, color: "var(--text-3)" };

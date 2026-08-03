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
 * Task 7 added the tag-view variant (`mode="tags"`): fetches via
 * `notesForTag(selectedTag, { limit: 200 })` instead of `notesForProject`,
 * renders the tag head (spec §5.4: name + vault-wide count, no description
 * editor, no rename, no delete — a tag is body-authoritative, so this panel
 * cannot write one and must not imply it can), and adds a per-row project
 * chip (spec §5.3: text + border, not a coloured pill — colour there would
 * be decoration) via `displayProject()`, the same sentinel guard used
 * everywhere else. The sort instrument, FLIP re-order, and provisional-row
 * filtering are unchanged and apply identically to both modes.
 *
 * Scope boundaries (binding, this task's brief):
 *  - No pager (spec §5.5.1 — Task 9's, and unreachable at <=200 notes).
 *
 * Task 6 (motion pass, spec §8) added: the note-row FLIP re-order and the
 * sort button's icon-swap/cycle-spin. Rows are keyed by `path` (not array
 * index), so the FLIP re-parent below moves the SAME DOM nodes React
 * already reconciles for a keyed list — hover/focus survive the reorder by
 * construction, nothing here re-creates a row. `--menu-travel-ease` /
 * `--hover-ease-out` are this repo's names for the spec's `--ease-travel` /
 * `--ease-settle` (see index.css's "PROJECTS full-window motion pass"
 * comment block) — reused, not reinvented.
 */
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import {
  notesForProject,
  notesForTag,
  renameProject,
  deleteProject,
  moveToTrash,
  updateProjectDescription,
  type ProjectEntry,
  type SearchResult,
} from "../../lib/api";
import {
  displayProject,
  excludeProvisional,
  flipStaggerDelayMs,
  formatAgo,
  metaEpochMs,
  nextSortMode,
  projectTagString,
  sortNotes,
  tagDisplayLabel,
  SORT_MODE_LABEL,
  SORT_MODE_META_VERB,
  type SortMode,
} from "../../lib/projectsView";
import { LOOSE_PROJECT_ID, type RailMode } from "./ProjectsRail";
import {
  PencilIcon, TrashIcon, CheckIcon, CloseIcon, FileIcon, ChevronRightIcon,
  SortNewestIcon, SortOldestIcon, SortEditedIcon, CycleIcon, CopyIcon,
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

/** Note re-order FLIP travel duration (spec §8: "380ms `--ease-travel`").
 *  Mirrored in JS so the invert/play code below and index.css's
 *  `.pp-sort-icon-pop`/icPop timing (260ms, a different row of the same
 *  table) never drift independently of the sort button's icon swap. */
const FLIP_TRAVEL_MS = 380;
/** Cleanup delay after the last possible stagger release (110ms cap) +
 *  travel duration, with slack for the frame the invert itself consumes —
 *  mirrors the board's own 560ms cleanup timeout (mock line 964). */
const FLIP_CLEANUP_MS = 560;

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

interface ProjectsPaneProps {
  /** Which half of the rail toggle is active (spec §5). Governs which head
   *  variant renders and which fetch (`notesForProject`/`notesForTag`)
   *  drives the note list — everything else (sort, FLIP, provisional
   *  filtering) is shared. */
  mode: RailMode;
  /** Registry entries — used to look up the selected project's identity
   *  (name/description) by `selectedId`. Same array ProjectsRail renders,
   *  so the two surfaces agree on what a project IS. */
  projects: ProjectEntry[];
  /** A project's `name`, `LOOSE_PROJECT_ID`, or null before the first list
   *  has loaded. Only consulted when `mode === "projects"`. */
  selectedId: string | null;
  /** The selected tag's RAW value (trailing slash preserved for a namespace
   *  parent — see lib/projectsView.ts's `flattenTagTree`), or null. Only
   *  consulted when `mode === "tags"`. */
  selectedTag: string | null;
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
  /** FR-04/FR-12: fired after a note is successfully moved to trash (the
   *  other half of the fork this component's caller needs — see this file's
   *  header). This pane already drops the row from its own `rows` state so
   *  its OWN count stays correct by construction (spec §5.6); the caller is
   *  only on the hook for refetching whatever ELSE went stale (the rail's
   *  stats-derived tile counts), the same "caller refetches after a
   *  mutation" contract onRenamed/onDeleted above already follow. */
  onNoteDeleted?: (path: string) => void;
}

export default function ProjectsPane({
  mode,
  projects,
  selectedId,
  selectedTag,
  onOpenNote,
  onRenamed,
  onDeleted,
  onDescriptionSaved,
  onNoteDeleted,
}: ProjectsPaneProps) {
  const isTagMode = mode === "tags";
  // Every project-only affordance (description editor, rename, delete, the
  // calm empty-vault head) is gated on mode === "projects" so a stale
  // selectedId left over from before the toggle flipped can never leak a
  // project-only control into the tag view (spec §5.4: "a tag head is not
  // a project head").
  const isLoose = !isTagMode && selectedId === LOOSE_PROJECT_ID;
  const isEmptyVault = !isTagMode && projects.length === 0;
  const selected = !isTagMode && selectedId && !isLoose ? projects.find((p) => p.name === selectedId) ?? null : null;
  const activeKey = isTagMode ? selectedTag : selectedId;
  // The copy-the-tag affordance (FR-21): the exact text a user pastes into a
  // note's body to file it under `selected`. null for loose/tag-mode/no
  // selection — projectTagString() is the one sanctioned builder, same
  // sentinel guard as displayProject() above (lib/projectsView.ts).
  const tagString = selected ? projectTagString(selected.name) : null;

  // ── notes: this pane's OWN fetch (spec §5.5's "the implementation trap") ──
  const [rows, setRows] = useState<SearchResult[]>([]);
  const [notesLoading, setNotesLoading] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>("newest");

  useEffect(() => {
    if (!activeKey) { setRows([]); return; }
    let cancelled = false;
    setNotesLoading(true);
    const fetchRows = isTagMode ? notesForTag(activeKey, { limit: 200 }) : notesForProject(activeKey, { limit: 200 });
    fetchRows
      .then((results) => {
        if (cancelled) return;
        // Rule 1: drop LAN-provisional overlay rows before this pane counts
        // or renders anything — see this file's header comment.
        setRows(excludeProvisional(results));
      })
      .catch(() => { if (!cancelled) setRows([]); })
      .finally(() => { if (!cancelled) setNotesLoading(false); });
    return () => { cancelled = true; };
  }, [isTagMode, activeKey]);

  // Memoized so identity only changes when `rows`/`sortMode` actually do —
  // the FLIP effect below is keyed on this reference, and re-sorting on
  // every unrelated render (e.g. a description keystroke) would fire it for
  // no reason (harmless, since it no-ops without a pending measurement, but
  // pointless work all the same).
  const sortedRows = useMemo(() => sortNotes(rows, sortMode), [rows, sortMode]);
  // Rule 2: the ONLY count this pane ever shows — derived from the rows it
  // just fetched and filtered, never from a sibling source (spec §5.6).
  // ponytail: this pane fetches with limit:200 (spec §5.5.1's server hard
  // clamp), so above 200 notes this count AND the delete-confirm's "Its N
  // notes" both understate the true total. Not a bug — Task 9's pager
  // upgrades both to GET /stats's by_project total when it lands; today's
  // real vault (17 notes) never gets near the ceiling. The tag head's
  // "{noteCount} notes across your vault" wording (below) makes this worse
  // than a silent under-report at >200: "across your vault" asserts a
  // vault-wide total, so past the cap it states a specific falsehood rather
  // than just showing a smaller-than-true number the way the project head's
  // plain "{noteCount} notes" does. Task 9's pager needs to fix this
  // string, not just the fetch.
  const noteCount = rows.length;

  // ── note re-order FLIP (spec §8) ────────────────────────────────────────
  // Measure (First) happens synchronously in handleSortClick, BEFORE
  // setSortMode — reading the still-current DOM via rowRefs. React then
  // re-parents the SAME row nodes into sortedRows' new order (Last); rows
  // are keyed by `path`, so nothing is destroyed/recreated. This effect
  // Inverts each row by the delta it just jumped and Plays the release on
  // the next frame, staggered per lib/projectsView.ts's flipStaggerDelayMs.
  // Skipped entirely under reduced motion: handleSortClick never populates
  // prevTopsRef there, so the guard below exits immediately and the DOM
  // simply sits in the new order (spec §8's last row).
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const prevTopsRef = useRef<Map<string, number> | null>(null);
  const flipTimersRef = useRef<{ raf: number; timeout: ReturnType<typeof setTimeout> } | null>(null);

  function setRowRef(path: string, el: HTMLDivElement | null) {
    if (el) rowRefs.current.set(path, el);
    else rowRefs.current.delete(path);
  }

  useLayoutEffect(() => {
    const prevTops = prevTopsRef.current;
    prevTopsRef.current = null;
    if (!prevTops) return;

    if (flipTimersRef.current) {
      cancelAnimationFrame(flipTimersRef.current.raf);
      clearTimeout(flipTimersRef.current.timeout);
      flipTimersRef.current = null;
    }

    const moved: { el: HTMLDivElement; delay: number }[] = [];
    sortedRows.forEach((row, index) => {
      const el = rowRefs.current.get(row.path);
      const prevTop = prevTops.get(row.path);
      if (!el || prevTop === undefined) return;
      const delta = prevTop - el.getBoundingClientRect().top;
      if (Math.abs(delta) < 0.5) return; // didn't actually move — nothing to invert
      el.style.transition = "none";
      el.style.transform = `translateY(${delta}px)`;
      moved.push({ el, delay: flipStaggerDelayMs(index) });
    });
    if (moved.length === 0) return;

    // Flush the inverted frame before releasing it (the board's own `void
    // box.offsetHeight`, mock line 956) — otherwise the browser coalesces
    // the invert and the release into one paint and nothing animates.
    moved[0].el.getBoundingClientRect();

    const raf = requestAnimationFrame(() => {
      moved.forEach(({ el, delay }) => {
        el.style.transitionDelay = `${delay}ms`;
        el.style.transition = `transform ${FLIP_TRAVEL_MS}ms var(--menu-travel-ease)`;
        el.style.transform = "";
      });
    });
    const timeout = setTimeout(() => {
      moved.forEach(({ el }) => {
        el.style.transition = "";
        el.style.transitionDelay = "";
        el.style.transform = "";
      });
      flipTimersRef.current = null;
    }, FLIP_CLEANUP_MS);
    flipTimersRef.current = { raf, timeout };
  }, [sortedRows]);

  useEffect(() => {
    return () => {
      if (flipTimersRef.current) {
        cancelAnimationFrame(flipTimersRef.current.raf);
        clearTimeout(flipTimersRef.current.timeout);
      }
    };
  }, []);

  // ── head interaction state, reset whenever the selection changes ────────
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [descDraft, setDescDraft] = useState("");
  const pendingSaveRef = useRef<{ name: string; value: string; timer: ReturnType<typeof setTimeout> } | null>(null);
  // FR-04/FR-12: which note row (by path) is showing its inline delete
  // confirm strip, or null. Board (Fork 1, shared across all three create
  // options): "a trailing danger icon appears on row hover/focus... opening
  // an inline confirm strip — no modal, no context menu, no multi-select" —
  // exactly one at a time, by construction (a single path, not a Set).
  const [confirmingDeleteNotePath, setConfirmingDeleteNotePath] = useState<string | null>(null);
  const [noteDeleteBusy, setNoteDeleteBusy] = useState(false);
  // FR-21: transient "copied" feedback for the tag-copy button — icon + label
  // swap to CheckIcon/"Copied" for a beat, never color alone (uiux-pro-max:
  // state must not be color-only). Cleared on selection change below so a
  // stale "Copied" can't survive onto a different project's chip.
  const [tagCopied, setTagCopied] = useState(false);
  const tagCopiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setRenaming(false);
    setConfirmingDelete(false);
    setConfirmingDeleteNotePath(null);
    setMutationError(null);
    setDescDraft(selected?.description ?? "");
    setTagCopied(false);
    if (tagCopiedTimerRef.current) { clearTimeout(tagCopiedTimerRef.current); tagCopiedTimerRef.current = null; }
  }, [selectedId, mode]); // eslint-disable-line react-hooks/exhaustive-deps -- `selected` is derived FROM selectedId/mode; re-running on every `projects` identity change would clobber an in-progress edit on every unrelated refetch. `mode` is included so leaving Projects mid-rename and coming back doesn't resurrect a stale rename/delete-confirm box (spec §5.4: a tag head must never look like a project head).

  useEffect(() => {
    return () => {
      if (tagCopiedTimerRef.current) clearTimeout(tagCopiedTimerRef.current);
    };
  }, []);

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

  function requestDeleteNote(path: string) {
    setMutationError(null);
    setConfirmingDeleteNotePath(path);
  }

  function cancelDeleteNote() {
    setConfirmingDeleteNotePath(null);
  }

  function confirmDeleteNote(path: string) {
    setMutationError(null);
    setNoteDeleteBusy(true);
    moveToTrash(path)
      .then(() => {
        setConfirmingDeleteNotePath(null);
        setNoteDeleteBusy(false);
        // Rule 2 (this file's header): the note count is always rows.length
        // off THIS pane's own fetched rows — dropping the row locally, not
        // waiting on a refetch, is what keeps that count correct the instant
        // the delete succeeds.
        setRows((prev) => prev.filter((r) => r.path !== path));
        onNoteDeleted?.(path);
      })
      .catch((e) => {
        setNoteDeleteBusy(false);
        setMutationError(e instanceof Error ? e.message : "Failed to move note to trash");
      });
  }

  // FR-21: the copy-the-tag affordance. Writes `tag` to the OS clipboard via
  // Tauri's clipboard-manager plugin (already a dependency, see file header
  // import) and nothing else — no api.ts call, no note-body write of any
  // kind. The user still has to paste it into their own editor themselves;
  // this function's only job is putting the exact string on the clipboard.
  function handleCopyTag(tag: string) {
    writeText(tag)
      .then(() => {
        setTagCopied(true);
        if (tagCopiedTimerRef.current) clearTimeout(tagCopiedTimerRef.current);
        tagCopiedTimerRef.current = setTimeout(() => {
          tagCopiedTimerRef.current = null;
          setTagCopied(false);
        }, 1500);
      })
      .catch((e) => setMutationError(e instanceof Error ? e.message : "Failed to copy tag"));
  }

  function handleSortClick() {
    if (!prefersReducedMotion()) {
      const tops = new Map<string, number>();
      rowRefs.current.forEach((el, path) => tops.set(path, el.getBoundingClientRect().top));
      prevTopsRef.current = tops;
    }
    setSortMode((m) => nextSortMode(m));
  }

  if (!activeKey) return <div style={paneStyle} />;

  const SortIcon = SORT_ICON[sortMode];
  const metaVerb = SORT_MODE_META_VERB[sortMode];

  return (
    <div style={paneStyle}>
      {/* Pseudo-class states (:hover/:focus-visible/:focus-within) for the
          `pp-` prefixed classNames below live in index.css's "PROJECTS
          full-window interaction states" block, not a component-local
          <style> tag here: the production CSP (style-src 'self', no
          'unsafe-inline') silently drops an inline <style> tag's rules — the
          FR-03 lesson (see index.css's [data-theme="custom"] comment,
          App.tsx, and lib/customThemeVars.ts for the same rule elsewhere).
          Do not reintroduce a <style> block here. */}

      {isTagMode ? (
        // Spec §5.4: a tag head is NOT a project head. No description
        // editor, no rename, no delete — tags are body-authoritative
        // (recomputed from the body's #hashtags on save, a workspace
        // lock), so this panel cannot write one and must not imply it
        // can. Just the name and its vault-wide count. The explainer
        // paragraph drafted for this head was cut by the user in round 3
        // (spec §5.4) — deliberately not reintroduced here.
        <div style={tagHeadStyle}>
          <span style={tagHeadNameStyle}>
            <span style={tagHeadHashStyle}>#</span>
            {tagDisplayLabel(selectedTag ?? "")}
          </span>
          <span style={tagHeadCountStyle}>{noteCount} notes across your vault</span>
        </div>
      ) : isEmptyVault ? (
        <div style={calmHeadStyle}>
          <h3 style={calmHeadingStyle}>No projects yet</h3>
          <p style={calmParaStyle}>
            {"All "}{noteCount}{" of your notes are loose — a normal, permanent state. A project is a tag: add "}
            <b style={{ color: "var(--text-1)" }}>#project@name</b>
            {" to a note's body and it belongs there. This panel can start the tag; it can't write it into a note for you."}
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
              <span style={descNoteStyle}>New captures are matched against this text — on this device, or a phone, if you use one.</span>
            ) : (
              <span style={{ ...descNoteStyle, color: "var(--yellow)" }}>
                Empty. Nothing to match new captures against yet.
              </span>
            )}
            <span style={savesAsYouTypeStyle}>saves as you type</span>
          </div>
          {/* FR-21: the one legitimate "assign a note to a project"
              affordance — show the exact tag, write nothing (board: Fork 3
              Option A, gui/mocks/2026-08-02-flowreview-decisions.html). A
              copy button, not an insert button: the user still pastes it
              into a note themselves. tagString is null only when selected is
              somehow a loose/invalid name (projectTagString's sentinel
              guard) — defensive, since a real registry entry's name can
              never be "_loose" (isValidProjectName's regex forbids a
              leading "_"), but this component never renders a chip it can't
              back with a real tag. */}
          {tagString && (
            <div style={tagChipRowStyle}>
              <span style={tagChipStyle}>
                <span style={tagChipHashStyle}>#</span>{tagString.slice(1)}
              </span>
              <button
                className={tagCopied ? "pp-tag-copy-btn pp-copied" : "pp-tag-copy-btn"}
                style={tagCopyBtnStyle}
                onClick={() => handleCopyTag(tagString)}
                title={tagCopied ? "Copied" : "Copy tag"}
                aria-label={tagCopied ? "Tag copied" : `Copy tag ${tagString}`}
              >
                {tagCopied ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
              </button>
            </div>
          )}
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
          {/* Sort icon swap + cycle-glyph turn (spec §8): keyed on sortMode
              so each click REMOUNTS these two spans, replaying icPop/
              icCycleSpin (index.css) — the same entrance-only keyed pattern
              as ProjectsRail.tsx's .seg-swap-panel, not a class-toggle +
              forced-reflow hack. */}
          <span key={`icon-${sortMode}`} className="pp-sort-icon-pop" style={sortIconSlotStyle}><SortIcon size={13} /></span>
          <span style={sortLabelStyle}>{SORT_MODE_LABEL[sortMode]}</span>
          <span key={`cycle-${sortMode}`} className="pp-sort-cycle-spin" style={sortCycleSlotStyle}><CycleIcon size={11} /></span>
        </button>
      </div>

      <div style={notesScrollStyle}>
        {notesLoading && rows.length === 0 && <div style={notesEmptyStyle}>Loading…</div>}
        {!notesLoading && sortedRows.length === 0 && <div style={notesEmptyStyle}>No notes here yet.</div>}
        {sortedRows.map((row) => {
          const epochMs = metaEpochMs(row, sortMode);
          const meta = epochMs === null ? "date unknown" : `${metaVerb} ${formatAgo(epochMs)}`;
          const title = row.filename ?? row.path.split(/[\\/]/).pop() ?? row.path;
          const isConfirmingThisRow = confirmingDeleteNotePath === row.path;
          const openEnabled = !isConfirmingThisRow;
          return (
            <Fragment key={row.path}>
              <div
                ref={(el) => setRowRef(row.path, el)}
                className="pp-noterow"
                role="button"
                tabIndex={0}
                style={noteRowStyle}
                onClick={openEnabled ? () => onOpenNote?.(row.path) : undefined}
                onKeyDown={(e) => {
                  if (!openEnabled) return;
                  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpenNote?.(row.path); }
                }}
              >
                <span style={noteRowFileIconStyle}><FileIcon size={12} /></span>
                <span style={noteRowTitleStyle}>{title}</span>
                {/* Spec §5.3: only the tag view renders this — a tag cuts
                    ACROSS projects, so it's the one view that has to answer
                    "where does this note actually live". Text + border, not a
                    coloured pill (colour there would be decoration).
                    displayProject() is the one sanctioned `_loose` guard
                    (spec §2.2) — never reimplemented inline. Trap 3
                    (task brief): this row's `project` always comes from the
                    FTS tier's captures.db `project` column (s127-fixed,
                    resolved against .projects.toml), never the semantic
                    tier's pre-s127 directory-derived one — notesForTag/
                    notesForProject (api.ts) both call searchCaptures() with
                    an EMPTY free-text query (just a project filter or a
                    stripped `tag:` token), and vault_admin.search_captures
                    only runs the semantic branch when `free_q.strip()` is
                    truthy, so a semantic-tier row (tier: "semantic") can
                    never appear in a row this pane fetches — verified at
                    source, not assumed. */}
                {isTagMode && (
                  <span style={row.project && row.project !== LOOSE_PROJECT_ID ? pjChipStyle : pjChipLooseStyle}>
                    {displayProject(row.project)}
                  </span>
                )}
                <span style={noteRowMetaStyle}>{meta}</span>
                {/* FR-04/FR-12: the full window's only way to delete a note
                    (board: hover-icon on the row, matching the danger-icon
                    language the pane head already teaches for deleting a
                    PROJECT, rather than a second/different affordance).
                    Hidden until row hover/focus via the .pp-note-del CSS
                    above — always in the DOM and tab-reachable, never
                    display:none, so keyboard-only use isn't penalized. */}
                <button
                  className="pp-note-del"
                  style={noteRowDelBtnStyle}
                  onClick={(e) => { e.stopPropagation(); requestDeleteNote(row.path); }}
                  title="Move to trash"
                  aria-label={`Move "${title}" to trash`}
                >
                  <TrashIcon size={12} />
                </button>
                <span style={noteRowChevStyle}><ChevronRightIcon size={11} /></span>
              </div>
              {isConfirmingThisRow && (
                <div style={noteConfirmStripStyle}>
                  <span style={confirmTextStyle}>
                    {"Move "}
                    <b style={{ color: "var(--text-1)" }}>{title}</b>
                    {" to Trash? It stays recoverable for 30 days."}
                  </span>
                  <button className="pp-ghost" style={ghostBtnStyle} onClick={cancelDeleteNote} disabled={noteDeleteBusy}>
                    Cancel
                  </button>
                  <button
                    className="pp-ghost"
                    style={ghostDangerBtnStyle}
                    onClick={() => confirmDeleteNote(row.path)}
                    disabled={noteDeleteBusy}
                  >
                    Move to Trash
                  </button>
                </div>
              )}
            </Fragment>
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

// Tag head (spec §5.4) — deliberately NOT a project head: no rename/delete
// icon row, no description editor. Padding matches looseHeadStyle, the
// other head with no editor under it (board mock lines 839-843).
const tagHeadStyle: CSSProperties = {
  flex: "0 0 auto", borderBottom: "1px solid var(--border)", padding: "14px 16px",
  display: "flex", alignItems: "baseline", gap: 9,
};
const tagHeadNameStyle: CSSProperties = { fontSize: 15, fontWeight: 600, color: "var(--text-1)" };
const tagHeadHashStyle: CSSProperties = { color: "var(--text-3)" };
const tagHeadCountStyle: CSSProperties = { fontSize: 10, color: "var(--text-3)" };

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
// Named descNoteStyle, not qmeterStyle: the quality GAUGE this line replaced
// was deleted in round 3 (spec §4.6) — it scored a character count as three
// bands of match quality, a measurement this product cannot make. What
// remains is one honest line stating the field's purpose (or, in yellow,
// that it's empty), not a meter of anything.
const descNoteStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 7, fontSize: 9.5, color: "var(--text-3)" };
const savesAsYouTypeStyle: CSSProperties = { fontSize: 9, color: "var(--text-3)", flex: "0 0 auto" };

// FR-21 copy-the-tag row (board: Fork 3 Option A's "tag-chip-row"). Sits on
// --surface so its own --ctl-face-faced copy button (below) never touches
// --surface-2 directly — the known --ctl-face === --surface-2 ceiling
// (index.css) only bites when a control's face sits ON --surface-2; here
// the ambient this row inherits is --bg (ProjectsView's containerStyle sets
// no background of its own), and the row itself repaints to --surface,
// giving the --ctl-face button a surface two steps away from its own face
// color in both themes.
const tagChipRowStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, marginTop: 8,
  padding: "8px 10px", border: "1px solid var(--border)", background: "var(--surface)", maxWidth: 420,
};
const tagChipStyle: CSSProperties = {
  fontSize: 11, color: "var(--text-1)", background: "var(--bg)", border: "1px solid var(--border)",
  padding: "4px 8px", flex: "1 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
};
const tagChipHashStyle: CSSProperties = { color: "var(--text-3)" };
const tagCopyBtnStyle: CSSProperties = {
  width: 26, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
  background: "var(--ctl-face)", border: "1px solid var(--border)", color: "var(--text-1)",
  cursor: "pointer", padding: 0, flex: "0 0 auto",
};

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
// FR-17 fix: was `minWidth: 96` — a fixed floor that never shrank, so at
// the 480px window floor (tauri.conf.json's real minimum, not a phantom —
// the rail alone is a fixed 260px, leaving this pane roughly 220px) the
// sort button was forced 96px+ wide regardless of how little room was
// left, pushing its right edge past the viewport. "Newest"/"Oldest"/
// "Recently edited" are each a single unbreakable word, so their own
// min-content width already prevents mid-word wrapping without a manual
// floor — removing it lets the button (and the note-row titles squeezed
// beside it) shrink to what the 480px floor actually has to offer instead
// of forcing an overflow. Needs a live CDP re-measure at 480px: expect the
// sort button's right edge to land at/near the pane's own right edge
// (no longer past `innerWidth`), and note-row titles to reclaim some of
// the width the button was hoarding (still legitimately ellipsis-truncated
// at this width — that's the flex:1/minWidth:0/textOverflow:ellipsis on
// noteRowTitleStyle working as designed, not a bug).
const sortLabelStyle: CSSProperties = { textAlign: "left" };
const sortCycleSlotStyle: CSSProperties = { display: "flex", color: "var(--text-2)" };

const notesScrollStyle: CSSProperties = { flex: "1 1 auto", minHeight: 0, overflowY: "auto", scrollbarGutter: "stable" };
const notesEmptyStyle: CSSProperties = { padding: 14, fontSize: 12, color: "var(--text-3)" };

const noteRowStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderBottom: "1px solid var(--border-2)",
  fontSize: 11.5, color: "var(--text-2)", cursor: "pointer", background: "var(--surface)",
};
const noteRowFileIconStyle: CSSProperties = { color: "var(--text-3)", flex: "0 0 auto", display: "flex" };
const noteRowTitleStyle: CSSProperties = { flex: "1 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
// Per-row project chip, tag view only (spec §5.3): text + border, never a
// coloured pill (colour there would be decoration). Dashed border for
// loose, same visual cue the loose tile/head already use.
const pjChipBase: CSSProperties = {
  fontSize: 9, color: "var(--text-3)", flex: "0 0 auto", border: "1px solid var(--border)",
  padding: "1px 5px", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
};
const pjChipStyle: CSSProperties = pjChipBase;
const pjChipLooseStyle: CSSProperties = { ...pjChipBase, borderStyle: "dashed" };
const noteRowMetaStyle: CSSProperties = { fontSize: 9.5, color: "var(--text-3)", flex: "0 0 auto", fontVariantNumeric: "tabular-nums" };
const noteRowChevStyle: CSSProperties = { color: "var(--text-3)", flex: "0 0 auto", display: "flex" };
const noteRowDelBtnStyle: CSSProperties = {
  width: 22, height: 22, display: "flex", alignItems: "center", justifyContent: "center", flex: "0 0 auto",
  color: "var(--text-3)", background: "none", border: "1px solid transparent", cursor: "pointer", padding: 0,
};
// Same visual language as confirmStripStyle (project-delete, above) — one
// danger-confirm pattern reused, not a second one invented for notes — but
// scoped to sit BETWEEN two note rows (board: the strip replaces the row
// immediately below the one being deleted) rather than the pane-wide band
// confirmStripStyle occupies under the head.
const noteConfirmStripStyle: CSSProperties = {
  ...confirmStripStyle, borderBottom: "1px solid var(--border-2)", padding: "8px 16px",
};

const moreRowStyle: CSSProperties = { padding: "9px 16px", fontSize: 10, color: "var(--text-3)" };

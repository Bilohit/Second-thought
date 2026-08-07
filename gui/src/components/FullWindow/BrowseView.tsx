/**
 * BrowseView.tsx — P3-C1: BROWSE's real interior (sectioned search + paged
 * 4x2 project tiles + tag list + the STARS placeholder mount). Board
 * (source of truth): SecondThoughtV2.html's `[data-scr="browse"]` block
 * (:969-1005 markup, :1618-1759 behavior). Desktop only — the mock's phone
 * variant (`.phone .proj-page`/`.phone .proj-card`, 2-col non-square tiles,
 * :589-590) is a different surface, not this one.
 *
 * P3-C1 builds items 1-4 of BROWSE's four pieces (sectioned search, paged
 * project tiles, tag list, LIST/STARS toggle) — the STARS constellation
 * itself is stubbed (BrowseStarsView, `// P3-C2:`); the toggle and its
 * `mode` prop are owned by FullWindow.tsx (titlebar, like the CHAT
 * Search/Chat toggle already is), not by this component.
 *
 * Deliberately renders NO loose/unfiled tile in the project grid — the
 * mock's own `PROJECTS()` (SecondThoughtV2.html:1408-1412) only ever lists
 * notes carrying a real `#project@<name>` tag; loose-bucket browsing stays
 * a ProjectsRail/ProjectsPane-only concept, out of BROWSE's spec.
 *
 * Data-fetch shape mirrors ProjectsView.tsx (projects+stats+tags, refetched
 * on every `visible` transition to true) rather than reusing ProjectsView
 * itself — ProjectsView is built around ProjectsRail's persistent-selection
 * two-column layout (spec docs/superpowers/specs/2026-08-02-projects-s3-
 * fullwindow-design.md §3-5), a different screen than the mock's
 * single-column paged-grid-plus-search BROWSE. See FullWindow.tsx's P3-C
 * comment for which components this leaves unmounted.
 *
 * P3-C3 adds project management (rename / set description / delete, plus
 * the FR-23 Option A tidy-preview strip and the FR-23 Option C folder-import
 * offer/checklist shared via FolderImportPanel.tsx) into the project
 * drill-in via a 3-dot overflow menu, mirroring NoteEditor.tsx's "More" menu
 * chrome exactly (same `menuDropStyle`/danger-last convention, retyped into
 * BrowseView's own `br-` class idiom rather than NoteEditor's `ne-`). This
 * CLOSES FR-36: the single `refetchProjects` function above (still the same
 * one function `visible` uses) is now also called directly from
 * `handleRenamed`/`handleDeleted`/`useFolderImport`'s `onApplied` the instant
 * each mutation's own API call resolves — no more navigate-away-and-back
 * round trip to see an updated tile.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  listProjects, getStats, getTagTree, searchCaptures, notesForProject, notesForTag,
  createProject, renameProject, updateProjectDescription, deleteProject, getTidyPreview, applyTidy,
  listHandMadeFolders,
  type ProjectEntry, type SearchResult, type TidyMove, type HandMadeFolder,
} from "../../lib/api";
import {
  filterMachineTags, flattenTagTree, tagDisplayLabel, excludeProvisional, formatAgo,
  describeTidyMove, isValidProjectName, INVALID_NAME_MESSAGE,
  type FlatTag,
} from "../../lib/projectsView";
import { sectionSearch, isSearchActive, type SearchableProject } from "../../lib/browseSearch";
import { chunkProjects, browsePagerInfo, PROJECTS_PER_PAGE } from "../../lib/browsePager";
import { useFolderImport, FolderImportOffer, FolderImportChecklist } from "../FolderImportPanel";
import {
  SearchIcon, FileIcon, ChevronLeftIcon, ChevronRightIcon,
  MoreIcon, PencilIcon, ListIcon, TrashIcon, CheckIcon, CloseIcon, PlusIcon,
} from "../PillMenu/icons";
import { INPUT_STYLE, focusRing, blurRing } from "../ui/styles";
import { micro, label as fsLabel, body as fsBody, read as fsRead, lead as fsLead } from "../../lib/type";
import BrowseStarsView from "./BrowseStarsView";

interface Props {
  visible: boolean;
  /** Owned by FullWindow's titlebar toggle (mirrors `browseSection`'s own
   *  lift-to-parent shape) — this component only renders off it. */
  mode: "list" | "stars";
  onOpenNote?: (path: string) => void;
}

type SubKind = "project" | "tag";
interface SubSelection { kind: SubKind; value: string; }

/** LookPanel.tsx's identical debounced-FTS-query pattern (its own
 *  `useEffect`, 150ms/limit 30) — reused, not reinvented, for the same
 *  reason: GET /search is real network I/O, not a per-keystroke call. */
const SEARCH_DEBOUNCE_MS = 150;
const SEARCH_LIMIT = 30;
/** P3-C3: the description editor's "saves as you type" debounce —
 *  ProjectsPane.tsx's identical constant (:120), reused verbatim. */
const DESC_SAVE_DEBOUNCE_MS = 500;

export default function BrowseView({ visible, mode, onOpenNote }: Props) {
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [projectCounts, setProjectCounts] = useState<Record<string, number>>({});
  const [tags, setTags] = useState<FlatTag[]>([]);
  // FR-34 (s146 #4): read-only census of the user's own hand-made vault
  // folders, surfaced under TAGS so the desktop panel mirrors the phone's.
  // See HandFolderRow below for the render.
  const [handFolders, setHandFolders] = useState<HandMadeFolder[]>([]);
  const [page, setPage] = useState(1);

  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [sub, setSub] = useState<SubSelection | null>(null);
  const [subRows, setSubRows] = useState<SearchResult[]>([]);
  const [subLoading, setSubLoading] = useState(false);

  // ── projects + tags, refetched on every `visible` transition to true
  // (ProjectsView.tsx's own pattern, adapted) AND reused as-is (P3-C3/FR-36)
  // by the drill-in's own rename/delete/folder-import handlers below — ONE
  // refetch function, two callers, per this task's brief ("reuse that
  // refetch function, do not add a second one"). A stale tile list after a
  // rename, delete, or folder-import now recovers WITHOUT the navigate-away-
  // and-back round trip the file header used to describe: each mutation
  // handler calls `refetchProjects()` directly the instant its own API call
  // resolves. ──
  const refetchProjects = useCallback(() => {
    listProjects().then(({ projects: rows }) => setProjects(rows)).catch(() => setProjects([]));
    getStats().then((stats) => {
      const counts: Record<string, number> = {};
      for (const row of stats.by_project) counts[row.project] = row.count;
      setProjectCounts(counts);
    }).catch(() => setProjectCounts({}));
    getTagTree().then((r) => setTags(flattenTagTree(filterMachineTags(r.tags)))).catch(() => setTags([]));
    // FR-34: failure is silent, never a visible error state, never a blocking
    // dependency (data-model-and-contracts.md §2.1) — a missing/malformed/
    // rejected fetch just means zero folder rows, same as an empty vault.
    listHandMadeFolders()
      .then((r) => setHandFolders(Array.isArray(r.folders) ? r.folders : []))
      .catch(() => setHandFolders([]));
  }, []);

  useEffect(() => {
    if (!visible) return;
    refetchProjects();
  }, [visible, refetchProjects]);

  useEffect(() => {
    if (!visible || mode !== "list") return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = query.trim();
    if (!q) { setSearchResults([]); return; }
    debounceRef.current = setTimeout(() => {
      searchCaptures(q, { limit: SEARCH_LIMIT }).then((r) => setSearchResults(r.results)).catch(() => setSearchResults([]));
    }, SEARCH_DEBOUNCE_MS);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, visible, mode]);

  // ── sub-page notes (project or tag drill-in). excludeProvisional matches
  // ProjectsPane.tsx's identical fetch — a LAN-provisional row has no real
  // file behind it and can never be opened (see lib/projectsView.ts's
  // comment on PROVISIONAL_PATH_PREFIX). ──
  useEffect(() => {
    if (!sub) { setSubRows([]); return; }
    let cancelled = false;
    setSubLoading(true);
    const fetcher = sub.kind === "project" ? notesForProject(sub.value) : notesForTag(sub.value);
    fetcher
      .then((rows) => { if (!cancelled) setSubRows(excludeProvisional(rows)); })
      .catch(() => { if (!cancelled) setSubRows([]); })
      .finally(() => { if (!cancelled) setSubLoading(false); });
    return () => { cancelled = true; };
  }, [sub]);

  // Mock's openSubD (SecondThoughtV2.html:1650-1658): landing on a sub-page
  // always clears any live query, whether the click came from a search hit
  // or a home-page tile/tag row (the latter already has an empty query, so
  // this is a no-op there).
  const openSub = useCallback((kind: SubKind, value: string) => {
    setQuery("");
    setSub({ kind, value });
  }, []);

  // ── P3-C3: project management, reached via the drill-in header's 3-dot
  // menu (mirrors NoteEditor.tsx's "More" menu chrome exactly — same
  // menuDropStyle/danger-last convention, retyped into this file's own `br-`
  // class idiom rather than NoteEditor's `ne-`). Only meaningful when
  // `sub.kind === "project"` — the tag drill-in never renders the kebab at
  // all (a tag is body-authoritative, ProjectsPane.tsx's identical
  // mode==="tags" gate). All hooks below run unconditionally, above the
  // `if (!visible)` early return, same rule NoteEditor.tsx's own header-
  // controls block documents. ──
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [descOpen, setDescOpen] = useState(false);
  const [descDraft, setDescDraft] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  // Set the instant `deleteProject` resolves; survives `sub` staying pointed
  // at a name no longer in the registry so the tidy-preview strip below (see
  // `tidyPreview`) still has somewhere to render — ProjectsPane.tsx's own
  // "selection falls to loose, tidyPreview is NOT scoped to it" pattern,
  // adapted (this drill-in has no loose bucket to fall back to, see file
  // header, so it shows a "deleted" head instead).
  const [deletedName, setDeletedName] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  // FR-23 Option A: same tidy-preview strip as ProjectsPane.tsx (:401),
  // deliberately NOT reset by the `deletedName` transition above — see that
  // file's identical comment on why.
  const [tidyPreview, setTidyPreview] = useState<TidyMove[] | null>(null);
  const [tidyBusy, setTidyBusy] = useState(false);
  const pendingSaveRef = useRef<{ name: string; value: string; timer: ReturnType<typeof setTimeout> } | null>(null);

  // FR-42: the PROJECTS section-head "+ NEW" affordance — list-level, not
  // drill-in-local, so it lives beside (not inside) the P3-C3 state block
  // above even though it reuses that block's inline-edit idiom (renameValue/
  // renameInputStyle/subIconBtnStyle's confirm+cancel pair).
  const [creatingProject, setCreatingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");

  const selectedProject = sub?.kind === "project" ? projects.find((p) => p.name === sub.value) ?? null : null;

  // Reset every piece of drill-in-local UI state whenever the drill-in's own
  // identity changes (a fresh project/tag selection, or leaving it
  // entirely) — ProjectsPane.tsx's identical reset-on-selection-change effect.
  useEffect(() => {
    setMenuOpen(false);
    setRenaming(false);
    setDescOpen(false);
    setConfirmingDelete(false);
    setDeletedName(null);
    setMutationError(null);
    setTidyPreview(null);
    setDescDraft(selectedProject?.description ?? "");
    setCreatingProject(false);
    setNewProjectName("");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `selectedProject` is derived FROM `sub`
    // (+ `projects`); re-running on every unrelated `projects` refetch would clobber an in-progress
    // rename/description edit. ProjectsPane.tsx's identical guard on its own `[selectedId, mode]`.
  }, [sub]);

  // Flush an in-flight debounced description save immediately when the
  // drill-in's identity moves on, rather than letting a save meant for the
  // PREVIOUS project land silently seconds later — ProjectsPane.tsx's
  // identical flush-on-selection-change effect.
  useEffect(() => {
    return () => {
      const pending = pendingSaveRef.current;
      if (!pending) return;
      clearTimeout(pending.timer);
      pendingSaveRef.current = null;
      updateProjectDescription(pending.name, pending.value).catch(() => { /* best-effort flush */ });
    };
  }, [sub]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = () => setMenuOpen(false);
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [menuOpen]);

  // FR-32/FR-23 Option C: the folder-import offer/checklist, shared with
  // ProjectsPane.tsx/VaultManager.tsx via FolderImportPanel.tsx — same hook,
  // same two presentational components, never a third copy. `onApplied` is
  // this task's other FR-36 wire: a successful import re-runs the SAME
  // `refetchProjects()` the `visible` effect above uses, so a project a
  // folder-import just created/tagged shows up in the tile grid with no
  // navigation round-trip.
  const folderImport = useFolderImport({
    onApplied: () => { refetchProjects(); checkTidyPreview(); },
    onError: setMutationError,
  });

  // FR-23 Option A: renaming/deleting a project no longer silently re-paths
  // files — the registry action happens right away; this just checks
  // whether anything is now waiting to physically move, and shows it.
  // ProjectsPane.tsx's identical `checkTidyPreview` (:484-492).
  function checkTidyPreview() {
    getTidyPreview()
      .then((preview) => setTidyPreview(preview.count > 0 ? preview.moves : null))
      .catch(() => { /* best-effort; see comment above */ });
    folderImport.probe();
  }

  function declineTidy() {
    setTidyPreview(null);
    folderImport.close();
  }

  function confirmTidy() {
    setTidyBusy(true);
    applyTidy()
      .then(() => { setTidyBusy(false); setTidyPreview(null); })
      .catch((e) => {
        setTidyBusy(false);
        setMutationError(e instanceof Error ? e.message : "Failed to move files");
      });
  }

  function startRename() {
    if (!selectedProject) return;
    setMutationError(null);
    setRenameValue(selectedProject.name);
    setRenaming(true);
  }

  function confirmRename() {
    if (!selectedProject) return;
    const newName = renameValue.trim();
    if (!newName || newName === selectedProject.name) { setRenaming(false); return; }
    const oldName = selectedProject.name;
    setMutationError(null);
    renameProject(oldName, newName)
      .then(() => {
        setRenaming(false);
        // FR-36: the tile grid + this drill-in's own title both go stale on
        // a rename — refetch the SAME function `visible` uses, and follow
        // the selection to its new name so the drill-in doesn't silently
        // keep pointing at a name that no longer exists.
        setSub({ kind: "project", value: newName });
        refetchProjects();
        checkTidyPreview();
      })
      .catch((e) => setMutationError(e instanceof Error ? e.message : "Failed to rename"));
  }

  function handleDescriptionInput(value: string) {
    setDescDraft(value);
    if (!selectedProject) return; // no editor is rendered without a selection, so this is unreachable there
    if (pendingSaveRef.current) clearTimeout(pendingSaveRef.current.timer);
    const name = selectedProject.name;
    const timer = setTimeout(() => {
      pendingSaveRef.current = null;
      updateProjectDescription(name, value)
        .then(() => {
          // Patch the local registry copy so a re-open of the "Set description"
          // editor (or another rename) sees the saved text without a full
          // refetch on every keystroke — ProjectsPane.tsx's `onDescriptionSaved`
          // callback did this for its own caller; this component IS that caller.
          setProjects((prev) => prev.map((p) => (p.name === name ? { ...p, description: value } : p)));
        })
        .catch((e) => setMutationError(e instanceof Error ? e.message : "Failed to save description"));
    }, DESC_SAVE_DEBOUNCE_MS);
    pendingSaveRef.current = { name, value, timer };
  }

  function confirmDelete() {
    if (!selectedProject) return;
    const name = selectedProject.name;
    setMutationError(null);
    deleteProject(name)
      .then(() => {
        setConfirmingDelete(false);
        setDeletedName(name);
        // FR-36: the tile grid must lose this tile immediately, no
        // navigate-away-and-back — same refetch, called directly.
        refetchProjects();
        checkTidyPreview();
      })
      .catch((e) => setMutationError(e instanceof Error ? e.message : "Failed to delete"));
  }

  // FR-42: the PROJECTS section-head "+ NEW" affordance (mock option B,
  // 2026-08-07-s157-fr42-new-project-placement.html) — same inline
  // confirm/cancel idiom as `startRename`/`confirmRename` above, reusing
  // this component's own `refetchProjects` (FR-36's one function, now a
  // fourth caller) so the new tile appears without a navigate-away-and-back.
  function startCreateProject() {
    setMutationError(null);
    setNewProjectName("");
    setCreatingProject(true);
  }

  function cancelCreateProject() {
    setCreatingProject(false);
  }

  function confirmCreateProject() {
    const name = newProjectName.trim();
    if (!name) { setCreatingProject(false); return; }
    // Contract §1.3/§13.1: "a writer MUST reject an invalid name rather than
    // write it." Client-side pre-check only — isValidProjectName mirrors the
    // server's own regex (see its doc comment); the server remains the
    // authority for anything that somehow slips past this.
    if (!isValidProjectName(name)) {
      setMutationError(INVALID_NAME_MESSAGE);
      return;
    }
    setMutationError(null);
    createProject(name)
      .then(() => {
        setCreatingProject(false);
        setNewProjectName("");
        refetchProjects();
      })
      .catch((e) => setMutationError(e instanceof Error ? e.message : "Failed to create project"));
  }

  if (!visible) return null;

  if (mode === "stars") {
    return <BrowseStarsView visible onOpenNote={onOpenNote} />;
  }

  const searchableProjects: SearchableProject[] = projects.map((p) => ({ name: p.name, count: projectCounts[p.name] ?? 0 }));
  const searching = isSearchActive(query);
  const sectioned = sectionSearch(query, { noteResults: searchResults, projects: searchableProjects, tags });

  const pages = chunkProjects(projects, PROJECTS_PER_PAGE);
  const pager = browsePagerInfo(projects.length, page, PROJECTS_PER_PAGE);
  const pageItems = pages[pager.page - 1] ?? [];

  return (
    <div style={rootStyle}>
      <div style={searchRowStyle}>
        <span style={searchIconStyle}><SearchIcon size={13} /></span>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={focusRing}
          onBlur={blurRing}
          placeholder="search notes, tags, projects"
          aria-label="search vault"
          style={searchInputStyle}
        />
      </div>

      {searching ? (
        <div style={scrollStyle}>
          <div style={sectionHeadStyle}>NOTES</div>
          {sectioned.noteHits.length > 0
            ? sectioned.noteHits.map((row) => (
              <NoteRow key={row.path} row={row} onClick={() => { setQuery(""); onOpenNote?.(row.path); }} />
            ))
            : <div style={emptyStyle}>no notes match</div>}

          <div style={sectionHeadStyle}>PROJECTS</div>
          {sectioned.projectHits.length > 0
            ? sectioned.projectHits.map((p) => (
              <TagRow key={p.name} label={p.name} count={p.count} onClick={() => openSub("project", p.name)} />
            ))
            : <div style={emptyStyle}>no projects match</div>}

          <div style={sectionHeadStyle}>TAGS</div>
          {sectioned.tagHits.length > 0
            ? sectioned.tagHits.map((t) => (
              <TagRow key={t.tag} label={`#${tagDisplayLabel(t.tag)}`} count={t.count} onClick={() => openSub("tag", t.tag)} />
            ))
            : <div style={emptyStyle}>no tags match</div>}
        </div>
      ) : sub ? (
        <div style={subWrapStyle}>
          <div style={subHeadStyle}>
            <button className="br-subback" style={subBackBtnStyle} onClick={() => setSub(null)} aria-label="back to browse">
              <ChevronLeftIcon size={15} />
            </button>
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
                <button className="br-kebab" style={subIconBtnStyle} onClick={confirmRename} title="Confirm rename" aria-label="Confirm rename">
                  <CheckIcon size={13} />
                </button>
                <button className="br-kebab" style={subIconBtnStyle} onClick={() => setRenaming(false)} title="Cancel rename" aria-label="Cancel rename">
                  <CloseIcon size={13} />
                </button>
              </>
            ) : (
              <h4 style={subTitleStyle}>
                {sub.kind === "tag"
                  ? `#${tagDisplayLabel(sub.value)}`
                  : deletedName ? `${deletedName} — deleted` : sub.value}
              </h4>
            )}
            <span style={subCountStyle}>{subRows.length} {subRows.length === 1 ? "note" : "notes"}</span>
            {/* P3-C3: the 3-dot overflow menu — project drill-in only (a tag
                head is not a project head, ProjectsPane.tsx's identical
                mode==="tags" gate), hidden mid-rename and once the project
                is gone. Mirrors NoteEditor.tsx's "More" menu chrome exactly
                (:780-793): same menuDropStyle geometry/shadow, same
                neutral-actions-then-danger-last ordering. */}
            {sub.kind === "project" && !renaming && !deletedName && (
              <div style={{ position: "relative" }}>
                <button
                  className="br-kebab" style={subIconBtnStyle}
                  aria-label="Project actions" aria-haspopup="true" aria-expanded={menuOpen}
                  onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
                >
                  <MoreIcon size={15} />
                </button>
                <div style={menuDropStyle(menuOpen)} role="menu" aria-hidden={!menuOpen}>
                  <button
                    className="br-menurow" style={menuRowStyle} role="menuitem" tabIndex={menuOpen ? 0 : -1}
                    onClick={() => { setMenuOpen(false); startRename(); }}
                  >
                    <PencilIcon size={13} />Rename
                  </button>
                  <button
                    className="br-menurow" style={menuRowStyle} role="menuitem" tabIndex={menuOpen ? 0 : -1}
                    onClick={() => { setMenuOpen(false); setDescOpen((v) => !v); }}
                  >
                    <ListIcon size={13} />Set description
                  </button>
                  <button
                    className="br-menurow" style={{ ...menuRowStyle, color: "var(--red)" }} role="menuitem" tabIndex={menuOpen ? 0 : -1}
                    onClick={() => { setMenuOpen(false); setConfirmingDelete(true); }}
                  >
                    <TrashIcon size={13} />Delete project
                  </button>
                </div>
              </div>
            )}
          </div>

          {mutationError && <div style={mutationErrorStyle}>{mutationError}</div>}

          {/* Delete requires an explicit confirm — the menu action above only
              opens this strip, it never deletes on its own. Copy is verbatim
              from ProjectsPane.tsx (:731-736), the FR-23 Option A wording this
              task's brief requires byte-for-byte. */}
          {confirmingDelete && selectedProject && (
            <div style={confirmStripStyle}>
              <span style={confirmTextStyle}>
                {"Delete "}
                <b style={{ color: "var(--text-1)" }}>{selectedProject.name}</b>
                {`? Its ${subRows.length} notes become loose. None is deleted, trashed or edited, and none moves `}
                {"on disk yet — you'll see a separate confirmation before anything is re-filed."}
              </span>
              <button className="pp-ghost" style={ghostBtnStyle} onClick={() => setConfirmingDelete(false)}>
                Cancel
              </button>
              <button className="pp-ghost" style={ghostDangerBtnStyle} onClick={confirmDelete}>
                Delete project only
              </button>
            </div>
          )}

          {/* The description editor — ProjectsPane.tsx's identical "saves as
              you type" textarea (:679-687), gated behind the menu's "Set
              description" instead of always-on, per this task's brief. */}
          {descOpen && selectedProject && !deletedName && (
            <div style={descWrapStyle}>
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
            </div>
          )}

          {/* FR-23 Option A: the project-tidy confirm/preview strip — appears
              only after a rename or delete actually leaves something to
              physically move. Grayscale, not accent-coloured: moving a file
              to match its own tag is safe housekeeping, not a destructive
              action. Copy verbatim from ProjectsPane.tsx (:754-793). */}
          {tidyPreview && tidyPreview.length > 0 && (
            <div style={tidyStripStyle}>
              <span style={confirmTextStyle}>
                <b style={{ color: "var(--text-1)" }}>{tidyPreview.length}</b>
                {tidyPreview.length === 1 ? " note" : " notes"}
                {" — possibly from other projects too — will move into the folder "}
                {"its own tag already points to. No project changes, no body is edited; only where "}
                {tidyPreview.length === 1 ? "the file" : "the files"}
                {" sit."}
              </span>
              <div style={tidyListStyle}>
                {tidyPreview.map((move) => {
                  const d = describeTidyMove(move);
                  return (
                    <div key={`${move.from}->${move.to}`} style={tidyRowStyle}>
                      <span style={tidyRowFileStyle}>{d.file}</span>
                      <span style={tidyRowPathStyle}>{d.from} <ChevronRightIcon size={9} /> {d.to}</span>
                    </div>
                  );
                })}
              </div>
              <div style={tidyActionsRowStyle}>
                <button className="pp-ghost" style={ghostBtnStyle} onClick={declineTidy} disabled={tidyBusy}>
                  Not now
                </button>
                <FolderImportOffer
                  offer={folderImport.offer}
                  checklistOpen={folderImport.rows !== null}
                  busy={tidyBusy || folderImport.busy}
                  onOpen={folderImport.open}
                  variant="strip"
                />
                <button className="pp-ghost" style={tidyPrimaryBtnStyle} onClick={confirmTidy} disabled={tidyBusy}>
                  {tidyBusy ? "Moving…" : `Move ${tidyPreview.length === 1 ? "file" : "files"}`}
                </button>
              </div>
            </div>
          )}

          {/* FR-23 Option C / FR-32: the per-folder import checklist, shared
              with ProjectsPane.tsx/VaultManager.tsx via FolderImportPanel.tsx. */}
          {folderImport.rows && (
            <FolderImportChecklist
              rows={folderImport.rows}
              busy={folderImport.busy}
              onToggle={folderImport.toggleRow}
              onRename={folderImport.renameRow}
              onCancel={folderImport.close}
              onApply={folderImport.apply}
              variant="strip"
            />
          )}

          <div style={scrollStyle}>
            {deletedName ? (
              <div style={emptyStyle}>Project deleted — its notes are now loose.</div>
            ) : (
              <>
                {subLoading && subRows.length === 0 && <div style={emptyStyle}>Loading…</div>}
                {!subLoading && subRows.length === 0 && <div style={emptyStyle}>No notes here yet.</div>}
                {subRows.map((row) => <NoteRow key={row.path} row={row} onClick={() => onOpenNote?.(row.path)} />)}
              </>
            )}
          </div>
        </div>
      ) : (
        <div style={scrollStyle}>
          <div style={sectionHeadStyle}>
            PROJECTS
            {creatingProject ? (
              <>
                <input
                  autoFocus
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") confirmCreateProject();
                    if (e.key === "Escape") cancelCreateProject();
                  }}
                  placeholder="project name"
                  aria-label="New project name"
                  style={renameInputStyle}
                />
                <button className="br-kebab" style={subIconBtnStyle} onClick={confirmCreateProject} title="Confirm create" aria-label="Confirm create project">
                  <CheckIcon size={13} />
                </button>
                <button className="br-kebab" style={subIconBtnStyle} onClick={cancelCreateProject} title="Cancel create" aria-label="Cancel create project">
                  <CloseIcon size={13} />
                </button>
              </>
            ) : (
              <button className="br-kebab" style={headBtnStyle} onClick={startCreateProject} aria-label="New project">
                <PlusIcon size={12} />NEW
              </button>
            )}
            <span style={dotsWrapStyle}>
              <button
                className="br-parrow" style={parrowStyle} disabled={!pager.canPrev}
                onClick={() => setPage((p) => p - 1)} aria-label="previous projects page"
              >
                <ChevronLeftIcon size={11} />
              </button>
              <span style={{ display: "flex", gap: 6 }}>
                {pages.map((_, i) => (
                  <button
                    key={i} className="br-pdot" aria-label={`projects page ${i + 1}`}
                    onClick={() => setPage(i + 1)}
                    style={i === pager.page - 1 ? pdotOnStyle : pdotStyle}
                  />
                ))}
              </span>
              <button
                className="br-parrow" style={parrowStyle} disabled={!pager.canNext}
                onClick={() => setPage((p) => p + 1)} aria-label="next projects page"
              >
                <ChevronRightIcon size={11} />
              </button>
            </span>
          </div>
          {mutationError && <div style={mutationErrorStyle}>{mutationError}</div>}
          {pageItems.length === 0 ? (
            <div style={emptyStyle}>No projects yet.</div>
          ) : (
            <div style={projPageStyle}>
              {pageItems.map((p) => {
                const count = projectCounts[p.name] ?? 0;
                return (
                  <button key={p.name} className="br-projcard" style={projCardStyle} onClick={() => openSub("project", p.name)}>
                    <span className="br-pc-name" style={pcNameStyle}>{p.name}</span>
                    <span style={pcCntStyle}>{count} {count === 1 ? "NOTE" : "NOTES"}</span>
                  </button>
                );
              })}
            </div>
          )}

          <div style={sectionHeadStyle}>TAGS</div>
          {/* FR-34 (s146 #4): hand-made folders are display-only — no empty-
              state row when there are none, since a missing/malformed/failed
              fetch must render exactly like "the user made no folders". */}
          {handFolders.map((f) => (
            <HandFolderRow key={f.path} path={f.path} noteCount={f.note_count} />
          ))}
          {tags.length === 0 ? (
            <div style={emptyStyle}>No tags yet.</div>
          ) : (
            tags.map((t) => (
              <TagRow key={t.tag} label={`#${tagDisplayLabel(t.tag)}`} count={t.count} onClick={() => openSub("tag", t.tag)} />
            ))
          )}
        </div>
      )}
    </div>
  );
}

/** A single note row — file icon + title + relative-age meta, no chevron/
 *  delete affordance (this is a jump-to list, not ProjectsPane's editable
 *  list). Title derivation mirrors ProjectsPane.tsx's identical one-liner. */
function NoteRow({ row, onClick }: { row: SearchResult; onClick: () => void }) {
  const title = row.filename ?? row.path.split(/[\\/]/).pop() ?? row.path;
  const meta = row.timestamp ? formatAgo(new Date(row.timestamp).getTime()) : null;
  return (
    <button className="br-noterow" style={noteRowStyle} onClick={onClick}>
      <span style={noteRowIconStyle}><FileIcon size={12} /></span>
      <span style={noteRowTitleStyle}>{title}</span>
      {meta && <span style={noteRowMetaStyle}>{meta}</span>}
    </button>
  );
}

function TagRow({ label, count, onClick }: { label: string; count: number; onClick: () => void }) {
  return (
    <button className="br-tagrow" style={tagRowStyle} onClick={onClick}>
      <span style={tagRowLabelStyle}>{label}</span>
      <span style={tagRowCountStyle}>{count}</span>
    </button>
  );
}

/** FR-34 (s146 #4) — a hand-made vault folder, surfaced read-only so the
 *  desktop panel mirrors the phone's (data-model-and-contracts.md §2.1).
 *  Same visual weight as `TagRow` (border-bottom row, same type scale), but
 *  a plain `<div>`, not a `<button>`: it carries no click handler and no
 *  hover/focus styling — a quiet reference row, not a new focal element.
 *
 *  ponytail: no click handler, no drill-in, no navigation — deliberate, not
 *  a stub. The phone has no per-folder note listing to drill into (its only
 *  view of the vault is Drive, filed by project tag; a hand-made folder at
 *  depth>=2 never gets a matching Drive folder — see the endpoint's doc
 *  comment in lib/api.ts), so a desktop-only drill-in would make the two
 *  BROWSE panels diverge, which s146 #4 rules out. Upgrade path: once a
 *  contract gives the phone an actual per-folder note list (a
 *  `notesForTag`-shaped endpoint scoped to `path`), wire a drill-in here to
 *  match it on both sides at once — never desktop-only. */
function HandFolderRow({ path, noteCount }: { path: string; noteCount: number }) {
  return (
    <div style={handFolderRowStyle}>
      <span style={handFolderPathStyle}>{path}</span>
      <span style={handFolderCountStyle}>{noteCount}</span>
    </div>
  );
}

// ── styles (mock values transcribed 1:1 where static — SecondThoughtV2.html
// :503-537's `.br-search`/`.sec-h`/`.proj-page`/`.proj-card`/`.tag-row`/
// `.sub-head`/`.res-h`/`.res-empty` — substituting this app's real tokens
// for the mock's own (`--glass`→`--surface`, `--glow-text`→text-shadow via
// `--accent-glow`, see index.css's "BrowseView.tsx" interaction-states
// block for the hover/focus-visible half of these). Hover/focus-visible
// pseudo-classes live there, not in a component-local <style> tag (dead in
// production, see ProjectsRail.tsx's identical comment). ──
const rootStyle: CSSProperties = { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" };
const searchRowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 8, padding: "12px 14px", flex: "0 0 auto" };
const searchIconStyle: CSSProperties = { color: "var(--text-3)", flex: "0 0 auto", display: "flex" };
const searchInputStyle: CSSProperties = { ...INPUT_STYLE, fontSize: fsRead };
const scrollStyle: CSSProperties = { flex: 1, minHeight: 0, overflowY: "auto" };
const sectionHeadStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, padding: "14px 14px 8px",
  fontSize: fsLabel, letterSpacing: "0.18em", color: "var(--text-3)",
};
const emptyStyle: CSSProperties = { padding: "10px 14px", fontSize: fsBody, color: "var(--text-3)" };
// FR-42: the pager used to own the row's sole `marginLeft: "auto"` — now the
// "+ NEW" button/input group (always rendered first) takes that role, so this
// only needs the mock's own fixed 10px gap after it (`.headbtn + .dots`).
const dotsWrapStyle: CSSProperties = { marginLeft: 10, display: "flex", gap: 8, alignItems: "center" };
// FR-42: PROJECTS section-head "+ NEW" trigger — mock option B's `.headbtn`
// (fs-micro, 0.14em tracking, bordered ghost button), `br-kebab` supplies the
// hover/focus-visible treatment already defined for this file's icon buttons.
const headBtnStyle: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, marginLeft: "auto",
  background: "none", border: "1px solid var(--border)", color: "var(--text-2)",
  cursor: "pointer", padding: "3px 8px", fontFamily: "inherit", fontSize: micro, letterSpacing: "0.14em",
};
const parrowStyle: CSSProperties = { background: "none", border: "none", color: "var(--text-3)", cursor: "pointer", padding: "0 2px", display: "inline-flex" };
const pdotStyle: CSSProperties = { width: 6, height: 6, background: "var(--surface-2)", border: "none", cursor: "pointer", padding: 0 };
const pdotOnStyle: CSSProperties = { ...pdotStyle, background: "var(--text-1)" };
const projPageStyle: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, padding: "2px 14px" };
const projCardStyle: CSSProperties = {
  aspectRatio: "1", background: "var(--surface)", border: "1px solid var(--border)", cursor: "pointer",
  display: "flex", flexDirection: "column", padding: 10, textAlign: "left", minWidth: 0, fontFamily: "inherit",
};
const pcNameStyle: CSSProperties = { fontSize: fsBody, fontWeight: 600, color: "var(--text-1)", wordBreak: "break-word", lineHeight: 1.5 };
const pcCntStyle: CSSProperties = { marginTop: "auto", fontSize: micro, color: "var(--text-3)", letterSpacing: "0.08em" };
const tagRowStyle: CSSProperties = {
  display: "flex", alignItems: "baseline", gap: 10, width: "100%", background: "none", border: "none",
  borderBottom: "1px solid var(--border-2)", padding: "9px 14px", cursor: "pointer", fontSize: fsRead, textAlign: "left", fontFamily: "inherit",
};
const tagRowLabelStyle: CSSProperties = { color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const tagRowCountStyle: CSSProperties = { marginLeft: "auto", fontSize: fsLabel, color: "var(--text-3)", flex: "0 0 auto" };
// FR-34: same row geometry/weight as tagRowStyle, minus the interactive
// affordances (no cursor, no button) — a plain non-interactive reference row.
const handFolderRowStyle: CSSProperties = {
  display: "flex", alignItems: "baseline", gap: 10, width: "100%",
  borderBottom: "1px solid var(--border-2)", padding: "9px 14px", fontSize: fsRead,
};
const handFolderPathStyle: CSSProperties = { color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const handFolderCountStyle: CSSProperties = { marginLeft: "auto", fontSize: fsLabel, color: "var(--text-3)", flex: "0 0 auto" };
const subWrapStyle: CSSProperties = { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" };
const subHeadStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderBottom: "1px solid var(--border-2)", flex: "0 0 auto" };
const subBackBtnStyle: CSSProperties = { background: "none", border: "none", color: "var(--text-3)", cursor: "pointer", padding: 2, display: "inline-flex" };
const subTitleStyle: CSSProperties = { fontSize: fsLead, fontWeight: 600, color: "var(--text-1)", margin: 0 };
const subCountStyle: CSSProperties = { marginLeft: "auto", fontSize: fsLabel, color: "var(--text-3)" };
const noteRowStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, width: "100%", background: "none", border: "none",
  borderBottom: "1px solid var(--border-2)", padding: "9px 14px", cursor: "pointer", textAlign: "left", fontFamily: "inherit", color: "var(--text-2)",
};
const noteRowIconStyle: CSSProperties = { flex: "0 0 auto", color: "var(--text-3)", display: "flex" };
const noteRowTitleStyle: CSSProperties = { flex: "1 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: fsRead, color: "var(--text-1)" };
const noteRowMetaStyle: CSSProperties = { flex: "0 0 auto", fontSize: fsLabel, color: "var(--text-3)" };

// ── P3-C3: project management styles, retyped from ProjectsPane.tsx's own
// (:964-1173) into this file's `--fs-*`/type.ts scale (no half-steps: 11.5
// becomes fsBody, 10.5 becomes fsLabel, 9.5 becomes micro) — visuals carried
// over 1:1, sizes snapped to the legal ladder. ──

const subIconBtnStyle: CSSProperties = {
  width: 26, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
  color: "var(--text-3)", background: "none", border: "1px solid transparent", cursor: "pointer", padding: 0, flex: "0 0 auto",
};
const renameInputStyle: CSSProperties = {
  flex: 1, minWidth: 0, background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text-1)",
  fontFamily: "inherit", fontSize: fsLead, fontWeight: 600, padding: "4px 8px",
};

// Mirrors NoteEditor.tsx's menuDropStyle/menuRowStyle (:728-743) exactly —
// same 138px width, same --surface + border + drop-shadow chrome, same
// opacity/transform open-state — retyped from `ne-` to this file's own
// `br-` class idiom (index.css's "P3-C3" block) rather than a second menu
// style being invented.
const menuDropStyle = (open: boolean): CSSProperties => ({
  position: "absolute", top: "calc(100% + 8px)", right: 0, width: 138, background: "var(--surface)",
  border: "1px solid var(--border)", zIndex: 20, boxShadow: "0 8px 20px rgba(0,0,0,0.35)",
  opacity: open ? 1 : 0, transform: open ? "translateY(0) scale(1)" : "translateY(-6px) scale(0.98)",
  pointerEvents: open ? "auto" : "none",
  transition: "opacity 190ms var(--hover-ease-out), transform 190ms var(--hover-ease-out)",
});
const menuRowStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 9, padding: "7px 11px", fontSize: fsBody,
  color: "var(--text-2)", cursor: "pointer", width: "100%", textAlign: "left", border: "none", font: "inherit",
};

const descWrapStyle: CSSProperties = {
  flex: "0 0 auto", padding: "10px 14px", borderBottom: "1px solid var(--border-2)",
  display: "flex", flexDirection: "column", gap: 8,
};
const descAreaStyle: CSSProperties = {
  width: "100%", background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text-1)",
  fontFamily: "inherit", fontSize: fsBody, lineHeight: 1.6, padding: "9px 11px", resize: "none", boxSizing: "border-box",
};
const descFootStyle: CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14 };
const descNoteStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 7, fontSize: micro, color: "var(--text-3)" };
const savesAsYouTypeStyle: CSSProperties = { fontSize: micro, color: "var(--text-3)", flex: "0 0 auto" };

const mutationErrorStyle: CSSProperties = {
  flex: "0 0 auto", padding: "6px 14px", fontSize: fsLabel, color: "var(--red)", borderBottom: "1px solid var(--border-2)",
};

// Danger confirm strip (project delete) — same red-tinted band as
// ProjectsPane.tsx's confirmStripStyle, reused verbatim (not a second
// idiom); the grayscale tidy strip below intentionally does NOT reuse this.
const confirmStripStyle: CSSProperties = {
  flex: "0 0 auto", borderBottom: "1px solid var(--border-2)", background: "rgba(255,100,103,0.08)",
  padding: "9px 14px", display: "flex", alignItems: "center", gap: 12,
};
const confirmTextStyle: CSSProperties = { fontSize: fsLabel, color: "var(--text-2)", flex: "1 1 auto" };
const ghostBtnStyle: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 5, fontSize: fsLabel, color: "var(--text-2)",
  border: "1px solid var(--border)", background: "var(--bg)", padding: "5px 9px", cursor: "pointer", fontFamily: "inherit",
};
const ghostDangerBtnStyle: CSSProperties = { ...ghostBtnStyle, borderColor: "var(--red)", color: "var(--red)" };

// FR-23 Option A: same strip shell as confirmStripStyle but grayscale — a
// file move to match its own tag is safe housekeeping, never a deletion,
// and the identity lock reserves red/yellow/green for real semantic state.
const tidyStripStyle: CSSProperties = {
  flex: "0 0 auto", borderBottom: "1px solid var(--border-2)", background: "var(--ctl-face)",
  padding: "9px 14px", display: "flex", flexDirection: "column", gap: 8,
};
const tidyListStyle: CSSProperties = {
  display: "flex", flexDirection: "column", gap: 2, maxHeight: 110, overflowY: "auto",
  border: "1px solid var(--border)", background: "var(--bg)", padding: "4px 8px",
};
const tidyRowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 8, fontSize: fsLabel, padding: "2px 0" };
const tidyRowFileStyle: CSSProperties = {
  flex: "0 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-1)",
};
const tidyRowPathStyle: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 3, flex: "0 0 auto", color: "var(--text-3)" };
const tidyActionsRowStyle: CSSProperties = { display: "flex", justifyContent: "flex-end", gap: 6 };
const tidyPrimaryBtnStyle: CSSProperties = { ...ghostBtnStyle, borderColor: "var(--text-1)", color: "var(--text-1)" };

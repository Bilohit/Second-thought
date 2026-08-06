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
 * comment for which components this leaves unmounted, and this task's
 * report for the FR-36 folder-import-refetch tracing.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  listProjects, getStats, getTagTree, searchCaptures, notesForProject, notesForTag,
  type ProjectEntry, type SearchResult,
} from "../../lib/api";
import {
  filterMachineTags, flattenTagTree, tagDisplayLabel, excludeProvisional, formatAgo,
  type FlatTag,
} from "../../lib/projectsView";
import { sectionSearch, isSearchActive, type SearchableProject } from "../../lib/browseSearch";
import { chunkProjects, browsePagerInfo, PROJECTS_PER_PAGE } from "../../lib/browsePager";
import { SearchIcon, FileIcon, ChevronLeftIcon, ChevronRightIcon } from "../PillMenu/icons";
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

export default function BrowseView({ visible, mode, onOpenNote }: Props) {
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [projectCounts, setProjectCounts] = useState<Record<string, number>>({});
  const [tags, setTags] = useState<FlatTag[]>([]);
  const [page, setPage] = useState(1);

  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [sub, setSub] = useState<SubSelection | null>(null);
  const [subRows, setSubRows] = useState<SearchResult[]>([]);
  const [subLoading, setSubLoading] = useState(false);

  // ── projects + tags, refetched on every `visible` transition to true
  // (ProjectsView.tsx's own pattern, adapted). This IS how a stale tile
  // list after a folder-import (or any other out-of-band registry mutation)
  // recovers here: BROWSE hosts no folder-import entry point of its own
  // (see the file header / this task's report), so there is no in-panel
  // `onApplied` to wire — navigating back into BROWSE always re-fetches the
  // current registry from scratch. ──
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    listProjects().then(({ projects: rows }) => { if (!cancelled) setProjects(rows); })
      .catch(() => { if (!cancelled) setProjects([]); });
    getStats().then((stats) => {
      if (cancelled) return;
      const counts: Record<string, number> = {};
      for (const row of stats.by_project) counts[row.project] = row.count;
      setProjectCounts(counts);
    }).catch(() => { if (!cancelled) setProjectCounts({}); });
    getTagTree().then((r) => { if (!cancelled) setTags(flattenTagTree(filterMachineTags(r.tags))); })
      .catch(() => { if (!cancelled) setTags([]); });
    return () => { cancelled = true; };
  }, [visible]);

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
            <h4 style={subTitleStyle}>{sub.kind === "tag" ? `#${tagDisplayLabel(sub.value)}` : sub.value}</h4>
            <span style={subCountStyle}>{subRows.length} {subRows.length === 1 ? "note" : "notes"}</span>
          </div>
          <div style={scrollStyle}>
            {subLoading && subRows.length === 0 && <div style={emptyStyle}>Loading…</div>}
            {!subLoading && subRows.length === 0 && <div style={emptyStyle}>No notes here yet.</div>}
            {subRows.map((row) => <NoteRow key={row.path} row={row} onClick={() => onOpenNote?.(row.path)} />)}
          </div>
        </div>
      ) : (
        <div style={scrollStyle}>
          <div style={sectionHeadStyle}>
            PROJECTS
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
          {/* FR-34: a read-only, non-interactive hand-made-folder row lands
              here in a follow-up (scope owned by the user, not this task) —
              structured additively, right below the tag list, so it slots
              in without reshaping this section. Build nothing for it yet:
              no endpoint call, no diff logic, no row. */}
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
const dotsWrapStyle: CSSProperties = { marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" };
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

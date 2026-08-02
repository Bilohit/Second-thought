/**
 * TagsView.tsx — F-4 Library tags browser (mock 05-desktop-tags.html, Tree
 * mode). Fetches the tag tree once, renders a flat two-level list (namespace
 * rows + indented children), and hands a click off to a tag-filtered search
 * via the existing `/search?q=tag:<value>` hand-off (vault_admin.py's
 * `_extract_tag_filter`).
 *
 * ponytail: Grid mode + arrow-key roving focus from the mock are cut for
 * this pass — Tree covers the actual "browse then jump to filtered search"
 * job. Add a Tree/Grid segmented toggle only if tree-only browsing proves
 * insufficient in practice.
 */
import { useEffect, useState } from "react";
import { getTagTree, searchCaptures, type TagNode, type SearchResult } from "../../lib/api";
// ISS-019 machine-tag filtering moved to lib/projectsView.ts (SP3 Task 7):
// this file is deleted in Task 8, and the new Projects-screen tag rail
// (ProjectsRail.tsx, via ProjectsView.tsx) needs the same filter, so it now
// lives in the shared lib module both sides import from. Re-imported here,
// unchanged, so this file still compiles and still filters its own tag tree
// the same way it always did.
import { filterMachineTags } from "../../lib/projectsView";

interface Props {
  visible: boolean;
  onOpenNote?: (path: string) => void;
}

/**
 * 2026-07-30 grouping split: `project/` tags are the app's one grouping
 * feature (folders keep the auto-categorize job only, see
 * docs/superpowers/specs/2026-07-30-grouping-split-design.md). Pulls the
 * `project/` namespace node's leaf children out as a pinned list -- full
 * "project/<leaf>" tag values kept intact (the /search hand-off needs the
 * whole value; only the render layer strips the prefix) -- and returns the
 * remaining tree with that namespace node removed so it isn't duplicated
 * under "ALL TAGS". A bare "project" node with no children (nothing tagged
 * yet) is an ordinary user tag, not a namespace -- it stays in `rest`.
 */
export function splitProjects(tags: TagNode[]): { projects: TagNode[]; rest: TagNode[] } {
  const isProjectNamespace = (tag: string) => tag.replace(/\/$/, "") === "project";
  const namespaceNode = tags.find((node) => isProjectNamespace(node.tag) && node.children?.length);
  const projects = namespaceNode?.children ?? [];
  const rest = tags.filter((node) => node !== namespaceNode);
  return { projects, rest };
}

export default function TagsView({ visible, onOpenNote }: Props) {
  const [tags, setTags] = useState<TagNode[] | null>(null);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [results, setResults] = useState<SearchResult[] | null>(null);

  useEffect(() => {
    if (!visible) return;
    getTagTree().then((r) => setTags(filterMachineTags(r.tags))).catch(() => setTags([]));
  }, [visible]);

  useEffect(() => {
    if (!activeTag) { setResults(null); return; }
    let cancelled = false;
    searchCaptures(`tag:${activeTag}`, { limit: 50 })
      .then((r) => { if (!cancelled) setResults(r.results); })
      .catch(() => { if (!cancelled) setResults([]); });
    return () => { cancelled = true; };
  }, [activeTag]);

  if (!visible) return null;

  const rowStyle = {
    display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left" as const,
    background: "none", border: "none", borderBottom: "1px solid var(--border-2)", font: "inherit",
    fontSize: 13, color: "var(--text-1)", padding: "8px 14px", cursor: "pointer",
  };

  if (activeTag) {
    return (
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderBottom: "1px solid var(--border-2)" }}>
          <button
            onClick={() => setActiveTag(null)}
            style={{ width: 26, height: 26, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "none", border: "1px solid var(--border)", color: "var(--text-2)", cursor: "pointer" }}
            aria-label="Back to tags" title="Back"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M15 5l-7 7 7 7" /></svg>
          </button>
          <span style={{ fontSize: 12, letterSpacing: "0.04em", color: "var(--text-1)", fontWeight: 600 }}>
            tag:{activeTag} {results ? `· ${results.length} notes` : ""}
          </span>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
          {results === null && <div style={{ padding: 14, fontSize: 12, color: "var(--text-3)" }}>Loading…</div>}
          {results !== null && results.length === 0 && <div style={{ padding: 14, fontSize: 12, color: "var(--text-3)" }}>No notes with this tag.</div>}
          {results?.map((r) => (
            <button
              key={r.id}
              style={rowStyle}
              onClick={() => onOpenNote?.(r.path)}
            >
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.filename ?? r.path}</span>
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>{r.project}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  const sectionLabelStyle = { fontSize: 12, letterSpacing: "0.04em", color: "var(--text-1)", fontWeight: 600, padding: "10px 14px 6px" };
  const { projects, rest } = tags ? splitProjects(tags) : { projects: [], rest: [] };

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
      <style>{`
        .tags-row { transition: background-color 150ms ease; }
        .tags-row:hover { background: var(--surface-2); }
        .tags-row:focus-visible { outline: 1px solid var(--border); outline-offset: -1px; }
      `}</style>
      {tags === null && <div style={{ padding: 14, fontSize: 12, color: "var(--text-3)" }}>Loading…</div>}
      {tags !== null && tags.length === 0 && <div style={{ padding: 14, fontSize: 12, color: "var(--text-3)" }}>No tags yet.</div>}
      {tags !== null && tags.length > 0 && (
        <>
          <div style={sectionLabelStyle}>PROJECTS</div>
          {projects.length === 0 && (
            <div style={{ padding: "0 14px 10px", fontSize: 12, color: "var(--text-3)" }}>
              no projects yet — add #project/name in any note
            </div>
          )}
          {projects.map((child) => (
            <button key={child.tag} className="tags-row" style={rowStyle} onClick={() => setActiveTag(child.tag)}>
              <span style={{ color: "var(--text-3)" }}>#</span>{child.tag.replace(/^project\//, "")}
              <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)" }}>{child.count}</span>
            </button>
          ))}
          <div style={sectionLabelStyle}>ALL TAGS</div>
          {rest.map((node) => (
            <div key={node.tag}>
              <button className="tags-row" style={rowStyle} onClick={() => setActiveTag(node.tag.replace(/\/$/, ""))}>
                <span style={{ color: "var(--text-3)" }}>#</span>{node.tag}
                <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)" }}>{node.count}</span>
              </button>
              {node.children.map((child) => (
                <button key={child.tag} className="tags-row" style={{ ...rowStyle, paddingLeft: 34 }} onClick={() => setActiveTag(child.tag)}>
                  <span style={{ color: "var(--text-3)" }}>#</span>{child.tag}
                  <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)" }}>{child.count}</span>
                </button>
              ))}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

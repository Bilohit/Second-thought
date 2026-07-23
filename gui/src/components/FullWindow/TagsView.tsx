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

interface Props {
  visible: boolean;
  onOpenNote?: (path: string) => void;
}

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
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>{r.category}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
      {tags === null && <div style={{ padding: 14, fontSize: 12, color: "var(--text-3)" }}>Loading…</div>}
      {tags !== null && tags.length === 0 && <div style={{ padding: 14, fontSize: 12, color: "var(--text-3)" }}>No tags yet.</div>}
      {tags?.map((node) => (
        <div key={node.tag}>
          <button style={rowStyle} onClick={() => setActiveTag(node.tag.replace(/\/$/, ""))}>
            <span style={{ color: "var(--text-3)" }}>#</span>{node.tag}
            <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)" }}>{node.count}</span>
          </button>
          {node.children.map((child) => (
            <button key={child.tag} style={{ ...rowStyle, paddingLeft: 34 }} onClick={() => setActiveTag(child.tag)}>
              <span style={{ color: "var(--text-3)" }}>#</span>{child.tag}
              <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)" }}>{child.count}</span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

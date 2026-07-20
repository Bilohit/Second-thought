import { useEffect, useState } from "react";
import VaultManager from "../VaultManager";
import TagsView from "./TagsView";
import TrashView from "./TrashView";
import { CategoryBar, DaySparkline } from "../StatsPanel";
import { getStats, type Stats } from "../../lib/api";

interface Props {
  visible: boolean;
  /** vault/tags/trash section — owned by FullWindow so its toggle can live in
   *  the topbar (like the Look search/chat toggle). */
  section: "vault" | "tags" | "trash";
  /** F-7 follow-up: opens a file in the full-window NoteEditor (threaded
   *  from FullWindow's setEditorPath). */
  onOpenNote?: (path: string) => void;
}

export default function LibraryView({ visible, section, onOpenNote }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    if (!visible) return;
    getStats().then(setStats).catch(() => {});
  }, [visible]);

  if (!visible) return null;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 14, padding: 14, overflow: "hidden" }}>
      {section === "vault" && (
        // Folders panel (1fr) spans the full row height; the 280px right column
        // stacks By category (fills) over Daily rhythm (natural height) so the
        // two right-hand panels equal the folders panel's length.
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 280px", gap: 14, minHeight: 0, overflow: "hidden" }}>
          <VaultManager visible={true} embedded onClose={() => {}} onOpenNote={onOpenNote} />
          <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0, overflow: "hidden" }}>
            <div style={{ flex: 1, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 14, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
              <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
                By category
              </div>
              {/* paddingRight keeps the scrollbar clear of the per-category count numbers. */}
              <div style={{ overflow: "auto", display: "flex", flexDirection: "column", gap: 8, paddingRight: 8 }}>
                {(stats?.by_category ?? []).map((c) => (
                  <CategoryBar key={c.category} category={c.category} count={c.count} pct={c.pct} />
                ))}
              </div>
            </div>
            <div style={{ flex: "none", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "10px 14px" }}>
              <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Daily rhythm</div>
              <DaySparkline days={stats?.by_day ?? []} />
            </div>
          </div>
        </div>
      )}
      {section === "tags" && (
        <div style={{ flex: 1, minHeight: 0, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <TagsView visible onOpenNote={onOpenNote} />
        </div>
      )}
      {section === "trash" && (
        <div style={{ flex: 1, minHeight: 0, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <TrashView visible />
        </div>
      )}
    </div>
  );
}

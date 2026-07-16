import { useEffect, useState } from "react";
import VaultManager from "../VaultManager";
import TagsView from "./TagsView";
import TrashView from "./TrashView";
import SegmentedToggle from "../ui/SegmentedToggle";
import { CategoryBar, DaySparkline } from "../StatsPanel";
import { getStats, type Stats } from "../../lib/api";

interface Props {
  visible: boolean;
  /** F-7 follow-up: opens a file in the full-window NoteEditor (threaded
   *  from FullWindow's setEditorPath). */
  onOpenNote?: (path: string) => void;
}

export default function LibraryView({ visible, onOpenNote }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [section, setSection] = useState<"vault" | "tags" | "trash">("vault");

  useEffect(() => {
    if (!visible) return;
    getStats().then(setStats).catch(() => {});
  }, [visible]);

  if (!visible) return null;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 14, padding: 14, overflow: "hidden" }}>
      <div style={{ flex: "none", display: "flex", justifyContent: "flex-end" }}>
        <SegmentedToggle
          ariaLabel="Library section"
          options={[
            { key: "vault" as const, label: "Vault" },
            { key: "tags" as const, label: "Tags" },
            { key: "trash" as const, label: "Trash" },
          ]}
          value={section}
          onChange={setSection}
        />
      </div>
      {section === "vault" && (
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 280px", gap: 14, minHeight: 0, overflow: "hidden" }}>
          <VaultManager visible={true} embedded onClose={() => {}} onOpenNote={onOpenNote} />
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 14, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
            <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10 }}>
              By category
            </div>
            <div style={{ overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
              {(stats?.by_category ?? []).map((c) => (
                <CategoryBar key={c.category} category={c.category} count={c.count} pct={c.pct} />
              ))}
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
      {section === "vault" && (
        // Reduced width: aligns to the vault list's 1fr column (matches the
        // grid above), not full-bleed — the 280px right column is left free.
        // Day-streak heatmap removed (user, s22); the shorter bar also stops
        // starving the flex:1 grid above at higher display scale.
        <div style={{ flex: "none", display: "grid", gridTemplateColumns: "1fr 280px", gap: 14 }}>
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "10px 14px" }}>
            <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Daily rhythm</div>
            <DaySparkline days={stats?.by_day ?? []} />
          </div>
        </div>
      )}
    </div>
  );
}

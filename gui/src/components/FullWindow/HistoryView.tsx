/**
 * HistoryView.tsx
 * ---------------
 * FR-07: the full-window rail's "History" destination. Was aliased onto
 * `library` (VIEW_TO_RAIL), which lost its "By project" panel when s130
 * pulled ProjectBar out of LibraryView -- firing the menu's History item
 * landed on a screen with no history content. The compact pill's own
 * CompactHistory.tsx never lost that panel; this view mounts the same
 * building block (StatsPanel.tsx's ProjectBar, left untouched by s130)
 * rather than re-authoring it.
 * "Recent activity" is deliberately not repeated here -- DashboardView already
 * has that card in the full window, and the design mock
 * (mocks/2026-08-02-flowreview-decisions.html, Fork 2 / Option A) shows only
 * this stat card for the restored History destination. (Task 11 removed the
 * sparkline card that used to sit above it -- deleted outright, not moved.)
 */
import { useEffect, useState } from "react";
import { ProjectBar } from "../StatsPanel";
import { getStats, type Stats } from "../../lib/api";
import { displayProject } from "../../lib/projectsView";

interface Props {
  visible: boolean;
}

const CARD: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
  padding: 14, display: "flex", flexDirection: "column", minHeight: 0,
};
const LABEL: React.CSSProperties = {
  fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10,
};

export default function HistoryView({ visible }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    if (!visible) return;
    getStats().then(setStats).catch(() => {});
  }, [visible]);

  if (!visible) return null;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 14, padding: 14, overflow: "auto" }}>
      <div style={CARD}>
        <div style={LABEL}>By project</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {(stats?.by_project ?? []).map((c) => (
            <ProjectBar key={c.project} project={displayProject(c.project)} count={c.count} pct={c.pct} />
          ))}
          {(!stats || stats.by_project.length === 0) && (
            <span style={{ fontSize: 11, color: "var(--text-3)" }}>No captures yet.</span>
          )}
        </div>
      </div>
    </div>
  );
}

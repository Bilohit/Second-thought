/**
 * CompactHistory.tsx
 * --------------------
 * Compact Mode Menu Decoupling, Task 2.4: FULL-parity History/Stats content
 * for the capsule's `CompactShell` body. Mirrors the "capture rhythm"
 * summary (`CategoryBar` by-category breakdown + `DaySparkline` daily
 * counts, both from `StatsPanel.tsx`) and the complete "Recent activity"
 * list (`DashboardView.tsx`'s `renderRecentCard`, driven by
 * `getStats().recent` — already newest-first from the server) in one
 * scrollable column instead of DashboardView's fixed-height card, since a
 * capsule panel has room to show the whole list rather than a preview.
 */
import { useEffect, useState } from "react";
import { CategoryBar, DaySparkline } from "../StatsPanel";
import { getStats, openFilePath, type Stats } from "../../lib/api";

interface Props {
  onOpenFile?: (path: string) => void;
}

export default function CompactHistory({ onOpenFile }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
  }, []);

  const rows = stats?.recent ?? [];
  const openFile = onOpenFile ?? ((path: string) => { void openFilePath(path); });

  return (
    <div style={{ height: "100%", minWidth: 0, display: "flex", flexDirection: "column", gap: 10, overflowY: "auto", overflowX: "hidden" }}>
      {/* minHeight sized so ~5 recent rows show at a glance before the outer
          column scrolls (the compact body is 288px; the Daily/Category cards
          live below the fold). A shorter min-height floored the card at ~2
          rows once the column became height-constrained. */}
      <div style={{ flex: "1 1 auto", minHeight: 260, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-3)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 8, display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          Recent activity
          {rows.length > 0 && (
            <span style={{ fontSize: 10, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "1px 7px", color: "var(--text-2)", background: "var(--glass-bg)" }}>
              {rows.length}
            </span>
          )}
        </div>
        <div style={{ overflowY: "auto", overflowX: "hidden", flex: 1, minHeight: 0 }}>
          {rows.map((row) => (
            <button
              key={row.id}
              type="button"
              className="btn-hover compact-recent-row"
              onClick={() => { if (row.path) openFile(row.path); }}
              style={{
                display: "flex", alignItems: "flex-start", gap: 10, width: "100%",
                padding: "7px 4px", cursor: "pointer", border: "none",
                background: "transparent", textAlign: "left", fontFamily: "inherit",
              }}
            >
              <span style={{ fontSize: 12, color: "var(--text-1)", flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {row.filename ?? row.path}
              </span>
              <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3, flexShrink: 0 }}>
                <span style={{ fontSize: 10, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "1px 5px", color: "var(--text-3)", display: "inline-block", maxWidth: 108, whiteSpace: "normal", wordBreak: "break-word", textAlign: "right", lineHeight: 1.25 }}>{row.category}</span>
                <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{row.timestamp}</span>
              </span>
            </button>
          ))}
          {rows.length === 0 && (
            <div style={{ fontSize: 11, color: "var(--text-3)", padding: "12px 0", textAlign: "center" }}>No recent captures</div>
          )}
        </div>
      </div>

      <div style={{ flex: "none", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-3)" }}>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 8 }}>
          Daily rhythm
        </div>
        <DaySparkline days={stats?.by_day ?? []} />
      </div>

      <div style={{ flex: "none", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "var(--space-3)" }}>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 8 }}>
          By category
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {(stats?.by_category ?? []).map((c) => (
            <CategoryBar key={c.category} category={c.category} count={c.count} pct={c.pct} />
          ))}
          {(!stats || stats.by_category.length === 0) && (
            <span style={{ fontSize: 11, color: "var(--text-3)" }}>No captures yet.</span>
          )}
        </div>
      </div>
    </div>
  );
}

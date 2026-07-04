/**
 * CompactVault.tsx
 * -----------------
 * Compact Mode Menu Decoupling, Task 2.4: FULL-parity Library/Vault content
 * for the capsule's `CompactShell` body. FullWindow's "Library" rail view
 * (`FullWindow/LibraryView.tsx`) is a side-by-side grid of `VaultManager`
 * (category tree + drill-in file list, create/rename/delete/describe,
 * open-note, open-vault-folder) and a "By category" stat card
 * (`CategoryBar`) + "Daily rhythm" sparkline (`DaySparkline`) fed by
 * `getStats()`. 288px is too narrow for that side-by-side grid, so this
 * re-flows the same three sections into one scrollable column instead —
 * GATE-3: layout-only, nothing dropped.
 */
import { useEffect, useState } from "react";
import VaultManager from "../VaultManager";
import { CategoryBar, DaySparkline } from "../StatsPanel";
import { getStats, type Stats } from "../../lib/api";

export default function CompactVault() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
  }, []);

  return (
    <div style={{ height: "100%", minWidth: 0, display: "flex", flexDirection: "column", gap: 10, overflowY: "auto" }}>
      {/* Category tree + drill-in file list, create/rename/delete/describe,
          open-note + open-vault-folder — identical to LibraryView's
          VaultManager, just given a bounded height so it scrolls internally
          instead of pushing the stat cards below off-screen. */}
      <div style={{ flex: "1 1 260px", minHeight: 220, position: "relative" }}>
        <VaultManager visible embedded onClose={() => {}} />
      </div>

      <div style={{ flex: "none", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "10px 12px" }}>
        <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
          By category
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {(stats?.by_category ?? []).map((c) => (
            <CategoryBar key={c.category} category={c.category} count={c.count} pct={c.pct} />
          ))}
          {(!stats || stats.by_category.length === 0) && (
            <span style={{ fontSize: 11, color: "var(--text-3)" }}>No categories yet.</span>
          )}
        </div>
      </div>

      <div style={{ flex: "none", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "10px 12px" }}>
        <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
          Daily rhythm
        </div>
        <DaySparkline days={stats?.by_day ?? []} />
      </div>
    </div>
  );
}

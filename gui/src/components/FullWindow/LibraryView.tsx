import { useEffect, useState } from "react";
import VaultManager from "../VaultManager";
import { CategoryBar, DaySparkline } from "../StatsPanel";
import { getStats, type Stats } from "../../lib/api";

interface Props {
  visible: boolean;
}

export default function LibraryView({ visible }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    if (!visible) return;
    getStats().then(setStats).catch(() => {});
  }, [visible]);

  if (!visible) return null;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 14, padding: 14, overflow: "hidden" }}>
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 280px", gap: 14, minHeight: 0, overflow: "hidden" }}>
        <VaultManager visible={true} embedded onClose={() => {}} />
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
      <div style={{ flex: "none", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "10px 14px" }}>
        <div style={{ fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>Daily rhythm</div>
        <DaySparkline days={stats?.by_day ?? []} />
      </div>
    </div>
  );
}

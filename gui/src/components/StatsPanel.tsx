/**
 * StatsPanel.tsx
 * --------------
 * History tab: recent activity, live category counts, daily sparkline, total.
 * Category counts come from getVaultCategories() (live vault folder listing)
 * rather than the /stats SQLite snapshot — files are source of truth.
 */

import { useState, useEffect } from "react";

export function CategoryBar({ category, count, pct }: { category: string; count: number; pct: number }) {
  const [width, setWidth] = useState(0);
  useEffect(() => { requestAnimationFrame(() => setWidth(pct)); }, [pct]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
        <span style={{ color: "var(--text-1)" }}>{category}</span>
        <span style={{ color: "var(--text-3)" }}>{count}</span>
      </div>
      <div style={{ height: 5, borderRadius: "var(--radius-sm)", background: "var(--border)", overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            width: "100%",
            borderRadius: "var(--radius-sm)",
            background: "var(--accent)",
            transform: `scaleX(${width / 100})`,
            transformOrigin: "left",
            willChange: "transform",
            transition: "transform 0.4s cubic-bezier(0.16,1,0.3,1)",
          }}
        />
      </div>
    </div>
  );
}

export function DaySparkline({ days }: { days: { date: string; count: number }[] }) {
  const ordered = days.slice().sort((a, b) => a.date.localeCompare(b.date));
  const max = Math.max(1, ...ordered.map((d) => d.count));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 36 }}>
      {ordered.map((d) => (
        <div
          key={d.date}
          title={`${d.date}: ${d.count}`}
          style={{
            flex: 1,
            minWidth: 2,
            height: `${Math.max(6, (d.count / max) * 100)}%`,
            background: "var(--accent)",
            borderRadius: "var(--radius-sm)",
          }}
        />
      ))}
    </div>
  );
}


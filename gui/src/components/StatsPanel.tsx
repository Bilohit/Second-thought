/**
 * StatsPanel.tsx
 * --------------
 * History tab: recent activity, live project counts, total.
 * Project counts come from getVaultFolders() (live vault folder listing)
 * rather than the /stats SQLite snapshot — files are source of truth.
 */

import { useState, useEffect } from "react";

export function ProjectBar({ project, count, pct }: { project: string; count: number; pct: number }) {
  const [width, setWidth] = useState(0);
  useEffect(() => { requestAnimationFrame(() => setWidth(pct)); }, [pct]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
        <span style={{ color: "var(--text-1)" }}>{project}</span>
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


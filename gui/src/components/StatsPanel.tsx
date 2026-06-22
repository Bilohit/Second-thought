/**
 * StatsPanel.tsx
 * --------------
 * Read-only capture statistics: total count, per-category breakdown as
 * width-animated bars, and a short recent-activity list. All numbers come
 * directly from the /stats endpoint — no client-side aggregation.
 */

import { useCallback, useEffect, useState } from "react";
import { getStats, type Stats } from "../lib/api";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  BTN_GHOST, ROW_CARD,
} from "./ui/styles";

interface Props {
  visible: boolean;
  onClose: () => void;
  measureRef?: (el: HTMLDivElement | null) => void;
}

const TILE_LABEL: React.CSSProperties = {
  fontSize: 10, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase",
};

// Tile — ROW_CARD surface + motivated entrance (fade-up, staggered by index
// to read top-down). Reduced-motion collapses fadeIn to a plain opacity step
// via index.css, so no transform motion plays. Single-column stack: every
// tile is inherently full-width, so there's no span/solo logic needed.
function Tile({
  index,
  style,
  children,
}: {
  index: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        ...ROW_CARD,
        animation: `fadeIn 0.42s cubic-bezier(0.16,1,0.3,1) ${index * 0.06}s both`,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function CategoryBar({ category, count, pct }: { category: string; count: number; pct: number }) {
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

function DaySparkline({ days }: { days: { date: string; count: number }[] }) {
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

export default function StatsPanel({ visible, onClose, measureRef }: Props) {
  const [mounted, setMounted] = useState(visible);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStats(await getStats());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load stats");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (visible) { setMounted(true); load(); }
  }, [visible, load]);

  const handleTransitionEnd = () => {
    if (!visible) setMounted(false);
  };

  if (!mounted) return null;

  const maxByCategory = stats?.by_category.slice().sort((a, b) => b.count - a.count) ?? [];

  return (
    <div
      ref={measureRef}
      style={{
        ...PANEL_FRAME,
        ...panelTransform(visible),
        overflowY: "auto",
      }}
      onTransitionEnd={handleTransitionEnd}
    >
      <div className="drag-region" style={PANEL_HEADER}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>Statistics</span>
        <div className="no-drag" style={{ display: "flex", gap: 4 }}>
          <button className="btn-hover" style={BTN_GHOST} title="Refresh" onClick={load}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </button>
          <button className="no-drag icon-close-btn" onClick={onClose} title="Close">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="2" y1="2" x2="12" y2="12" />
              <line x1="12" y1="2" x2="2" y2="12" />
            </svg>
          </button>
        </div>
      </div>

      <div className="no-drag" style={{ padding: "16px 16px 14px", display: "flex", flexDirection: "column", gap: 18 }}>
        {loading && (
          <div style={{ display: "flex", justifyContent: "center", padding: 20 }}>
            <span style={{ fontSize: 12, color: "var(--text-3)" }}>Loading…</span>
          </div>
        )}
        {error && (
          <span style={{ fontSize: 11, color: "var(--red)" }}>{error} — is the Python server running?</span>
        )}

        {stats && !loading && !error && (() => {
          const hasCats   = maxByCategory.length > 0;
          const hasRecent = stats.recent.length > 0;
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Tile index={0} style={{ padding: "16px 16px", background: "var(--surface)" }}>
                <div style={{ fontSize: 30, fontWeight: 600, color: "var(--text-1)", lineHeight: 1 }}>{stats.total}</div>
                <div style={{ ...TILE_LABEL, marginTop: 4 }}>Total captures</div>
              </Tile>

              {hasCats && (
                <Tile index={1} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <span style={TILE_LABEL}>By category</span>
                  {maxByCategory.map((c) => (
                    <CategoryBar key={c.category} category={c.category} count={c.count} pct={c.pct} />
                  ))}
                </Tile>
              )}

              {stats.by_day.length > 0 && (
                <Tile index={2} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <span style={TILE_LABEL}>Daily activity (30 days)</span>
                  <DaySparkline days={stats.by_day} />
                </Tile>
              )}

              {hasRecent && (
                <Tile index={3} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <span style={TILE_LABEL}>Recent activity</span>
                  {stats.recent.slice(0, 10).map((r) => (
                    <div key={r.id} className="row-hover-flat" style={{ display: "flex", flexDirection: "column", gap: 2, padding: "4px 0", borderBottom: "1px solid var(--border-2)" }}>
                      <span style={{
                        fontSize: 9, fontWeight: 600, color: "var(--text-3)",
                        background: "var(--surface-2)", border: "1px solid var(--border)",
                        borderRadius: "var(--radius-sm)", padding: "1px 5px", whiteSpace: "nowrap", alignSelf: "flex-start",
                      }}>
                        {r.category}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {r.filename || r.source_url || r.path.split(/[\\/]/).pop()}
                      </span>
                    </div>
                  ))}
                </Tile>
              )}
            </div>
          );
        })()}
      </div>
    </div>
  );
}

/**
 * Tabs.tsx
 * --------
 * Generic segmented tab bar: flat, sharp, full-width, equal-width buttons
 * with a sliding underline indicator. Token-styled (no literal colors), no
 * new dependencies — see 2026-06-21-settings-tabs-and-recenter-design.md §3.
 */
import { useState } from "react";

export interface TabDef<T extends string> {
  id: T;
  label: string;
}

interface TabsProps<T extends string> {
  tabs: TabDef<T>[];
  active: T;
  onChange: (id: T) => void;
  /** Compact-only dense variant: shrinks per-button vertical padding. Default false (unchanged). */
  dense?: boolean;
}

export function Tabs<T extends string>({ tabs, active, onChange, dense = false }: TabsProps<T>) {
  const [hovered, setHovered] = useState<T | null>(null);
  const activeIndex = tabs.findIndex((t) => t.id === active);
  const n = tabs.length;

  return (
    <div
      role="tablist"
      className="no-drag"
      style={{
        position: "relative",
        display: "flex",
        borderBottom: "1px solid var(--border-2)",
        flexShrink: 0,
      }}
    >
      {tabs.map((t) => {
        const isActive = t.id === active;
        const isHovered = hovered === t.id;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(t.id)}
            onMouseEnter={() => setHovered(t.id)}
            onMouseLeave={() => setHovered(null)}
            style={{
              flex: 1,
              padding: dense ? "6px 0" : "10px 0",
              background: isActive ? "var(--accent-d)" : "none",
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: "0.02em",
              color: isActive ? "var(--text-1)" : isHovered ? "var(--text-2)" : "var(--text-3)",
              transition: "color 0.15s, background 0.15s",
            }}
          >
            {t.label}
          </button>
        );
      })}
      <span
        aria-hidden="true"
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          height: 2,
          width: `${100 / n}%`,
          background: "var(--accent)",
          borderRadius: "var(--radius-sm)",
          transform: `translateX(${activeIndex * 100}%)`,
          transition: "transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
        }}
      />
    </div>
  );
}

import type { ReactNode } from "react";
import { indicatorWidth, indicatorTransform } from "../../lib/segmentedToggle";

interface Option<K extends string> {
  key: K;
  label: string;
  /** Icon-only rendering (compact panels) — `label` still supplies the
   *  button's accessible name and hover tooltip; chrome is unchanged. */
  icon?: ReactNode;
}

interface Props<K extends string> {
  options: Option<K>[];
  value: K;
  onChange: (key: K) => void;
  ariaLabel: string;
}

export default function SegmentedToggle<K extends string>({ options, value, onChange, ariaLabel }: Props<K>) {
  const activeIndex = options.findIndex((o) => o.key === value);
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      style={{
        position: "relative",
        display: "grid",
        // Equal-width segments so the one-segment-wide pill lines up on a pure
        // `index * 100%` translate (see lib/segmentedToggle.ts).
        gridTemplateColumns: `repeat(${options.length}, 1fr)`,
        background: "var(--surface)",
        borderRadius: "var(--radius)",
        padding: 2,
      }}
    >
      {/* Sliding active-pill indicator (behind the labels). Motion is gated by
          the global prefers-reduced-motion rule in index.css, which forces
          transition-duration to ~0 and makes this an instant swap. */}
      <span
        aria-hidden="true"
        style={{
          position: "absolute",
          top: 2,
          bottom: 2,
          left: 2,
          width: indicatorWidth(options.length),
          background: "var(--accent)",
          borderRadius: "var(--radius-sm)",
          transform: indicatorTransform(activeIndex),
          transition: "transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
          opacity: activeIndex < 0 ? 0 : 1,
          pointerEvents: "none",
        }}
      />
      {options.map((o) => {
        const isActive = value === o.key;
        return (
          <button
            key={o.key}
            role="tab"
            aria-selected={isActive}
            title={o.label}
            aria-label={o.icon ? o.label : undefined}
            onClick={() => onChange(o.key)}
            style={{
              position: "relative",
              zIndex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 11,
              padding: o.icon ? "5px 10px" : "4px 10px",
              minWidth: o.icon ? 0 : 60,
              textAlign: "center",
              borderRadius: "var(--radius-sm)",
              border: "none",
              // Transparent — the active state is carried by the sliding pill
              // behind the label plus the text colour swap below.
              background: "transparent",
              color: isActive ? "var(--on-accent)" : "var(--text-2)",
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "color 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
            }}
          >
            {o.icon ?? o.label}
          </button>
        );
      })}
    </div>
  );
}

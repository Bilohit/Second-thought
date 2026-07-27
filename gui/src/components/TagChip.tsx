// Second Thought/gui/src/components/TagChip.tsx
//
// Void-styled tag chip, visual parity with the phone app's TagChip.tsx: 1px bordered box, mono
// font, text-2 label; dashed border for an unconfirmed/heuristic tag.
import type { CSSProperties } from "react";

export function TagChip({ label, dashed = false }: { label: string; dashed?: boolean }) {
  const style: CSSProperties = {
    display: "inline-flex", alignItems: "center",
    padding: "3px 8px", fontSize: 11, fontFamily: "inherit",
    color: "var(--text-2)", border: `1px ${dashed ? "dashed" : "solid"} var(--border)`,
    whiteSpace: "nowrap",
  };
  return <span style={style}>{label}</span>;
}

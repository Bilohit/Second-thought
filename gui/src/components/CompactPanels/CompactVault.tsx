/**
 * CompactVault.tsx
 * -----------------
 * Compact Mode Menu Decoupling, Task 2.4 (+ B3 de-clutter): FULL-parity
 * category tree + drill-in file list for the capsule's `CompactShell` body.
 * VaultManager's top-level action buttons (open vault folder / refresh /
 * new category) are lifted into CompactShell's `headerActions` slot instead
 * of duplicating a second header row (`compactHeader` on VaultManager); the
 * "By category" / "Daily rhythm" stat sections FullWindow's LibraryView
 * shows alongside VaultManager are dropped outright here — not enough room
 * at 288px to justify them, and they duplicate the History panel's stats.
 */
import type { ReactNode } from "react";
import VaultManager from "../VaultManager";

interface Props {
  onHeaderActionsChange?: (actions: ReactNode | null) => void;
}

export default function CompactVault({ onHeaderActionsChange }: Props) {
  return (
    <div style={{ height: "100%", minWidth: 0, position: "relative" }}>
      <VaultManager
        visible
        embedded
        compactHeader
        onHeaderActionsChange={onHeaderActionsChange}
        onClose={() => {}}
      />
    </div>
  );
}

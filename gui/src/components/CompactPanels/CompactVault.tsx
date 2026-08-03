/**
 * CompactVault.tsx
 * -----------------
 * Compact Mode Menu Decoupling, Task 2.4 (+ B3 de-clutter): FULL-parity
 * folder tree + drill-in file list for the capsule's `CompactShell` body.
 * VaultManager's top-level action buttons (open vault folder / refresh /
 * new project) are lifted into CompactShell's `headerActions` slot instead
 * of duplicating a second header row (`compactHeader` on VaultManager); the
 * "By project" stat section FullWindow's LibraryView shows alongside
 * VaultManager is dropped outright here — not enough room at 288px to
 * justify it, and it duplicates the History panel's own stats.
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

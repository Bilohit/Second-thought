/**
 * CompactInbox.tsx
 * -----------------
 * Compact Mode Menu Decoupling, Task 2.4 (+ B5 de-clutter): FULL-parity
 * Inbox content for the capsule's `CompactShell` body. `InboxPanel`'s own
 * header row is suppressed (`compactHeader`) — the Inbox/Reminders toggle
 * and refresh button it used to render inline move into CompactShell's
 * `headerActions` slot instead, so there's a single merged header
 * (`Inbox  [Inbox|Reminders] ↻`, no count badge) rather than two stacked
 * ones. Body rows (category select incl. "+ New folder…", Approve,
 * Discard, delete reminder) are unchanged — nothing re-flowed there.
 */
import type { ReactNode } from "react";
import InboxPanel from "../InboxPanel";

interface Props {
  onCountChange?: (count: number) => void;
  onHeaderActionsChange?: (actions: ReactNode | null) => void;
}

export default function CompactInbox({ onCountChange, onHeaderActionsChange }: Props) {
  return (
    <div style={{ height: "100%", minWidth: 0 }}>
      <InboxPanel
        visible
        embedded
        compactHeader
        onHeaderActionsChange={onHeaderActionsChange}
        onClose={() => {}}
        onCountChange={onCountChange}
      />
    </div>
  );
}

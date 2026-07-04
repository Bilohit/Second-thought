/**
 * CompactInbox.tsx
 * -----------------
 * Compact Mode Menu Decoupling, Task 2.4: FULL-parity Inbox content for the
 * capsule's `CompactShell` body. `InboxPanel` already has an `embedded` mode
 * (used by FullWindow's Inbox rail view) whose header carries both tabs
 * (Inbox / Reminders via `SegmentedToggle`), the badge count, and a refresh
 * button, and whose body carries every row action (category select incl.
 * "+ New folder…", Approve, Discard, delete reminder) — nothing needed
 * re-flowing for 288px, so this is a direct embed with no new layout code.
 */
import InboxPanel from "../InboxPanel";

interface Props {
  onCountChange?: (count: number) => void;
}

export default function CompactInbox({ onCountChange }: Props) {
  return (
    <div style={{ height: "100%", minWidth: 0 }}>
      <InboxPanel visible embedded onClose={() => {}} onCountChange={onCountChange} />
    </div>
  );
}

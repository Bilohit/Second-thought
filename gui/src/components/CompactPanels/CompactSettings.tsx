/**
 * CompactSettings.tsx
 * --------------------
 * Compact Mode Menu Decoupling, Task 2.4: FULL-parity Settings content for
 * the capsule's `CompactShell` body. Thin wrapper around the existing
 * `SettingsPanel` (embedded, no slide frame/close button of its own —
 * `CompactShell` already supplies both) with `compact` set so its
 * multi-button option rows stack into one column instead of clipping at
 * 288px (see `SettingsPanel.tsx`'s `optionRowStyle`). Every field FullWindow
 * exposes (Form tab: theme, display mode, corner, stay-pinned, placement,
 * display picker, fan style, snap; Function tab: vault path, hotkey, model,
 * inbox sensitivity, classification strictness, auto-describe, reminders,
 * log level, geometry debug, look-chat persist, look chat system prompt) is
 * still rendered — GATE-3: no control dropped, only re-flowed.
 */
import SettingsPanel from "../SettingsPanel";
import type { SettingsForward } from "../FullWindow/FullWindow";

interface Props extends SettingsForward {
  onClose: () => void;
}

export default function CompactSettings({ onClose, ...settingsProps }: Props) {
  return (
    <div style={{ height: "100%", minWidth: 0 }}>
      <SettingsPanel visible onClose={onClose} embedded compact {...settingsProps} />
    </div>
  );
}

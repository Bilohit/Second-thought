/**
 * Toggle.tsx
 * ----------
 * The ONE boolean idiom (Wave 4): a `role="switch"` pill with a sliding knob,
 * used for every real on/off state control. Promoted out of Sync/parts.tsx —
 * originated there but is not sync-specific, so it now lives with the other
 * generic controls in ui/. Token-styled only (no literal colors); self-contained
 * (imports nothing but React itself).
 */

export function Toggle({
  checked, onChange, label, disabled = false,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  const W = 34, H = 18, KNOB = H - 6;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        width: W,
        height: H,
        flexShrink: 0,
        padding: 0,
        position: "relative",
        background: "var(--surface)",
        border: `1px solid ${checked && !disabled ? "var(--green)" : "var(--border)"}`,
        borderRadius: "var(--radius-sm)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        transition: "border-color 160ms var(--hover-ease-out)",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          position: "absolute",
          top: 2,
          left: 2,
          width: KNOB,
          height: KNOB,
          background: checked && !disabled ? "var(--green)" : "var(--text-3)",
          transform: checked ? `translateX(${W - H + 2}px)` : "translateX(0)",
          transition: "transform 160ms var(--hover-ease-out), background 160ms var(--hover-ease-out)",
        }}
      />
    </button>
  );
}

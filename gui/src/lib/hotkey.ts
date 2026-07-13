/**
 * hotkey.ts
 * ---------
 * Hotkey display formatting. Split out of the old config.ts re-export shim
 * (config access lives in lib/api.ts; this file is display-only helpers).
 */

/** Human-readable display label for a raw hotkey string like "ctrl+shift+space" */
export function formatHotkey(raw: string): string {
  return raw
    .split("+")
    .map((part) => {
      const map: Record<string, string> = {
        ctrl: "Ctrl",
        control: "Ctrl",
        cmd: "⌘",
        meta: "⌘",
        alt: "⌥",
        option: "⌥",
        shift: "⇧",
        space: "Space",
        backspace: "⌫",
        enter: "↵",
        tab: "⇥",
      };
      return map[part.toLowerCase()] ?? part.toUpperCase();
    })
    .join(" + ");
}

/** Default hotkey if config.toml doesn't have a [gui] section yet */
export const DEFAULT_HOTKEY = "ctrl+shift+space";

/**
 * JS mirror of `parse_shortcut` in `src-tauri/src/lib.rs` — must stay in
 * sync with it. Rust's parser silently skips any `+`-segment it doesn't
 * recognize (modifiers, space/enter/tab/backspace, or a single A–Z/0–9
 * char) and only fails to produce a `Shortcut` when NO segment resolved to
 * an actual key code (e.g. "ctrl+escape", "ctrl+f1", "ctrl+arrowup"). This
 * lets SettingsPanel (A-2) reject an unparsable hotkey client-side, before
 * it's ever sent to `patchConfig`/`setHotkeyRust`.
 */
export function canParseHotkey(hotkey: string): boolean {
  let hasKeyCode = false;
  for (const rawPart of hotkey.split("+")) {
    const part = rawPart.trim().toLowerCase();
    switch (part) {
      case "ctrl":
      case "control":
      case "cmd":
      case "meta":
      case "alt":
      case "option":
      case "shift":
        break;
      case "space":
      case "enter":
      case "return":
      case "tab":
      case "backspace":
        hasKeyCode = true;
        break;
      default:
        if (part.length === 1 && /[a-z0-9]/.test(part)) hasKeyCode = true;
        // else: unknown key part — skip (mirrors Rust's silent skip)
        break;
    }
  }
  return hasKeyCode;
}

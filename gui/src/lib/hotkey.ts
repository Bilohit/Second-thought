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

/**
 * config.ts
 * ---------
 * Thin wrapper for reading and writing config preferences via the Python server.
 *
 * The hotkey string is stored in config.toml under [gui] hotkey = "..."
 * and re-registered in Rust at startup by reading it from disk.
 */

import { getConfig, patchConfig, type Config } from "./api";

export { getConfig, patchConfig, type Config };

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

/**
 * smartConnectionsPref.ts — the single source of truth for the STARS "Smart connections" client-only
 * pref (s152). Two surfaces read/write it now — `BrowseStarsView.tsx` (the sky's own quiet toggle)
 * and `SettingsPanel.tsx` (the user's ruling that the setting also belongs in Settings, so it's
 * reachable the same way the phone's Settings screen will eventually reach it) — and they must never
 * drift: flipping it in either place has to update an already-mounted instance of the other live.
 *
 * Same shape as `lib/devTuning.ts`'s store (module-singleton + listener Set + a subscribing hook),
 * the existing idiom in this codebase for a client-only pref shared by more than one reader. NOT a
 * `useSyncExternalStore` + `storage`-event design: this is a single-window Tauri app, so the browser
 * `storage` event (which only fires in OTHER documents) would never fire between two panels in the
 * SAME window — the listener Set is what actually crosses that gap.
 *
 * SAME localStorage key BrowseStarsView.tsx shipped with in s152 — never migrated, never renamed.
 */
import { useEffect, useState } from "react";

export const SMART_CONNECTIONS_KEY = "omni-stars-smart-connections";

function load(): boolean {
  try {
    return localStorage.getItem(SMART_CONNECTIONS_KEY) === "1";
  } catch { /* ignore */ }
  return false;
}

let current: boolean = load();
const listeners = new Set<(v: boolean) => void>();

export function getSmartConnectionsPref(): boolean {
  return current;
}

export function setSmartConnectionsPref(enabled: boolean): void {
  current = enabled;
  try {
    localStorage.setItem(SMART_CONNECTIONS_KEY, enabled ? "1" : "0");
  } catch { /* ignore */ }
  listeners.forEach((l) => l(current));
}

/** Live-subscribes to the pref; re-renders on every setSmartConnectionsPref call from ANY mounted
 *  reader (BrowseStarsView, SettingsPanel), which is what keeps the two surfaces in sync. */
export function useSmartConnectionsPref(): [boolean, (enabled: boolean) => void] {
  const [value, setValue] = useState(current);
  useEffect(() => {
    listeners.add(setValue);
    return () => { listeners.delete(setValue); };
  }, []);
  return [value, setSmartConnectionsPref];
}

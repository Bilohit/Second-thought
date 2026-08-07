/**
 * skyPrefs.ts — the STARS sky's two persisted client-only prefs (s156): the density index and the
 * SKY panel's open state. Same shape as `lib/smartConnectionsPref.ts` (module-singleton + listener
 * Set + a subscribing hook) — the existing idiom in this codebase for a client-only pref shared by
 * more than one reader, and NOT a `useSyncExternalStore` + `storage`-event design for the same reason
 * that file gives: this is a single-window Tauri app, so the browser `storage` event (which only
 * fires in OTHER documents) would never fire between two panels in the SAME window.
 *
 * Bundled into one module (rather than two, one per pref) because both are read and written from the
 * same place — `SkyPanel.tsx` via `BrowseStarsView.tsx` — with no independent second reader today;
 * splitting them would just be two copies of the same load/save/listener boilerplate.
 */
import { useEffect, useState } from "react";
import { densityStep, DENSITY_STEPS, DENSITY_DEFAULT_INDEX } from "./starsSim";

export const DENSITY_KEY = "omni-stars-density";
export const PANEL_OPEN_KEY = "omni-stars-panel-open";

/** `densityStep` returns the actual DENSITY_STEPS element it clamped to, so indexOf recovers the
 *  clamped INDEX from it — a stored value that is out of range or malformed (or absent) resolves
 *  through the same clamp `buildStarEdges` itself uses, never to `-1` or `NaN`. */
function clampToIndex(raw: number): number {
  const idx = DENSITY_STEPS.indexOf(densityStep(raw));
  return idx === -1 ? DENSITY_DEFAULT_INDEX : idx;
}

function loadDensityIndex(): number {
  try {
    const raw = localStorage.getItem(DENSITY_KEY);
    if (raw == null) return DENSITY_DEFAULT_INDEX;
    return clampToIndex(Number(raw));
  } catch { /* ignore */ }
  return DENSITY_DEFAULT_INDEX;
}

let currentDensityIndex: number = loadDensityIndex();
const densityListeners = new Set<(v: number) => void>();

export function getDensityIndex(): number {
  return currentDensityIndex;
}

export function setDensityIndex(index: number): void {
  currentDensityIndex = clampToIndex(index);
  try {
    localStorage.setItem(DENSITY_KEY, String(currentDensityIndex));
  } catch { /* ignore */ }
  densityListeners.forEach((l) => l(currentDensityIndex));
}

/** Default `true` when the key is ABSENT (D2: open on first visit), `false` only once the user has
 *  actually collapsed it. Deliberately NOT a `"1"`-means-on decode — that reads a missing key as
 *  closed, the opposite of the ruling. */
function loadPanelOpen(): boolean {
  try {
    const raw = localStorage.getItem(PANEL_OPEN_KEY);
    if (raw == null) return true;
    return raw === "1";
  } catch { /* ignore */ }
  return true;
}

let currentPanelOpen: boolean = loadPanelOpen();
const panelOpenListeners = new Set<(v: boolean) => void>();

export function getPanelOpen(): boolean {
  return currentPanelOpen;
}

export function setPanelOpen(open: boolean): void {
  currentPanelOpen = open;
  try {
    localStorage.setItem(PANEL_OPEN_KEY, open ? "1" : "0");
  } catch { /* ignore */ }
  panelOpenListeners.forEach((l) => l(currentPanelOpen));
}

/** Live-subscribes to both prefs; re-renders on every set*() call from ANY mounted reader — the same
 *  cross-surface live-update shape as `useSmartConnectionsPref`. */
export function useSkyPrefs(): {
  densityIndex: number;
  setDensityIndex: (index: number) => void;
  panelOpen: boolean;
  setPanelOpen: (open: boolean) => void;
} {
  const [densityIndex, setDensityIndexState] = useState(currentDensityIndex);
  const [panelOpen, setPanelOpenState] = useState(currentPanelOpen);
  useEffect(() => {
    densityListeners.add(setDensityIndexState);
    panelOpenListeners.add(setPanelOpenState);
    return () => {
      densityListeners.delete(setDensityIndexState);
      panelOpenListeners.delete(setPanelOpenState);
    };
  }, []);
  return { densityIndex, setDensityIndex, panelOpen, setPanelOpen };
}

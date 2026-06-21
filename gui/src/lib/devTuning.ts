/**
 * devTuning.ts
 * ------------
 * Hidden dev-only troubleshooting tuner state (for_sonnet.md "Dev-only
 * troubleshooting tuner"). Off by default, not part of normal Settings.
 * Persists to its own localStorage key and overrides the production
 * `unifiedFan` defaults live — every reader (RadialMenu, App.tsx's window
 * sizing, DevTuner itself) shares this one module-level store so an edit in
 * the tuner is reflected everywhere in the same render pass.
 */
import { useEffect, useState } from "react";

export interface RadialTuning {
  radius: number;
  minSpacingDeg: number;
  chipMax: number;
  chipMin: number;
  pad: number;
  spreadMaxArc: number;
  /** null = no override, defer to the Settings "Fan style" choice. The
   *  tuner's A/B toggle sets an explicit value that wins until Reset. */
  fanStyleOverride: "spread" | "capped" | null;
}

export const RADIAL_TUNING_KEY = "omni-radial-tuning";

// Mirrors the production constants table in for_sonnet.md.
export const RADIAL_TUNING_DEFAULTS: RadialTuning = {
  radius: 100,
  minSpacingDeg: 34,
  chipMax: 36,
  chipMin: 33,
  pad: 0,
  spreadMaxArc: 300,
  fanStyleOverride: null,
};

function load(): RadialTuning {
  try {
    const saved = JSON.parse(localStorage.getItem(RADIAL_TUNING_KEY) ?? "{}");
    return { ...RADIAL_TUNING_DEFAULTS, ...saved };
  } catch {
    return RADIAL_TUNING_DEFAULTS;
  }
}

let current: RadialTuning = load();
const listeners = new Set<(t: RadialTuning) => void>();

export function getRadialTuning(): RadialTuning {
  return current;
}

export function setRadialTuning(next: Partial<RadialTuning>) {
  current = { ...current, ...next };
  try { localStorage.setItem(RADIAL_TUNING_KEY, JSON.stringify(current)); } catch { /* ignore */ }
  listeners.forEach((l) => l(current));
}

export function resetRadialTuning() {
  current = RADIAL_TUNING_DEFAULTS;
  try { localStorage.removeItem(RADIAL_TUNING_KEY); } catch { /* ignore */ }
  listeners.forEach((l) => l(current));
}

/** Live-subscribes to the tuning store; re-renders on every setRadialTuning. */
export function useRadialTuning(): RadialTuning {
  const [tuning, setTuningState] = useState(current);
  useEffect(() => {
    listeners.add(setTuningState);
    return () => { listeners.delete(setTuningState); };
  }, []);
  return tuning;
}

/** Ctrl+Shift+Alt+G toggles the hidden tuner overlay's visibility. */
export function useDevTunerVisible(): boolean {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.altKey && e.code === "KeyG") {
        e.preventDefault();
        setVisible((v) => !v);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  return visible;
}

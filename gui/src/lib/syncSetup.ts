// Pure derivations for the Settings -> Sync tab (E6). Everything the tab shows is
// resolved here from real server state; the components only fetch, commit, and render.
//
// Three concerns, one module, because they are all "what does the Sync tab derive
// from {config, /sync/status, /drive/auth/status, PairingInfo}":
//   1. resolveSyncSetup  — the wizard/dashboard state machine (the tab's spine)
//   2. resolve*Tone      — semantic colour, wired to real state (never a hardcoded green)
//   3. interval sentinel — `Never` (0) vs the server's min-5 clamp
//
// No side effects, no fetches, no React. See sibling syncSetup.test.ts.

// ── 1. The wizard/dashboard state machine ───────────────────────────────────
//
// The user's journey, verbatim from the E6 spec:
//
//   master toggle "Syncing System"
//        OFF ------------->  DASHBOARD, rendered in its "sync off" state
//        ON + not set up ->  WIZARD: step 1 Drive -> step 2 LAN -> done
//        ON + set up ----->  DASHBOARD
//   Wizard completion -> DASHBOARD.
//
// "Set up" is derived, never a persisted flag: setup is complete exactly when Drive
// is connected. That is the honest definition — Drive is the only required plane
// (LAN is an accelerator that is never a dependency, per CLAUDE.md's baseline
// reachability lock), and it needs no new config field the backend would have to
// carry. A LAN step that is skipped forever therefore never reads as unfinished.

export type SyncView = "wizard" | "dashboard";

/** Wizard progression. `done` is terminal: the resolver maps it straight to the dashboard. */
export type WizardStep = "drive" | "lan" | "done";

export interface SyncSetupInputs {
  /** `[sync] enabled` — the master "Syncing System" switch. OFF means the whole system is off. */
  master: boolean;
  /** `/drive/auth/status` -> connected. The sole "is setup complete" signal. */
  driveConnected: boolean;
  /**
   * Session flag: the user is walking the wizard right now. Set when they enter it
   * (auto on a not-set-up tab, or explicitly via "Set up sync again"), cleared on
   * Cancel. It is what keeps step 2 (LAN) reachable after step 1 connects Drive —
   * without it, `driveConnected` flipping true mid-wizard would eject the user to
   * the dashboard before they were ever offered the LAN step.
   */
  wizardActive: boolean;
  /**
   * Session flag: the wizard was cancelled without connecting Drive. Stops the tab
   * from auto-reopening the wizard on top of the user who just left it.
   */
  setupDismissed: boolean;
  /**
   * Wizard step 2 was closed by the user — either "Skip" or "Done" after enabling
   * the accelerator. Deliberately NOT derived from the LAN toggle: flipping the
   * toggle on would otherwise complete the step and eject the user to the dashboard
   * mid-way through scanning the QR the toggle just revealed.
   */
  lanStepDone: boolean;
}

export interface SyncSetupResolution {
  view: SyncView;
  /** Only meaningful when `view === "wizard"`; `done` never renders as a step. */
  step: WizardStep;
  /** Dashboard renders its "sync off" state: no passes, no manual run, no setup. */
  masterOff: boolean;
}

export function resolveSyncSetup(i: SyncSetupInputs): SyncSetupResolution {
  // Master OFF outranks everything, including an active wizard: "no automatic passes,
  // no manual Sync now, no setup shown, nothing syncs at all". Turning the system off
  // mid-wizard must not leave the wizard on screen still asking for a Google grant.
  if (!i.master) return { view: "dashboard", step: "drive", masterOff: true };

  if (i.wizardActive) {
    const step = resolveWizardStep(i);
    // Wizard completion -> DASHBOARD, resolved here rather than by a component effect,
    // so there is no frame where a finished wizard is still mounted.
    if (step === "done") return { view: "dashboard", step, masterOff: false };
    return { view: "wizard", step, masterOff: false };
  }

  // Not set up and not dismissed -> the tab opens on the wizard by itself.
  if (!i.driveConnected && !i.setupDismissed) {
    return { view: "wizard", step: "drive", masterOff: false };
  }

  return { view: "dashboard", step: i.driveConnected ? "done" : "drive", masterOff: false };
}

/** Step 1 is Drive (done by connecting), step 2 is LAN (done by enabling or skipping). */
function resolveWizardStep(i: SyncSetupInputs): WizardStep {
  if (!i.driveConnected) return "drive";
  if (!i.lanStepDone) return "lan";
  return "done";
}

// ── 2. Semantic tone ────────────────────────────────────────────────────────
//
// green/yellow/red are semantic ONLY and must be wired to real state. `none` is the
// unknown/neutral tone and renders as --text-3 — never green. A green dot wired to
// nothing has already shipped once in this codebase and is a lock violation, which
// is why every tone below is a tested function of real server fields rather than a
// literal in a component.

export type StatusTone = "ok" | "wait" | "fail" | "none";

export interface DriveToneInputs {
  connected: boolean;
  connecting: boolean;
  clientSecretPresent: boolean;
}

export function resolveDriveTone(i: DriveToneInputs): StatusTone {
  // Missing OAuth credentials is the one state the Connect button cannot fix, so it
  // is a real failure even though nothing has been attempted yet.
  if (!i.clientSecretPresent) return "fail";
  if (i.connecting) return "wait";
  if (i.connected) return "ok";
  // Not connected is not an error — it is simply not set up yet.
  return "none";
}

export interface SyncToneInputs {
  /** `[sync] enabled`. */
  master: boolean;
  /** `/sync/status` -> running. */
  running: boolean;
  /**
   * False when `/sync/status` omitted `interval_minutes`, which is exactly how the
   * server reports "the scheduler never started" (the 503 condition).
   */
  schedulerStarted: boolean;
  /** `/sync/status` -> last_pass. `null` means no pass has ever run. */
  lastPassOk: boolean | null;
}

export function resolveSyncTone(i: SyncToneInputs): StatusTone {
  // With the system off, a stopped scheduler is the correct state, not a fault.
  if (!i.master) return "none";
  if (i.running) return "wait";
  if (!i.schedulerStarted) return "fail";
  // Never run -> unknown. This is the case that must not be green.
  if (i.lastPassOk === null) return "none";
  return i.lastPassOk ? "ok" : "fail";
}

export interface LanToneInputs {
  enabled: boolean;
  /** `PairingInfo.lan_ip` resolved to a real address. */
  hasLanIp: boolean;
  /** A bind/secret change is written but not yet served — needs a restart. */
  restartRequired: boolean;
}

export function resolveLanTone(i: LanToneInputs): StatusTone {
  if (!i.enabled) return "none";
  // Enabled but not actually serving the current secret / not reachable: both are
  // "on, but not working yet" — yellow, never green.
  if (i.restartRequired) return "wait";
  if (!i.hasLanIp) return "wait";
  return "ok";
}

// ── 3. Interval: the `Never` sentinel and the server's clamp ────────────────

/** `interval_minutes = 0` means "no automatic passes of any kind". Manual Sync now still works. */
export const NEVER_INTERVAL_MINUTES = 0;

/** The server's existing floor for any real interval. Values above 0 clamp up to this. */
export const MIN_INTERVAL_MINUTES = 5;

export function intervalIsNever(minutes: number): boolean {
  return minutes === NEVER_INTERVAL_MINUTES;
}

/**
 * Mirrors the server's rule so the UI never shows a value the backend would silently
 * rewrite: 0 is the `Never` sentinel and survives untouched; anything above 0 clamps
 * to >= 5. A negative or non-numeric interval is nonsense rather than a request for a
 * fast pass, so it resolves to `Never` — the safe direction (it cannot cause traffic).
 */
export function normalizeIntervalMinutes(minutes: number): number {
  if (!Number.isFinite(minutes)) return NEVER_INTERVAL_MINUTES;
  const n = Math.round(minutes);
  if (n <= 0) return NEVER_INTERVAL_MINUTES;
  return Math.max(MIN_INTERVAL_MINUTES, n);
}

/**
 * Whether the automatic triggers (`sync_on_launch` / `sync_after_capture`) can fire at
 * all. When this is false their toggles are inoperative and must be shown disabled with
 * a reason — never silently ignored.
 */
export function autoPassesActive(master: boolean, intervalMinutes: number): boolean {
  return master && !intervalIsNever(intervalMinutes);
}

// ── 4. The dashboard gauge ──────────────────────────────────────────────────
//
// The one round instrument on the tab, and the only thing that earns the shape:
// it is wired to elapsed-since-last-pass over the interval. When there is nothing
// real to count it reads empty rather than inventing a position.

export interface GaugeInputs {
  intervalMinutes: number;
  /** `Date.parse(last_pass.started)`, or null when no pass has ever run. */
  lastPassStartedMs: number | null;
  nowMs: number;
}

export interface GaugeResolution {
  /** 0..1 of the interval elapsed. 0 whenever there is no real basis to count from. */
  fraction: number;
  /** Whole minutes to the next automatic pass, or null when none is scheduled. */
  minutesRemaining: number | null;
}

const EMPTY_GAUGE: GaugeResolution = { fraction: 0, minutesRemaining: null };

export function resolveGauge(i: GaugeInputs): GaugeResolution {
  // `Never` schedules no pass, so there is no countdown to draw.
  if (intervalIsNever(normalizeIntervalMinutes(i.intervalMinutes))) return EMPTY_GAUGE;
  // No pass has ever run (or the timestamp did not parse) — there is no anchor to
  // measure from, so the gauge shows empty instead of guessing a position.
  if (i.lastPassStartedMs === null || !Number.isFinite(i.lastPassStartedMs)) return EMPTY_GAUGE;

  const elapsedMinutes = (i.nowMs - i.lastPassStartedMs) / 60_000;
  // A clock skew / future timestamp must not draw a negative arc.
  if (elapsedMinutes < 0) return { fraction: 0, minutesRemaining: i.intervalMinutes };

  const fraction = Math.min(1, elapsedMinutes / i.intervalMinutes);
  const minutesRemaining = Math.max(0, Math.ceil(i.intervalMinutes - elapsedMinutes));
  return { fraction, minutesRemaining };
}

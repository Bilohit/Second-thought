import { describe, expect, it } from "vitest";
import {
  resolveSyncSetup,
  resolveDriveTone,
  resolveSyncTone,
  resolveLanTone,
  normalizeIntervalMinutes,
  intervalIsNever,
  autoPassesActive,
  resolveGauge,
  MIN_INTERVAL_MINUTES,
  NEVER_INTERVAL_MINUTES,
  type SyncSetupInputs,
} from "./syncSetup";

// Baseline: system on, nothing set up, tab just opened. Resolves to the wizard.
const base: SyncSetupInputs = {
  master: true,
  driveConnected: false,
  wizardActive: false,
  setupDismissed: false,
  lanStepDone: false,
};

function setup(overrides: Partial<SyncSetupInputs>) {
  return resolveSyncSetup({ ...base, ...overrides });
}

describe("resolveSyncSetup", () => {
  describe("the three journey rows from the E6 spec", () => {
    it("master OFF -> dashboard in its sync-off state", () => {
      const r = setup({ master: false });
      expect(r.view).toBe("dashboard");
      expect(r.masterOff).toBe(true);
    });

    it("master ON + not set up -> wizard at step 1 (Drive)", () => {
      const r = setup({ driveConnected: false });
      expect(r.view).toBe("wizard");
      expect(r.step).toBe("drive");
      expect(r.masterOff).toBe(false);
    });

    it("master ON + set up -> dashboard", () => {
      const r = setup({ driveConnected: true });
      expect(r.view).toBe("dashboard");
      expect(r.masterOff).toBe(false);
    });
  });

  describe("master OFF outranks every other input", () => {
    // "OFF = the whole system is off: no automatic passes, no manual Sync now,
    // no setup shown, nothing syncs at all." Turning the system off mid-wizard
    // must not leave the wizard on screen still asking for a Google grant.
    it("hides an active wizard when the master switch goes off", () => {
      const r = setup({ master: false, wizardActive: true, driveConnected: false });
      expect(r.view).toBe("dashboard");
      expect(r.masterOff).toBe(true);
    });

    it("never auto-opens setup while off, however un-set-up the system is", () => {
      const r = setup({ master: false, driveConnected: false, setupDismissed: false });
      expect(r.view).toBe("dashboard");
    });
  });

  describe("wizard progression: step 1 Drive -> step 2 LAN -> done", () => {
    it("holds step 2 (LAN) open after Drive connects mid-wizard", () => {
      // The regression this input exists for: driveConnected flipping true during
      // the wizard must NOT eject the user to the dashboard before they have been
      // offered the LAN step at all.
      const r = setup({ wizardActive: true, driveConnected: true });
      expect(r.view).toBe("wizard");
      expect(r.step).toBe("lan");
    });

    it("completes to the dashboard once the user closes step 2", () => {
      // LAN is an accelerator, never a dependency — Skip and Done both complete setup.
      const r = setup({ wizardActive: true, driveConnected: true, lanStepDone: true });
      expect(r.view).toBe("dashboard");
      expect(r.step).toBe("done");
    });

    it("holds step 2 open while the accelerator is being set up", () => {
      // The step must NOT complete off the LAN toggle itself: enabling the
      // accelerator reveals the pairing QR, and completing there would eject the
      // user to the dashboard mid-scan.
      const r = setup({ wizardActive: true, driveConnected: true, lanStepDone: false });
      expect(r.view).toBe("wizard");
      expect(r.step).toBe("lan");
    });

    it("stays on step 1 while Drive is unconnected, even if step 2 was already closed", () => {
      const r = setup({ wizardActive: true, driveConnected: false, lanStepDone: true });
      expect(r.view).toBe("wizard");
      expect(r.step).toBe("drive");
    });
  });

  describe("auto-enter and Cancel", () => {
    it("auto-opens the wizard on a not-set-up tab", () => {
      expect(setup({ wizardActive: false, driveConnected: false }).view).toBe("wizard");
    });

    it("Cancel (dismissed, Drive still unconnected) lands on the dashboard and stays there", () => {
      // Cancel must not bounce straight back into the wizard it just left.
      const r = setup({ wizardActive: false, setupDismissed: true, driveConnected: false });
      expect(r.view).toBe("dashboard");
      expect(r.masterOff).toBe(false);
    });

    it("re-entering the wizard with Drive already connected reopens it at the LAN step", () => {
      // "Set up sync again" on a connected system: step 1 is already satisfied.
      const r = setup({ wizardActive: true, driveConnected: true, setupDismissed: true });
      expect(r.view).toBe("wizard");
      expect(r.step).toBe("lan");
    });

    it("a dismissed setup does not suppress the wizard once it is re-entered", () => {
      const r = setup({ wizardActive: true, setupDismissed: true, driveConnected: false });
      expect(r.view).toBe("wizard");
      expect(r.step).toBe("drive");
    });
  });
});

describe("resolveDriveTone", () => {
  const drive = { connected: false, connecting: false, clientSecretPresent: true };

  it("is `none` (not green) when Drive was simply never connected", () => {
    expect(resolveDriveTone({ ...drive })).toBe("none");
  });

  it("is `ok` only for a real connection", () => {
    expect(resolveDriveTone({ ...drive, connected: true })).toBe("ok");
  });

  it("is `wait` while a consent window is open", () => {
    expect(resolveDriveTone({ ...drive, connecting: true })).toBe("wait");
  });

  it("is `fail` when client_secret.json is missing — Connect cannot fix it", () => {
    expect(resolveDriveTone({ ...drive, clientSecretPresent: false })).toBe("fail");
    // Outranks connecting/connected: without credentials neither is real.
    expect(resolveDriveTone({ connected: true, connecting: false, clientSecretPresent: false })).toBe("fail");
  });
});

describe("resolveSyncTone", () => {
  const sync = { master: true, running: false, schedulerStarted: true, lastPassOk: true as boolean | null };

  it("is `ok` for a successful last pass", () => {
    expect(resolveSyncTone({ ...sync })).toBe("ok");
  });

  it("is `fail` for ok:false — the most likely real-world state, not an edge case", () => {
    expect(resolveSyncTone({ ...sync, lastPassOk: false })).toBe("fail");
  });

  it("is `none` (never green) when no pass has ever run", () => {
    expect(resolveSyncTone({ ...sync, lastPassOk: null })).toBe("none");
  });

  it("is `wait` while a pass is running", () => {
    expect(resolveSyncTone({ ...sync, running: true })).toBe("wait");
  });

  it("is `fail` when the scheduler never started (the 503 condition)", () => {
    expect(resolveSyncTone({ ...sync, schedulerStarted: false })).toBe("fail");
  });

  it("is `none` with the master off — a stopped scheduler is then correct, not a fault", () => {
    expect(resolveSyncTone({ ...sync, master: false, schedulerStarted: false })).toBe("none");
    expect(resolveSyncTone({ ...sync, master: false, lastPassOk: false })).toBe("none");
  });
});

describe("resolveLanTone", () => {
  const lan = { enabled: true, hasLanIp: true, restartRequired: false };

  it("is `none` when the accelerator is off", () => {
    expect(resolveLanTone({ ...lan, enabled: false })).toBe("none");
  });

  it("is `ok` when enabled and actually reachable", () => {
    expect(resolveLanTone({ ...lan })).toBe("ok");
  });

  it("is `wait` (never green) when enabled but no LAN IP was found", () => {
    expect(resolveLanTone({ ...lan, hasLanIp: false })).toBe("wait");
  });

  it("is `wait` when a restart is needed before the new secret is served", () => {
    expect(resolveLanTone({ ...lan, restartRequired: true })).toBe("wait");
  });
});

describe("interval sentinel and clamp", () => {
  it("keeps 0 as the `Never` sentinel instead of clamping it up to 5", () => {
    // The whole point: the server turns 0 into a 5-minute pass unless the
    // sentinel is honoured, which would make the `Never` option a lie.
    expect(normalizeIntervalMinutes(0)).toBe(NEVER_INTERVAL_MINUTES);
    expect(intervalIsNever(normalizeIntervalMinutes(0))).toBe(true);
  });

  it("clamps any real interval up to the 5-minute floor", () => {
    expect(normalizeIntervalMinutes(1)).toBe(MIN_INTERVAL_MINUTES);
    expect(normalizeIntervalMinutes(4)).toBe(MIN_INTERVAL_MINUTES);
    expect(normalizeIntervalMinutes(5)).toBe(5);
  });

  it("leaves values above the floor untouched", () => {
    expect(normalizeIntervalMinutes(60)).toBe(60);
    expect(normalizeIntervalMinutes(1440)).toBe(1440);
  });

  it("resolves nonsense to `Never` — the direction that cannot cause traffic", () => {
    expect(normalizeIntervalMinutes(-10)).toBe(NEVER_INTERVAL_MINUTES);
    expect(normalizeIntervalMinutes(NaN)).toBe(NEVER_INTERVAL_MINUTES);
  });

  it("rounds fractional input rather than passing a float to the server", () => {
    expect(normalizeIntervalMinutes(59.6)).toBe(60);
  });
});

describe("autoPassesActive", () => {
  it("is false on `Never`, so on-launch/after-capture render disabled with a reason", () => {
    expect(autoPassesActive(true, NEVER_INTERVAL_MINUTES)).toBe(false);
  });

  it("is false with the master off", () => {
    expect(autoPassesActive(false, 60)).toBe(false);
  });

  it("is true only when the system is on and an interval is set", () => {
    expect(autoPassesActive(true, 60)).toBe(true);
  });
});

describe("resolveGauge", () => {
  const NOW = 1_700_000_000_000;
  const minutesAgo = (m: number) => NOW - m * 60_000;

  it("reads a real position from elapsed-over-interval", () => {
    const g = resolveGauge({ intervalMinutes: 60, lastPassStartedMs: minutesAgo(15), nowMs: NOW });
    expect(g.fraction).toBeCloseTo(0.25);
    expect(g.minutesRemaining).toBe(45);
  });

  it("is empty on `Never` — there is no pass to count down to", () => {
    const g = resolveGauge({ intervalMinutes: 0, lastPassStartedMs: minutesAgo(15), nowMs: NOW });
    expect(g.fraction).toBe(0);
    expect(g.minutesRemaining).toBeNull();
  });

  it("is empty when no pass has ever run, rather than guessing a position", () => {
    const g = resolveGauge({ intervalMinutes: 60, lastPassStartedMs: null, nowMs: NOW });
    expect(g.fraction).toBe(0);
    expect(g.minutesRemaining).toBeNull();
  });

  it("is empty when the last-pass timestamp did not parse", () => {
    const g = resolveGauge({ intervalMinutes: 60, lastPassStartedMs: NaN, nowMs: NOW });
    expect(g.fraction).toBe(0);
    expect(g.minutesRemaining).toBeNull();
  });

  it("saturates at a full arc when the pass is overdue, never past 1", () => {
    const g = resolveGauge({ intervalMinutes: 60, lastPassStartedMs: minutesAgo(600), nowMs: NOW });
    expect(g.fraction).toBe(1);
    expect(g.minutesRemaining).toBe(0);
  });

  it("does not draw a negative arc when the clock skews backwards", () => {
    const g = resolveGauge({ intervalMinutes: 60, lastPassStartedMs: NOW + 60_000, nowMs: NOW });
    expect(g.fraction).toBe(0);
    expect(g.minutesRemaining).toBe(60);
  });
});

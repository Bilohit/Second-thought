/**
 * Sync/SyncPanel.tsx
 * ------------------
 * The Settings -> Sync tab body (E6). Owns the tab's master switch and every fetch;
 * delegates "which view am I" to the pure resolveSyncSetup() in lib/syncSetup.ts and
 * the rendering to SyncWizard (direction A) / SyncDashboard (direction B).
 *
 * The two sync switches are DIFFERENT things and are deliberately not merged:
 *   · master "Syncing System" (`[sync] enabled`) — off means the whole system is off:
 *     no automatic passes, no manual Sync now (the server refuses it with a 403), no
 *     setup shown, nothing syncs at all.
 *   · interval `Never` (`interval_minutes = 0`)  — on, but no automatic passes of any
 *     kind. Manual Sync now still works and the setup stands.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getConfig, patchConfig, getSyncStatus, runSync,
  getDriveAuthStatus, connectDrive, disconnectDrive,
  type SyncStatus, type DriveAuthStatus, type SyncRunResult,
} from "../../lib/api";
import { setPairingEnabled } from "../../lib/tauri";
import {
  resolveSyncSetup, resolveDriveTone, resolveSyncTone, resolveLanTone,
  normalizeIntervalMinutes,
} from "../../lib/syncSetup";
import PairingPanel, { type PairingState } from "../PairingPanel";
import SyncWizard from "./SyncWizard";
import SyncDashboard, { type SyncSettings } from "./SyncDashboard";
import { Toggle } from "../ui/Toggle";

// omni_capture/config.py:SyncConfig — the fallbacks when [sync] is absent from the
// TOML entirely. Kept in sync with the server's dataclass by hand, deliberately: a
// wrong guess here would auto-save a value the user never chose.
const DEFAULTS: SyncSettings = {
  intervalMinutes: 60,
  syncOnLaunch: true,
  syncAfterCapture: false,
  mirrorCaptures: false,
};

const POLL_MS = 4000;

export default function SyncPanel({ compact }: { compact: boolean }) {
  const [master, setMaster] = useState(false);
  const [settings, setSettings] = useState<SyncSettings>(DEFAULTS);
  const [drive, setDrive] = useState<DriveAuthStatus | null>(null);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [lan, setLan] = useState<PairingState>({ info: null, restartRequired: false });

  const [connecting, setConnecting] = useState(false);
  const [driveError, setDriveError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState<SyncRunResult | null>(null);

  // Session-scoped view state — the inputs resolveSyncSetup() cannot derive from
  // the server. See lib/syncSetup.ts for why each one exists.
  const [wizardActive, setWizardActive] = useState(false);
  const [setupDismissed, setSetupDismissed] = useState(false);
  const [lanStepDone, setLanStepDone] = useState(false);

  // Config is only read once per mount; a poll would race the user's own edits and
  // revert a toggle mid-flight. Server status polls freely because it is read-only.
  const loadedRef = useRef(false);
  // What the LAN toggle was when the wizard was entered — Cancel restores exactly this.
  const lanOnWizardEntryRef = useRef<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const cfg = await getConfig();
        if (cancelled) return;
        setMaster(cfg.sync?.enabled ?? false);
        setSettings({
          intervalMinutes: cfg.sync?.interval_minutes ?? DEFAULTS.intervalMinutes,
          syncOnLaunch: cfg.sync?.sync_on_launch ?? DEFAULTS.syncOnLaunch,
          syncAfterCapture: cfg.sync?.sync_after_capture ?? DEFAULTS.syncAfterCapture,
          mirrorCaptures: cfg.sync?.mirror_captures ?? DEFAULTS.mirrorCaptures,
        });
        loadedRef.current = true;
      } catch {
        // Server not up yet. Leave loadedRef false so no edit can auto-save over the
        // real on-disk config with a fallback — same guard as SettingsPanel's loader.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const poll = useCallback(async () => {
    const [d, s] = await Promise.allSettled([getDriveAuthStatus(), getSyncStatus()]);
    if (d.status === "fulfilled") setDrive(d.value);
    if (s.status === "fulfilled") {
      setStatus(s.value);
      // The server is the authority on whether a pass is in flight — a local `running`
      // flag alone would strand the spinner if the pass finished in another window.
      setRunning(s.value.running);
    }
  }, []);

  useEffect(() => {
    void poll();
    const t = setInterval(() => { void poll(); }, POLL_MS);
    return () => clearInterval(t);
  }, [poll]);

  // ── Commits ───────────────────────────────────────────────────────────────

  const commitMaster = async (next: boolean) => {
    if (!loadedRef.current) return;
    setMaster(next);
    setLastRun(null);
    try {
      await patchConfig({ sync_enabled: next });
    } catch {
      setMaster(!next); // nothing persisted — put the switch back where it was
    }
  };

  const commitSettings = async (patch: Partial<SyncSettings>) => {
    if (!loadedRef.current) return;
    const prev = settings;
    const next = { ...settings, ...patch };
    if (patch.intervalMinutes !== undefined) {
      // Show the server's own rule rather than letting it silently rewrite the value.
      next.intervalMinutes = normalizeIntervalMinutes(patch.intervalMinutes);
    }
    setSettings(next);
    try {
      await patchConfig({
        sync_interval_minutes: next.intervalMinutes,
        sync_on_launch: next.syncOnLaunch,
        sync_after_capture: next.syncAfterCapture,
        sync_mirror_captures: next.mirrorCaptures,
      });
    } catch {
      setSettings(prev);
    }
  };

  const onConnectDrive = async () => {
    setDriveError(null);
    setConnecting(true);
    try {
      // Resolves only when the user finishes or abandons the real browser consent
      // window, which is why the pending state has its own way out (onStopWaiting).
      const r = await connectDrive();
      if (r.outcome === "failed") setDriveError(r.error);
      else if (r.outcome === "no_client_secret") setDriveError("Google credentials file not found.");
      else if (r.outcome === "busy") setDriveError("A sign-in window is already open.");
    } catch (e) {
      setDriveError(e instanceof Error ? e.message : String(e));
    } finally {
      setConnecting(false);
      void poll();
    }
  };

  const onDisconnectDrive = async () => {
    setDriveError(null);
    try {
      await disconnectDrive();
    } catch (e) {
      setDriveError(e instanceof Error ? e.message : String(e));
    } finally {
      void poll();
    }
  };

  const onRunSync = async () => {
    setRunning(true);
    setLastRun(null);
    try {
      const r = await runSync();
      setLastRun(r);
    } catch (e) {
      setDriveError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
      void poll();
    }
  };

  // ── Wizard navigation ─────────────────────────────────────────────────────

  const enterWizard = () => {
    lanOnWizardEntryRef.current = lan.info?.enabled ?? null;
    setLanStepDone(false);
    setSetupDismissed(false);
    setWizardActive(true);
  };

  /**
   * Cancel exits to the dashboard and leaves config exactly as it was on entry —
   * except the Drive token, which is a real Google grant and is NOT silently revoked.
   * The wizard says so on screen rather than pretending otherwise.
   */
  const onCancelWizard = async () => {
    const entry = lanOnWizardEntryRef.current;
    if (entry !== null && lan.info && lan.info.enabled !== entry) {
      try { await setPairingEnabled(entry); } catch { /* leave it; the panel refetches on remount */ }
    }
    lanOnWizardEntryRef.current = null;
    setWizardActive(false);
    setSetupDismissed(true);
  };

  const onSkipDrive = () => {
    // Nothing after Drive can do anything without it, so skipping step 1 leaves setup.
    setWizardActive(false);
    setSetupDismissed(true);
  };

  const finishWizard = () => {
    setLanStepDone(true);
    setWizardActive(false);
  };

  // ── Resolve ───────────────────────────────────────────────────────────────

  const driveConnected = drive?.connected ?? false;

  const resolution = resolveSyncSetup({
    master,
    driveConnected,
    wizardActive,
    setupDismissed,
    lanStepDone,
  });

  const driveTone = resolveDriveTone({
    connected: driveConnected,
    connecting: connecting || (drive?.connecting ?? false),
    clientSecretPresent: drive?.client_secret_present ?? true,
  });

  const syncTone = resolveSyncTone({
    master,
    running,
    schedulerStarted: status?.interval_minutes !== undefined,
    lastPassOk: status?.last_pass ? status.last_pass.ok : null,
  });

  const lanTone = resolveLanTone({
    enabled: lan.info?.enabled ?? false,
    hasLanIp: Boolean(lan.info?.lan_ip ?? lan.info?.host),
    restartRequired: lan.restartRequired,
  });

  const lanLabel =
    !lan.info?.enabled ? "off · Drive only"
    : lan.restartRequired ? "restart required before the change is served"
    : lan.info.lan_ip ?? lan.info.host
      ? `listening on ${lan.info.lan_ip ?? lan.info.host}:${lan.info.port}`
      : "no network address found";

  const onLanState = useCallback((s: PairingState) => setLan(s), []);
  const lanSection = <PairingPanel compact={compact} onStateChange={onLanState} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: compact ? 12 : 16 }}>
      {/* The master switch: above both views, because it decides which one shows. */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        paddingBottom: 12, borderBottom: "1px solid var(--border-2)",
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, color: "var(--text-1)" }}>Syncing system</div>
        </div>
        <Toggle label="Syncing system" checked={master} onChange={(v) => void commitMaster(v)} />
      </div>

      {resolution.view === "wizard" ? (
        <SyncWizard
          compact={compact}
          step={resolution.step}
          drive={drive}
          driveTone={driveTone}
          connecting={connecting}
          driveError={driveError}
          onConnectDrive={() => void onConnectDrive()}
          onStopWaiting={() => setConnecting(false)}
          onSkipDrive={onSkipDrive}
          lanSection={lanSection}
          onLanDone={finishWizard}
          onSkipLan={finishWizard}
          onCancel={() => void onCancelWizard()}
        />
      ) : (
        <SyncDashboard
          compact={compact}
          masterOff={resolution.masterOff}
          drive={drive}
          driveTone={driveTone}
          status={status}
          syncTone={syncTone}
          settings={settings}
          onChangeSettings={(p) => void commitSettings(p)}
          onConnectDrive={() => void onConnectDrive()}
          onDisconnectDrive={() => void onDisconnectDrive()}
          connecting={connecting}
          driveError={driveError}
          onRunSync={() => void onRunSync()}
          running={running}
          lastRun={lastRun}
          onRunSetupAgain={enterWizard}
          lanSection={lanSection}
          lanTone={lanTone}
          lanLabel={lanLabel}
        />
      )}
    </div>
  );
}

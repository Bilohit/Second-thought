/**
 * Sync/SyncDashboard.tsx
 * ----------------------
 * Direction B — "two planes". The resting state of the Sync tab: shown whenever
 * the system is set up, and whenever the master switch is off.
 *
 * Thesis (from the approved mock): the mental model is the layout. Drive is one
 * large instrument panel; the same-WiFi shortcut hangs off it on a rail, inset and
 * a type-step down, with no instrument of its own. You learn the hierarchy by
 * looking, not by reading a caption — so hierarchy is carried by scale, weight and
 * containment, never by dimming a healthy thing.
 *
 * Deviation from the mock, per the E6 spec's binding finetunes: the mock's
 * `PLANE 1` / `PLANE 2` labels are cut for plain language, and the account email
 * line is dropped (/drive/auth/status does not return an email and will not).
 */
import type { ReactNode } from "react";
import type { StatusTone } from "../../lib/syncSetup";
import {
  resolveGauge, intervalIsNever,
  NEVER_INTERVAL_MINUTES,
} from "../../lib/syncSetup";
import type { DriveAuthStatus, SyncStatus, SyncRunResult } from "../../lib/api";
import { CloudIcon, RefreshIcon, AlertIcon } from "../PillMenu/icons";
import { BTN_SECONDARY } from "../ui/styles";
import { Toggle } from "../ui/Toggle";
import {
  Group, SettingRow, Note, StatusDot, TONE_COLOR,
} from "./parts";

export interface SyncSettings {
  intervalMinutes: number;
  syncOnLaunch: boolean;
  syncAfterCapture: boolean;
  mirrorCaptures: boolean;
}

interface Props {
  compact: boolean;
  masterOff: boolean;
  drive: DriveAuthStatus | null;
  driveTone: StatusTone;
  status: SyncStatus | null;
  syncTone: StatusTone;
  settings: SyncSettings;
  onChangeSettings: (patch: Partial<SyncSettings>) => void;
  onConnectDrive: () => void;
  onDisconnectDrive: () => void;
  connecting: boolean;
  driveError: string | null;
  onRunSync: () => void;
  running: boolean;
  lastRun: SyncRunResult | null;
  onRunSetupAgain: () => void;
  /** The absorbed PairingPanel, rendered by the parent. */
  lanSection: ReactNode;
  lanTone: StatusTone;
  lanLabel: string;
}

// ── The gauge: the one round instrument, wired to real data ──────────────────

const GAUGE_R = 46;
const GAUGE_C = 2 * Math.PI * GAUGE_R;

function Gauge({
  size, fraction, tone, value, unit, running, textless = false,
}: {
  size: number;
  fraction: number;
  tone: StatusTone;
  value: string;
  unit: string;
  running: boolean;
  /** Textless: no center value/unit, thicker ring so it stays legible small.
   *  The value/unit still carry the aria-label, so screen readers lose nothing. */
  textless?: boolean;
}) {
  const empty = tone === "none";
  const strokeWidth = textless ? 7 : 3;
  return (
    <div
      role="img"
      aria-label={`${value} ${unit.toLowerCase()}`}
      style={{ position: "relative", width: size, height: size, flexShrink: 0 }}
    >
      <svg
        viewBox="0 0 104 104"
        width={size}
        height={size}
        aria-hidden="true"
        style={{
          display: "block",
          transform: "rotate(-90deg)",
          animation: running ? "spin 900ms linear infinite" : undefined,
        }}
      >
        <circle
          cx="52" cy="52" r={GAUGE_R} fill="none" strokeWidth={strokeWidth}
          // Unknown reads as a dashed empty track, never a lit ring.
          stroke={empty ? "var(--text-3)" : "var(--border)"}
          strokeDasharray={empty ? "3 4" : undefined}
        />
        {!empty && (
          <circle
            cx="52" cy="52" r={GAUGE_R} fill="none" strokeWidth={strokeWidth} strokeLinecap="butt"
            stroke={running ? "var(--text-1)" : TONE_COLOR[tone]}
            strokeDasharray={GAUGE_C}
            strokeDashoffset={GAUGE_C * (1 - fraction)}
            style={{ transition: "stroke-dashoffset 260ms var(--menu-travel-ease), stroke 160ms var(--hover-ease-out)" }}
          />
        )}
      </svg>
      {!textless && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", gap: 1, pointerEvents: "none",
        }}>
          <span style={{ fontSize: size > 80 ? 17 : 12, fontWeight: 600, letterSpacing: "-0.03em", color: "var(--text-1)" }}>
            {value}
          </span>
          <span style={{ fontSize: size > 80 ? 8.5 : 7.5, letterSpacing: "0.06em", color: "var(--text-3)", textAlign: "center", padding: "0 4px" }}>
            {unit}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Interval control: `Never` is a first-class choice, not an edge case ──────

const PRESETS: { minutes: number; label: string }[] = [
  { minutes: NEVER_INTERVAL_MINUTES, label: "Never" },
  { minutes: 15, label: "15m" },
  { minutes: 60, label: "1h" },
  { minutes: 360, label: "6h" },
  { minutes: 1440, label: "24h" },
];

function IntervalControl({
  minutes, onChange, disabled, compact,
}: {
  minutes: number;
  onChange: (m: number) => void;
  disabled: boolean;
  compact: boolean;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      {/* Wraps rather than overflowing: the capsule panel is 288px and this group
          must never push its own row wider than the panel. */}
      <div role="group" aria-label="Sync interval" style={{ display: "flex", flexWrap: "wrap" }}>
        {PRESETS.map((p, idx) => {
          const active = p.minutes === minutes;
          return (
            <button
              key={p.minutes}
              type="button"
              className="btn-hover"
              aria-pressed={active}
              disabled={disabled}
              onClick={() => onChange(p.minutes)}
              style={{
                ...BTN_SECONDARY,
                fontSize: compact ? 10.5 : 11,
                padding: compact ? "4px 7px" : "4px 8px",
                marginLeft: idx === 0 ? 0 : -1,
                background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                borderColor: active ? "var(--accent)" : "var(--border)",
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.4 : 1,
              }}
            >
              {p.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── The Drive plane's own schedule ──────────────────────────────────────────

function Schedule({
  compact, masterOff, settings, onChangeSettings, delay,
}: Pick<Props, "compact" | "masterOff" | "settings" | "onChangeSettings"> & { delay: number }) {
  const never = intervalIsNever(settings.intervalMinutes);

  return (
    <Group label="Schedule" delay={delay} gap={6}>
      <div>
      <SettingRow title="Auto-sync" disabled={masterOff}>
        <IntervalControl
          minutes={settings.intervalMinutes}
          onChange={(m) => onChangeSettings({ intervalMinutes: m })}
          disabled={masterOff}
          compact={compact}
        />
      </SettingRow>

      {never && !masterOff && (
        <Note style={{ padding: "8px 0" }}>
          No automatic passes will run. Sync now still works.
        </Note>
      )}

      <SettingRow title="On launch" disabled={masterOff}>
        <Toggle
          label="Sync on launch"
          checked={settings.syncOnLaunch}
          disabled={masterOff}
          onChange={(v) => onChangeSettings({ syncOnLaunch: v })}
        />
      </SettingRow>

      <SettingRow title="After capture" disabled={masterOff}>
        <Toggle
          label="Sync after capture"
          checked={settings.syncAfterCapture}
          disabled={masterOff}
          onChange={(v) => onChangeSettings({ syncAfterCapture: v })}
        />
      </SettingRow>

      <SettingRow
        title="Mirror captures"
        disabled={masterOff}
        last
      >
        <Toggle
          label="Mirror captures to the hub"
          checked={settings.mirrorCaptures}
          disabled={masterOff}
          onChange={(v) => onChangeSettings({ mirrorCaptures: v })}
        />
      </SettingRow>
      </div>
    </Group>
  );
}

// ── Banner: the ok:false / 503 / 403 / no-credentials surface ────────────────

function Banner({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <div style={{
      display: "flex", gap: 8, alignItems: "flex-start",
      margin: 0,
      border: `1px solid ${tone === "none" ? "var(--border)" : TONE_COLOR[tone]}`,
      borderRadius: "var(--radius)",
      padding: 12, fontSize: 11, color: "var(--text-2)", lineHeight: 1.6,
    }}>
      <span aria-hidden="true" style={{ flexShrink: 0, marginTop: 2, color: TONE_COLOR[tone], display: "flex" }}>
        <AlertIcon size={14} />
      </span>
      <span>{children}</span>
    </div>
  );
}

// ── The dashboard ───────────────────────────────────────────────────────────

export default function SyncDashboard({
  compact, masterOff, drive, driveTone, status, syncTone,
  settings, onChangeSettings, onConnectDrive, onDisconnectDrive,
  connecting, driveError, onRunSync, running, lastRun, onRunSetupAgain,
  lanSection, lanTone, lanLabel,
}: Props) {
  const connected = drive?.connected ?? false;
  const secretMissing = drive ? !drive.client_secret_present : false;
  const schedulerStarted = status?.interval_minutes !== undefined;

  const gauge = resolveGauge({
    intervalMinutes: settings.intervalMinutes,
    lastPassStartedMs: status?.last_pass ? Date.parse(status.last_pass.started) : null,
    nowMs: Date.now(),
  });
  // The gauge is Drive's instrument: it reads the sync tone, and goes blank the
  // moment there is nothing real to count.
  const gaugeTone: StatusTone = masterOff || !connected ? "none" : syncTone;
  const gaugeValue =
    running ? "···"
    : gauge.minutesRemaining === null ? "—"
    : `${gauge.minutesRemaining}m`;
  const gaugeUnit =
    running ? "RUNNING"
    : masterOff ? "SYNCING OFF"
    : !connected ? "NOT CONNECTED"
    : intervalIsNever(settings.intervalMinutes) ? "NO AUTOMATIC PASSES"
    : gauge.minutesRemaining === null ? "NO PASS YET"
    : compact ? "TO NEXT" : "TO NEXT PASS";

  const stateText =
    masterOff ? "syncing system is off"
    : secretMissing ? "credentials file missing"
    : connecting || drive?.connecting ? "waiting for browser consent"
    : !connected ? "not connected"
    : running ? "pass running"
    : status?.last_pass && !status.last_pass.ok ? "last pass failed"
    : status?.last_pass ? "connected · syncing"
    : "connected";

  const banner: { tone: StatusTone; body: ReactNode } | null =
    masterOff ? {
      tone: "none",
      body: <>The syncing system is off. No passes run, automatic or manual, and nothing is sent anywhere. Your setup below is kept exactly as it is.</>,
    }
    : secretMissing ? {
      tone: "fail",
      body: <>Google credentials file not found. Drive cannot be connected until an OAuth client file is in place.</>,
    }
    : driveError ? { tone: "fail", body: <>{driveError}</> }
    : lastRun?.outcome === "disabled" ? {
      tone: "fail",
      body: <>The server refused the pass: the syncing system is off.</>,
    }
    : lastRun?.outcome === "busy" ? {
      tone: "wait",
      body: <>A pass is already running. This one was not started.</>,
    }
    : lastRun?.outcome === "unavailable" ? {
      tone: "fail",
      body: <>The background scheduler is not running, so no pass could start. Restart Second Thought.</>,
    }
    : connected && !schedulerStarted ? {
      tone: "fail",
      body: <>Drive is connected but the background scheduler is not running, so no automatic pass will fire. Restart Second Thought.</>,
    }
    : connected && status?.last_pass && !status.last_pass.ok ? {
      tone: "fail",
      body: <>
        Drive refused the last pass{status.last_pass.error ? <> — <span style={{ color: "var(--text-1)" }}>{status.last_pass.error}</span></> : null}.
        {" "}Your notes are untouched and queued; the next pass will try again.
      </>,
    }
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: compact ? 16 : 20 }}>
      {/* DRIVE — the plane that has to work. Flat on the panel surface, same
          Field dialect as the Form/Function tabs (no card, no darker fill). */}
      <Group label="Drive" delay={0} gap={compact ? 10 : 12}>
        {compact ? (
          // Compact (mock variant A1): textless ring at the left, title + status
          // column to its right — no tagline, no side-by-side buttons.
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Gauge
              size={34}
              fraction={gauge.fraction}
              tone={gaugeTone}
              value={gaugeValue}
              unit={gaugeUnit}
              running={running}
              textless
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 12.5, fontWeight: 600, color: "var(--text-1)",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                Google Drive
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: "var(--text-2)", marginTop: 2 }}>
                <StatusDot tone={masterOff ? "none" : driveTone} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{stateText}</span>
              </div>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
            <Gauge
              size={84}
              fraction={gauge.fraction}
              tone={gaugeTone}
              value={gaugeValue}
              unit={gaugeUnit}
              running={running}
            />

            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 15, fontWeight: 600, letterSpacing: "-0.02em",
                color: "var(--text-1)", display: "flex", alignItems: "center", gap: 8,
              }}>
                <span aria-hidden="true" style={{ display: "flex", flexShrink: 0 }}><CloudIcon size={16} /></span>
                Google Drive
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, color: "var(--text-2)", marginTop: 5 }}>
                <StatusDot tone={masterOff ? "none" : driveTone} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{stateText}</span>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end", flexShrink: 0 }}>
              {connected ? (
                <>
                  <button
                    type="button"
                    className="btn-hover"
                    disabled={masterOff || running}
                    onClick={onRunSync}
                    style={{
                      ...BTN_SECONDARY,
                      background: "var(--text-1)", color: "var(--bg)", borderColor: "var(--text-1)",
                      fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 6,
                      cursor: masterOff || running ? "not-allowed" : "pointer",
                      opacity: masterOff || running ? 0.4 : 1,
                    }}
                  >
                    <span aria-hidden="true" style={{ display: "flex", animation: running ? "spin 900ms linear infinite" : undefined }}>
                      <RefreshIcon size={12} />
                    </span>
                    {running ? "Running" : "Sync now"}
                  </button>
                  <button
                    type="button"
                    className="btn-hover"
                    onClick={onDisconnectDrive}
                    style={{
                      background: "none", border: "none", font: "inherit",
                      fontSize: 12, color: "var(--text-3)", padding: 2, cursor: "pointer",
                    }}
                  >
                    Disconnect
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn-hover"
                  disabled={masterOff || secretMissing || connecting}
                  onClick={onConnectDrive}
                  style={{
                    ...BTN_SECONDARY,
                    background: "var(--text-1)", color: "var(--bg)", borderColor: "var(--text-1)", fontWeight: 600,
                    cursor: masterOff || secretMissing || connecting ? "not-allowed" : "pointer",
                    opacity: masterOff || secretMissing || connecting ? 0.4 : 1,
                  }}
                >
                  {connecting ? "Waiting…" : "Connect Drive"}
                </button>
              )}
            </div>
          </div>
        )}

        {/* Compact: primary full-width, Disconnect demoted to a ghost line below
            (approved design mock A1). Full window keeps the pair beside the gauge. */}
        {compact && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {connected ? (
              <>
                <button
                  type="button"
                  className="btn-hover"
                  disabled={masterOff || running}
                  onClick={onRunSync}
                  style={{
                    ...BTN_SECONDARY, width: "100%", justifyContent: "center",
                    display: "inline-flex", alignItems: "center", gap: 6,
                    background: "var(--text-1)", color: "var(--bg)", borderColor: "var(--text-1)", fontWeight: 600,
                    cursor: masterOff || running ? "not-allowed" : "pointer",
                    opacity: masterOff || running ? 0.4 : 1,
                  }}
                >
                  <span aria-hidden="true" style={{ display: "flex", animation: running ? "spin 900ms linear infinite" : undefined }}>
                    <RefreshIcon size={12} />
                  </span>
                  {running ? "Running" : "Sync now"}
                </button>
                <button
                  type="button"
                  className="btn-hover"
                  onClick={onDisconnectDrive}
                  style={{
                    alignSelf: "center", background: "none", border: "none", font: "inherit",
                    fontSize: 12, color: "var(--text-3)", padding: 6, cursor: "pointer",
                  }}
                >
                  Disconnect
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn-hover"
                disabled={masterOff || secretMissing || connecting}
                onClick={onConnectDrive}
                style={{
                  ...BTN_SECONDARY, width: "100%", justifyContent: "center",
                  background: "var(--text-1)", color: "var(--bg)", borderColor: "var(--text-1)", fontWeight: 600,
                  cursor: masterOff || secretMissing || connecting ? "not-allowed" : "pointer",
                  opacity: masterOff || secretMissing || connecting ? 0.4 : 1,
                }}
              >
                {connecting ? "Waiting…" : "Connect Drive"}
              </button>
            )}
          </div>
        )}
      </Group>

      {banner && <Banner tone={banner.tone}>{banner.body}</Banner>}

      <Schedule compact={compact} masterOff={masterOff} settings={settings} onChangeSettings={onChangeSettings} delay={compact ? 45 : 90} />

      {/* SAME-WIFI SHORTCUT — the accelerator; Drive still does the sync. Now a
          flat Field group like the rest, not a docked card on a rail. */}
      <Group label="Same-WiFi shortcut" delay={compact ? 90 : 135}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: "var(--text-2)" }}>
          <StatusDot tone={lanTone} />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lanLabel}</span>
        </div>
        {lanSection}
      </Group>

      {/* Re-entry to the guided setup. */}
      <button
        type="button"
        onClick={onRunSetupAgain}
        disabled={masterOff}
        style={{
          alignSelf: "flex-start",
          background: "none", border: "none", font: "inherit", fontSize: 11,
          color: "var(--text-3)", textDecoration: "underline",
          padding: "4px 0",
          cursor: masterOff ? "not-allowed" : "pointer",
          opacity: masterOff ? 0.4 : 1,
        }}
      >
        Walk through setup again
      </button>
    </div>
  );
}

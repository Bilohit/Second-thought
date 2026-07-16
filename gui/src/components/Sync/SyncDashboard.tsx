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
import { useState } from "react";
import type { ReactNode } from "react";
import type { StatusTone } from "../../lib/syncSetup";
import {
  resolveGauge, intervalIsNever, autoPassesActive,
  NEVER_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES,
} from "../../lib/syncSetup";
import type { DriveAuthStatus, SyncStatus, SyncRunResult } from "../../lib/api";
import { CloudIcon, RefreshIcon, ChevronRightIcon, AlertIcon } from "../PillMenu/icons";
import { BTN_SECONDARY, INPUT_STYLE } from "../ui/styles";
import { Toggle } from "../ui/Toggle";
import {
  SettingRow, Note, StatusDot, TONE_COLOR,
  passTime, passSummary, passTone,
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
  size, fraction, tone, value, unit, running,
}: {
  size: number;
  fraction: number;
  tone: StatusTone;
  value: string;
  unit: string;
  running: boolean;
}) {
  const empty = tone === "none";
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
          cx="52" cy="52" r={GAUGE_R} fill="none" strokeWidth="3"
          // Unknown reads as a dashed empty track, never a lit ring.
          stroke={empty ? "var(--text-3)" : "var(--border)"}
          strokeDasharray={empty ? "3 4" : undefined}
        />
        {!empty && (
          <circle
            cx="52" cy="52" r={GAUGE_R} fill="none" strokeWidth="3" strokeLinecap="butt"
            stroke={running ? "var(--text-1)" : TONE_COLOR[tone]}
            strokeDasharray={GAUGE_C}
            strokeDashoffset={GAUGE_C * (1 - fraction)}
            style={{ transition: "stroke-dashoffset 260ms var(--menu-travel-ease), stroke 160ms var(--hover-ease-out)" }}
          />
        )}
      </svg>
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
  const [draft, setDraft] = useState<string | null>(null);
  const custom = !PRESETS.some((p) => p.minutes === minutes);

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
              onClick={() => { setDraft(null); onChange(p.minutes); }}
              style={{
                ...BTN_SECONDARY,
                fontSize: 11,
                padding: "4px 8px",
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
      {!compact && (
        <>
          <input
            type="number"
            min={MIN_INTERVAL_MINUTES}
            aria-label="Custom interval in minutes"
            disabled={disabled}
            value={draft ?? (custom ? String(minutes) : "")}
            placeholder={custom ? undefined : "custom"}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => {
              if (draft === null) return;
              if (draft.trim() === "") { setDraft(null); return; }
              // The server's real clamp, applied where the user can see it happen.
              onChange(Math.max(MIN_INTERVAL_MINUTES, Math.round(Number(draft))));
              setDraft(null);
            }}
            style={{ ...INPUT_STYLE, width: 72, textAlign: "right", opacity: disabled ? 0.4 : 1 }}
          />
          <span style={{ fontSize: 11, color: "var(--text-3)" }}>min</span>
        </>
      )}
    </div>
  );
}

// ── The Drive plane's own schedule ──────────────────────────────────────────

function Schedule({
  compact, masterOff, settings, onChangeSettings,
}: Pick<Props, "compact" | "masterOff" | "settings" | "onChangeSettings">) {
  const never = intervalIsNever(settings.intervalMinutes);
  const autoLive = autoPassesActive(!masterOff, settings.intervalMinutes);

  return (
    <div style={{ borderTop: "1px solid var(--border-2)", padding: compact ? 12 : "16px 20px 8px" }}>
      <div style={{ fontSize: 10, letterSpacing: "0.08em", color: "var(--text-3)", marginBottom: 8 }}>
        SCHEDULE
      </div>

      <SettingRow title="How often" sub="Drive runs a pass in the background" disabled={masterOff} stack={compact}>
        <IntervalControl
          minutes={settings.intervalMinutes}
          onChange={(m) => onChangeSettings({ intervalMinutes: m })}
          disabled={masterOff}
          compact={compact}
        />
      </SettingRow>

      {never && !masterOff && (
        <Note style={{ padding: "8px 0" }}>
          No automatic passes of any kind will run. Sync now still works, and your setup stays exactly
          as it is.
        </Note>
      )}

      <SettingRow title="Also sync when the app starts" disabled={!autoLive}>
        <Toggle
          label="Sync on launch"
          checked={settings.syncOnLaunch}
          disabled={!autoLive}
          onChange={(v) => onChangeSettings({ syncOnLaunch: v })}
        />
      </SettingRow>

      <SettingRow title="Also sync after every capture" disabled={!autoLive}>
        <Toggle
          label="Sync after capture"
          checked={settings.syncAfterCapture}
          disabled={!autoLive}
          onChange={(v) => onChangeSettings({ syncAfterCapture: v })}
        />
      </SettingRow>

      {/* Inoperative controls say why, rather than being silently ignored. */}
      {!autoLive && (
        <Note style={{ padding: "2px 0 8px" }}>
          {masterOff
            ? "Turn the syncing system on to use these."
            : "These two do nothing while the schedule is set to Never — they are automatic passes."}
        </Note>
      )}

      <SettingRow
        title="Also copy captures to Drive"
        sub="captures are not notes · off by default"
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
  );
}

// ── History ─────────────────────────────────────────────────────────────────

function History({ status, compact }: { status: SyncStatus | null; compact: boolean }) {
  const [open, setOpen] = useState(false);
  const rows = status?.history ?? [];
  const last = status?.last_pass ?? null;

  return (
    <>
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: compact ? "8px 12px" : "12px 20px",
        borderTop: "1px solid var(--border-2)",
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, color: "var(--text-1)" }}>Last pass</div>
          <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {last ? `${passTime(last.started)} · ${passSummary(last)}` : "never"}
          </div>
        </div>
        {rows.length > 0 && (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            style={{
              background: "none", border: "none", font: "inherit", fontSize: 11,
              color: "var(--text-3)", cursor: "pointer", display: "inline-flex",
              alignItems: "center", gap: 5, padding: "2px 4px",
            }}
          >
            <span style={{
              display: "flex",
              transform: open ? "rotate(90deg)" : "rotate(0deg)",
              transition: "transform 160ms var(--hover-ease-out)",
            }}>
              <ChevronRightIcon size={12} />
            </span>
            History
          </button>
        )}
      </div>

      {open && (
        <div style={{ borderTop: "1px solid var(--border-2)" }}>
          {rows.map((row, i) => (
            <div
              key={`${row.started}-${i}`}
              className="sync-rise"
              style={{
                display: "flex", alignItems: "center", gap: 9,
                padding: compact ? "5px 12px" : "5px 20px 5px 44px",
                fontSize: 11, color: "var(--text-2)",
                borderBottom: i === rows.length - 1 ? "none" : "1px solid var(--border-2)",
                animationDelay: `${i * 45}ms`,
              }}
            >
              <StatusDot tone={passTone(row)} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {passTime(row.started)} · {passSummary(row)}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ── Banner: the ok:false / 503 / 403 / no-credentials surface ────────────────

function Banner({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <div style={{
      display: "flex", gap: 8, alignItems: "flex-start",
      margin: "0 20px 16px",
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

  const pad = compact ? 12 : 20;

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {/* ── Drive: the plane that has to work ── */}
      <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", background: "var(--bg)" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: compact ? 12 : 20, padding: pad, alignItems: "flex-start" }}>
          <Gauge
            size={compact ? 60 : 104}
            fraction={gauge.fraction}
            tone={gaugeTone}
            value={gaugeValue}
            unit={gaugeUnit}
            running={running}
          />

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontSize: compact ? 13 : 15, fontWeight: 600, letterSpacing: "-0.02em",
              color: "var(--text-1)", display: "flex", alignItems: "center", gap: 8,
            }}>
              <span aria-hidden="true" style={{ display: "flex", flexShrink: 0 }}><CloudIcon size={16} /></span>
              Google Drive
            </div>
            <div className="sync-rise" style={{ display: "flex", alignItems: "center", gap: 7, fontSize: compact ? 11 : 12, color: "var(--text-2)", marginTop: 5 }}>
              <StatusDot tone={masterOff ? "none" : driveTone} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{stateText}</span>
            </div>
            {!compact && (
              <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 3 }}>
                Your notes, both ways, in batches. Nothing else here works without it.
              </div>
            )}
          </div>

          {!compact && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
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
                  <button type="button" className="btn-hover" style={BTN_SECONDARY} onClick={onDisconnectDrive}>
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
          )}
        </div>

        {banner && <Banner tone={banner.tone}>{banner.body}</Banner>}

        {compact && (
          <div style={{ display: "flex", gap: 8, padding: `0 ${pad}px ${pad}px` }}>
            {connected ? (
              <button
                type="button"
                className="btn-hover"
                disabled={masterOff || running}
                onClick={onRunSync}
                style={{
                  ...BTN_SECONDARY, flex: 1, justifyContent: "center",
                  background: "var(--text-1)", color: "var(--bg)", borderColor: "var(--text-1)", fontWeight: 600,
                  cursor: masterOff || running ? "not-allowed" : "pointer",
                  opacity: masterOff || running ? 0.4 : 1,
                }}
              >
                {running ? "Running" : "Sync now"}
              </button>
            ) : (
              <button
                type="button"
                className="btn-hover"
                disabled={masterOff || secretMissing || connecting}
                onClick={onConnectDrive}
                style={{
                  ...BTN_SECONDARY, flex: 1, justifyContent: "center",
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

        <History status={status} compact={compact} />

        {/* Drive's own settings, inside Drive's border — so they cannot be misread as app-wide. */}
        <Schedule compact={compact} masterOff={masterOff} settings={settings} onChangeSettings={onChangeSettings} />
      </div>

      {/* ── The shortcut, docked to the plane it accelerates ── */}
      <div style={{ position: "relative", paddingLeft: compact ? 18 : 32, paddingTop: 20 }}>
        <span aria-hidden="true" style={{
          position: "absolute", left: compact ? 8 : 15, top: 0, bottom: 0, width: 1, background: "var(--border)",
        }} />
        <span aria-hidden="true" style={{
          position: "absolute", left: compact ? 8 : 15, top: "50%", width: compact ? 10 : 17, height: 1, background: "var(--border)",
        }} />

        <div style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--text-3)", marginBottom: 8 }}>
          OPTIONAL
        </div>

        <div style={{ border: "1px solid var(--border-2)", borderRadius: "var(--radius)", background: "var(--bg)", padding: compact ? 12 : "12px 16px" }}>
          <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--text-1)", marginBottom: 4 }}>
            Same-WiFi shortcut
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: "var(--text-2)", marginBottom: 3 }}>
            <StatusDot tone={lanTone} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lanLabel}</span>
          </div>
          {!compact && (
            <Note style={{ marginBottom: 12 }}>
              Moves files faster when the phone is on this network. Drive still does the sync — turning
              this off changes nothing about what syncs, only how fast.
            </Note>
          )}
          {lanSection}
        </div>
      </div>

      {/* Re-entry to the guided setup. */}
      <button
        type="button"
        onClick={onRunSetupAgain}
        disabled={masterOff}
        style={{
          alignSelf: "flex-start", marginTop: 16,
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

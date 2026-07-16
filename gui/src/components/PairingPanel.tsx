/**
 * PairingPanel.tsx
 * -----------------
 * Same-WiFi LAN file-sync pairing.
 *
 *   · Toggle: enable/disable the LAN listener (accelerator only; Drive
 *     remains the sync fallback — see CLAUDE.md "Amendment 2026-07-11").
 *   · QR: encodes {v:3,host,port,key,secret,device} (contract §9/§11.4) for the phone to scan.
 *   · Rotate secret: writes a new [gui] secret; effective after restart.
 *
 * Kept out of the 1000+ line SettingsPanel per plan Task 6.
 *
 * E6: this stopped being its own "Pairing" tab and is now the LAN section of the
 * Sync tab — rendered as step 2 of SyncWizard and as the docked plane of
 * SyncDashboard. Every behaviour above is unchanged; the tab only moved. The one
 * addition is the optional `onStateChange` report, so the host can render the LAN
 * status beside its own planes without this component losing ownership of the
 * fetch (the same lift-state-to-the-host idiom as VaultManager/InboxPanel's
 * `onHeaderActionsChange`).
 */

import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import {
  getPairingInfo, setPairingEnabled, rotateSecret, buildPairingPayload,
  type PairingInfo,
} from "../lib/tauri";
import { getLanDeviceId } from "../lib/api";
import { resolveLanTone } from "../lib/syncSetup";
import { INPUT_STYLE, BTN_SECONDARY } from "./ui/styles";
import { Toggle } from "./ui/Toggle";
import { TONE_COLOR } from "./Sync/parts";

// ── Small labelled row (mirrors SettingsPanel's local Field) ────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <label
        style={{
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--text-3)",
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}

/** What the host needs to render LAN status outside this panel. */
export interface PairingState {
  info: PairingInfo | null;
  /** A bind/secret change is written but not served until the app restarts. */
  restartRequired: boolean;
}

export default function PairingPanel({
  compact,
  onStateChange,
}: {
  compact: boolean;
  /** Optional (E6): report state up so the Sync tab can show the LAN dot on its own plane header. */
  onStateChange?: (state: PairingState) => void;
}) {
  const [info, setInfo] = useState<PairingInfo | null>(null);
  const [device, setDevice] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restartHint, setRestartHint] = useState(false);

  const qrSize = compact ? 160 : 220;

  // Fetches PairingInfo (Rust get_pairing_info) once on mount only — this call spawns a
  // blocking ipconfig subprocess, so it must never re-fire on a parent re-render (was the
  // pairing-tab lag: qrSize/compact used to be a refresh() dependency).
  const refresh = useCallback(async () => {
    const i = await getPairingInfo();
    setInfo(i);
    // Device-id (v3 QR anchor) is stable; fetch once — a failure just leaves the QR unrendered
    // until retry, rather than emitting a v2 payload the phone would reject.
    try { setDevice(await getLanDeviceId()); } catch { /* leave null; QR waits for it */ }
  }, []);

  useEffect(() => { refresh().catch((e) => setError(String(e))); }, [refresh]);

  // Report up whenever the LAN state actually changes. Effect (not a call inside the
  // handlers) so the host also sees the initial fetch, and so this stays a pure
  // notification rather than a second source of truth.
  useEffect(() => {
    onStateChange?.({ info, restartRequired: restartHint });
  }, [info, restartHint, onStateChange]);

  // QR re-encode is pure client-side work — safe to rerun whenever info/device/size changes.
  // v3 requires `device`; hold the QR until it's fetched (the phone rejects any v1/v2 payload).
  useEffect(() => {
    if (!info || !device) return;
    if (!info.enabled) { setQr(null); return; }
    let cancelled = false;
    QRCode.toDataURL(buildPairingPayload(info, device), { margin: 1, width: qrSize }).then((d) => {
      if (!cancelled) setQr(d);
    });
    return () => { cancelled = true; };
  }, [info, device, qrSize]);

  const onToggle = async (next: boolean) => {
    setBusy(true); setError(null);
    try {
      const i = await setPairingEnabled(next);
      setInfo(i); // QR re-encode handled by the info/qrSize effect above
      setRestartHint(true); // bind change applies next launch
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onRotate = async () => {
    setBusy(true); setError(null);
    try {
      await rotateSecret();
      setRestartHint(true); // new secret active after restart; QR still shows the live one
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!info) {
    return <div style={{ fontSize: 12, color: "var(--text-3)" }}>Loading pairing…</div>;
  }

  // Wired to real state, not to `enabled` alone: enabled-but-no-LAN-IP and
  // enabled-but-awaiting-restart are both "on, not working yet" and must not read
  // green. Resolved by the tested resolveLanTone(), never picked here.
  const tone = resolveLanTone({
    enabled: info.enabled,
    hasLanIp: Boolean(info.lan_ip ?? info.host),
    restartRequired: restartHint,
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: compact ? 12 : 16 }}>
      <Field label="Same-WiFi sync">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            aria-hidden="true"
            style={{
              width: 8,
              height: 8,
              flexShrink: 0,
              background: tone === "none" ? "var(--text-3)" : TONE_COLOR[tone],
            }}
          />
          <span style={{ flex: 1, fontSize: 12, color: "var(--text-2)" }}>
            {info.enabled ? "Enabled" : "Disabled"}
          </span>
          <Toggle
            label="Same-WiFi sync"
            checked={info.enabled}
            disabled={busy}
            onChange={(next) => onToggle(next)}
          />
        </div>
      </Field>

      {error && (
        <div style={{ fontSize: 11, color: "var(--red)" }}>{error}</div>
      )}

      {info.enabled && qr && (
        <>
          <Field label="Scan on phone">
            <div
              style={{
                ...INPUT_STYLE,
                width: qrSize + 16,
                height: qrSize + 16,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: 0,
              }}
            >
              <img src={qr} alt="Pairing QR code" width={qrSize} height={qrSize} />
            </div>
          </Field>
          <div style={{ fontSize: 11, color: "var(--text-3)" }}>
            {info.lan_ip ?? info.host}:{info.port} — scan once in the phone app.
          </div>
          <button
            className="btn-hover"
            style={BTN_SECONDARY}
            disabled={busy}
            onClick={onRotate}
          >
            Rotate secret
          </button>
        </>
      )}

      {info.enabled && !qr && !info.lan_ip && (
        <div style={{ fontSize: 11, color: "var(--yellow)" }}>
          LAN IP not found — connect to WiFi and toggle again.
        </div>
      )}

      {restartHint && (
        <div style={{ fontSize: 11, color: "var(--text-3)" }}>
          Restart Second Thought to apply the bind/secret change.
        </div>
      )}
    </div>
  );
}

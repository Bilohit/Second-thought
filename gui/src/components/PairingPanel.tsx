/**
 * PairingPanel.tsx
 * -----------------
 * Settings "Pairing" tab body — same-WiFi LAN file-sync pairing.
 *
 *   · Toggle: enable/disable the LAN listener (accelerator only; Drive
 *     remains the sync fallback — see CLAUDE.md "Amendment 2026-07-11").
 *   · QR: encodes {v:2,host,port,key,secret} (contract §9) for the phone to scan.
 *   · Rotate secret: writes a new [gui] secret; effective after restart.
 *
 * Kept out of the 1000+ line SettingsPanel per plan Task 6.
 */

import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import {
  getPairingInfo, setPairingEnabled, rotateSecret, buildPairingPayload,
  type PairingInfo,
} from "../lib/tauri";
import { INPUT_STYLE, BTN_SECONDARY } from "./ui/styles";

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

export default function PairingPanel({ compact }: { compact: boolean }) {
  const [info, setInfo] = useState<PairingInfo | null>(null);
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
  }, []);

  useEffect(() => { refresh().catch((e) => setError(String(e))); }, [refresh]);

  // QR re-encode is pure client-side work — safe to rerun whenever info or size changes.
  useEffect(() => {
    if (!info) return;
    if (!info.enabled) { setQr(null); return; }
    let cancelled = false;
    QRCode.toDataURL(buildPairingPayload(info), { margin: 1, width: qrSize }).then((d) => {
      if (!cancelled) setQr(d);
    });
    return () => { cancelled = true; };
  }, [info, qrSize]);

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
              background: info.enabled ? "var(--green)" : "var(--text-3)",
            }}
          />
          <button
            className="btn-hover"
            style={{ ...BTN_SECONDARY, flex: 1 }}
            aria-pressed={info.enabled}
            disabled={busy}
            onClick={() => onToggle(!info.enabled)}
          >
            {info.enabled ? "Enabled — tap to disable" : "Disabled — tap to enable"}
          </button>
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

/**
 * PairingPanel.tsx
 * -----------------
 * Same-WiFi LAN file-sync pairing.
 *
 *   · Toggle: enable/disable the LAN listener (accelerator only; Drive
 *     remains the sync fallback — see CLAUDE.md "Amendment 2026-07-11").
 *   · QR: encodes {v:4,host,port,lan_secret,key,device} (contract §11.4) for the phone to scan.
 *     The QR carries a LIVE credential (`lan_secret` + the NaCl `key`), so it is gated behind an
 *     explicit reveal (GUI-19): it is not encoded — never enters the DOM — until the user asks for
 *     it, and it reseals itself after a bounded window (see lib/pairingReveal.ts). This defends
 *     against a glance, a screenshot, or a screen-share catching the code.
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

import { useCallback, useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import {
  getPairingInfo, setPairingEnabled, rotateSecret, buildPairingPayload,
  type PairingInfo,
} from "../lib/tauri";
import { getLanDeviceId } from "../lib/api";
import { resolveLanTone } from "../lib/syncSetup";
import {
  REVEAL_WINDOW_MS, tickRemaining, revealFraction, formatCountdown, barColor,
} from "../lib/pairingReveal";
import { BTN_SECONDARY } from "./ui/styles";
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

// ── Reveal-gate lock glyph (inline SVG, house icon spec: stroke=currentColor,
//    ~1.7 weight, 24 grid, sharp — never emoji). ──────────────────────────────
function LockIcon({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="4.5" y="10.5" width="15" height="10" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
      <circle cx="12" cy="15.2" r="1.1" fill="currentColor" stroke="none" />
    </svg>
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

  // GUI-19 reveal gate. `revealed` gates the ENCODE (so a sealed QR is never in the DOM);
  // `remaining` drives the reseal loading bar + countdown; `paused` (hover) freezes it so
  // reading the code never races the user. Refs keep the rAF loop off React's dependency churn.
  const [revealed, setRevealed] = useState(false);
  const [remaining, setRemaining] = useState(REVEAL_WINDOW_MS);
  const [paused, setPaused] = useState(false);
  const hoverRef = useRef(false);
  const remainingRef = useRef(REVEAL_WINDOW_MS); // mirrors `remaining` so the rAF loop reads it without re-subscribing

  const qrSize = compact ? 160 : 220;

  // Fetches PairingInfo (Rust get_pairing_info) once on mount only — this call spawns a
  // blocking ipconfig subprocess, so it must never re-fire on a parent re-render (was the
  // pairing-tab lag: qrSize/compact used to be a refresh() dependency).
  const refresh = useCallback(async () => {
    const i = await getPairingInfo();
    setInfo(i);
    // Device-id (v4 QR anchor) is stable; fetch once — a failure just leaves the QR unrendered
    // until retry, rather than emitting a v3 payload the phone would reject.
    try { setDevice(await getLanDeviceId()); } catch { /* leave null; QR waits for it */ }
  }, []);

  useEffect(() => { refresh().catch((e) => setError(String(e))); }, [refresh]);

  // Report up whenever the LAN state actually changes. Effect (not a call inside the
  // handlers) so the host also sees the initial fetch, and so this stays a pure
  // notification rather than a second source of truth.
  useEffect(() => {
    onStateChange?.({ info, restartRequired: restartHint });
  }, [info, restartHint, onStateChange]);

  const conceal = useCallback(() => {
    setRevealed(false);
    setQr(null);                 // drop the credential out of the DOM
    remainingRef.current = REVEAL_WINDOW_MS;
    setRemaining(REVEAL_WINDOW_MS);
    setPaused(false);
    hoverRef.current = false;
  }, []);

  const reveal = useCallback(() => {
    remainingRef.current = REVEAL_WINDOW_MS;
    setRemaining(REVEAL_WINDOW_MS);
    setRevealed(true);
  }, []);

  // QR encode is GATED on `revealed` — the credential is only ever computed once the user asks.
  // Pure client-side work otherwise; v4 requires `device`, so hold until it's fetched.
  useEffect(() => {
    if (!info || !device || !info.enabled || !revealed) { setQr(null); return; }
    let cancelled = false;
    QRCode.toDataURL(buildPairingPayload(info, device), { margin: 1, width: qrSize }).then((d) => {
      if (!cancelled) setQr(d);
    });
    return () => { cancelled = true; };
  }, [info, device, qrSize, revealed]);

  // Reseal countdown: one rAF loop while revealed, driving the bar + clock. Pauses on hover or a
  // hidden tab; reseals when it hits zero. Reads hover through a ref so the loop never restarts.
  useEffect(() => {
    if (!revealed) return;
    let raf = 0;
    let last: number | null = null;
    const step = (ts: number) => {
      if (last == null) last = ts;
      const dt = ts - last; last = ts;
      const isPaused = hoverRef.current || document.hidden;
      const next = tickRemaining(remainingRef.current, dt, isPaused);
      remainingRef.current = next;
      setPaused(isPaused);
      setRemaining(next);
      if (next <= 0) { conceal(); return; }   // window closed — reseal and stop the loop
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [revealed, conceal]);

  // A window blur (alt-tab, screen-share picker, lock) reseals at once — the screen-share defence.
  useEffect(() => {
    if (!revealed) return;
    const onBlur = () => conceal();
    window.addEventListener("blur", onBlur);
    return () => window.removeEventListener("blur", onBlur);
  }, [revealed, conceal]);

  const onToggle = async (next: boolean) => {
    setBusy(true); setError(null);
    try {
      const i = await setPairingEnabled(next);
      setInfo(i);
      if (!next) conceal();       // turning LAN off also reseals
      setRestartHint(true);       // bind change applies next launch
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

  const hasLanIp = Boolean(info.lan_ip ?? info.host);
  const frac = revealFraction(remaining, REVEAL_WINDOW_MS);
  const tileW = qrSize + 20;

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

      {info.enabled && hasLanIp && (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, textAlign: "center" }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-1)" }}>Pair your phone</div>

          {/* Fixed QR footprint — reserved whether sealed or revealed, so the panel never jumps. */}
          <div style={{ position: "relative", width: tileW, height: tileW }}>
            {revealed && qr ? (
              // Light quiet-zone tile — a QR on the dark surface risks failing to scan.
              <div
                onMouseEnter={() => { hoverRef.current = true; }}
                onMouseLeave={() => { hoverRef.current = false; }}
                style={{
                  width: tileW, height: tileW, background: "#fafafa",
                  display: "flex", alignItems: "center", justifyContent: "center", padding: 10,
                }}
              >
                <img
                  src={qr} alt="Pairing QR code" width={qrSize} height={qrSize}
                  style={{ animation: "fadeIn 240ms var(--hover-ease-out) both" }}
                />
                {/* Reseal loading bar — flush at the tile's bottom edge; drains over the window. */}
                <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 3, background: "var(--accent-d)" }}>
                  <div
                    style={{
                      height: "100%", width: "100%", transformOrigin: "left center",
                      transform: `scaleX(${frac})`, background: barColor(frac),
                      transition: "transform 90ms linear, background-color 400ms ease",
                    }}
                  />
                </div>
              </div>
            ) : (
              // Sealed: no QR in the DOM. One click reveals it.
              <button
                type="button"
                onClick={reveal}
                aria-label="Reveal pairing code"
                style={{
                  width: tileW, height: tileW, cursor: "pointer",
                  display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10,
                  background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-1)",
                  font: "inherit",
                }}
              >
                <LockIcon />
                <span style={{ fontSize: 12 }}>Reveal pairing code</span>
                <span style={{ fontSize: 10, color: "var(--text-2)" }}>contains a live credential</span>
              </button>
            )}
          </div>

          <ol style={{ listStyle: "none", margin: 0, padding: 0, textAlign: "left", display: "flex", flexDirection: "column", gap: 5 }}>
            {[
              "Open Second Thought on your phone",
              "Go to Settings → Pair device",
            ].map((step, i) => (
              <li key={i} style={{ fontSize: 11, color: "var(--text-2)", display: "flex", gap: 8 }}>
                <span style={{ color: "var(--accent)", fontWeight: 600 }}>{i + 1}</span> {step}
              </li>
            ))}
            <li style={{ fontSize: 11, color: "var(--text-2)", display: "flex", gap: 8 }}>
              <span style={{ color: "var(--accent)", fontWeight: 600 }}>3</span>
              <span>Reveal &amp; scan · <span style={{ color: "var(--text-3)", fontVariantNumeric: "tabular-nums" }}>{info.lan_ip ?? info.host}:{info.port}</span></span>
            </li>
          </ol>

          {/* Revealed-only meta: the exposure warning + the countdown + an explicit reseal. */}
          {revealed && (
            <div style={{ width: tileW, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, minHeight: 20 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10.5, color: "var(--yellow)" }}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 9v4" /><path d="M12 17h.01" />
                  <path d="M10.3 3.9 2.4 18a1.9 1.9 0 0 0 1.7 2.9h15.8a1.9 1.9 0 0 0 1.7-2.9L13.7 3.9a1.9 1.9 0 0 0-3.4 0z" />
                </svg>
                {paused ? "Paused — reading" : "Secret is on screen"}
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 11, color: "var(--text-2)", fontVariantNumeric: "tabular-nums" }}>
                  Hides in {formatCountdown(remaining)}
                </span>
                <button className="btn-hover" style={BTN_SECONDARY} onClick={conceal}>
                  Hide now
                </button>
              </span>
            </div>
          )}

          <button
            className="btn-hover"
            style={BTN_SECONDARY}
            disabled={busy}
            onClick={onRotate}
          >
            Rotate secret
          </button>
        </div>
      )}

      {info.enabled && !hasLanIp && (
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

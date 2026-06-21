/**
 * CaptureOverlay.tsx
 * ------------------
 * Primary floating capture card — Zen Browser aesthetic.
 *
 * Changes from prior version
 *   - All hard-coded rgba/hex replaced with CSS variables (theme-aware)
 *   - Animation via CSS keyframe overlayIn (reduced-motion-safe via index.css)
 *   - Full ARIA: role="dialog", aria-label, aria-live, aria-pressed
 *   - Icon buttons use .icon-btn utility class (focus-visible ring included)
 *   - Confidence bar width animates via CSS transition
 */
import { useCallback, useEffect, useRef, useState } from "react";
import StepIndicator from "./StepIndicator";
import { HEADER_PAD } from "./ui/styles";
import type { CaptureState, CaptureStep, ThinkingState } from "../hooks/useCapture";
import { deriveYoutubeSteps } from "../hooks/useCapture";
import { getConfig, formatHotkey, DEFAULT_HOTKEY } from "../lib/config";

interface Props {
  measureRef?:    (el: HTMLDivElement | null) => void;
  captureState:   CaptureState;
  stepDefs:       CaptureStep[];
  onOpenSettings: () => void;
  onOpenVault:    () => void;
  onOpenInbox:    () => void;
  onOpenSearch:   () => void;
  onOpenStats:    () => void;
  visible:        boolean;
  inboxCount:     number;
  /** Only set when Display Mode (Settings) is Capsule/Minimal — shows a
   *  "collapse back to pill" icon button next to the other header actions. */
  onCollapseToPill?: () => void;
}

// ── Content preview ────────────────────────────────────────────────────────

function ContentPreview({ preview }: { preview: CaptureState["preview"] }) {
  if (!preview) {
    return (
      <div
        aria-live="polite"
        aria-label="Reading clipboard"
        style={{
          height: 48,
          borderRadius: "var(--radius)",
          background: "var(--surface)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
          Reading clipboard…
        </span>
      </div>
    );
  }

  if (preview.type === "image" && preview.imageSrc) {
    return (
      <div style={{ height: 80, borderRadius: "var(--radius)", overflow: "hidden", background: "var(--surface)", border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <img src={preview.imageSrc} alt="Clipboard image" style={{ maxHeight: "100%", maxWidth: "100%", objectFit: "contain" }} />
      </div>
    );
  }

  const isUrl = preview.type === "url";
  return (
    <div style={{ padding: "9px 12px", borderRadius: "var(--radius)", background: "var(--surface)", border: "1px solid var(--border)" }}>
      {isUrl && preview.domain && (
        <div style={{ fontSize: 10, fontWeight: 600, color: "var(--accent)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 3 }}>
          {preview.domain}
        </div>
      )}
      <p style={{ margin: 0, fontSize: 12, color: "var(--text-2)", lineHeight: 1.45, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", fontFamily: isUrl ? "monospace" : "inherit" }}>
        {preview.snippet}
      </p>
    </div>
  );
}

// ── Footer ─────────────────────────────────────────────────────────────────

function useHotkeyLabel(): string {
  const [hotkey, setHotkey] = useState(DEFAULT_HOTKEY);
  useEffect(() => {
    getConfig()
      .then((cfg) => setHotkey(cfg.gui?.hotkey ?? DEFAULT_HOTKEY))
      .catch(() => {});
  }, []);
  return formatHotkey(hotkey);
}

function Footer({ state }: { state: CaptureState }) {
  const hotkeyLabel = useHotkeyLabel();
  if (state.phase === "done" && state.result) {
    const short = state.result.path ? state.result.path.split(/[\\/]/).slice(-2).join("/") : null;
    return (
      <div role="status" aria-live="polite" style={{ display: "flex", alignItems: "center", gap: 6, animation: "fadeIn 0.22s ease forwards" }}>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <circle cx="6" cy="6" r="5.5" stroke="var(--green)" strokeWidth="1.2"/>
          <polyline points="3,6 5.2,8.2 9,3.5" stroke="var(--green)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <span style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "monospace" }}>{short ? `Saved to ${short}` : "Saved"}</span>
      </div>
    );
  }
  if (state.phase === "error" && state.errorMsg) {
    const firstLine = state.errorMsg.split("\n")[0];
    return <span role="alert" style={{ fontSize: 11, color: "var(--red)" }}>{firstLine.length > 60 ? firstLine.slice(0, 57) + "…" : firstLine}</span>;
  }
  // Background job in progress: the step list above already shows live
  // status, so the footer stays quiet instead of showing the idle hotkey hint.
  if (state.phase === "background") return null;
  return <span style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: "0.03em" }}>{hotkeyLabel} to capture</span>;
}

// ── One-time tray hint ───────────────────────────────────────────────────
// The window now auto-hides quickly after a capture, so the header's vault
// button is on screen only briefly. Tell the user, once, that the tray icon
// (right-click → "Vault Settings") reaches the same place at any time.

const TRAY_HINT_KEY = "omni-tray-hint-seen";

function useTrayHintVisible(idle: boolean): boolean {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!idle) return;
    try {
      if (localStorage.getItem(TRAY_HINT_KEY)) return;
      localStorage.setItem(TRAY_HINT_KEY, "1");
    } catch { /* ignore */ }
    setShow(true);
  }, [idle]);
  return show;
}

// ── Background job indicator (Task 2: YouTube etc.) ─────────────────────────
// Renders the live job as a real step-by-step list -- same icons/rail/
// animations as the main capture StepIndicator, by construction, since it
// reuses that component with stages derived from the actual backend phases.

function BackgroundJobIndicator({ job }: { job: CaptureState["backgroundJob"] }) {
  if (!job) return null;
  const { steps, stepDefs } = deriveYoutubeSteps(job);
  const showCount = job.status === "summarizing" && !!job.chunkTotal && job.chunkTotal > 1;
  return (
    <div role="status" aria-live="polite" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", color: "var(--text-3)", textTransform: "uppercase" }}>
        Processing {job.kind} in background
      </span>
      <StepIndicator steps={steps} stepDefs={stepDefs} />
      {showCount && (
        <div
          role="progressbar"
          aria-valuenow={job.chunkIndex ?? 0}
          aria-valuemin={0}
          aria-valuemax={job.chunkTotal ?? 0}
          aria-label="Sections summarized"
          style={{ height: 3, borderRadius: "var(--radius-sm)", background: "var(--border)", marginLeft: 26 }}
        >
          <div
            style={{
              height: "100%",
              borderRadius: "var(--radius-sm)",
              background: "var(--accent)",
              width: `${Math.round(((job.chunkIndex ?? 0) / (job.chunkTotal || 1)) * 100)}%`,
              transition: "width 0.3s cubic-bezier(0.16,1,0.3,1)",
            }}
          />
        </div>
      )}
    </div>
  );
}

// ── Thinking panel ─────────────────────────────────────────────────────────

// Single source of truth for confidence → colour, so the % badge and the
// progress-bar fill can never drift apart (UI-ENHANCEMENT-PLAN.md B4.2).
function confidenceColor(confidence: number): string {
  if (confidence >= 0.9) return "var(--green)";
  if (confidence >= 0.7) return "var(--yellow)";
  return "var(--red)";
}

function ThinkingPanel({ thinking }: { thinking: ThinkingState | null }) {
  const [open, setOpen] = useState(false);
  useEffect(() => { if (thinking) setOpen(true); }, [thinking]);
  if (!thinking) return null;

  const pct = Math.round(thinking.confidence * 100);
  const confColor = confidenceColor(thinking.confidence);

  return (
    <div style={{ borderRadius: "var(--radius)", background: "var(--accent-d)", border: "1px solid color-mix(in srgb, var(--accent) 14%, transparent)", overflow: "hidden" }}>
      <button
        aria-expanded={open}
        aria-controls="thinking-body"
        onClick={() => setOpen((o) => !o)}
        style={{ width: "100%", background: "none", border: "none", cursor: "pointer", padding: "7px 10px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M9.5 2a2.5 2.5 0 0 1 5 0v.5"/>
            <path d="M9 2.5C6.5 2.5 4 4.5 4 7c0 1.5.7 2.8 1.8 3.7C4.7 11.5 4 12.9 4 14.5 4 17 6 19 8.5 19H12"/>
            <path d="M15 2.5c2.5 0 5 2 5 4.5 0 1.5-.7 2.8-1.8 3.7C19.3 11.5 20 12.9 20 14.5 20 17 18 19 15.5 19H12"/>
            <line x1="12" y1="2.5" x2="12" y2="19"/>
          </svg>
          <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", color: "var(--accent)", textTransform: "uppercase" }}>Decision</span>
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--text-1)", background: "var(--accent-d)", borderRadius: "var(--radius-sm)", padding: "1px 5px", letterSpacing: "0.04em" }}>
            {thinking.category}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ fontSize: 10, color: confColor, fontWeight: 700 }}>{pct}%</span>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="var(--text-3)" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"
            style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.18s ease" }}>
            <polyline points="2,3 5,7 8,3"/>
          </svg>
        </div>
      </button>

      <div
        style={{
          display: "grid",
          gridTemplateRows: open ? "1fr" : "0fr",
          transition: "grid-template-rows 0.22s cubic-bezier(0.16,1,0.3,1)",
        }}
      >
        <div id="thinking-body" style={{ overflow: "hidden", minHeight: 0 }}>
          <div style={{ padding: "0 10px 10px", display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div
                role="progressbar"
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`Confidence ${pct}%`}
                style={{ flex: 1, height: 3, borderRadius: "var(--radius-sm)", background: "var(--border)" }}
              >
                <div
                  style={{
                    height: "100%",
                    width: "100%",
                    borderRadius: "var(--radius-sm)",
                    background: confColor,
                    transform: `scaleX(${pct / 100})`,
                    transformOrigin: "left",
                    willChange: "transform",
                    transition: "transform 0.4s cubic-bezier(0.16,1,0.3,1)",
                  }}
                />
              </div>
              <span style={{ fontSize: 9, color: "var(--text-3)", whiteSpace: "nowrap" }}>confidence</span>
            </div>

            {thinking.key_signals.length > 0 && (
              <ul aria-label="Key signals" style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 3 }}>
                {thinking.key_signals.map((sig, i) => (
                  <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: 5 }}>
                    <span aria-hidden="true" style={{ color: "var(--accent)", fontSize: 9, marginTop: 1, flexShrink: 0 }}>&#9658;</span>
                    <span style={{ fontSize: 11, color: "var(--text-2)", lineHeight: 1.4 }}>{sig}</span>
                  </li>
                ))}
              </ul>
            )}

            {thinking.rationale && (
              <p style={{ margin: 0, fontSize: 11, color: "var(--text-3)", lineHeight: 1.5, fontStyle: "italic", borderTop: "1px solid var(--border)", paddingTop: 6 }}>
                {thinking.rationale}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main overlay ───────────────────────────────────────────────────────────

export default function CaptureOverlay({
  measureRef,
  captureState,
  stepDefs,
  onOpenSettings,
  onOpenVault,
  onOpenInbox,
  onOpenSearch,
  onOpenStats,
  visible,
  inboxCount,
  onCollapseToPill,
}: Props) {
  const [mounted, setMounted] = useState(false);
  const cardRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (visible) { requestAnimationFrame(() => setMounted(true)); }
    else { setMounted(false); }
  }, [visible]);

  useEffect(() => {
    if (mounted) cardRef.current?.focus();
  }, [mounted]);

  // Combined ref must keep a stable identity across renders — an inline
  // `(el) => {...}` literal here gets torn down and recreated by React on
  // every render, which calls measureRef(null) then measureRef(el) each
  // time, defeating its own change-detection and causing an infinite
  // render loop (React error #185).
  const setCardRef = useCallback(
    (el: HTMLDivElement | null) => {
      cardRef.current = el;
      measureRef?.(el);
    },
    [measureRef],
  );

  const isCapturing = captureState.phase === "capturing" || captureState.phase === "background";
  const showTrayHint = useTrayHintVisible(captureState.phase === "idle");

  return (
    <div
      ref={setCardRef}
      role="dialog"
      aria-label="Second Thought capture"
      aria-live="polite"
      tabIndex={-1}
      className="glass-card"
      style={{
        width: 440,
        padding: "0 0 14px 0",
        opacity: mounted ? 1 : 0,
        transform: mounted ? "scale(1) translateY(0)" : "scale(0.97) translateY(5px)",
        transition: "opacity 0.16s cubic-bezier(0.16,1,0.3,1), transform 0.16s cubic-bezier(0.16,1,0.3,1)",
        pointerEvents: mounted ? undefined : "none",
        outline: "none",
      }}
    >
      {/* Header */}
      <div
        className="drag-region"
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: HEADER_PAD, borderBottom: "1px solid var(--border)" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            aria-hidden="true"
            style={{
              display: "inline-block", width: 7, height: 7, borderRadius: "50%",
              background: isCapturing ? "var(--accent)" : "var(--border)",
              boxShadow: isCapturing ? "0 0 8px var(--accent-glow)" : "none",
              transition: "all 0.3s ease",
            }}
          />
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)", letterSpacing: "0.02em" }}>
            Second Thought
          </span>
        </div>

        <div className="no-drag" style={{ display: "flex", gap: 2 }}>
          {onCollapseToPill && (
            <button className="icon-btn" onClick={onCollapseToPill} title="Collapse to pill" aria-label="Collapse to pill">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M16 3h3a2 2 0 0 1 2 2v3m0 8v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3m0-8V5a2 2 0 0 1 2-2h3"/>
              </svg>
            </button>
          )}
          <button className="icon-btn" onClick={onOpenSearch} title="Search vault (Ctrl+K)" aria-label="Search vault">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>
          <button className="icon-btn" onClick={onOpenStats} title="Statistics" aria-label="Open statistics">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="18" y1="20" x2="18" y2="10" />
              <line x1="12" y1="20" x2="12" y2="4" />
              <line x1="6" y1="20" x2="6" y2="14" />
            </svg>
          </button>
          <button className="icon-btn" onClick={onOpenVault} title="Vault (Ctrl+\)" aria-label="Open vault manager">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
          </button>
          <button
            className="icon-btn"
            onClick={onOpenInbox}
            title="Inbox (Ctrl+I)"
            aria-label={inboxCount > 0 ? `Open inbox, ${inboxCount} item${inboxCount === 1 ? "" : "s"} need review` : "Open inbox"}
            style={{ position: "relative" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M22 12h-6l-2 3h-4l-2-3H2" />
              <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
            </svg>
            {inboxCount > 0 && (
              <span
                aria-hidden="true"
                style={{
                  position: "absolute", top: 2, right: 2,
                  minWidth: 7, height: 7, borderRadius: "50%",
                  background: "var(--accent)",
                }}
              />
            )}
          </button>
          <button className="icon-btn" onClick={onOpenSettings} title="Settings (Ctrl+,)" aria-label="Open settings">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 2v2m0 16v2M4.22 4.22l1.42 1.42m12.72 12.72 1.42 1.42M2 12h2m16 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: "13px 16px 0", display: "flex", flexDirection: "column", gap: 14 }}>
        <ContentPreview preview={captureState.preview} />
        {!captureState.backgroundJob && (
          <StepIndicator steps={captureState.steps} stepDefs={stepDefs} />
        )}
        <ThinkingPanel thinking={captureState.thinking ?? null} />
        {captureState.backgroundJob && <BackgroundJobIndicator job={captureState.backgroundJob} />}
      </div>

      {showTrayHint && (
        <div style={{ padding: "10px 16px 0" }}>
          <span style={{ fontSize: 10.5, color: "var(--text-3)", letterSpacing: "0.02em" }}>
            Tip: right-click the tray icon → Vault Settings to manage your vault anytime.
          </span>
        </div>
      )}

      {/* Footer */}
      <div style={{ padding: "10px 16px 0", display: "flex", alignItems: "center", justifyContent: "space-between", minHeight: 18 }}>
        <Footer state={captureState} />
      </div>
    </div>
  );
}

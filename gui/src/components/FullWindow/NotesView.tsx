/**
 * NotesView.tsx
 * -------------
 * P3-B: the full window's real NOTES interior — replaces DashboardView as
 * the "notes" tab's mount. List pane (VAULT) + a 280px morphing capture
 * pane, per `SecondThoughtV2.html`'s desktop NOTES screen
 * (`data-scr="notes"`, `.split > .list-pane + .edit-pane > .cap-pane`).
 *
 * The capture pane's radial is NET NEW — the pill's `RadialMenu` has never
 * mounted in the full window, and this is a different, unrelated 4-item fan
 * (blank note / voice / clip / screenshot) built in `lib/captureRadial.ts`,
 * not a reuse of the pill's own nav radial or the frozen `CapsuleMenu`.
 *
 * Real capabilities only — every satellite calls a real capture path:
 *   - note:  `onOpenFile(null)` → NoteEditor's own path===null "create on
 *            first keystroke" flow (already ships, s135 locked decision).
 *   - voice: `onVoiceToggle()` — the same recorder DashboardView already
 *            drove; the pane switches to the recording sub-view for as
 *            long as `voicePhase !== "idle"`.
 *   - clip:  `onCaptureNow()` — reads the clipboard right now, exactly like
 *            DashboardView's drop-box tile. The mock shows a preview-then-
 *            confirm step for this; the real pipeline has no such
 *            intermediate state (`useCapture`'s `phase` flips to
 *            "capturing" synchronously on click), so this intentionally
 *            skips straight to the live StepIndicator rather than faking a
 *            confirmation the backend doesn't have.
 *   - shot:  there is no live screen-capture API anywhere in this app
 *            (verified at source — no Rust command, no frontend call).
 *            "Screenshot" here opens a real OS file picker filtered to
 *            image extensions and hands the chosen file to the existing
 *            `onCaptureFile` path — a real, working capture of an
 *            already-taken screenshot file, not a stub.
 *
 * Whenever a capture is in flight (`captureState.phase !== "idle"`), the
 * pane shows the live `StepIndicator` over the real `stepDefs` regardless
 * of which satellite (or the global hotkey) started it — this is the same
 * `captureState`/`stepDefs` `useCapture()` already produces and
 * `FullWindow` already threads through (see `hooks/useCapture.ts:83-88`
 * for `STEP_DEFS`), not a mock sequence.
 */
import { useEffect, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import StepIndicator from "../StepIndicator";
import FluidVisualizer from "../PillMenu/FluidVisualizer";
import { MicIcon, PencilIcon, ClipboardIcon, ImageIcon, PlusIcon, ChevronRightIcon } from "../PillMenu/icons";
import { formatElapsed } from "../../lib/voiceLimits";
import { captureRadialFan, type CaptureSatelliteId } from "../../lib/captureRadial";
import { searchCaptures, getConfig, checkHealth, type SearchResult } from "../../lib/api";
import { fileKind } from "../../lib/fileIngest";
import { logger } from "../../lib/logger";
import { formatHotkey, DEFAULT_HOTKEY } from "../../lib/hotkey";
import { displayProject } from "../../lib/projectsView";
import { label as fsLabel, body as fsBody, read as fsRead, title as fsTitle } from "../../lib/type";
import type { CaptureState, CaptureStep } from "../../hooks/useCapture";
import type { VoicePhase } from "../../hooks/useVoiceRecording";

const VAULT_LIST_LIMIT = 200;
const RADIAL_RADIUS = 78;
const RADIAL_ICON_SIZE = 16;

interface NotesViewProps {
  visible: boolean;
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  /** `null` opens a brand-new blank note (NoteEditor's own path===null flow). */
  onOpenFile: (path: string | null) => void;
  onCaptureFile: (path: string) => void;
  onCaptureNow: () => void;
  voicePhase: VoicePhase;
  voiceElapsedMs: number;
  readWaveform: (out: Float32Array) => void;
  readSpectrum: (out: Uint8Array) => void;
  sampleRate: number;
  onVoiceToggle: () => void;
  onVoiceCancel: () => void;
}

const SATELLITE_ICON: Record<CaptureSatelliteId, (size: number) => React.ReactNode> = {
  note: (size) => <PencilIcon size={size} />,
  voice: (size) => <MicIcon size={size} />,
  clip: (size) => <ClipboardIcon size={size} />,
  shot: (size) => <ImageIcon size={size} />,
};
const SATELLITE_TITLE: Record<CaptureSatelliteId, string> = {
  note: "Blank note",
  voice: "Voice capture",
  clip: "Capture clipboard",
  shot: "Capture a screenshot file",
};

const IMAGE_FILTER = { name: "Image", extensions: ["png", "jpg", "jpeg", "gif", "webp"] };

export default function NotesView({
  visible, captureState, stepDefs, onOpenFile, onCaptureFile, onCaptureNow,
  voicePhase, voiceElapsedMs, readWaveform, readSpectrum, sampleRate, onVoiceToggle, onVoiceCancel,
}: NotesViewProps) {
  const [notes, setNotes] = useState<SearchResult[]>([]);
  const [radialOpen, setRadialOpen] = useState(false);
  const [hotkey, setHotkey] = useState(DEFAULT_HOTKEY);
  const [ffmpegOk, setFfmpegOk] = useState(true);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    getConfig().then((cfg) => setHotkey(cfg.gui?.hotkey ?? DEFAULT_HOTKEY)).catch(() => {});
    checkHealth().then((h) => setFfmpegOk(h.ffmpeg)).catch(() => setFfmpegOk(true));
  }, []);

  // Refetch on open and whenever a capture just settled -- same trigger
  // DashboardView already used for its Recent-activity card.
  useEffect(() => {
    if (!visible) return;
    if (captureState.phase === "capturing" || captureState.phase === "background") return;
    searchCaptures("", { limit: VAULT_LIST_LIMIT })
      .then((r) => setNotes(r.results))
      .catch((err) => logger.warn("notes", "vault list fetch failed", err));
  }, [visible, captureState.phase]);

  useEffect(() => {
    if (!visible) return;
    let unlisten: (() => void) | undefined;
    getCurrentWebview().onDragDropEvent((event) => {
      const { type } = event.payload;
      if (type === "over") setDragOver(true);
      else if (type === "leave") setDragOver(false);
      else if (type === "drop") {
        setDragOver(false);
        const path = event.payload.paths[0];
        if (!path || !fileKind(path)) return;
        onCaptureFile(path);
      }
    }).then((fn) => { unlisten = fn; });
    return () => { unlisten?.(); };
  }, [visible, onCaptureFile]);

  if (!visible) return null;

  const isIdle = captureState.phase === "idle";
  const showAction = !isIdle;
  const showVoice = isIdle && voicePhase !== "idle";
  const showFan = isIdle && voicePhase === "idle";

  const runSatellite = (id: CaptureSatelliteId) => {
    setRadialOpen(false);
    if (id === "note") { onOpenFile(null); return; }
    if (id === "voice") { if (ffmpegOk) onVoiceToggle(); return; }
    if (id === "clip") { onCaptureNow(); return; }
    // shot: no live screen-grab API anywhere in this app -- pick an
    // already-captured screenshot file and ingest it via the real
    // captureFile path (see file header for the honest-substitute note).
    openDialog({ multiple: false, filters: [IMAGE_FILTER] })
      .then((picked) => {
        const path = Array.isArray(picked) ? picked[0] : picked;
        if (path) onCaptureFile(path);
      })
      .catch((err) => logger.warn("notes", "screenshot file pick failed", err));
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", overflow: "hidden" }}>
      {/* list pane */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderBottom: "1px solid var(--border-2)", flex: "none" }}>
          <span style={{ fontSize: fsLabel, letterSpacing: "0.18em", color: "var(--text-3)" }}>VAULT</span>
          <span style={{ fontSize: fsLabel, color: "var(--text-3)" }}>{notes.length} notes</span>
        </div>
        <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>
          {notes.map((n) => (
            <button
              key={n.path}
              type="button"
              className="btn-hover"
              onClick={() => onOpenFile(n.path)}
              style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%",
                padding: "8px 14px", cursor: "pointer", border: "none", borderBottom: "1px solid var(--border-2)",
                background: "transparent", textAlign: "left", fontFamily: "inherit",
              }}
            >
              <span style={{ fontSize: fsRead, color: "var(--text-1)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {n.filename ?? n.path}
              </span>
              <span style={{ fontSize: fsLabel, border: "1px solid var(--border)", padding: "0 5px", color: "var(--text-3)", whiteSpace: "nowrap", flexShrink: 0 }}>
                {displayProject(n.project)}
              </span>
              {n.timestamp && (
                <span style={{ fontSize: fsLabel, color: "var(--text-3)", flexShrink: 0 }}>{n.timestamp}</span>
              )}
            </button>
          ))}
          {notes.length === 0 && (
            <div style={{ fontSize: fsBody, color: "var(--text-3)", padding: "16px 0", textAlign: "center" }}>No notes yet</div>
          )}
        </div>
      </div>

      {/* 280px morphing capture pane */}
      <div
        style={{
          width: 280, flex: "none", borderLeft: `1px solid ${dragOver ? "var(--accent)" : "var(--border)"}`,
          display: "flex", flexDirection: "column", minHeight: 0, padding: "16px 14px", gap: 16,
          transition: "border-color 0.2s ease",
        }}
      >
        {showAction && <StepIndicator steps={captureState.steps} stepDefs={stepDefs} />}

        {showVoice && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, flex: 1, justifyContent: "center" }}>
            <span style={{ fontSize: fsLabel, letterSpacing: "0.18em", color: "var(--text-3)", textAlign: "center" }}>VOICE CAPTURE</span>
            <FluidVisualizer readWaveform={readWaveform} readSpectrum={readSpectrum} sampleRate={sampleRate} height={64} active />
            <div style={{ textAlign: "center", fontSize: fsTitle, fontWeight: 600, color: "var(--text-1)", fontVariantNumeric: "tabular-nums" }}>
              {formatElapsed(voiceElapsedMs)}
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
              <button type="button" className="btn-hover" onClick={onVoiceCancel} style={captureBtnStyle(false)}>Discard</button>
              <button type="button" className="btn-hover" onClick={onVoiceToggle} style={captureBtnStyle(true)}>Stop & Save</button>
            </div>
          </div>
        )}

        {showFan && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, flex: 1 }}>
            <div style={{ position: "relative", width: "100%", height: 160, display: "flex", alignItems: "flex-end", justifyContent: "center" }}>
              {captureRadialFan(RADIAL_RADIUS).map((sat) => (
                <button
                  key={sat.id}
                  type="button"
                  className="btn-hover"
                  title={SATELLITE_TITLE[sat.id]}
                  aria-label={SATELLITE_TITLE[sat.id]}
                  disabled={sat.id === "voice" && !ffmpegOk}
                  onClick={() => runSatellite(sat.id)}
                  style={{
                    position: "absolute", left: "50%", bottom: 22,
                    width: 36, height: 36, display: "flex", alignItems: "center", justifyContent: "center",
                    border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text-2)",
                    cursor: sat.id === "voice" && !ffmpegOk ? "default" : "pointer",
                    opacity: radialOpen ? (sat.id === "voice" && !ffmpegOk ? 0.4 : 1) : 0,
                    pointerEvents: radialOpen ? "auto" : "none",
                    transform: radialOpen
                      ? `translate(calc(-50% + ${Math.round(sat.x)}px), ${Math.round(sat.y)}px)`
                      : "translate(-50%, 0)",
                    transition: "transform 220ms cubic-bezier(0.16,1,0.3,1), opacity 180ms ease",
                  }}
                >
                  {SATELLITE_ICON[sat.id](RADIAL_ICON_SIZE)}
                </button>
              ))}
              <button
                type="button"
                className="btn-hover"
                aria-label="Open capture radial"
                aria-expanded={radialOpen}
                onClick={() => setRadialOpen((v) => !v)}
                style={{
                  position: "absolute", left: "50%", bottom: 0, transform: "translateX(-50%)",
                  width: 44, height: 44, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                  border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text-1)", cursor: "pointer",
                  transition: "transform 200ms cubic-bezier(0.16,1,0.3,1)",
                }}
              >
                <span style={{ display: "inline-flex", transform: radialOpen ? "rotate(45deg)" : "none", transition: "transform 200ms cubic-bezier(0.16,1,0.3,1)" }}>
                  <PlusIcon size={18} />
                </span>
              </button>
            </div>
            <button
              type="button"
              className="btn-hover"
              onClick={onCaptureNow}
              style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: "auto", fontSize: fsLabel, color: "var(--text-2)", background: "none", border: "1px solid var(--border)", padding: "6px 10px", cursor: "pointer" }}
            >
              or press {formatHotkey(hotkey)} anywhere
              <ChevronRightIcon size={10} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function captureBtnStyle(primary: boolean): React.CSSProperties {
  return {
    fontSize: fsLabel, border: `1px solid ${primary ? "var(--accent)" : "var(--border)"}`,
    background: "transparent", color: primary ? "var(--text-1)" : "var(--text-2)",
    padding: "5px 12px", cursor: "pointer", fontFamily: "inherit",
  };
}

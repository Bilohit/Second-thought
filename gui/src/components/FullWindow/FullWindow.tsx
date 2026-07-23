import { useRef, useState, useLayoutEffect, useCallback, useEffect } from "react";
import StatusIndicator from "../StatusIndicator";
import SegmentedToggle from "../ui/SegmentedToggle";
import LookPanel from "../LookPanel";
import SettingsPanel from "../SettingsPanel";
import DashboardView from "./DashboardView";
import LibraryView from "./LibraryView";
import { railSliderFromElement } from "../../lib/railSelection";
import { MenuIcon, DashboardIcon } from "../PillMenu/icons";
import { syncVaultIndex, getStats, getInbox } from "../../lib/api";
import InboxPanel, { type InboxTab } from "../InboxPanel";
import ErrorBoundary from "../ErrorBoundary";
import NoteEditor from "../NoteEditor";
import type { CaptureState, CaptureStep } from "../../hooks/useCapture";
import type { LlmStatus } from "../../lib/api";
import type { LookChatPersist } from "../../App";
import type { ChatMessage } from "../../hooks/useLookChat";
import type { PillCorner } from "../PillOverlay";
import type { VoicePhase } from "../../hooks/useVoiceRecording";

interface LookChatHook {
  messages: ChatMessage[];
  streaming: boolean;
  ask: (q: string) => void;
  reset: () => void;
  retry: (index: number) => void;
  ignoreHistory: boolean;
  setIgnoreHistory: (enabled: boolean) => void;
}

type MainView = "dashboard" | "look" | "library";
type RailView = MainView | "settings" | "inbox";
const MAIN_VIEWS: MainView[] = ["dashboard", "look", "library"];
// ISS-022: the folder-panel nav label is "Vault" everywhere — was "Library"
// here vs "Vault" in Capsule/Minimal mode. The container still holds the
// Vault/Tags/Trash sub-tabs (segmented toggle below); its own "Vault"
// sub-tab was renamed to "Folders" so the title bar and the tab directly
// under it don't repeat the same word.
const TITLES: Record<RailView, [string, string]> = {
  dashboard: ["Dashboard", "capture · recent · inbox"],
  look:      ["Look", "search · chat over vault"],
  library:   ["Vault", "folders · category · rhythm"],
  settings:  ["Settings", ""],
  inbox:     ["Inbox", "review · reminders"],
};

// Subset of SettingsPanel props that FullWindow receives and forwards
export interface SettingsForward {
  theme?: Parameters<typeof SettingsPanel>[0]["theme"];
  onSelectTheme?: Parameters<typeof SettingsPanel>[0]["onSelectTheme"];
  customTheme?: Parameters<typeof SettingsPanel>[0]["customTheme"];
  onSaveCustomTheme?: Parameters<typeof SettingsPanel>[0]["onSaveCustomTheme"];
  displayMode?: Parameters<typeof SettingsPanel>[0]["displayMode"];
  onSelectDisplayMode?: Parameters<typeof SettingsPanel>[0]["onSelectDisplayMode"];
  pillCorner?: Parameters<typeof SettingsPanel>[0]["pillCorner"];
  onSelectPillCorner?: Parameters<typeof SettingsPanel>[0]["onSelectPillCorner"];
  pillPinned?: boolean;
  onTogglePillPinned?: (pinned: boolean) => void;
  pillAnchor?: Parameters<typeof SettingsPanel>[0]["pillAnchor"];
  onSelectPillAnchor?: Parameters<typeof SettingsPanel>[0]["onSelectPillAnchor"];
  pillFanStyle?: "spread" | "capped";
  onSelectPillFanStyle?: (style: "spread" | "capped") => void;
  pillSnapEnabled?: boolean;
  onTogglePillSnap?: (enabled: boolean) => void;
  monitors?: Parameters<typeof SettingsPanel>[0]["monitors"];
  selectedMonitorId?: string | null;
  onSelectMonitor?: (id: string) => void;
  lookChatPersist?: LookChatPersist;
  onSelectLookChatPersist?: (v: LookChatPersist) => void;
}

interface FullWindowProps {
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  llmStatus: LlmStatus;
  lookMode: "search" | "chat";
  onSelectLookMode: (m: "search" | "chat") => void;
  lookChat: LookChatHook;
  lookChatPersist: LookChatPersist;
  onOpenFile: (path: string) => void;
  onHideToTray: () => void;
  onCaptureFile: (path: string) => void;
  onCaptureNow: () => void;
  pillCorner: PillCorner;
  settingsProps: SettingsForward;
  voicePhase: VoicePhase;
  voiceElapsedMs: number;
  readWaveform: (out: Float32Array) => void;
  readSpectrum: (out: Uint8Array) => void;
  sampleRate: number;
  onVoiceToggle: () => void;
  onVoiceCancel: () => void;
  initialView?: RailView;
}

export default function FullWindow(props: FullWindowProps) {
  const [view, setView] = useState<RailView>(props.initialView ?? "dashboard");
  useEffect(() => {
    if (props.initialView) setView(props.initialView);
  }, [props.initialView]);
  const [inboxTab, setInboxTab] = useState<InboxTab>("inbox");
  const [librarySection, setLibrarySection] = useState<"vault" | "tags" | "trash">("vault");
  const [healthOpen, setHealthOpen] = useState(false);
  const [healthVault, setHealthVault] = useState<number | null>(null);
  const [healthInbox, setHealthInbox] = useState<number | null>(null);
  const openHealth = useCallback(() => {
    setHealthOpen(true);
    getStats().then((s) => setHealthVault(s.total)).catch(() => {});
    getInbox().then((r) => setHealthInbox(r.inbox.length)).catch(() => {});
  }, []);
  const railTrackRef = useRef<HTMLDivElement | null>(null);
  const railBtnRefs = useRef<Partial<Record<RailView, HTMLButtonElement | null>>>({});
  const [sliderRect, setSliderRect] = useState<{ translateY: number; height: number } | null>(null);

  const syncSlider = useCallback(() => {
    const btn = railBtnRefs.current[view];
    if (!btn) { setSliderRect(null); return; }
    setSliderRect(railSliderFromElement(btn));
  }, [view]);

  useLayoutEffect(() => {
    syncSlider();
    const track = railTrackRef.current;
    if (!track) return;
    const ro = new ResizeObserver(() => syncSlider());
    ro.observe(track);
    return () => ro.disconnect();
  }, [syncSlider]);

  const [title, subtitle] = TITLES[view];

  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleRefresh = useCallback(async () => {
    if (syncing) return;
    setSyncing(true);
    setSyncStatus(null);
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    try {
      const result = await syncVaultIndex();
      const total = result.added + result.removed + result.updated;
      setSyncStatus(
        total === 0
          ? `Index up to date — ${result.skipped} unchanged`
          : `Index updated: +${result.added} new, −${result.removed} removed, ${result.updated} changed, ${result.skipped} unchanged`
      );
    } catch (err) {
      setSyncStatus(`Sync failed — ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      setSyncing(false);
      syncTimerRef.current = setTimeout(() => setSyncStatus(null), 4000);
    }
  }, [syncing]);

  useEffect(() => () => { if (syncTimerRef.current) clearTimeout(syncTimerRef.current); }, []);

  // F-7: full-window note editor overlay. FullWindow-exclusive entry point
  // (recent-note row, dashboard-only) -- deliberately does NOT repoint
  // props.onOpenFile itself, since that prop is shared with PillOverlay's
  // compact-mode CompactHistory (external-open there stays untouched; F-7
  // is full-window-mode only). NoteEditor's own "open in external editor"
  // instrument button calls props.onOpenFile to reach the same OS-handler
  // path compact mode already uses.
  const [editorPath, setEditorPath] = useState<string | null>(null);

  return (
    <div
      className="fw-shell"
      data-corner={props.pillCorner}
      style={{ display: "flex", width: "100%", height: "100%", background: "var(--bg)", border: "1px solid var(--border)", overflow: "hidden" }}
    >
      {/* Rail */}
      <div
        className="fw-chrome"
        data-corner={props.pillCorner}
        style={{ width: 56, background: "var(--glass-bg)", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", padding: 8, gap: 8, flex: "none" }}
      >
        <div
          style={{ height: 40, display: "flex", alignItems: "center", justifyContent: "center", flex: "none", position: "relative" }}
          onMouseEnter={openHealth}
          onMouseLeave={() => setHealthOpen(false)}
        >
          <StatusIndicator captureState={props.captureState} llmStatus={props.llmStatus} size={9} />
          {healthOpen && (
            <div
              role="tooltip"
              style={{
                position: "absolute", left: 44, top: 8, zIndex: 60,
                background: "var(--surface)", border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)", padding: "6px 12px",
                boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
                display: "flex", gap: 14, alignItems: "center", whiteSpace: "nowrap",
                fontSize: 11, color: "var(--text-2)", overflow: "hidden",
              }}
            >
              <AmbientStrand />
              {([
                { label: props.llmStatus === "ready" ? "LLM" : props.llmStatus === "loading" ? "LLM warming" : "LLM offline", ok: props.llmStatus === "ready" },
                { label: healthVault === null ? "… notes" : `${healthVault} notes`, ok: true },
                { label: healthInbox === null ? "… inbox" : healthInbox === 0 ? "inbox clear" : `${healthInbox} inbox`, ok: healthInbox === 0 || healthInbox === null },
              ]).map((r) => (
                <span key={r.label} style={{ position: "relative", display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: r.ok ? "var(--green)" : "var(--yellow)", flexShrink: 0 }} />
                  {r.label}
                </span>
              ))}
            </div>
          )}
        </div>

        <div ref={railTrackRef} style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, position: "relative", minHeight: 0 }}>
          <div
            className="rail-slider"
            aria-hidden="true"
            style={{
              transform: sliderRect ? `translateY(${sliderRect.translateY}px)` : undefined,
              height: sliderRect?.height ?? 0,
              opacity: sliderRect ? 1 : 0,
            }}
          />
          <div style={{ flex: "4 1 0", display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
            {MAIN_VIEWS.map((v) => (
              <button
                key={v}
                ref={(el) => { railBtnRefs.current[v] = el; }}
                className="btn-hover rail-btn rail-btn--main"
                onClick={() => setView(v)}
                title={TITLES[v][0]}
                aria-label={TITLES[v][0]}
                aria-pressed={view === v}
              >
                {v === "dashboard" ? <DashboardIcon size={18} /> : v === "look" ? <MenuIcon target="search" size={18} /> : <MenuIcon target="vault" size={18} />}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: "1 1 0", minHeight: 0 }}>
            <div style={{ height: 1, background: "var(--border)", margin: "0 2px 8px", flex: "none" }} />
            <button
              ref={(el) => { railBtnRefs.current.settings = el; }}
              className="btn-hover rail-btn rail-btn--footer"
              onClick={() => setView("settings")}
              title="Settings"
              aria-label="Settings"
              aria-pressed={view === "settings"}
            >
              <MenuIcon target="settings" size={16} />
            </button>
            <button
              className="btn-hover rail-btn rail-btn--footer"
              onClick={props.onHideToTray}
              title="Hide"
              aria-label="Hide"
              aria-pressed={false}
            >
              <MenuIcon target="hide" size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Main content area */}
      <div className="fw-chrome" data-corner={props.pillCorner} style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}>
        {/* Topbar */}
        <div className="drag-region" style={{ height: 46, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10, padding: "0 14px", flex: "none" }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-1)" }}>{title}</span>
          <span style={{ fontSize: 11, color: "var(--text-3)" }}>{subtitle}</span>
          <span style={{ flex: 1 }} />
          {view === "look" && (
            <div className="no-drag" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                className="btn-hover no-drag"
                onClick={handleRefresh}
                disabled={syncing}
                title="Sync vault index"
                aria-label="Sync vault index"
                style={{ opacity: syncing ? 0.5 : 1, display: "flex", alignItems: "center", justifyContent: "center", background: "transparent", border: "none", cursor: "pointer", padding: 4, color: "var(--text-2)" }}
              >
                <svg
                  width="13" height="13" viewBox="0 0 24 24"
                  fill="none" stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round"
                >
                  <polyline points="23 4 23 10 17 10" />
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                </svg>
              </button>
              <SegmentedToggle
                ariaLabel="Look mode"
                options={[{ key: "search" as const, label: "Search" }, { key: "chat" as const, label: "Chat" }]}
                value={props.lookMode}
                onChange={props.onSelectLookMode}
              />
            </div>
          )}
          {view === "library" && (
            <div className="no-drag" style={{ display: "flex", alignItems: "center" }}>
              <SegmentedToggle
                ariaLabel="Vault section"
                options={[
                  { key: "vault" as const, label: "Folders" },
                  { key: "tags" as const, label: "Tags" },
                  { key: "trash" as const, label: "Trash" },
                ]}
                value={librarySection}
                onChange={setLibrarySection}
              />
            </div>
          )}
        </div>

        {/* C2: a render throw in the routed view never blanks the whole
            window — this boundary is keyed by `view` (auto-resets on tab
            switch) and lives entirely inside the content area, so the rail
            above (view switching itself) always survives a tab crash. */}
        <ErrorBoundary key={view}>
        {view === "dashboard" && (
          <div key="dashboard" className="fw-view-panel">
            <DashboardView
              visible
              captureState={props.captureState}
              stepDefs={props.stepDefs}
              onOpenFile={setEditorPath}
              onCaptureFile={props.onCaptureFile}
              onCaptureNow={props.onCaptureNow}
              llmStatus={props.llmStatus}
              onNavigate={(t) => {
                if (t === "library") { setView("library"); return; }
                setInboxTab(t === "reminders" ? "reminders" : "inbox");
                setView("inbox");
              }}
              voicePhase={props.voicePhase}
              voiceElapsedMs={props.voiceElapsedMs}
              readWaveform={props.readWaveform}
              readSpectrum={props.readSpectrum}
              sampleRate={props.sampleRate}
              onVoiceToggle={props.onVoiceToggle}
              onVoiceCancel={props.onVoiceCancel}
            />
          </div>
        )}
        {view === "look" && (
          <div key="look" className="fw-view-panel">
            <LookPanel
              visible
              mode={props.lookMode}
              onSelectMode={props.onSelectLookMode}
              onClose={() => setView("dashboard")}
              lookChat={props.lookChat}
              lookChatPersist={props.lookChatPersist}
              hideToggle
              embedded
              externalSyncing={syncing}
              externalSyncStatus={syncStatus}
            />
          </div>
        )}
        {view === "library" && (
          <div key="library" className="fw-view-panel">
            <LibraryView visible section={librarySection} onOpenNote={setEditorPath} />
          </div>
        )}
        {view === "inbox" && (
          <div key={`inbox-${inboxTab}`} className="fw-view-panel">
            <InboxPanel visible embedded initialTab={inboxTab} onClose={() => setView("dashboard")} />
          </div>
        )}
        {view === "settings" && (
          <div key="settings" className="fw-view-panel fw-settings-sharp">
            <SettingsPanel visible onClose={() => setView("dashboard")} {...props.settingsProps} embedded />
          </div>
        )}
        </ErrorBoundary>
        <NoteEditor
          open={editorPath !== null}
          path={editorPath}
          onClose={() => setEditorPath(null)}
          onOpenExternal={props.onOpenFile}
        />
      </div>
    </div>
  );
}

/** Slow drifting harmonic line behind the health-strip text (user-locked
 *  Q4). Decorative only: two fixed sines at ~0.05 cycles/s, accent color at
 *  low alpha, no audio input. Sized once per mount from the parent strip —
 *  the strip's content is fixed while open, so no resize handling needed. */
function AmbientStrand() {
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !canvas.parentElement) return;
    const w = canvas.parentElement.clientWidth;
    const h = canvas.parentElement.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#737373";
    let raf = 0;
    const t0 = performance.now();
    const draw = () => {
      const t = (performance.now() - t0) / 1000;
      ctx.clearRect(0, 0, w, h);
      ctx.beginPath();
      for (let i = 0; i < 48; i++) {
        const x = i / 47;
        const y = h / 2
          + Math.sin(2 * Math.PI * (1.4 * x + 0.05 * t)) * (h * 0.19)
          + Math.sin(2 * Math.PI * (2.6 * x - 0.03 * t) + 2) * (h * 0.115);
        i === 0 ? ctx.moveTo(0, y) : ctx.lineTo(x * w, y);
      }
      ctx.strokeStyle = accent;
      ctx.globalAlpha = 0.16;
      ctx.lineWidth = 1;
      ctx.stroke();
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={ref} aria-hidden="true" style={{ position: "absolute", inset: 0, pointerEvents: "none" }} />;
}

import { useRef, useState, useLayoutEffect, useCallback } from "react";
import StatusIndicator from "../StatusIndicator";
import SegmentedToggle from "../ui/SegmentedToggle";
import LookPanel from "../LookPanel";
import SettingsPanel from "../SettingsPanel";
import DashboardView from "./DashboardView";
import LibraryView from "./LibraryView";
import { railSliderFromElement } from "../../lib/railSelection";
import { MenuIcon } from "../PillMenu/icons";
import type { CaptureState, CaptureStep } from "../../hooks/useCapture";
import type { LlmStatus } from "../../lib/api";
import type { LookChatPersist } from "../../App";
import type { ChatMessage } from "../../hooks/useLookChat";
import type { PillCorner } from "../PillOverlay";

interface LookChatHook {
  messages: ChatMessage[];
  streaming: boolean;
  ask: (q: string) => void;
  reset: () => void;
  ignoreHistory: boolean;
  setIgnoreHistory: (enabled: boolean) => void;
}

type MainView = "dashboard" | "look" | "library";
type RailView = MainView | "settings";
const MAIN_VIEWS: MainView[] = ["dashboard", "look", "library"];
const TITLES: Record<RailView, [string, string]> = {
  dashboard: ["Dashboard", "capture · recent · health · inbox"],
  look:      ["Look", "search · chat over vault"],
  library:   ["Library", "vault · category · rhythm"],
  settings:  ["Settings", "preferences"],
};

// Subset of SettingsPanel props that FullWindow receives and forwards
interface SettingsForward {
  theme?: Parameters<typeof SettingsPanel>[0]["theme"];
  themeLabel?: string;
  onSelectTheme?: Parameters<typeof SettingsPanel>[0]["onSelectTheme"];
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
  pillCorner: PillCorner;
  settingsProps: SettingsForward;
}

export default function FullWindow(props: FullWindowProps) {
  const [view, setView] = useState<RailView>("dashboard");
  const railTrackRef = useRef<HTMLDivElement | null>(null);
  const railBtnRefs = useRef<Partial<Record<RailView, HTMLButtonElement | null>>>({});
  const [sliderRect, setSliderRect] = useState<{ translateY: number; height: number } | null>(null);

  const syncSlider = useCallback(() => {
    const btn = railBtnRefs.current[view];
    if (!btn) return;
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
        <div style={{ height: 40, display: "flex", alignItems: "center", justifyContent: "center", flex: "none" }}>
          <StatusIndicator captureState={props.captureState} llmStatus={props.llmStatus} size={9} />
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
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
            {MAIN_VIEWS.map((v) => (
              <button
                key={v}
                ref={(el) => { railBtnRefs.current[v] = el; }}
                className="btn-hover rail-btn rail-btn--main"
                onClick={() => setView(v)}
                title={TITLES[v][0]}
                aria-pressed={view === v}
              >
                {v === "dashboard" ? "⊞" : v === "look" ? "⌕" : <MenuIcon target="vault" size={18} />}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: "none" }}>
            <div style={{ height: 1, background: "var(--border)", margin: "0 2px 8px" }} />
            <button
              ref={(el) => { railBtnRefs.current.settings = el; }}
              className="btn-hover rail-btn rail-btn--footer"
              onClick={() => setView("settings")}
              title="Settings"
              aria-pressed={view === "settings"}
            >
              <MenuIcon target="settings" size={16} />
            </button>
            <button
              className="btn-hover rail-btn rail-btn--footer"
              onClick={props.onHideToTray}
              title="Hide to tray"
              aria-pressed={false}
            >
              ⊝
            </button>
          </div>
        </div>
      </div>

      {/* Main content area */}
      <div className="fw-chrome" data-corner={props.pillCorner} style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* Topbar */}
        <div className="drag-region" style={{ height: 46, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10, padding: "0 14px", flex: "none" }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-1)" }}>{title}</span>
          <span style={{ fontSize: 11, color: "var(--text-3)" }}>{subtitle}</span>
          <span style={{ flex: 1 }} />
          {view === "look" && (
            <div className="no-drag">
            <SegmentedToggle
              ariaLabel="Look mode"
              options={[{ key: "search" as const, label: "Search" }, { key: "chat" as const, label: "Chat" }]}
              value={props.lookMode}
              onChange={props.onSelectLookMode}
            />
            </div>
          )}
        </div>

        {view === "dashboard" && (
          <div key="dashboard" className="fw-view-panel">
            <DashboardView
              visible
              captureState={props.captureState}
              stepDefs={props.stepDefs}
              llmStatus={props.llmStatus}
              onOpenFile={props.onOpenFile}
              onCaptureFile={props.onCaptureFile}
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
            />
          </div>
        )}
        {view === "library" && (
          <div key="library" className="fw-view-panel">
            <LibraryView visible />
          </div>
        )}
        {view === "settings" && (
          <div key="settings" className="fw-view-panel fw-settings-sharp">
            <SettingsPanel visible onClose={() => setView("dashboard")} {...props.settingsProps} embedded />
          </div>
        )}
      </div>
    </div>
  );
}

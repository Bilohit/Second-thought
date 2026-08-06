import { useRef, useState, useLayoutEffect, useCallback, useEffect } from "react";
import StatusIndicator from "../StatusIndicator";
import SegmentedToggle from "../ui/SegmentedToggle";
import LookPanel from "../LookPanel";
import SettingsPanel from "../SettingsPanel";
import DashboardView from "./DashboardView";
import LibraryView from "./LibraryView";
import HistoryView from "./HistoryView";
import { railSliderFromElement } from "../../lib/railSelection";
import { MenuIcon, RefreshIcon, FileIcon, CloudIcon, ChatIcon } from "../PillMenu/icons";
import { syncVaultIndex, getStats, getInbox } from "../../lib/api";
import InboxPanel, { type InboxTab } from "../InboxPanel";
import ErrorBoundary from "../ErrorBoundary";
import NoteEditor from "../NoteEditor";
import SyncPanel from "../Sync/SyncPanel";
import { title as fsTitle, body as fsBody } from "../../lib/type";
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

// P3-A (2026-08-06): rail rewrite — 4 views + footer (Dashboard·Look·Vault·
// History + New Note/Settings) become 5 evenly-split tabs: NOTES·BROWSE·
// CHAT·SYNC·SET. This is the shell only — the interiors named per tab below
// (P3-B..P3-E) are each a later task's scope; today's nearest-equivalent
// component is mounted as a placeholder so the app keeps working in the
// meantime. `history` and `inbox` stay valid RailView values with NO rail
// button (same precedent `inbox` already set before this rewrite) — neither
// earned one of the 5 new slots, but both remain reachable programmatically
// (pill-menu "History"/reminders links via viewRouting.ts's VIEW_TO_RAIL,
// DashboardView's onNavigate) so no destination is orphaned.
type MainTab = "notes" | "browse" | "chat" | "sync" | "set";
type RailView = MainTab | "history" | "inbox" | "note";
const MAIN_TABS: MainTab[] = ["notes", "browse", "chat", "sync", "set"];
// ISS-022: the folder-panel nav label is "Vault" everywhere — was "Library"
// here vs "Vault" in Capsule/Minimal mode. SP3 Task 8: the container's
// sub-tabs are now Projects/Trash (the standalone Tags page and the old
// folders/stats grid are gone — ProjectsView is the "vault" sub-tab, spec
// docs/superpowers/specs/2026-08-02-projects-s3-fullwindow-design.md §1).
// FR-07: "history" used to alias "library"/"vault" via App.tsx's
// VIEW_TO_RAIL, which stopped carrying any stats content once s130 pulled
// ProjectBar/DaySparkline out of LibraryView — that regression guard
// (viewRouting.test.ts) still holds post-P3-A: `stats` keeps its own
// `history` destination, distinct from `vault`'s new `browse` destination.
// FR-22: the sub-tab label below is "Notes", not "Projects" — "Projects" now
// names exactly one thing on this screen, ProjectsView's own Projects|Tags
// toggle. Task 3: "Today" is gone — its daily-note card moved into Inbox (a
// strip, full-window only); its Reminders/Scratchpad cards were deleted
// outright, both already duplicated by Inbox's own Reminders tab and header
// count.
// Task 9 (C1): "note" is deliberately absent here now -- NoteEditor's own
// topbar content (back/title/sync/mode-toggle/external/more) is lifted into
// this component's topbar via the `onHeaderActionsChange` slot (see
// `noteHeaderActions` state below), the same seam InboxPanel/CompactQuickNote
// already use for CompactShell. A fixed "Note" placeholder would be wrong the
// instant a real note (or "New Note") is open, so the note view's title is
// computed from `editorPath` at render time instead -- see `title`/`subtitle`
// below -- and used only as the one-frame fallback before NoteEditor's effect
// fires on mount. P3-B: this whole view becomes a window-level slide-over
// from the right instead of a plain routed view — out of scope here.
const TITLES: Record<Exclude<RailView, "note">, [string, string]> = {
  // P3-B owns NOTES' real interior (list + 280px morphing capture pane,
  // radial → blank/voice/clip/screenshot, hotkey → live StepIndicator over
  // STEP_DEFS). DashboardView is today's nearest equivalent — it already
  // carries the capture front door + recent notes + inbox/reminders nav.
  notes:   ["Notes", "capture · recent · inbox"],
  // P3-D splits CHAT out of LookPanel's search/chat toggle into its own tab.
  // Until then this mounts LookPanel unchanged (both modes) so search stays
  // reachable — losing it here would be a real regression, not a shell nicety.
  chat:    ["Chat", "search · chat over vault"],
  // P3-C owns BROWSE's real interior (sectioned search + paged 4×2 project
  // rects + tag list + LIST/STARS toggle — none of that exists today).
  // LibraryView (ProjectsRail + ProjectsPane + Trash) is the nearest
  // equivalent: today's one project/tag browsing surface.
  browse:  ["Browse", "projects · tags · notes"],
  // P3-E owns SYNC's real interior over Phase 1's /sync/activity + /sync/pending
  // endpoints (hub strip · queue · conflicts · activity, gap-filled for real,
  // no stubbed rows). SyncPanel — today's Settings › Sync sub-tab body — is
  // the nearest equivalent and is mounted here unmodified.
  sync:    ["Sync", "hub · queue · conflicts · activity"],
  // SET is a VISUAL NO-FLY ZONE (Form/Function/Sync stay exactly as shipped) —
  // this is a direct, unmodified mount of SettingsPanel, not a placeholder.
  set:     ["Settings", ""],
  history: ["History", "by project"],
  inbox:   ["Inbox", "review · reminders"],
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
  /** s114/d07: the capsule's Inbox badge went stale after an approve/discard because nothing
   *  consumed InboxPanel's existing count callback. Both hosts forward it to App now. */
  onInboxCountChange?: (count: number) => void;
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  llmStatus: LlmStatus;
  lookMode: "search" | "chat";
  onSelectLookMode: (m: "search" | "chat") => void;
  lookChat: LookChatHook;
  lookChatPersist: LookChatPersist;
  onOpenFile: (path: string) => void;
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
  /** FR-07 dead-control fix: bumped by App.tsx on every menu/nav-event
   *  selection, independent of whether `initialView`'s *value* changed.
   *  Re-selecting the rail section you're already on (e.g. clicking History
   *  in the pill menu while already viewing it) previously did nothing —
   *  `initialView` was the same string as last time, so the effect below
   *  (keyed only on that value) never re-ran. This is the general fix, not
   *  a per-target special case: it re-applies for any RailView, including
   *  a case the App-level `view` state never even changes for. */
  initialViewToken?: number;
}

export default function FullWindow(props: FullWindowProps) {
  const [view, setView] = useState<RailView>(props.initialView ?? "notes");
  useEffect(() => {
    if (props.initialView) setView(props.initialView);
  }, [props.initialView, props.initialViewToken]);
  const [inboxTab, setInboxTab] = useState<InboxTab>("inbox");
  const [browseSection, setBrowseSection] = useState<"vault" | "trash">("vault");
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

  // Task 8: opening a note now has to switch the rail to the "note" view too
  // (not just set the path) -- the editor is an ordinary keyed view, so
  // nothing shows it unless `view` actually points at it.
  const openNote = useCallback((path: string) => {
    setEditorPath(path);
    setView("note");
  }, []);

  // Task 9 (C1): NoteEditor's own topbar is deleted -- it pushes its content
  // (back/title/sync/mode-toggle/external/more) up into this component's
  // shared topbar through `onHeaderActionsChange`, exactly the seam
  // InboxPanel/CompactQuickNote already use to reach CompactShell's
  // `headerActions` slot. `null` until NoteEditor's effect fires (or once it
  // unmounts), and reset whenever the rail leaves the note view so a stale
  // note's controls can't survive into "New Note" or a different rail tab.
  const [noteHeaderActions, setNoteHeaderActions] = useState<React.ReactNode | null>(null);
  useEffect(() => {
    if (view !== "note") setNoteHeaderActions(null);
  }, [view]);

  // Task 9: "note" has no static TITLES entry (see comment above the map) --
  // derive a real filename fallback from `editorPath` instead of a fixed
  // placeholder. This only ever paints for the one frame before NoteEditor's
  // own `onHeaderActionsChange` effect fires and `noteHeaderActions` above
  // takes over rendering the topbar for real.
  const [title, subtitle] = view === "note"
    ? [editorPath ? (editorPath.split(/[\\/]/).pop() ?? "Note").replace(/\.md$/i, "") : "New Note", ""]
    : TITLES[view];

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
                fontSize: fsBody, color: "var(--text-2)", overflow: "hidden",
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

        <div ref={railTrackRef} data-testid="fw-rail" style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, position: "relative", minHeight: 0 }}>
          <div
            className="rail-slider"
            aria-hidden="true"
            style={{
              transform: sliderRect ? `translateY(${sliderRect.translateY}px)` : undefined,
              height: sliderRect?.height ?? 0,
              opacity: sliderRect ? 1 : 0,
            }}
          />
          {/* P3-A: 5 tabs, evenly split (one flex column, all rail-btn--main) —
              replaces the old 4-main + divider + 2-footer split. "New Note"
              is deliberately gone as a standalone slot: P3-B folds it into
              NOTES' capture-pane radial (blank-note satellite), matching the
              V2 mock's 5-button rail exactly (SecondThoughtV2.html:904-908). */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
            {MAIN_TABS.map((v) => (
              <button
                key={v}
                ref={(el) => { railBtnRefs.current[v] = el; }}
                className="btn-hover rail-btn rail-btn--main"
                onClick={() => setView(v)}
                title={TITLES[v][0]}
                aria-label={TITLES[v][0]}
                aria-pressed={view === v}
              >
                {v === "notes" ? <FileIcon size={18} />
                  : v === "browse" ? <MenuIcon target="vault" size={18} />
                  : v === "chat" ? <ChatIcon size={18} />
                  : v === "sync" ? <CloudIcon size={18} />
                  : <MenuIcon target="settings" size={18} />}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main content area */}
      <div className="fw-chrome" data-corner={props.pillCorner} style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}>
        {/* Topbar */}
        <div className="drag-region" style={{ height: 46, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10, padding: "0 14px", flex: "none" }}>
          {view === "note" ? (
            // Task 9 (C1): NoteEditor supplies its whole row (back/title/sync/
            // mode-toggle/external/more) through the slot -- this wrapper only
            // provides `no-drag` (a "drag-region" ancestor would otherwise eat
            // clicks on the lifted buttons) and the fallback title for the one
            // frame before that content arrives.
            <div className="no-drag" style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 0 }}>
              {noteHeaderActions ?? <span style={{ fontSize: fsTitle, fontWeight: 600, color: "var(--text-1)" }}>{title}</span>}
            </div>
          ) : (
            <>
              <span style={{ fontSize: fsTitle, fontWeight: 600, color: "var(--text-1)" }}>{title}</span>
              <span style={{ fontSize: fsBody, color: "var(--text-3)" }}>{subtitle}</span>
              <span style={{ flex: 1 }} />
            </>
          )}
          {view === "chat" && (
            <div className="no-drag" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                className="btn-hover no-drag"
                onClick={handleRefresh}
                disabled={syncing}
                title="Sync vault index"
                aria-label="Sync vault index"
                style={{ opacity: syncing ? 0.5 : 1, display: "flex", alignItems: "center", justifyContent: "center", background: "transparent", border: "none", cursor: "pointer", padding: 4, color: "var(--text-2)" }}
              >
                <RefreshIcon size={13} />
              </button>
              {/* P3-D: CHAT splits from Search into its own tab — this toggle
                  (and the search mode it exposes) moves into BROWSE's
                  sectioned search (P3-C). --swap-dir is coupled to the
                  Search=0/Chat=1 ordering below; reordering flips slide
                  direction silently. */}
              <SegmentedToggle
                ariaLabel="Look mode"
                options={[{ key: "search" as const, label: "Search" }, { key: "chat" as const, label: "Chat" }]}
                value={props.lookMode}
                onChange={props.onSelectLookMode}
              />
            </div>
          )}
          {view === "browse" && (
            <div className="no-drag" style={{ display: "flex", alignItems: "center" }}>
              <SegmentedToggle
                ariaLabel="Vault section"
                options={[
                  { key: "vault" as const, label: "Notes" },
                  { key: "trash" as const, label: "Trash" },
                ]}
                value={browseSection}
                onChange={setBrowseSection}
              />
            </div>
          )}
        </div>

        {/* C2: a render throw in the routed view never blanks the whole
            window — this boundary is keyed by `view` (auto-resets on tab
            switch) and lives entirely inside the content area, so the rail
            above (view switching itself) always survives a tab crash. */}
        <ErrorBoundary key={view}>
        {view === "notes" && (
          <div key="notes" className="fw-view-panel">
            {/* P3-B: NOTES' real interior is a note list + a 280px morphing
                capture pane (radial → blank-note/voice/clip/screenshot; the
                hotkey path drives a live StepIndicator over the real
                STEP_DEFS). DashboardView is today's nearest equivalent —
                mounted unmodified. */}
            <DashboardView
              visible
              captureState={props.captureState}
              stepDefs={props.stepDefs}
              onOpenFile={openNote}
              onCaptureFile={props.onCaptureFile}
              onCaptureNow={props.onCaptureNow}
              llmStatus={props.llmStatus}
              onNavigate={(t) => {
                if (t === "library") { setView("browse"); return; }
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
        {view === "chat" && (
          <div key="chat" className="fw-view-panel">
            <LookPanel
              visible
              mode={props.lookMode}
              onSelectMode={props.onSelectLookMode}
              onClose={() => setView("notes")}
              lookChat={props.lookChat}
              lookChatPersist={props.lookChatPersist}
              hideToggle
              embedded
              externalSyncing={syncing}
              externalSyncStatus={syncStatus}
            />
          </div>
        )}
        {view === "browse" && (
          <div key="browse" className="fw-view-panel">
            {/* P3-C: BROWSE is entirely net-new (sectioned search + paged
                4x2 project rects + tag list + a titlebar LIST/STARS toggle —
                none of that exists today). LibraryView (ProjectsRail +
                ProjectsPane + Trash) is the nearest equivalent — mounted
                unmodified. */}
            <LibraryView visible section={browseSection} onOpenNote={openNote} />
          </div>
        )}
        {view === "sync" && (
          <div key="sync" className="fw-view-panel">
            {/* P3-E: SYNC's real interior renders over Phase 1's real
                endpoints (GET /sync/activity, GET /sync/pending) — hub strip,
                queue, conflicts, activity, gap-filled for real, no stubbed
                rows or invented data. SyncPanel is today's Settings > Sync
                sub-tab body, the exact "Today: Settings tab 3" source named
                in the program plan's surface table — mounted unmodified. */}
            <SyncPanel compact={false} />
          </div>
        )}
        {/* History has no rail slot in the new 5-tab IA (it never earned one
            of the 5 evenly-split tabs), but stays reachable exactly the way
            `inbox` already was pre-P3-A: no button, still a valid RailView,
            still reachable via viewRouting.ts's VIEW_TO_RAIL (pill menu
            "History") so nothing here is orphaned. Its "by project" content
            is the most likely feed into BROWSE's future project rects (P3-C)
            but that merge is not this task's call to make. */}
        {view === "history" && (
          <div key="history" className="fw-view-panel">
            <HistoryView visible />
          </div>
        )}
        {view === "inbox" && (
          <div key={`inbox-${inboxTab}`} className="fw-view-panel">
            <InboxPanel visible embedded initialTab={inboxTab} onClose={() => setView("notes")} onCountChange={props.onInboxCountChange} onOpenNote={openNote} />
          </div>
        )}
        {view === "set" && (
          <div key="set" className="fw-view-panel fw-settings-sharp">
            {/* SET is a VISUAL NO-FLY ZONE — SettingsPanel mounted exactly as
                it ships today (Form/Function/Sync ordering untouched). */}
            <SettingsPanel visible onClose={() => setView("notes")} {...props.settingsProps} embedded />
          </div>
        )}
        {view === "note" && (
          <div key="note" className="fw-view-panel">
            {/* P3-B: this becomes a window-level slide-over from the right
                (view/edit toggle, open-in-OS-editor, 3-dot: Reminder / Set as
                template / Outline / History / Delete). Stays a plain routed
                view for now — out of scope here. Per s145: the editor must
                close on EVERY tab switch, BROWSE included; that already
                holds today via the ErrorBoundary-keyed `view` switch below,
                unchanged by this task. */}
            <NoteEditor
              open
              path={editorPath}
              onClose={() => { setView("notes"); setEditorPath(null); }}
              onOpenExternal={props.onOpenFile}
              onHeaderActionsChange={setNoteHeaderActions}
            />
          </div>
        )}
        </ErrorBoundary>
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

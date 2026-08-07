import { useRef, useState, useLayoutEffect, useCallback, useEffect } from "react";
import StatusIndicator from "../StatusIndicator";
import SegmentedToggle from "../ui/SegmentedToggle";
import LookPanel from "../LookPanel";
import SettingsPanel from "../SettingsPanel";
import NotesView from "./NotesView";
import BrowseView from "./BrowseView";
import TrashView from "./TrashView";
import HistoryView from "./HistoryView";
import { railSliderFromElement } from "../../lib/railSelection";
import { MenuIcon, RefreshIcon, FileIcon, CloudIcon, ChatIcon, ListIcon, StarIcon } from "../PillMenu/icons";
import { syncVaultIndex, getStats, getInbox } from "../../lib/api";
import InboxPanel, { type InboxTab } from "../InboxPanel";
import ErrorBoundary from "../ErrorBoundary";
import NoteEditor from "../NoteEditor";
import SyncPanel from "../Sync/SyncPanel";
import SyncFeed from "../Sync/SyncFeed";
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
// CHAT·SYNC·SET. `history` and `inbox` stay valid RailView values with NO
// rail button (same precedent `inbox` already set before this rewrite) —
// neither earned one of the 5 new slots, but both remain reachable
// programmatically (pill-menu "History"/reminders links via
// viewRouting.ts's VIEW_TO_RAIL, NotesView's/InboxPanel's own nav) so no
// destination is orphaned.
//
// P3-B: the note editor is NO LONGER a routed RailView value — it is a
// window-level slide-over (`editorOpen`/`editorPath` below), independent of
// which tab is showing underneath, and per the s145 override it closes on
// EVERY tab switch (BROWSE included; the mock left it open over BROWSE,
// which is a mock bug — DECISIONS.md §5 s145). `ExternalNav` keeps "note"
// as a value ONLY for `initialView`/`initialViewToken` (App.tsx's pill-menu
// "New Note" selection, `VIEW_TO_RAIL["note"] === "note"`, still needs a way
// to ask FullWindow to open a blank note from outside) — it is translated
// into `openNote(null)` below and never assigned to `view` itself.
type MainTab = "notes" | "browse" | "chat" | "sync" | "set";
type RailView = MainTab | "history" | "inbox";
type ExternalNav = RailView | "note";
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
// Task 9 (C1) / P3-B: "note" is not a RailView any more, so it never needs an
// entry here — NoteEditor's own header content (back/title/sync/mode-toggle/
// external/more) still reaches the DOM via the `onHeaderActionsChange` slot
// (see `noteHeaderActions` state below), the same seam InboxPanel/
// CompactQuickNote already use for CompactShell, but P3-B now renders that
// lifted content inside the slide-over's own header strip instead of this
// shared per-tab topbar, so the two never compete for the same row.
// P3-D: LookPanel's `onSelectMode` is required but unreachable when
// `hideToggle` is set (its only call site is the internal toggle that prop
// suppresses) — a single module-level no-op avoids allocating a fresh
// closure per render for a callback that can never fire.
function noOpSelectMode(): void {}

const TITLES: Record<RailView, [string, string]> = {
  // P3-B: real interior — list pane + 280px morphing capture pane (radial →
  // blank/voice/clip/screenshot; any in-flight capture, hotkey-triggered or
  // not, shows the live StepIndicator over the real `stepDefs`).
  notes:   ["Notes", "capture · recent"],
  // P3-D: CHAT is chat-only now — Search moved into BROWSE's own sectioned
  // search (P3-C, BrowseView.tsx) and the Search/Chat toggle that used to
  // pick between them left this tab's topbar entirely (see the `view ===
  // "chat"` block below). LookPanel is locked to `mode="chat"` at the call
  // site instead of forwarding `props.lookMode`.
  chat:    ["Chat", "local model · your vault"],
  // P3-C owns BROWSE's real interior (sectioned search + paged 4×2 project
  // rects + tag list + LIST/STARS toggle — none of that exists today).
  // LibraryView (ProjectsRail + ProjectsPane + Trash) is the nearest
  // equivalent: today's one project/tag browsing surface.
  browse:  ["Browse", "projects · tags · notes"],
  // P3-E owns SYNC's real interior over Phase 1's /sync/activity + /sync/pending
  // endpoints (hub strip · pending · conflicts · activity, gap-filled for real,
  // no stubbed rows). SyncPanel — today's Settings › Sync sub-tab body — is
  // mounted here unmodified as the hub strip (constraint: never fork its
  // behavior for a caller); SyncFeed.tsx adds the three new real sections below
  // it. "Queue" is intentionally absent from this subtitle and everywhere in
  // SyncFeed — the resting Pending read is a local diff, not a live Drive
  // listing, and only earns drain semantics on an explicit user gesture.
  sync:    ["Sync", "hub · pending · conflicts · activity"],
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
  /** "note" is accepted here even though it is no longer a `RailView` value
   *  (P3-B) — App.tsx's pill-menu "New Note" selection still needs a way to
   *  ask for a blank note from outside; see the effect below that translates
   *  it into `openNote(null)` instead of ever assigning it to `view`. */
  initialView?: ExternalNav;
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
  const [view, setView] = useState<RailView>(
    props.initialView && props.initialView !== "note" ? props.initialView : "notes",
  );

  // P3-B: the note editor is a WINDOW-LEVEL SLIDE-OVER from the right,
  // tracked independently of `view` — opening a note no longer navigates the
  // rail. `editorOpen` (not `editorPath !== null`) is the open/closed flag,
  // because `null` is itself a valid open state (a brand-new blank note,
  // NoteEditor's own path===null create-on-first-keystroke flow, s135).
  const [editorPath, setEditorPath] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const openNote = useCallback((path: string | null) => {
    setEditorPath(path);
    setEditorOpen(true);
  }, []);
  const closeNote = useCallback(() => setEditorOpen(false), []);

  // ★ s145 override of the mock (binding, DECISIONS.md §5 s145): the editor
  // closes on EVERY tab switch, BROWSE included — the mock leaves it open
  // over BROWSE, which was a mock bug. Keyed on `view` alone: reselecting the
  // already-active tab doesn't change `view`'s value, so it correctly does
  // NOT close the editor (not a "switch").
  useEffect(() => { setEditorOpen(false); }, [view]);

  // `initialView === "note"` — App.tsx's pill-menu "New Note" selection —
  // opens the blank-note overlay instead of ever assigning "note" to `view`
  // (which is no longer a valid `RailView` value at all, P3-B).
  useEffect(() => {
    if (!props.initialView) return;
    if (props.initialView === "note") { openNote(null); return; }
    setView(props.initialView);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.initialView, props.initialViewToken]);

  // P3-B: NOTES no longer carries a "jump to Reminders sub-tab" shortcut
  // (DashboardView's old onNavigate) — the mock's own NOTES screen has no
  // such affordance either. Inbox itself stays reachable exactly as P3-A's
  // own comment anticipated: the pill menu's "Inbox" target routes here via
  // `viewRouting.ts`, independent of anything NOTES renders.
  const [inboxTab] = useState<InboxTab>("inbox");
  const [browseSection, setBrowseSection] = useState<"vault" | "trash">("vault");
  // P3-C1: the mock's titlebar LIST/STARS toggle (SecondThoughtV2.html:897-899)
  // — lives here, not inside BrowseView, for the same reason `browseSection`
  // does: both are per-tab topbar controls FullWindow already owns (see the
  // CHAT tab's Search/Chat SegmentedToggle above). Only meaningful over the
  // vault half of `browseSection` — Trash has no list/stars concept, the
  // mock doesn't cover it at all (see this task's report).
  const [browseMode, setBrowseMode] = useState<"list" | "stars">("list");
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

  // Task 9 (C1) / P3-B: NoteEditor still has no topbar of its own — it pushes
  // its header content (back/title/sync/mode-toggle/external/more) up
  // through `onHeaderActionsChange`, the same seam InboxPanel/
  // CompactQuickNote use for CompactShell — but that content now renders
  // inside the slide-over's own header strip (below), not this shared
  // per-tab topbar. NoteEditor's own effect already pushes `null` the moment
  // its `open` prop goes false (see NoteEditor.tsx), so nothing here needs
  // to reset it manually on tab switch any more.
  const [noteHeaderActions, setNoteHeaderActions] = useState<React.ReactNode | null>(null);

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
        {/* Topbar — P3-B: always the current tab's own title/controls now.
            The note editor is a slide-over with its own header strip (below),
            so it no longer competes with this row for `noteHeaderActions`. */}
        <div className="drag-region" style={{ height: 46, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10, padding: "0 14px", flex: "none" }}>
          <span style={{ fontSize: fsTitle, fontWeight: 600, color: "var(--text-1)" }}>{title}</span>
          <span style={{ fontSize: fsBody, color: "var(--text-3)" }}>{subtitle}</span>
          <span style={{ flex: 1 }} />
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
            </div>
          )}
          {view === "browse" && (
            <div className="no-drag" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <SegmentedToggle
                ariaLabel="Vault section"
                options={[
                  { key: "vault" as const, label: "Notes" },
                  { key: "trash" as const, label: "Trash" },
                ]}
                value={browseSection}
                onChange={setBrowseSection}
              />
              {/* P3-C1: the mock's LIST/STARS toggle — icon-only per the
                  identity rule (all switches are icon-only), `label` still
                  supplies the accessible name/tooltip. Only shown over the
                  vault half of the split — see `browseMode`'s comment. */}
              {browseSection === "vault" && (
                <SegmentedToggle
                  ariaLabel="Browse view"
                  options={[
                    { key: "list" as const, label: "List", icon: <ListIcon size={13} /> },
                    { key: "stars" as const, label: "Constellation", icon: <StarIcon size={13} /> },
                  ]}
                  value={browseMode}
                  onChange={setBrowseMode}
                />
              )}
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
            {/* P3-B: NOTES' real interior — a vault list pane + a 280px
                morphing capture pane. The radial (blank-note/voice/clip/
                screenshot) is net new: it has never mounted in the full
                window before this. Any in-flight capture — hotkey-triggered
                or started from a satellite — shows the live StepIndicator
                over the real `stepDefs` (see NotesView.tsx's file header). */}
            <NotesView
              visible
              captureState={props.captureState}
              stepDefs={props.stepDefs}
              onOpenFile={openNote}
              onCaptureFile={props.onCaptureFile}
              onCaptureNow={props.onCaptureNow}
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
            {/* P3-D: CHAT is chat-only — `mode` is locked to "chat" here
                rather than forwarding the app-level `lookMode` state (that
                state still exists for the pill's own Search/Chat toggle,
                CompactLook.tsx, which keeps both modes and is unaffected —
                see LookPanel.test.tsx's swap-direction pin). `onSelectMode`
                is a stable no-op: LookPanel only ever calls it from its own
                internal toggle, permanently hidden here by `hideToggle`. */}
            <LookPanel
              visible
              mode="chat"
              onSelectMode={noOpSelectMode}
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
            {/* P3-C1: BROWSE is now the mock's real interior — sectioned
                search + paged 4x2 project tiles + tag list, STARS stubbed
                (BrowseView.tsx). `browseSection` keeps its pre-existing
                vault/trash split (topbar above) — the mock has no trash
                concept at all, so Trash renders TrashView directly here
                exactly as LibraryView used to, instead of going through the
                now-unmounted LibraryView/ProjectsView/ProjectsRail/
                ProjectsPane stack (left in place per this task's brief —
                not deleted, just superseded on this route). */}
            {browseSection === "vault" ? (
              <BrowseView visible mode={browseMode} onOpenNote={openNote} />
            ) : (
              <div style={{ flex: 1, minHeight: 0, padding: 14, display: "flex" }}>
                <div style={{ flex: 1, minHeight: 0, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
                  <TrashView visible />
                </div>
              </div>
            )}
          </div>
        )}
        {view === "sync" && (
          <div key="sync" className="fw-view-panel" style={{ overflowY: "auto" }}>
            {/* P3-E: SYNC's real interior renders over Phase 1's real
                endpoints (GET /sync/activity, GET /sync/pending) — hub strip,
                pending, conflicts, activity, gap-filled for real, no stubbed
                rows or invented data. SyncPanel is today's Settings > Sync
                sub-tab body, the exact "Today: Settings tab 3" source named
                in the program plan's surface table — mounted here unmodified
                as the hub strip (master switch, Drive gauge, schedule,
                same-WiFi shortcut); it is shared with Settings' own Sync
                sub-tab so its behavior is never forked for this caller.
                SyncFeed.tsx owns the three new sections: Pending (the local
                diff, GET /sync/pending), Conflicts (GET /vault/conflicts —
                see SyncFeed.tsx's header comment for why this is the real
                render location, not DashboardView.tsx, which P3-A already
                made unreachable), and Activity (GET /sync/activity). */}
            {/* Padding/gap match SettingsPanel's own full-window Sync-tab
                container (SettingsPanel.tsx:709) so the two mounts of
                SyncPanel read identically. */}
            <div style={{ padding: "16px 16px 14px", display: "flex", flexDirection: "column", gap: 16 }}>
              <SyncPanel compact={false} />
              <SyncFeed onOpenNote={openNote} />
            </div>
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
        </ErrorBoundary>

        {/* P3-B: the note editor is a WINDOW-LEVEL SLIDE-OVER from the right
            — an absolutely-positioned overlay sibling of the topbar+content
            column above (not a routed view inside the ErrorBoundary switch),
            so it can stay open over whichever tab was showing when it opened
            and slides independently of tab navigation. Per the ★ s145
            override of the mock (DECISIONS.md §5 s145): it still closes on
            EVERY tab switch, BROWSE included — see the `[view]`-keyed effect
            above — the mock's own "stays open over BROWSE" behavior was a
            mock bug, not the spec. Always mounted (never conditionally
            rendered) so the slide transition has something to animate;
            NoteEditor itself returns null while its own `open` prop is
            false, same as it always has. */}
        <div
          className="no-drag"
          style={{
            position: "absolute", top: 0, right: 0, bottom: 0, width: "54%",
            display: "flex", flexDirection: "column", minWidth: 0,
            background: "var(--surface)", borderLeft: "1px solid var(--border)",
            transform: editorOpen ? "translateX(0)" : "translateX(103%)",
            transition: "transform 340ms cubic-bezier(0.22,1,0.36,1)",
            pointerEvents: editorOpen ? "auto" : "none",
            zIndex: 5,
          }}
        >
          <div style={{ height: 46, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10, padding: "0 14px", flex: "none" }}>
            {noteHeaderActions}
          </div>
          <NoteEditor
            open={editorOpen}
            path={editorPath}
            onClose={closeNote}
            onOpenExternal={props.onOpenFile}
            onHeaderActionsChange={setNoteHeaderActions}
          />
        </div>
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

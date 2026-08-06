// @vitest-environment happy-dom
/**
 * FullWindow.test.tsx — Task 8, this component's first tests.
 *
 * Regression: NoteEditor used to be a permanently-mounted, position:absolute
 * overlay sibling of the view switch, so once a note was opened the left
 * rail's clicks fired (setView DID change) but nothing ever appeared to
 * happen -- the overlay just kept covering the content column. Task 8 moves
 * NoteEditor inside the `<ErrorBoundary key={view}>` switch as an ordinary
 * `view === "note"` branch, so opening a note is real navigation and a rail
 * click away from it unmounts the editor like any other view swap.
 *
 * P3-A (2026-08-06): the rail went from 4 main views + a 2-button footer
 * (New Note / Settings) to 5 evenly-split tabs (NOTES · BROWSE · CHAT ·
 * SYNC · SET) with no separate "New Note" slot -- P3-B folds note creation
 * into NOTES' capture-pane radial.
 *
 * P3-B (2026-08-06): the note editor stopped being a routed `RailView` value
 * entirely -- it is now a window-level slide-over, tracked by its own
 * `editorOpen` state, independent of `view`. Opening a note (via
 * `initialView="note"`, the same prop path App.tsx's pill-menu "New Note"
 * drives FullWindow through) no longer changes which rail tab is pressed;
 * closing it happens on every `view` change instead (★ s145 override of the
 * mock, binding: closes even when the switch is to BROWSE).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, within, fireEvent, cleanup } from "@testing-library/react";
import FullWindow from "./FullWindow";
import * as api from "../../lib/api";
import type { CaptureState, CaptureStep } from "../../hooks/useCapture";
import type { Stats } from "../../lib/api";

vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({
    onDragDropEvent: vi.fn().mockResolvedValue(() => {}),
  }),
}));

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    getStats: vi.fn(),
    getInbox: vi.fn(),
    listReminders: vi.fn(),
    getConfig: vi.fn(),
    getVaultConflicts: vi.fn(),
    checkHealth: vi.fn(),
    searchCaptures: vi.fn(),
  };
});

const emptyStats: Stats = { total: 0, by_project: [], by_day: [], recent: [] };

const idleCapture: CaptureState = {
  phase: "idle",
  steps: { intercept: "pending", enrich: "pending", decide: "pending", write: "pending" },
  preview: null,
  result: null,
  errorMsg: null,
  thinking: null,
  backgroundJob: null,
  starting: false,
  reminderOffer: null,
  aiOffline: false,
};

const stepDefs: CaptureStep[] = [];

const baseProps = {
  captureState: idleCapture,
  stepDefs,
  llmStatus: "ready" as const,
  lookMode: "search" as const,
  onSelectLookMode: vi.fn(),
  lookChat: {
    messages: [],
    streaming: false,
    ask: vi.fn(),
    reset: vi.fn(),
    retry: vi.fn(),
    ignoreHistory: false,
    setIgnoreHistory: vi.fn(),
  },
  lookChatPersist: "preserve" as const,
  onOpenFile: vi.fn(),
  onCaptureFile: vi.fn(),
  onCaptureNow: vi.fn(),
  pillCorner: "sharp" as const,
  settingsProps: {},
  voicePhase: "idle" as const,
  voiceElapsedMs: 0,
  readWaveform: vi.fn(),
  readSpectrum: vi.fn(),
  sampleRate: 44100,
  onVoiceToggle: vi.fn(),
  onVoiceCancel: vi.fn(),
};

function mockNetworkDefaults() {
  vi.mocked(api.getStats).mockResolvedValue(emptyStats);
  vi.mocked(api.getInbox).mockResolvedValue({ inbox: [], count: 0 });
  vi.mocked(api.listReminders).mockResolvedValue([]);
  vi.mocked(api.getConfig).mockResolvedValue({});
  vi.mocked(api.getVaultConflicts).mockResolvedValue([]);
  vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });
  vi.mocked(api.searchCaptures).mockResolvedValue({ results: [], count: 0, query: "" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FullWindow — rail stays live behind the note editor (Task 8)", () => {
  it("switches view when a rail tab is clicked while a note is open", async () => {
    mockNetworkDefaults();
    // P3-A: opened via `initialView` (the exact prop App.tsx's pill menu
    // already drives FullWindow through) instead of a rail "New Note"
    // click -- that button no longer exists (see file docblock).
    render(<FullWindow {...baseProps} initialView="note" />);

    expect(screen.getByRole("dialog", { name: /note editor/i })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^sync$/i }));

    expect(screen.queryByRole("dialog", { name: /note editor/i })).toBeNull();
    expect(screen.getByRole("button", { name: /^sync$/i }).getAttribute("aria-pressed")).toBe("true");
  });

  // ★ s145 override of the mock (binding, DECISIONS.md §5 s145): the mock's
  // own desktop screen (`setDeskScreen` in SecondThoughtV2.html) leaves the
  // editor open when switching TO browse specifically -- `if (s !== "browse")
  // closeDesk()`. That is the one case this program plan overrides: the
  // editor must close on EVERY tab switch, BROWSE included.
  it("closes the editor when switching to BROWSE specifically (s145 override of the mock)", async () => {
    mockNetworkDefaults();
    render(<FullWindow {...baseProps} initialView="note" />);
    expect(screen.getByRole("dialog", { name: /note editor/i })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^browse$/i }));

    expect(screen.queryByRole("dialog", { name: /note editor/i })).toBeNull();
  });

  it("stays open while re-selecting the same tab it opened on (not a 'switch')", async () => {
    mockNetworkDefaults();
    render(<FullWindow {...baseProps} initialView="note" />);
    expect(screen.getByRole("dialog", { name: /note editor/i })).toBeTruthy();

    // The overlay opened on top of the default "Notes" view -- clicking the
    // already-active Notes tab is not a switch (`view`'s value is unchanged),
    // so the editor must not close.
    fireEvent.click(screen.getByRole("button", { name: /^notes$/i }));

    expect(screen.getByRole("dialog", { name: /note editor/i })).toBeTruthy();
  });

  it("has exactly 5 evenly-split tabs, in order NOTES · BROWSE · CHAT · SYNC · SET", () => {
    mockNetworkDefaults();
    render(<FullWindow {...baseProps} />);

    const rail = screen.getByTestId("fw-rail");
    const buttons = within(rail).getAllByRole("button");
    const labels = buttons.map((b) => b.getAttribute("aria-label"));

    // P3-A: the old 4-main + divider + 2-footer split is gone -- all 5 tabs
    // are `rail-btn--main` now, none is `rail-btn--footer`, and "New Note"
    // is no longer a standalone slot (folds into NOTES' future capture
    // pane, P3-B).
    expect(labels).toEqual(["Notes", "Browse", "Chat", "Sync", "Settings"]);
    expect(buttons.every((b) => b.className.includes("rail-btn--main"))).toBe(true);
    expect(buttons.some((b) => b.className.includes("rail-btn--footer"))).toBe(false);
  });

  it("clicking a tab presses it and un-presses every other tab (railSliderFromElement's target)", () => {
    mockNetworkDefaults();
    render(<FullWindow {...baseProps} />);

    const rail = screen.getByTestId("fw-rail");
    const pressed = () =>
      within(rail).getAllByRole("button").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.getAttribute("aria-label"));

    expect(pressed()).toEqual(["Notes"]); // default view

    fireEvent.click(screen.getByRole("button", { name: /^browse$/i }));
    expect(pressed()).toEqual(["Browse"]);

    fireEvent.click(screen.getByRole("button", { name: /^chat$/i }));
    expect(pressed()).toEqual(["Chat"]);
  });

  it("has no Hide control", () => {
    mockNetworkDefaults();
    render(<FullWindow {...baseProps} />);

    expect(screen.queryByRole("button", { name: /hide/i })).toBeNull();
  });
});

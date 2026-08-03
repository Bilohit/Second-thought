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
 * `openANote()` below opens the editor via the new rail "New Note" button
 * (null path, no note ever created since nothing is typed) rather than via
 * an existing vault note -- that keeps this file's mocking to exactly the
 * views that actually mount (Dashboard, then History) instead of also
 * needing LibraryView/ProjectsView's own note-listing API surface. The
 * assertion under test -- a rail click while `view === "note"` actually
 * switches views -- doesn't care whether the open note is new or existing.
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
}

/** Opens NoteEditor via the rail's "New Note" button (null path -- no
 *  keystroke, so no createNote() call fires; see file docblock). */
function openANote() {
  fireEvent.click(screen.getByRole("button", { name: /new note/i }));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FullWindow — rail stays live behind the note editor (Task 8)", () => {
  it("switches view when a rail tab is clicked while a note is open", async () => {
    mockNetworkDefaults();
    render(<FullWindow {...baseProps} />);

    openANote();
    expect(screen.getByRole("dialog", { name: /note editor/i })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^history$/i }));

    expect(screen.queryByRole("dialog", { name: /note editor/i })).toBeNull();
    // Exact, case-sensitive match: FullWindow's own topbar subtitle for this
    // view ("by project") also contains the substring "by project" lowercase,
    // so a loose regex here matches two elements.
    expect(await screen.findByText("By project")).toBeTruthy();
  });

  it("puts Settings last in the rail, below New Note", () => {
    mockNetworkDefaults();
    render(<FullWindow {...baseProps} />);

    const rail = screen.getByTestId("fw-rail");
    const labels = within(rail).getAllByRole("button").map((b) => b.getAttribute("aria-label"));

    expect(labels.slice(-2)).toEqual(["New Note", "Settings"]);
  });

  it("has no Hide control", () => {
    mockNetworkDefaults();
    render(<FullWindow {...baseProps} />);

    expect(screen.queryByRole("button", { name: /hide/i })).toBeNull();
  });
});

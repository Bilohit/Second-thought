// @vitest-environment happy-dom
/**
 * FR-11 regression: the Dashboard "Review" header links to the Inbox screen,
 * which only ever calls getInbox() (InboxPanel.tsx never fetches
 * /vault/conflicts). A single "inbox.length + conflicts.length" count over-
 * promised what that link delivers -- a conflict-only vault showed "1 needs
 * review" on the card and "Nothing needs review" on the destination. These
 * tests pin the fix: the chip next to the Review link now matches
 * inbox.length exactly, and conflicts get their own separate, honest count
 * (they stay visible and resolvable inline via the card's own Resolve
 * button, never hidden).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import DashboardView from "./DashboardView";
import * as api from "../../lib/api";
import type { CaptureState, CaptureStep } from "../../hooks/useCapture";
import type { InboxItem, VaultConflictEntry, Stats } from "../../lib/api";

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

function inboxItem(id: string): InboxItem {
  return { note_id: id, filename: `${id}.md`, path: `Inbox/${id}.md`, project: "_loose", size: 10, modified: 0 };
}
function conflictEntry(path: string): VaultConflictEntry {
  return { path, conflict_path: `${path}.conflict`, title: path };
}

function renderDashboard(inbox: InboxItem[], conflicts: VaultConflictEntry[]) {
  vi.mocked(api.getStats).mockResolvedValue(emptyStats);
  vi.mocked(api.getInbox).mockResolvedValue({ inbox, count: inbox.length });
  vi.mocked(api.listReminders).mockResolvedValue([]);
  vi.mocked(api.getConfig).mockResolvedValue({});
  vi.mocked(api.getVaultConflicts).mockResolvedValue(conflicts);
  vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });
  return render(
    <DashboardView
      visible
      captureState={idleCapture}
      stepDefs={stepDefs}
      onOpenFile={vi.fn()}
      onCaptureFile={vi.fn()}
      onCaptureNow={vi.fn()}
      onNavigate={vi.fn()}
      llmStatus="ready"
      voicePhase="idle"
      voiceElapsedMs={0}
      readWaveform={() => {}}
      readSpectrum={() => {}}
      sampleRate={44100}
      onVoiceToggle={vi.fn()}
      onVoiceCancel={vi.fn()}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DashboardView — project sentinel guard (FR-02)", () => {
  it("renders a loose capture's routed-to project as 'loose', and a loose Recent activity chip the same way", async () => {
    const doneCapture: CaptureState = {
      ...idleCapture,
      phase: "done",
      result: { path: "Inbox/note.md", project: "_loose" },
    };
    const stats: Stats = {
      total: 1,
      by_project: [],
      by_day: [],
      recent: [{ id: 1, project: "_loose", path: "Inbox/note.md", filename: "note.md", timestamp: "2026-08-02T00:00:00Z" }],
    };
    vi.mocked(api.getStats).mockResolvedValue(stats);
    vi.mocked(api.getInbox).mockResolvedValue({ inbox: [], count: 0 });
    vi.mocked(api.listReminders).mockResolvedValue([]);
    vi.mocked(api.getConfig).mockResolvedValue({});
    vi.mocked(api.getVaultConflicts).mockResolvedValue([]);
    vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });

    render(
      <DashboardView
        visible
        captureState={doneCapture}
        stepDefs={stepDefs}
        onOpenFile={vi.fn()}
        onCaptureFile={vi.fn()}
        onCaptureNow={vi.fn()}
        onNavigate={vi.fn()}
        llmStatus="ready"
        voicePhase="idle"
        voiceElapsedMs={0}
        readWaveform={() => {}}
        readSpectrum={() => {}}
        sampleRate={44100}
        onVoiceToggle={vi.fn()}
        onVoiceCancel={vi.fn()}
      />,
    );

    // Two sites at once: the "Routed to <b>" line (275, synchronous from
    // captureState) and the Recent activity chip (330, async from
    // getStats()) -- both must read "loose", never "_loose". Wait for the
    // async row before counting, so findAllByText doesn't resolve early on
    // just the synchronous match.
    await screen.findByText("note.md");
    const looseEls = screen.getAllByText("loose");
    expect(looseEls.length).toBe(2);
    expect(screen.queryByText("_loose")).toBeNull();
  });
});

describe("DashboardView — Review card count honesty (FR-11)", () => {
  it("0 inbox + 0 conflicts: no chips, empty-state text shown", async () => {
    renderDashboard([], []);
    await screen.findByText("No items need review");
    expect(screen.queryByText(/^\d+ needs?/)).toBeNull();
    expect(screen.queryByText(/conflict/)).toBeNull();
  });

  it("0 inbox + 1 conflict: only the conflict chip shows, no misleading review count, conflict stays visible inline", async () => {
    renderDashboard([], [conflictEntry("Notes/a.md")]);
    await screen.findByText("1 conflict");
    expect(screen.queryByText(/need.*review/)).toBeNull();
    expect(screen.queryByText("No items need review")).toBeNull();
    expect(screen.getByText("Edited on both devices")).toBeTruthy();
    expect(screen.getByText("Resolve")).toBeTruthy();
  });

  it("2 inbox + 1 conflict: both chips show, and the review count matches inbox.length exactly (what Review actually opens)", async () => {
    renderDashboard([inboxItem("a"), inboxItem("b")], [conflictEntry("Notes/c.md")]);
    await screen.findByText("1 conflict");
    expect(screen.getByText("2 need review")).toBeTruthy();
    expect(screen.getByText("Edited on both devices")).toBeTruthy();
  });
});

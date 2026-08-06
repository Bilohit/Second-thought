// @vitest-environment happy-dom
/**
 * P3-B: NotesView is the real NOTES-tab interior — list pane + the 280px
 * capture-pane radial. These pin: the radial's 4 satellites reach the real
 * capture paths (never a mock action), the blank-note satellite opens via
 * `onOpenFile(null)` (NoteEditor's own path===null flow), and the pane
 * shows the live StepIndicator (driven by the real `stepDefs`) the instant
 * a capture leaves "idle" — regardless of which satellite started it.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import NotesView from "./NotesView";
import * as api from "../../lib/api";
import type { CaptureState, CaptureStep } from "../../hooks/useCapture";

vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({ onDragDropEvent: vi.fn().mockResolvedValue(() => {}) }),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return { ...actual, searchCaptures: vi.fn(), getConfig: vi.fn(), checkHealth: vi.fn() };
});

const idleCapture: CaptureState = {
  phase: "idle",
  steps: { intercept: "pending", enrich: "pending", decide: "pending", write: "pending" },
  preview: null, result: null, errorMsg: null, thinking: null, backgroundJob: null,
  starting: false, reminderOffer: null, aiOffline: false,
};
const stepDefs: CaptureStep[] = [{ id: "intercept", label: "Intercepting" }];

function baseProps(overrides: Partial<React.ComponentProps<typeof NotesView>> = {}) {
  return {
    visible: true,
    captureState: idleCapture,
    stepDefs,
    onOpenFile: vi.fn(),
    onCaptureFile: vi.fn(),
    onCaptureNow: vi.fn(),
    voicePhase: "idle" as const,
    voiceElapsedMs: 0,
    readWaveform: () => {},
    readSpectrum: () => {},
    sampleRate: 44100,
    onVoiceToggle: vi.fn(),
    onVoiceCancel: vi.fn(),
    ...overrides,
  };
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("NotesView — capture radial reaches real capture paths", () => {
  it("blank-note satellite calls onOpenFile(null), never a mock stub", async () => {
    vi.mocked(api.searchCaptures).mockResolvedValue({ results: [], count: 0, query: "" });
    vi.mocked(api.getConfig).mockResolvedValue({});
    vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });
    const onOpenFile = vi.fn();
    render(<NotesView {...baseProps({ onOpenFile })} />);

    fireEvent.click(await screen.findByLabelText("Open capture radial"));
    fireEvent.click(screen.getByLabelText("Blank note"));

    expect(onOpenFile).toHaveBeenCalledWith(null);
  });

  it("clip satellite calls the real onCaptureNow (no fake preview step)", async () => {
    vi.mocked(api.searchCaptures).mockResolvedValue({ results: [], count: 0, query: "" });
    vi.mocked(api.getConfig).mockResolvedValue({});
    vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });
    const onCaptureNow = vi.fn();
    render(<NotesView {...baseProps({ onCaptureNow })} />);

    fireEvent.click(await screen.findByLabelText("Open capture radial"));
    fireEvent.click(screen.getByLabelText("Capture clipboard"));

    expect(onCaptureNow).toHaveBeenCalledTimes(1);
  });

  it("voice satellite is disabled (not clickable) when ffmpeg is unavailable", async () => {
    vi.mocked(api.searchCaptures).mockResolvedValue({ results: [], count: 0, query: "" });
    vi.mocked(api.getConfig).mockResolvedValue({});
    vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: false });
    const onVoiceToggle = vi.fn();
    render(<NotesView {...baseProps({ onVoiceToggle })} />);

    fireEvent.click(await screen.findByLabelText("Open capture radial"));
    fireEvent.click(await screen.findByLabelText("Voice capture"));

    expect(onVoiceToggle).not.toHaveBeenCalled();
  });
});

describe("NotesView — StepIndicator reads the real stepDefs whenever a capture is in flight", () => {
  it("shows the pipeline steps (not the radial) once phase leaves idle, regardless of trigger", async () => {
    vi.mocked(api.searchCaptures).mockResolvedValue({ results: [], count: 0, query: "" });
    vi.mocked(api.getConfig).mockResolvedValue({});
    vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });
    const capturing: CaptureState = { ...idleCapture, phase: "capturing", steps: { ...idleCapture.steps, intercept: "active" } };
    render(<NotesView {...baseProps({ captureState: capturing })} />);

    expect(await screen.findByText("Intercepting")).toBeTruthy();
    expect(screen.queryByLabelText("Open capture radial")).toBeNull();
  });
});

describe("NotesView — vault list", () => {
  it("renders fetched notes and opens the clicked one via onOpenFile(path)", async () => {
    vi.mocked(api.searchCaptures).mockResolvedValue({
      results: [{ project: "ideas", path: "Notes/a.md", filename: "a.md", timestamp: "2m ago" }],
      count: 1, query: "",
    });
    vi.mocked(api.getConfig).mockResolvedValue({});
    vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });
    const onOpenFile = vi.fn();
    render(<NotesView {...baseProps({ onOpenFile })} />);

    const row = await screen.findByText("a.md");
    fireEvent.click(row);
    expect(onOpenFile).toHaveBeenCalledWith("Notes/a.md");
  });

  // FR-02 regression guard, relocated here: NoteEditor's own "Metadata" drawer
  // (which used to carry this assertion) was dropped in P3-B along with its
  // menu row -- displayProject() now renders reachably only in this list
  // pane's rows.
  it("renders a loose note's project as 'loose', never the raw _loose sentinel", async () => {
    vi.mocked(api.searchCaptures).mockResolvedValue({
      results: [{ project: "_loose", path: "Inbox/a.md", filename: "a.md", timestamp: null }],
      count: 1, query: "",
    });
    vi.mocked(api.getConfig).mockResolvedValue({});
    vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });
    render(<NotesView {...baseProps()} />);

    expect(await screen.findByText("loose")).toBeTruthy();
    expect(screen.queryByText("_loose")).toBeNull();
  });
});

// @vitest-environment happy-dom
/**
 * LookPanel.test.tsx
 * -------------------
 * P3-D (2026-08-07): CHAT splits from Search into its own FullWindow tab —
 * FullWindow.tsx now locks LookPanel to `mode="chat"` and drops the
 * Search/Chat SegmentedToggle from its topbar entirely (search moved into
 * BrowseView.tsx, P3-C). LookPanel ITSELF is untouched by that split: it
 * stays a controlled dual-mode component, still driven by `mode`/
 * `onSelectMode`, because the pill's CompactLook.tsx keeps both modes and
 * is the caller "LookPanel.tsx IS SHARED WITH THE PILL" binds us to leaving
 * byte-identical.
 *
 * That shared internal `modeIndex = mode === "chat" ? 1 : 0` (search=0,
 * chat=1) is exactly the coupling the program plan calls out by name
 * (docs/superpowers/plans/2026-08-06-v2-redesign-port-program.md:337):
 * "`--swap-dir` is coupled to the Search=0/Chat=1 ordering — reordering the
 * tabs flips the slide direction SILENTLY, with no test failure." No test
 * anywhere else in the suite reads `--swap-dir`, so this file pins it for
 * the forward direction, which is the one sensitive to that coupling: flip
 * the mapping (e.g. chat=0/search=1) and the "forward" test below goes red.
 *
 * ★ FOUND, NOT FIXED (out of scope for P3-D — see task report): the THIRD
 * test below pins a separate, pre-existing defect this file's construction
 * surfaced, unrelated to the Search=0/Chat=1 ordering. Transitioning INTO
 * "search" always runs the `mode === "search"` reset branch of LookPanel's
 * own visibility effect (`setResults([])` et al.), which schedules a SECOND
 * render. By the time that second render runs, `prevModeIndexRef` has
 * already been advanced by the (separately declared, earlier-run) ref-sync
 * effect to match the new mode index, so `slideDirection` sees no delta and
 * recomputes 0 — collapsing what should be a `-1` backward slide into a
 * plain fade. Transitioning INTO "chat" has no such reset branch, so the
 * forward direction is unaffected (see the second test). This is REAL,
 * deterministic, already-shipping behavior in the pill's Search<->Chat
 * toggle (CompactLook.tsx) — not introduced by P3-D and not something this
 * task touches: LookPanel.tsx is pill-shared, frozen territory per the
 * task's hard constraint #2 ("if you cannot [stay byte-identical], STOP and
 * report" — fixing the race is a real behavior change to the pill and
 * belongs to a separate task, not a silent side-effect of splitting CHAT).
 */
import { useState } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import LookPanel from "./LookPanel";
import * as api from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    checkHealth: vi.fn(),
    searchCaptures: vi.fn(),
    syncVaultIndex: vi.fn(),
    openFilePath: vi.fn(),
  };
});

function mockNetworkDefaults() {
  vi.mocked(api.checkHealth).mockResolvedValue({ serverOk: true, llmStatus: "ready", ffmpeg: true });
  vi.mocked(api.searchCaptures).mockResolvedValue({ results: [], count: 0, query: "" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const lookChat = {
  messages: [],
  streaming: false,
  ask: vi.fn(),
  reset: vi.fn(),
  retry: vi.fn(),
  ignoreHistory: false,
  setIgnoreHistory: vi.fn(),
};

/** Controlled-mode harness — the exact shape both real callers (App.tsx's
 *  `lookMode`/`setLookMode` for the pill, FullWindow.tsx's now-locked
 *  literal for CHAT) drive LookPanel through: `mode` lifted to the caller,
 *  `onSelectMode` written back into it. Non-embedded with the toggle shown
 *  (`hideToggle` defaults to false) so the test can drive mode changes the
 *  same way a real user click on the pill's Search/Chat toggle does. */
function Harness() {
  const [mode, setMode] = useState<"search" | "chat">("search");
  return (
    <LookPanel
      mode={mode}
      onSelectMode={setMode}
      visible
      onClose={() => {}}
      lookChat={lookChat}
      lookChatPersist="preserve"
    />
  );
}

function swapDir(): string | null {
  return document.querySelector<HTMLElement>(".seg-swap-panel")?.style.getPropertyValue("--swap-dir") ?? null;
}

describe("LookPanel — Search(0)/Chat(1) swap direction (P3-D named trap)", () => {
  it("mounts on Search with no travel (fade only, first render)", () => {
    mockNetworkDefaults();
    render(<Harness />);
    expect(swapDir()).toBe("0");
  });

  it("slides forward (+1) Search -> Chat — the Search=0/Chat=1 coupling", () => {
    mockNetworkDefaults();
    render(<Harness />);
    fireEvent.click(screen.getByRole("tab", { name: "Chat" }));
    expect(swapDir()).toBe("1");
  });

  it("Chat -> Search collapses to 0, not -1 (pre-existing defect, found not fixed — see file header)", () => {
    mockNetworkDefaults();
    render(<Harness />);
    fireEvent.click(screen.getByRole("tab", { name: "Chat" }));
    fireEvent.click(screen.getByRole("tab", { name: "Search" }));
    expect(swapDir()).toBe("0");
  });
});

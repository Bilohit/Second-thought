// @vitest-environment happy-dom
/**
 * Task 3 (shell rework): Today merged into Inbox. Only the daily-note card
 * moved -- Inbox's own Reminders tab already superset-covers Today's
 * overdue+due-today reminders, and the scratchpad count came from the same
 * list_scratchpad() source Inbox's own header already prints. This file
 * guards the one thing that DID move: a slim daily-note strip, full-window
 * only (gated on `compactHeader`, never `embedded` -- see CLAUDE.md's hard
 * rule and DECISIONS.md §5 s135).
 */
import { it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import InboxPanel from "./InboxPanel";
import * as api from "../lib/api";
import type { TodayViewData } from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    getInbox: vi.fn(),
    getVaultFolders: vi.fn(),
    listReminders: vi.fn(),
    getToday: vi.fn(),
    createDailyNote: vi.fn(),
  };
});

const emptyToday: TodayViewData = {
  date: "2026-08-03",
  overdue: [],
  due_today: [],
  scratchpad_count: 0,
  daily_note: null,
};

beforeEach(() => {
  vi.mocked(api.getInbox).mockResolvedValue({ inbox: [], count: 0 });
  vi.mocked(api.getVaultFolders).mockResolvedValue({ folders: [], vault_root: "" });
  vi.mocked(api.listReminders).mockResolvedValue([]);
  vi.mocked(api.getToday).mockResolvedValue(emptyToday);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("renders the daily-note strip in full window", async () => {
  render(<InboxPanel visible embedded compactHeader={false} onClose={() => {}} />);
  expect(await screen.findByRole("button", { name: /start today's note/i })).toBeTruthy();
});

it("hides the daily-note strip when hosted in a compact panel", async () => {
  render(<InboxPanel visible embedded compactHeader onClose={() => {}} onHeaderActionsChange={() => {}} />);
  // Plan anchor correction: compactHeader suppresses InboxPanel's own header
  // row entirely (its "Inbox" text moves out via onHeaderActionsChange to a
  // parent this render tree doesn't include), so `/inbox/i` never appears in
  // this DOM regardless of the strip. The empty-inbox state text is the
  // reliable "panel mounted" signal instead.
  await screen.findByText(/nothing needs review/i);
  expect(screen.queryByRole("button", { name: /start today's note/i })).toBeNull();
});

// @vitest-environment happy-dom
/**
 * FR-08 regression: the daily note card used to print `data.daily_note.path`
 * verbatim -- the server's absolute OS path (e.g.
 * "C:\Users\<name>\...\Daily\2026-08-02.md") -- as permanent UI text right
 * under the note's own title. Doctrine bans presenting a path as the source
 * of truth. The fix keeps the line (it is still useful: the exact filename)
 * but renders only the leaf via TodayView's own `basename()` helper, never
 * the full OS directory tree.
 */
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import TodayView from "./TodayView";
import * as api from "../../lib/api";
import type { TodayViewData } from "../../lib/api";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    getToday: vi.fn(),
    deleteReminder: vi.fn(),
    createDailyNote: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("renders only the daily note's filename, never the absolute OS path (FR-08)", async () => {
  const winPath = "C:\\Users\\biloh\\vault\\Daily\\2026-08-02.md";
  const data: TodayViewData = {
    date: "2026-08-02",
    overdue: [],
    due_today: [],
    scratchpad_count: 0,
    daily_note: { id: "1", path: winPath, title: "Saturday, August 2" },
  };
  vi.mocked(api.getToday).mockResolvedValue(data);

  render(<TodayView visible onOpenNote={vi.fn()} />);

  await screen.findByText("2026-08-02.md");
  expect(screen.queryByText(winPath)).toBeNull();
  expect(screen.queryByText(/C:\\Users/)).toBeNull();
});

it("also strips a forward-slash path down to its filename", async () => {
  const data: TodayViewData = {
    date: "2026-08-02",
    overdue: [],
    due_today: [],
    scratchpad_count: 0,
    daily_note: { id: "1", path: "/home/user/vault/Daily/2026-08-02.md", title: "Saturday, August 2" },
  };
  vi.mocked(api.getToday).mockResolvedValue(data);

  render(<TodayView visible onOpenNote={vi.fn()} />);

  await screen.findByText("2026-08-02.md");
});

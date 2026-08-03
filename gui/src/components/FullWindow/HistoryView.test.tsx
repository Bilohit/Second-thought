// @vitest-environment happy-dom
/**
 * HistoryView.test.tsx — FR-07 regression.
 *
 * Confirms the restored full-window History destination actually renders
 * the by-project content from getStats(), and that it routes project names
 * through displayProject() rather than ever printing the "_loose" index
 * sentinel directly (the P1 seven sites leaked before).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import HistoryView from "./HistoryView";
import * as api from "../../lib/api";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return { ...actual, getStats: vi.fn() };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("HistoryView — FR-07: a real History destination, not an alias of Vault", () => {
  it("renders the by-project cards from getStats()", async () => {
    vi.mocked(api.getStats).mockResolvedValue({
      total: 3,
      by_day: [{ date: "2026-08-01", count: 2 }, { date: "2026-08-02", count: 1 }],
      by_project: [{ project: "kitchen-remodel", count: 2, pct: 66 }, { project: "_loose", count: 1, pct: 34 }],
      recent: [],
    });

    render(<HistoryView visible />);

    expect(await screen.findByText("By project")).toBeTruthy();
    expect(await screen.findByText("kitchen-remodel")).toBeTruthy();
    // The index's "_loose" sentinel must never reach the DOM as literal text.
    expect(screen.getByText("loose")).toBeTruthy();
    expect(screen.queryByText("_loose")).toBeNull();
  });

  it("shows the empty state instead of an empty list when there are no captures yet", async () => {
    vi.mocked(api.getStats).mockResolvedValue({ total: 0, by_day: [], by_project: [], recent: [] });
    render(<HistoryView visible />);
    expect(await screen.findByText("No captures yet.")).toBeTruthy();
  });

  it("renders nothing while not visible, and does not fetch", () => {
    const { container } = render(<HistoryView visible={false} />);
    expect(container.firstChild).toBeNull();
    expect(api.getStats).not.toHaveBeenCalled();
  });
});

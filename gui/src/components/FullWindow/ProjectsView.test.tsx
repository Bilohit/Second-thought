// @vitest-environment happy-dom
/**
 * ProjectsView.test.tsx — sub-project 3 Task 7.
 *
 * Container-level tests for behavior that lives in ProjectsView.tsx itself,
 * not in ProjectsRail or ProjectsPane individually: fetching + filtering
 * (ISS-019) + flattening the tag tree, auto-selecting the first tag on
 * switching to Tags (spec §5.2), and that each surface renders its OWN
 * correctly-sourced number rather than inventing/echoing one from the other
 * (spec §5.6, trap 2) — which only actually shows up once both components
 * are wired to the same fetched data, not from either component in
 * isolation. NOT tested (and not guaranteed by the gui/ code — see
 * ProjectsView.tsx's tags-state comment): that the rail's file-scan count
 * and the pane's DB-row count can never drift. A note whose index pass
 * hasn't caught up with a just-saved tag can make the rail read one higher
 * than the pane briefly; the pane still shows exactly what it fetched.
 *
 * ponytail: happy-dom ships no layout engine — see ProjectsRail.test.tsx's
 * same note. These tests assert DOM/ARIA structure and text content only.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import ProjectsView from "./ProjectsView";
import * as api from "../../lib/api";
import type { SearchResult } from "../../lib/api";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    listProjects: vi.fn(),
    getStats: vi.fn(),
    getTagTree: vi.fn(),
    notesForProject: vi.fn(),
    notesForTag: vi.fn(),
  };
});

function row(path: string): SearchResult {
  return { id: 1, timestamp: null, project: "research", path, filename: path, modified: null };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(api.listProjects).mockResolvedValue({ projects: [], vault_root: "" });
  vi.mocked(api.getStats).mockResolvedValue({ total: 0, by_project: [], by_day: [], recent: [] });
  vi.mocked(api.getTagTree).mockResolvedValue({ tags: [] });
  vi.mocked(api.notesForProject).mockResolvedValue([]);
  vi.mocked(api.notesForTag).mockResolvedValue([]);
});

describe("ProjectsView — auto-select the first tag on switching to Tags (spec §5.2)", () => {
  it("clicking the Tags tab selects the first tag and the pane lists its notes, not a dead panel", async () => {
    vi.mocked(api.getTagTree).mockResolvedValue({
      tags: [
        { tag: "reading", count: 2, recent: [], children: [] },
        { tag: "invoice", count: 1, recent: [], children: [] },
      ],
    });
    vi.mocked(api.notesForTag).mockImplementation(async (tag) =>
      tag === "reading" ? [row("a.md"), row("b.md")] : [],
    );
    render(<ProjectsView visible />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tags" }));

    const option = await screen.findByRole("option", { name: /reading/ });
    expect(option.getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("2 notes across your vault")).toBeTruthy();
  });

  it("never overwrites a live tag selection", async () => {
    vi.mocked(api.getTagTree).mockResolvedValue({
      tags: [
        { tag: "reading", count: 2, recent: [], children: [] },
        { tag: "invoice", count: 1, recent: [], children: [] },
      ],
    });
    render(<ProjectsView visible />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tags" }));
    await screen.findByRole("option", { name: /reading/ });

    fireEvent.click(screen.getByRole("option", { name: /invoice/ }));
    expect((await screen.findByRole("option", { name: /invoice/ })).getAttribute("aria-selected")).toBe("true");

    // Flip away and back: the live selection survives, it is not forced
    // back to "reading" a second time.
    fireEvent.click(screen.getByRole("tab", { name: "Projects" }));
    fireEvent.click(screen.getByRole("tab", { name: "Tags" }));
    expect((await screen.findByRole("option", { name: /invoice/ })).getAttribute("aria-selected")).toBe("true");
  });
});

describe("ProjectsView — each surface renders its own correctly-sourced count (spec §5.6, trap 2)", () => {
  // Not a claim that the two counts can never drift (they can — see
  // ProjectsView.tsx's tags-state comment: /tags is a file scan, /search
  // returns only indexed DB rows filtered by that scan's membership set, so
  // an unindexed note can make the rail read one higher). This pins that
  // WHEN the backend's index is caught up (as it is here — 11 tagged files,
  // 11 matching DB rows), neither surface invents a number: the rail shows
  // GET /tags' own count, the pane shows rows.length off GET /search, and
  // — because both counts are backed by data that agrees in this scenario —
  // they land on the same number.
  it("the rail's tag count (GET /tags) and the pane's head count (rows.length from GET /search?q=tag:<x>) match when the backend's file scan and index agree", async () => {
    vi.mocked(api.getTagTree).mockResolvedValue({
      tags: [{ tag: "reading", count: 11, recent: [], children: [] }],
    });
    vi.mocked(api.notesForTag).mockResolvedValue(Array.from({ length: 11 }, (_, i) => row(`n${i}.md`)));
    render(<ProjectsView visible />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tags" }));

    const option = await screen.findByRole("option", { name: /reading/ });
    expect(option.textContent).toContain("11");
    expect(await screen.findByText("11 notes across your vault")).toBeTruthy();
  });
});

describe("ProjectsView — machine tags never reach the rail (ISS-019, trap 1)", () => {
  it("filters the sys/ namespace out of the tag list end to end, through the real filterMachineTags/flattenTagTree pipeline", async () => {
    vi.mocked(api.getTagTree).mockResolvedValue({
      tags: [
        {
          tag: "sys/", count: 2, recent: [],
          children: [{ tag: "sys/llm-failed", count: 2, recent: [], children: [] }],
        },
        { tag: "reading", count: 3, recent: [], children: [] },
      ],
    });
    render(<ProjectsView visible />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tags" }));

    await screen.findByRole("option", { name: /reading/ });
    expect(screen.queryByText(/sys/)).toBeNull();
    expect(screen.getAllByRole("option").length).toBe(1);
  });
});

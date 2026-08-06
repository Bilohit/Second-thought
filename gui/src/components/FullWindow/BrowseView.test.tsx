// @vitest-environment happy-dom
/**
 * BrowseView.test.tsx — P3-C3: project management in the BROWSE drill-in
 * (3-dot overflow menu: Rename / Set description / Delete project) plus the
 * FR-36 regression guard (a rename/delete/folder-import re-runs the SAME
 * `refetchProjects()` the `visible` effect uses — no navigate-away-and-back
 * round trip to see an updated tile).
 *
 * ponytail: happy-dom ships no layout engine (see ProjectsPane.test.tsx's
 * identical note) — these tests assert DOM/ARIA structure, mock call
 * sequencing, and text content only.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import BrowseView from "./BrowseView";
import * as api from "../../lib/api";
import type { ProjectEntry, SearchResult, Stats, TagNode } from "../../lib/api";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    listProjects: vi.fn(),
    getStats: vi.fn(),
    getTagTree: vi.fn(),
    searchCaptures: vi.fn(),
    notesForProject: vi.fn(),
    notesForTag: vi.fn(),
    renameProject: vi.fn(),
    updateProjectDescription: vi.fn(),
    deleteProject: vi.fn(),
    getTidyPreview: vi.fn(),
    applyTidy: vi.fn(),
    getFolderImportPreview: vi.fn(),
    applyFolderImport: vi.fn(),
  };
});

function project(overrides: Partial<ProjectEntry> = {}): ProjectEntry {
  return {
    name: "trip-japan", description: "Planning notes.", renamed_from: null,
    created: "", modified: "", file_count: 2,
    ...overrides,
  };
}

function stats(byProject: { project: string; count: number }[]): Stats {
  return {
    total: byProject.reduce((n, r) => n + r.count, 0),
    by_project: byProject.map((r) => ({ ...r, pct: 0 })),
    by_day: [],
    recent: [],
  };
}

function row(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    id: 1, timestamp: "2026-07-01T00:00:00Z", project: "trip-japan", path: "trip-japan/plan.md",
    filename: "plan.md", modified: 1_700_000_000,
    ...overrides,
  };
}

const emptyTags: { tags: TagNode[] } = { tags: [] };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(api.listProjects).mockResolvedValue({ projects: [project()], vault_root: "" });
  vi.mocked(api.getStats).mockResolvedValue(stats([{ project: "trip-japan", count: 2 }]));
  vi.mocked(api.getTagTree).mockResolvedValue(emptyTags);
  vi.mocked(api.searchCaptures).mockResolvedValue({ results: [], count: 0, query: "" });
  vi.mocked(api.notesForProject).mockResolvedValue([row(), row({ path: "trip-japan/b.md", filename: "b.md" })]);
  vi.mocked(api.notesForTag).mockResolvedValue([]);
  vi.mocked(api.renameProject).mockResolvedValue(undefined);
  vi.mocked(api.updateProjectDescription).mockResolvedValue(undefined);
  vi.mocked(api.deleteProject).mockResolvedValue(undefined);
  vi.mocked(api.getTidyPreview).mockResolvedValue({ moves: [], count: 0 });
  vi.mocked(api.applyTidy).mockResolvedValue({ moved: 0, skipped: 0, removed_dirs: 0 });
  vi.mocked(api.getFolderImportPreview).mockResolvedValue({ folders: [], count: 0 });
  vi.mocked(api.applyFolderImport).mockResolvedValue({ tagged: 0, registered: [], skipped: [] });
});

function renderBrowse() {
  return render(<BrowseView visible mode="list" />);
}

/** Navigates from the home grid into the "trip-japan" project drill-in and
 *  waits for its notes to load — every menu/FR-36 test below starts here. */
async function openDrillIn() {
  renderBrowse();
  const tile = await screen.findByText("trip-japan");
  fireEvent.click(tile);
  await screen.findByRole("heading", { name: "trip-japan" });
  await screen.findByText("plan.md");
}

describe("BrowseView — P3-C3 kebab menu (mirrors NoteEditor.tsx's 'More' menu exactly)", () => {
  it("renders exactly Rename / Set description / Delete project, in that order, Delete last and danger-styled", async () => {
    await openDrillIn();
    fireEvent.click(screen.getByLabelText("Project actions"));
    const items = screen.getAllByRole("menuitem");
    expect(items.map((el) => el.textContent)).toEqual(["Rename", "Set description", "Delete project"]);
    expect(items[2].style.color).toBe("var(--red)");
    expect(items[0].style.color).not.toBe("var(--red)");
    expect(items[1].style.color).not.toBe("var(--red)");
  });

  it("the menu is keyboard-reachable: items are tab-reachable only while open", async () => {
    await openDrillIn();
    // `hidden: true` includes the menu's aria-hidden-while-closed items in
    // the query -- the accessibility-tree exclusion IS the closed state
    // (correctly invisible to a screen reader), so this asserts the DOM's
    // own tabindex flip, not a query artifact of that exclusion.
    const items = () => screen.getAllByRole("menuitem", { hidden: true });
    expect(items()[0].getAttribute("tabindex")).toBe("-1");
    fireEvent.click(screen.getByLabelText("Project actions"));
    expect(items()[0].getAttribute("tabindex")).toBe("0");
    expect(items()[2].getAttribute("tabindex")).toBe("0");
  });

  it("no kebab renders in the tag drill-in — a tag head is not a project head", async () => {
    vi.mocked(api.getTagTree).mockResolvedValue({ tags: [{ tag: "reading", count: 1, recent: [], children: [] }] });
    vi.mocked(api.notesForTag).mockResolvedValue([row({ path: "a.md", filename: "a.md" })]);
    renderBrowse();
    const tagRow = await screen.findByText("#reading");
    fireEvent.click(tagRow);
    await screen.findByRole("heading", { name: "#reading" });
    expect(screen.queryByLabelText("Project actions")).toBeNull();
  });
});

describe("BrowseView — delete requires confirmation", () => {
  it("clicking 'Delete project' in the menu does NOT call deleteProject — it opens the confirm strip", async () => {
    await openDrillIn();
    fireEvent.click(screen.getByLabelText("Project actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete project" }));
    expect(api.deleteProject).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete project only" })).toBeTruthy();
    expect(
      screen.getByText((_, el) => el?.textContent ===
        "Delete trip-japan? Its 2 notes become loose. None is deleted, trashed or edited, and none moves "
        + "on disk yet — you'll see a separate confirmation before anything is re-filed."),
    ).toBeTruthy();
  });

  it("only the explicit 'Delete project only' click calls deleteProject", async () => {
    await openDrillIn();
    fireEvent.click(screen.getByLabelText("Project actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete project" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete project only" }));
    await vi.waitFor(() => expect(api.deleteProject).toHaveBeenCalledWith("trip-japan"));
  });

  it("Cancel dismisses the strip without calling deleteProject", async () => {
    await openDrillIn();
    fireEvent.click(screen.getByLabelText("Project actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete project" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Delete project only" })).toBeNull();
    expect(api.deleteProject).not.toHaveBeenCalled();
  });
});

describe("BrowseView — Set description (ProjectsPane.tsx's 'saves as you type' textarea, lifted)", () => {
  it("Set description reveals the textarea prefilled with the current description", async () => {
    await openDrillIn();
    fireEvent.click(screen.getByLabelText("Project actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Set description" }));
    const textarea = screen.getByLabelText("Project description") as HTMLTextAreaElement;
    expect(textarea.value).toBe("Planning notes.");
  });

  it("saves debounced as you type, not on every keystroke", async () => {
    await openDrillIn();
    fireEvent.click(screen.getByLabelText("Project actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Set description" }));
    const textarea = screen.getByLabelText("Project description");
    vi.useFakeTimers();
    fireEvent.change(textarea, { target: { value: "New text." } });
    expect(api.updateProjectDescription).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(600);
    expect(api.updateProjectDescription).toHaveBeenCalledWith("trip-japan", "New text.");
    vi.useRealTimers();
  });
});

describe("BrowseView — FR-36 regression guard: rename/delete/folder-import re-run the SAME refetchProjects()", () => {
  it("a successful rename re-fetches listProjects/getStats/getTagTree", async () => {
    await openDrillIn();
    const before = vi.mocked(api.listProjects).mock.calls.length;
    fireEvent.click(screen.getByLabelText("Project actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByLabelText("New project name");
    fireEvent.change(input, { target: { value: "trip-japan-2026" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await vi.waitFor(() => expect(api.renameProject).toHaveBeenCalledWith("trip-japan", "trip-japan-2026"));
    await vi.waitFor(() => expect(vi.mocked(api.listProjects).mock.calls.length).toBeGreaterThan(before));
    await vi.waitFor(() => expect(api.getStats).toHaveBeenCalledTimes(vi.mocked(api.listProjects).mock.calls.length));
  });

  it("a successful delete re-fetches listProjects/getStats/getTagTree", async () => {
    await openDrillIn();
    const before = vi.mocked(api.listProjects).mock.calls.length;
    fireEvent.click(screen.getByLabelText("Project actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete project" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete project only" }));
    await vi.waitFor(() => expect(api.deleteProject).toHaveBeenCalledWith("trip-japan"));
    await vi.waitFor(() => expect(vi.mocked(api.listProjects).mock.calls.length).toBeGreaterThan(before));
  });

  it("useFolderImport's onApplied also re-fetches — same function, third caller", async () => {
    vi.mocked(api.getTidyPreview).mockResolvedValue({
      moves: [{ from: "trip-japan/plan.md", to: "_loose/plan.md" }],
      count: 1,
    });
    vi.mocked(api.getFolderImportPreview).mockResolvedValue({
      folders: [{ folder: "recipes", suggested: "recipes", valid: true, existing: false, count: 3, phone_count: 0 }],
      count: 3,
    });
    vi.mocked(api.applyFolderImport).mockResolvedValue({ tagged: 3, registered: ["recipes"], skipped: [] });

    await openDrillIn();
    fireEvent.click(screen.getByLabelText("Project actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete project" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete project only" }));
    const offerBtn = await screen.findByRole("button", { name: /Keep my folders/ });

    const before = vi.mocked(api.listProjects).mock.calls.length;
    fireEvent.click(offerBtn);
    const applyBtn = await screen.findByRole("button", { name: /Add tags to 3 notes/ });
    fireEvent.click(applyBtn);
    await vi.waitFor(() => expect(api.applyFolderImport).toHaveBeenCalled());
    await vi.waitFor(() => expect(vi.mocked(api.listProjects).mock.calls.length).toBeGreaterThan(before));
  });
});

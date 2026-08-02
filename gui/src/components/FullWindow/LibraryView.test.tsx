// @vitest-environment happy-dom
/**
 * LibraryView.test.tsx — FR-06 regression.
 *
 * The Projects|Trash toggle used to unmount <ProjectsView> entirely
 * (`section === "vault" && <ProjectsView/>`), which reset its local
 * mode/selectedId/selectedTag state on every trip through Trash: a user who
 * had built up a Tags-mode selection lost it the moment they glanced at
 * Trash and came back. Fixed by always mounting <ProjectsView> and
 * threading `visible={section === "vault"}` instead of the conditional
 * mount — ProjectsView already returns null and pauses its fetch effects
 * while `visible` is false, so this is "keep mounted, hide", not "keep
 * mounted and let it keep working in the background".
 *
 * ponytail: happy-dom ships no layout engine (see ProjectsRail.test.tsx's
 * same note) — these tests assert DOM/ARIA structure and text content only.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import LibraryView from "./LibraryView";
import * as api from "../../lib/api";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    listProjects: vi.fn(),
    getStats: vi.fn(),
    getTagTree: vi.fn(),
    notesForProject: vi.fn(),
    notesForTag: vi.fn(),
    getTrash: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(api.listProjects).mockResolvedValue({ projects: [], vault_root: "" });
  vi.mocked(api.getStats).mockResolvedValue({ total: 0, by_project: [], by_day: [], recent: [] });
  vi.mocked(api.getTagTree).mockResolvedValue({
    tags: [
      { tag: "reading", count: 2, recent: [], children: [] },
      { tag: "invoice", count: 1, recent: [], children: [] },
    ],
  });
  vi.mocked(api.notesForProject).mockResolvedValue([]);
  vi.mocked(api.notesForTag).mockResolvedValue([]);
  vi.mocked(api.getTrash).mockResolvedValue([]);
});

describe("LibraryView — FR-06: Projects|Trash toggle preserves the Projects screen's state", () => {
  it("Tags mode with a chosen tag survives a round trip through Trash", async () => {
    const { rerender } = render(<LibraryView visible section="vault" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Tags" }));
    await screen.findByRole("option", { name: /reading/ });

    fireEvent.click(screen.getByRole("option", { name: /invoice/ }));
    expect(screen.getByRole("option", { name: /invoice/ }).getAttribute("aria-selected")).toBe("true");

    rerender(<LibraryView visible section="trash" />);
    // ProjectsView is hidden (returns null) while in Trash -- its rail/pane
    // are not in the DOM, but its component instance (and state) is not
    // unmounted.
    expect(screen.queryByRole("tab", { name: "Tags" })).toBeNull();

    rerender(<LibraryView visible section="vault" />);
    const tagsTab = await screen.findByRole("tab", { name: "Tags" });
    expect(tagsTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("option", { name: /invoice/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("a genuine first visit still lands on the board's own defaults (Projects mode, first project; Tags mode, first tag)", async () => {
    vi.mocked(api.listProjects).mockResolvedValue({
      projects: [{ name: "research", description: "", renamed_from: null, created: "", modified: "", file_count: 0 }],
      vault_root: "",
    });
    render(<LibraryView visible section="vault" />);
    // Projects mode is the default toggle position; the sole project
    // auto-selects (rows[0] ?? loose) -- renders both as the rail tile and
    // the pane's head name.
    await vi.waitFor(() => expect(screen.getAllByText("research").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("tab", { name: "Tags" }));
    const option = await screen.findByRole("option", { name: /reading/ });
    expect(option.getAttribute("aria-selected")).toBe("true");
  });
});

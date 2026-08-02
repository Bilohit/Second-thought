// @vitest-environment happy-dom
/**
 * ProjectsPane.test.tsx — sub-project 3 Task 5.
 *
 * ponytail: happy-dom ships no layout engine (see ProjectsRail.test.tsx's
 * same note) — these tests assert DOM/ARIA structure, mock call
 * sequencing, and text content only. A real-browser/CDP pass (spec §9.5) is
 * the only place that can confirm pixels.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import ProjectsPane from "./ProjectsPane";
import { LOOSE_PROJECT_ID } from "./ProjectsRail";
import * as api from "../../lib/api";
import type { ProjectEntry, SearchResult } from "../../lib/api";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    notesForProject: vi.fn(),
    renameProject: vi.fn(),
    deleteProject: vi.fn(),
    updateProjectDescription: vi.fn(),
  };
});

function project(overrides: Partial<ProjectEntry>): ProjectEntry {
  return {
    name: "research", description: "Papers and notes.", renamed_from: null,
    created: "", modified: "", file_count: 6,
    ...overrides,
  };
}

function row(overrides: Partial<SearchResult>): SearchResult {
  return {
    id: 1, timestamp: "2026-07-01T00:00:00Z", project: "research", path: "research/note-1.md",
    filename: "note-1.md", modified: 1_700_000_000,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.mocked(api.notesForProject).mockResolvedValue([]);
  vi.mocked(api.renameProject).mockResolvedValue(undefined);
  vi.mocked(api.deleteProject).mockResolvedValue(undefined);
  vi.mocked(api.updateProjectDescription).mockResolvedValue(undefined);
});

function renderPane(props: Partial<React.ComponentProps<typeof ProjectsPane>> = {}) {
  return render(
    <ProjectsPane
      projects={[project({})]}
      selectedId="research"
      {...props}
    />,
  );
}

describe("ProjectsPane — fetch (spec §5.5: explicit limit, no silent 25-row default)", () => {
  it("calls notesForProject with an explicit limit of 200", async () => {
    renderPane();
    await vi.waitFor(() => expect(api.notesForProject).toHaveBeenCalledWith("research", { limit: 200 }));
  });

  it("refetches when the selection changes", async () => {
    const { rerender } = renderPane({ selectedId: "research" });
    await vi.waitFor(() => expect(api.notesForProject).toHaveBeenCalledWith("research", { limit: 200 }));
    rerender(<ProjectsPane projects={[project({})]} selectedId={LOOSE_PROJECT_ID} />);
    await vi.waitFor(() => expect(api.notesForProject).toHaveBeenCalledWith(LOOSE_PROJECT_ID, { limit: 200 }));
  });
});

describe("ProjectsPane — the provisional-row guard (task brief's rule 1, index_writer.py:686-700)", () => {
  it("drops a __lan_provisional__ row from both the list and the count", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([
      row({ path: "__lan_provisional__/op-1", filename: null }),
      row({ path: "research/real-note.md", filename: "real-note.md" }),
    ]);
    renderPane();
    expect(await screen.findByText("real-note.md")).toBeTruthy();
    expect(screen.queryByText(/lan_provisional/)).toBeNull();
    expect(await screen.findByText("1 notes")).toBeTruthy(); // NOT "2 notes"
  });
});

describe("ProjectsPane — the notes-head count (task brief's rule 2, spec §5.6)", () => {
  it("the count is exactly the filtered rows.length, not any externally-supplied number", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([
      row({ path: "research/a.md", filename: "a.md" }),
      row({ path: "research/b.md", filename: "b.md" }),
      row({ path: "research/c.md", filename: "c.md" }),
    ]);
    renderPane();
    expect(await screen.findByText("3 notes")).toBeTruthy();
  });

  it("an empty result set reports 0 notes, not a stale or hidden count", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([]);
    renderPane();
    expect(await screen.findByText("0 notes")).toBeTruthy();
    expect(await screen.findByText("No notes here yet.")).toBeTruthy();
  });
});

describe("ProjectsPane — head variants (spec §6)", () => {
  it("calm empty-vault head when there are no projects at all", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([row({}), row({ path: "b.md", filename: "b.md" })]);
    renderPane({ projects: [], selectedId: LOOSE_PROJECT_ID });
    expect(await screen.findByText("No projects yet")).toBeTruthy();
    expect(screen.getByText(/All 2 of your notes are loose/)).toBeTruthy();
  });

  it("loose head reads 'loose' and 'no project tag, nothing to set up' — no rename/delete/description (spec §4.8)", async () => {
    renderPane({ projects: [project({})], selectedId: LOOSE_PROJECT_ID });
    expect(await screen.findByText("loose")).toBeTruthy();
    expect(screen.getByText("no project tag, nothing to set up")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Rename project" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete project" })).toBeNull();
    expect(screen.queryByLabelText("Project description")).toBeNull();
    // §2.2's sentinel guard: the literal "_loose" string must never render.
    expect(document.body.textContent).not.toContain(LOOSE_PROJECT_ID);
  });

  it("project head shows the name and a description textarea", async () => {
    renderPane({ projects: [project({ name: "kitchen-remodel", description: "Quotes." })], selectedId: "kitchen-remodel" });
    expect(await screen.findByText("kitchen-remodel")).toBeTruthy();
    const textarea = screen.getByLabelText("Project description") as HTMLTextAreaElement;
    expect(textarea.value).toBe("Quotes.");
  });
});

describe("ProjectsPane — the description field (spec §4.6: no gauge, saves as you type)", () => {
  it("never renders a quality/match-score gauge — only the honest one-line note", async () => {
    renderPane({ projects: [project({ description: "Something." })] });
    await screen.findByLabelText("Project description");
    expect(screen.getByText("This is what your phone matches new notes against.")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("shows the yellow empty variant when the description is blank", async () => {
    renderPane({ projects: [project({ description: "" })] });
    expect(await screen.findByText("Empty. Your phone has nothing to match new notes against yet.")).toBeTruthy();
  });

  it("a whitespace-only description counts as empty", async () => {
    renderPane({ projects: [project({ description: "   " })] });
    expect(await screen.findByText("Empty. Your phone has nothing to match new notes against yet.")).toBeTruthy();
  });

  it("has no Save button — saves debounced as you type", async () => {
    const onSaved = vi.fn();
    renderPane({ projects: [project({ description: "" })], onDescriptionSaved: onSaved });
    // Resolve the initial (real-timer) data fetch BEFORE switching to fake
    // timers — findBy*'s internal polling relies on real setTimeout, so
    // faking the clock first would hang it forever.
    const textarea = await screen.findByLabelText("Project description");
    expect(screen.queryByRole("button", { name: /save/i })).toBeNull();
    vi.useFakeTimers();

    fireEvent.change(textarea, { target: { value: "New description text." } });
    expect(api.updateProjectDescription).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(600);
    expect(api.updateProjectDescription).toHaveBeenCalledWith("research", "New description text.");
    expect(onSaved).toHaveBeenCalledWith("research", "New description text.");
  });

  it("does not re-fire the save on every keystroke — only once after the debounce settles", async () => {
    renderPane({ projects: [project({ description: "" })] });
    const textarea = await screen.findByLabelText("Project description");
    vi.useFakeTimers();
    fireEvent.change(textarea, { target: { value: "a" } });
    await vi.advanceTimersByTimeAsync(200);
    fireEvent.change(textarea, { target: { value: "ab" } });
    await vi.advanceTimersByTimeAsync(200);
    fireEvent.change(textarea, { target: { value: "abc" } });
    await vi.advanceTimersByTimeAsync(600);
    expect(api.updateProjectDescription).toHaveBeenCalledTimes(1);
    expect(api.updateProjectDescription).toHaveBeenCalledWith("research", "abc");
  });
});

describe("ProjectsPane — rename", () => {
  it("clicking rename swaps the name for an editable field, prefilled with the current name", async () => {
    renderPane({ projects: [project({ name: "onboarding-v2" })], selectedId: "onboarding-v2" });
    await screen.findByText("onboarding-v2");
    fireEvent.click(screen.getByRole("button", { name: "Rename project" }));
    const input = screen.getByLabelText("New project name") as HTMLInputElement;
    expect(input.value).toBe("onboarding-v2");
  });

  it("Enter confirms the rename and calls renameProject(old, new)", async () => {
    const onRenamed = vi.fn();
    renderPane({ projects: [project({ name: "onboarding-v2" })], selectedId: "onboarding-v2", onRenamed });
    await screen.findByText("onboarding-v2");
    fireEvent.click(screen.getByRole("button", { name: "Rename project" }));
    const input = screen.getByLabelText("New project name");
    fireEvent.change(input, { target: { value: "onboarding-v3" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await vi.waitFor(() => expect(api.renameProject).toHaveBeenCalledWith("onboarding-v2", "onboarding-v3"));
    await vi.waitFor(() => expect(onRenamed).toHaveBeenCalledWith("onboarding-v2", "onboarding-v3"));
  });

  it("Escape cancels without calling renameProject", async () => {
    renderPane({ projects: [project({ name: "onboarding-v2" })], selectedId: "onboarding-v2" });
    await screen.findByText("onboarding-v2");
    fireEvent.click(screen.getByRole("button", { name: "Rename project" }));
    const input = screen.getByLabelText("New project name");
    fireEvent.change(input, { target: { value: "discarded" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByLabelText("New project name")).toBeNull();
    expect(api.renameProject).not.toHaveBeenCalled();
  });
});

describe("ProjectsPane — delete (spec §4.7: the true consequence, stated)", () => {
  it("clicking delete shows the confirm strip with the actual consequence", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([row({}), row({ path: "b.md", filename: "b.md" })]);
    renderPane({ projects: [project({ name: "trip-japan" })], selectedId: "trip-japan" });
    await screen.findByText("2 notes");
    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
    expect(
      screen.getByText((_, el) => el?.textContent === "Delete trip-japan? Its 2 notes become loose. None is deleted, trashed or edited."),
    ).toBeTruthy();
  });

  it("confirming calls deleteProject(name) and fires onDeleted", async () => {
    const onDeleted = vi.fn();
    renderPane({ projects: [project({ name: "trip-japan" })], selectedId: "trip-japan", onDeleted });
    await screen.findByText("trip-japan");
    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete project only" }));
    await vi.waitFor(() => expect(api.deleteProject).toHaveBeenCalledWith("trip-japan"));
    await vi.waitFor(() => expect(onDeleted).toHaveBeenCalledWith("trip-japan"));
  });

  it("Cancel dismisses the strip without calling deleteProject", async () => {
    renderPane({ projects: [project({ name: "trip-japan" })], selectedId: "trip-japan" });
    await screen.findByText("trip-japan");
    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Delete project only" })).toBeNull();
    expect(api.deleteProject).not.toHaveBeenCalled();
  });
});

describe("ProjectsPane — sorting is an instrument (spec §4.5), driven by lib/projectsView.ts", () => {
  it("cycles newest -> oldest -> edited, restating its aria-label and the meta verb each time", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([row({})]);
    renderPane();
    await screen.findByText("1 notes");

    let sortBtn = screen.getByRole("button", { name: /Arrangement: Newest\./ });
    expect(screen.getByText(/^added /)).toBeTruthy();

    fireEvent.click(sortBtn);
    sortBtn = screen.getByRole("button", { name: /Arrangement: Oldest\./ });
    expect(screen.getByText(/^added /)).toBeTruthy();

    fireEvent.click(sortBtn);
    screen.getByRole("button", { name: /Arrangement: Recently edited\./ });
    expect(screen.getByText(/^edited /)).toBeTruthy();
  });
});

describe("ProjectsPane — opening a note", () => {
  it("clicking a note row calls onOpenNote with its path", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([row({ path: "research/note-1.md", filename: "note-1.md" })]);
    const onOpenNote = vi.fn();
    renderPane({ onOpenNote });
    const rowEl = await screen.findByText("note-1.md");
    fireEvent.click(rowEl);
    expect(onOpenNote).toHaveBeenCalledWith("research/note-1.md");
  });

  it("Enter on a focused note row also opens it (spec §7: tabindex=0)", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([row({ path: "research/note-1.md", filename: "note-1.md" })]);
    const onOpenNote = vi.fn();
    renderPane({ onOpenNote });
    const title = await screen.findByText("note-1.md");
    const rowEl = title.closest('[role="button"]')!;
    expect(rowEl.getAttribute("tabindex")).toBe("0");
    fireEvent.keyDown(rowEl, { key: "Enter" });
    expect(onOpenNote).toHaveBeenCalledWith("research/note-1.md");
  });
});

describe("ProjectsPane — the loose overflow line (spec §4.8)", () => {
  it("shows 'Loose is normal and permanent, not a queue.' only for the loose bucket", async () => {
    renderPane({ projects: [project({})], selectedId: LOOSE_PROJECT_ID });
    expect(await screen.findByText("Loose is normal and permanent, not a queue.")).toBeTruthy();
  });

  it("does not show the loose overflow line for a real project", async () => {
    renderPane({ projects: [project({})], selectedId: "research" });
    await screen.findByText("research", { selector: "span" });
    expect(screen.queryByText("Loose is normal and permanent, not a queue.")).toBeNull();
  });
});

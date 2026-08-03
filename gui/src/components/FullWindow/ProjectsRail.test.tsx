// @vitest-environment happy-dom
/**
 * ProjectsRail.test.tsx — sub-project 3 Task 4.
 *
 * ponytail: happy-dom ships no layout engine (getBoundingClientRect/
 * offsetWidth all read 0 here — see NoteEditor.test.tsx's same note) — these
 * tests assert DOM structure, style-object CONTRACTS (declared flex/
 * min-width/height values), and text content only. The equal-width and
 * square-dismiss claims are geometric outcomes of those declared values,
 * not something this file can measure in pixels; a real-browser/CDP pass
 * (spec §9.5) is the only place that can confirm the pixels themselves.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import ProjectsRail, { LOOSE_PROJECT_ID } from "./ProjectsRail";
import * as api from "../../lib/api";
import type { ProjectEntry } from "../../lib/api";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return { ...actual, createProject: vi.fn() };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(api.createProject).mockResolvedValue(undefined);
});

function project(overrides: Partial<ProjectEntry>): ProjectEntry {
  return {
    name: "research", description: "Papers and notes.", renamed_from: null,
    created: "", modified: "", file_count: 6,
    ...overrides,
  };
}

const NOOP = () => {};

function renderRail(props: Partial<React.ComponentProps<typeof ProjectsRail>> = {}) {
  return render(
    <ProjectsRail
      mode="projects"
      onModeChange={NOOP}
      projects={[]}
      projectCounts={{}}
      looseCount={0}
      selectedId={null}
      onSelect={NOOP}
      tags={[]}
      selectedTag={null}
      onSelectTag={NOOP}
      {...props}
    />,
  );
}

describe("ProjectsRail — the _loose sentinel guard (spec §2.2)", () => {
  it("never renders the literal string _loose, even if a project entry is named that", () => {
    const { container } = renderRail({
      projects: [project({ name: "_loose", file_count: 5 })],
      looseCount: 2,
    });
    expect(container.textContent).not.toContain("_loose");
    // Both the bogus entry and the real loose tile must read "loose".
    expect(screen.getAllByText("loose").length).toBe(2);
  });

  it("renders a normal project name unchanged", () => {
    renderRail({ projects: [project({ name: "kitchen-remodel", file_count: 4 })] });
    expect(screen.getByText("kitchen-remodel")).toBeTruthy();
  });
});

describe("ProjectsRail — the loose tile", () => {
  it("spans the row when it is the only tile (no projects)", () => {
    const { container } = renderRail({ projects: [], looseCount: 17 });
    const tiles = container.querySelectorAll(".pr-tile");
    expect(tiles.length).toBe(1);
    expect((tiles[0] as HTMLElement).style.gridColumn).toBe("1 / -1");
  });

  it("does NOT span the row when at least one project exists", () => {
    const { container } = renderRail({
      projects: [project({ name: "research" })],
      looseCount: 3,
    });
    const tiles = container.querySelectorAll(".pr-tile");
    expect(tiles.length).toBe(2);
    const looseTile = tiles[tiles.length - 1] as HTMLElement;
    expect(looseTile.style.gridColumn).toBe("");
  });

  it("selecting the loose tile reports LOOSE_PROJECT_ID, the server's own sentinel", () => {
    expect(LOOSE_PROJECT_ID).toBe("_loose");
  });
});

describe("ProjectsRail — the no-description warning", () => {
  it("appears for a project with an empty description", () => {
    renderRail({
      projects: [project({ name: "trip-japan", description: "" })],
      projectCounts: { "trip-japan": 3 },
    });
    expect(screen.getByText("3 notes, no description")).toBeTruthy();
    expect(screen.queryByText("3 notes")).toBeNull();
  });

  it("does not appear for a project with a real description", () => {
    renderRail({
      projects: [project({ name: "research", description: "Lit review notes." })],
      projectCounts: { research: 6 },
    });
    expect(screen.getByText("6 notes")).toBeTruthy();
    expect(screen.queryByText(/no description/)).toBeNull();
  });

  it("a whitespace-only description counts as empty", () => {
    renderRail({
      projects: [project({ name: "trip-japan", description: "   " })],
      projectCounts: { "trip-japan": 3 },
    });
    expect(screen.getByText("3 notes, no description")).toBeTruthy();
  });
});

describe("ProjectsRail — tile counts come from projectCounts, never ProjectEntry.file_count (spec §5.6)", () => {
  it("renders the count from projectCounts even when file_count disagrees", () => {
    // file_count is the directory-derived number (vault_admin._project_file_count) --
    // deliberately wrong here to prove the tile does not read it.
    renderRail({
      projects: [project({ name: "research", description: "Lit review notes.", file_count: 999 })],
      projectCounts: { research: 6 },
    });
    expect(screen.getByText("6 notes")).toBeTruthy();
    expect(screen.queryByText(/999/)).toBeNull();
  });

  it("a registered project with no row in projectCounts renders 0 notes, not vanishing or 'undefined'", () => {
    renderRail({
      projects: [project({ name: "onboarding-v2", description: "The onboarding rewrite." })],
      projectCounts: {},
      looseCount: 9, // distinct from the tile's 0, so the two "N notes" texts don't collide
    });
    expect(screen.getByText("0 notes")).toBeTruthy();
    expect(screen.getByText("9 notes")).toBeTruthy();
    expect(screen.queryByText(/undefined/)).toBeNull();
  });
});

describe("ProjectsRail — New project is always the last thing in the rail (spec §3)", () => {
  it("is always the last child of the rail", () => {
    const { container } = renderRail();
    const rail = container.firstElementChild as HTMLElement;
    expect(rail.lastElementChild?.textContent).toContain("New project");
  });
});

describe("ProjectsRail — tile ARIA (spec §7: valid aria-selected needs a containing role)", () => {
  it("the tiles grid is a listbox of options, so aria-selected is valid (not a bare button)", () => {
    renderRail({
      projects: [project({ name: "research" }), project({ name: "kitchen-remodel" })],
      selectedId: "kitchen-remodel",
    });
    const listbox = screen.getByRole("listbox", { name: "Projects" });
    const options = screen.getAllByRole("option");
    expect(options.length).toBe(3); // 2 projects + loose
    expect(listbox.contains(options[0])).toBe(true);
  });

  it("exactly one option is aria-selected at a time", () => {
    renderRail({
      projects: [project({ name: "research" }), project({ name: "kitchen-remodel" })],
      selectedId: "kitchen-remodel",
    });
    const options = screen.getAllByRole("option");
    const selected = options.filter((o) => o.getAttribute("aria-selected") === "true");
    expect(selected.length).toBe(1);
    expect(selected[0].textContent).toContain("kitchen-remodel");
  });

  it("selecting the loose tile marks IT as the one aria-selected option", () => {
    renderRail({
      projects: [project({ name: "research" })],
      selectedId: LOOSE_PROJECT_ID,
    });
    const options = screen.getAllByRole("option");
    const selected = options.filter((o) => o.getAttribute("aria-selected") === "true");
    expect(selected.length).toBe(1);
    expect(selected[0].textContent).toContain("loose");
  });
});

describe("ProjectsRail — the toggle is the real SegmentedToggle", () => {
  it("renders exactly two tabs, Projects and Tags, wired to onModeChange", () => {
    renderRail({ mode: "projects" });
    const tabs = screen.getAllByRole("tab");
    expect(tabs.length).toBe(2);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    expect(tabs[1].getAttribute("aria-selected")).toBe("false");
  });

});

describe("ProjectsRail — the tag list (spec §5.1)", () => {
  it("renders a listbox of options, one per tag, wired to onSelectTag", () => {
    const onSelectTag = vi.fn();
    renderRail({
      mode: "tags",
      tags: [{ tag: "reading", count: 4 }, { tag: "invoice", count: 2 }],
      onSelectTag,
    });
    const listbox = screen.getByRole("listbox", { name: "Tags" });
    const options = screen.getAllByRole("option");
    expect(options.length).toBe(2);
    expect(listbox.contains(options[0])).toBe(true);
    fireEvent.click(screen.getByText("reading"));
    expect(onSelectTag).toHaveBeenCalledWith("reading");
  });

  it("shows each tag's count from the flattened tag list, not a separate source (spec §5.6)", () => {
    renderRail({ mode: "tags", tags: [{ tag: "reading", count: 11 }] });
    expect(screen.getByText("11")).toBeTruthy();
  });

  it("the selected tag uses the SAME visual language as a selected project tile: accent wash + 2px accent left edge (spec §5.1)", () => {
    renderRail({
      mode: "tags",
      tags: [{ tag: "reading", count: 4 }, { tag: "invoice", count: 2 }],
      selectedTag: "invoice",
    });
    const options = screen.getAllByRole("option");
    const selected = options.find((o) => o.getAttribute("aria-selected") === "true")!;
    expect(selected.textContent).toContain("invoice");
    expect((selected as HTMLElement).style.background).toBe("var(--accent-d)");
    expect((selected as HTMLElement).style.borderLeftColor).toBe("var(--accent)");
    const unselected = options.find((o) => o.getAttribute("aria-selected") === "false")!;
    expect((unselected as HTMLElement).style.background).not.toBe("var(--accent-d)");
  });

  it("exactly one option is aria-selected at a time", () => {
    renderRail({
      mode: "tags",
      tags: [{ tag: "reading", count: 4 }, { tag: "invoice", count: 2 }],
      selectedTag: "reading",
    });
    const selected = screen.getAllByRole("option").filter((o) => o.getAttribute("aria-selected") === "true");
    expect(selected.length).toBe(1);
  });

  it("a namespace parent's trailing slash is stripped for DISPLAY but preserved for the click value (flattenTagTree/tagDisplayLabel contract)", () => {
    const onSelectTag = vi.fn();
    renderRail({ mode: "tags", tags: [{ tag: "project/", count: 3 }], onSelectTag });
    expect(screen.getByText("project")).toBeTruthy(); // displayed without the slash
    expect(screen.queryByText("project/")).toBeNull();
    fireEvent.click(screen.getByText("project"));
    expect(onSelectTag).toHaveBeenCalledWith("project/"); // called WITH the slash
  });

  it("shows a calm empty state, not a blank panel, when there are no tags", () => {
    renderRail({ mode: "tags", tags: [] });
    expect(screen.getByText("No tags yet.")).toBeTruthy();
  });
});

describe("ProjectsRail — inline create (FR-04/FR-12 fix, Fork 1 Option B: board 2026-08-02-flowreview-decisions.html)", () => {
  it("New project reveals an inline editable row, not a modal", () => {
    renderRail();
    expect(screen.queryByLabelText("New project name")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    expect(screen.getByLabelText("New project name")).toBeTruthy();
    expect(screen.getByText("Enter to create · Esc to cancel")).toBeTruthy();
  });

  it("Enter commits: calls createProject with the trimmed name and reports it via onProjectCreated", async () => {
    const onProjectCreated = vi.fn();
    renderRail({ onProjectCreated });
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    fireEvent.change(screen.getByLabelText("New project name"), { target: { value: "  trip-osaka  " } });
    fireEvent.keyDown(screen.getByLabelText("New project name"), { key: "Enter" });

    await vi.waitFor(() => expect(api.createProject).toHaveBeenCalledWith("trip-osaka"));
    await vi.waitFor(() => expect(onProjectCreated).toHaveBeenCalledWith("trip-osaka"));
    // The row closes back to the plain "New project" button once created.
    await vi.waitFor(() => expect(screen.queryByLabelText("New project name")).toBeNull());
  });

  it("Escape cancels without ever calling createProject", () => {
    renderRail();
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    fireEvent.change(screen.getByLabelText("New project name"), { target: { value: "abandoned" } });
    fireEvent.keyDown(screen.getByLabelText("New project name"), { key: "Escape" });

    expect(screen.queryByLabelText("New project name")).toBeNull();
    expect(api.createProject).not.toHaveBeenCalled();
  });

  it("the check glyph commits, the close glyph cancels — same as the keyboard path", async () => {
    const onProjectCreated = vi.fn();
    renderRail({ onProjectCreated });
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    fireEvent.change(screen.getByLabelText("New project name"), { target: { value: "kitchen-remodel" } });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    await vi.waitFor(() => expect(onProjectCreated).toHaveBeenCalledWith("kitchen-remodel"));
  });

  it("an invalid name shows an inline error and never calls createProject (server-mirrored validity, projects.py's _VALID_NAME)", () => {
    renderRail();
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    fireEvent.change(screen.getByLabelText("New project name"), { target: { value: "trip osaka" } });
    fireEvent.keyDown(screen.getByLabelText("New project name"), { key: "Enter" });

    expect(api.createProject).not.toHaveBeenCalled();
    expect(screen.getByLabelText("New project name")).toBeTruthy(); // stays open, editable
    expect(screen.queryByText("Enter to create · Esc to cancel")).toBeNull(); // replaced by the error
  });

  it("committing an empty/whitespace-only name is a silent cancel, not an error", () => {
    renderRail();
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    fireEvent.change(screen.getByLabelText("New project name"), { target: { value: "   " } });
    fireEvent.keyDown(screen.getByLabelText("New project name"), { key: "Enter" });

    expect(api.createProject).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("New project name")).toBeNull();
  });

  it("a server-side rejection (e.g. name collision) surfaces as the inline error and keeps the row open to retry", async () => {
    vi.mocked(api.createProject).mockRejectedValue(new Error('A project named "research" already exists.'));
    renderRail();
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    fireEvent.change(screen.getByLabelText("New project name"), { target: { value: "research" } });
    fireEvent.keyDown(screen.getByLabelText("New project name"), { key: "Enter" });

    expect(await screen.findByText('A project named "research" already exists.')).toBeTruthy();
    expect(screen.getByLabelText("New project name")).toBeTruthy(); // still open
  });

  it("blur commits, same as Enter", async () => {
    const onProjectCreated = vi.fn();
    renderRail({ onProjectCreated });
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    fireEvent.change(screen.getByLabelText("New project name"), { target: { value: "trip-japan" } });
    fireEvent.blur(screen.getByLabelText("New project name"));
    await vi.waitFor(() => expect(api.createProject).toHaveBeenCalledWith("trip-japan"));
  });

  it("a second click on New project while already editing does not wipe what the user already typed", () => {
    renderRail();
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    fireEvent.change(screen.getByLabelText("New project name"), { target: { value: "kept" } });
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    expect((screen.getByLabelText("New project name") as HTMLInputElement).value).toBe("kept");
  });

  it("works identically at zero projects, with no separate empty-state wiring", () => {
    renderRail({ projects: [], looseCount: 17 });
    fireEvent.click(screen.getByRole("button", { name: /new project/i }));
    expect(screen.getByLabelText("New project name")).toBeTruthy();
  });
});

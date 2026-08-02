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
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import ProjectsRail, { LOOSE_PROJECT_ID, type ProjectsRailSuggestion } from "./ProjectsRail";
import type { ProjectEntry } from "../../lib/api";

afterEach(cleanup);

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
      onNewProject={NOOP}
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

describe("ProjectsRail — suggestion button geometry (spec §4.2, user-specified)", () => {
  const SUGG: ProjectsRailSuggestion = { name: "trip-japan", fact: "3 loose captures, past 6 days, matching no project" };

  it("Create and Rename are equal-width BY CONSTRUCTION (flex:1 1 0, min-width:0) regardless of label length", () => {
    renderRail({ suggestion: SUGG });
    const create = screen.getByRole("button", { name: /create/i });
    const rename = screen.getByRole("button", { name: /rename/i });
    // happy-dom's CSSOM normalizes the flex-basis component to "0px" even
    // though the declared value was the unitless "0" — assert what the DOM
    // actually reports, same 0-basis contract either way.
    expect(create.style.flex).toBe("1 1 0px");
    expect(rename.style.flex).toBe("1 1 0px");
    expect(create.style.minWidth).toBe("0");
    expect(rename.style.minWidth).toBe("0");
    // Same declared height, driven by the ONE --ctl custom property (not
    // three padding values that happen to agree).
    expect(create.style.height).toBe("var(--ctl)");
    expect(rename.style.height).toBe("var(--ctl)");
  });

  it("the dismiss button is a TRUE square, excluded from flex growth", () => {
    renderRail({ suggestion: SUGG });
    const dismiss = screen.getByRole("button", { name: "Not a project" });
    expect(dismiss.style.width).toBe("var(--ctl)");
    expect(dismiss.style.height).toBe("var(--ctl)");
    expect(dismiss.style.width).toBe(dismiss.style.height);
    expect(dismiss.style.flex).toBe("0 0 auto");
  });

  it("Create keeps the accent; Rename and the dismiss square use the raised control face (spec §4.4)", () => {
    renderRail({ suggestion: SUGG });
    const create = screen.getByRole("button", { name: /create/i });
    const rename = screen.getByRole("button", { name: /rename/i });
    const dismiss = screen.getByRole("button", { name: "Not a project" });
    expect(create.style.background).toBe("var(--accent-glow)");
    expect(rename.style.background).toBe("var(--ctl-face)");
    expect(dismiss.style.background).toBe("var(--ctl-face)");
  });

  it("does not render at all when suggestion is null", () => {
    renderRail({ suggestion: null });
    expect(screen.queryByText("Inbox suggests")).toBeNull();
    expect(screen.queryByRole("button", { name: /create/i })).toBeNull();
  });
});

describe("ProjectsRail — New project is always the last thing in the rail (spec §3)", () => {
  it("is last when no suggestion is present", () => {
    const { container } = renderRail({ suggestion: null });
    const rail = container.firstElementChild as HTMLElement;
    expect(rail.lastElementChild?.textContent).toContain("New project");
  });

  it("is still last when a suggestion IS present", () => {
    const { container } = renderRail({
      suggestion: { name: "trip-japan", fact: "3 loose captures" },
    });
    const rail = container.firstElementChild as HTMLElement;
    expect(rail.lastElementChild?.textContent).toContain("New project");
    // and the suggestion box sits directly above it, not above the toggle.
    const children = Array.from(rail.children);
    const suggIndex = children.findIndex((c) => c.textContent?.includes("Inbox suggests"));
    const footIndex = children.findIndex((c) => c.textContent?.includes("New project"));
    expect(suggIndex).toBeGreaterThan(-1);
    expect(suggIndex).toBe(footIndex - 1);
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

  it("switching to tags shows the Task 7 seam, not a fake tag list", () => {
    renderRail({ mode: "tags" });
    expect(screen.getByText("Tags (Task 7)")).toBeTruthy();
  });
});

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
import * as clipboard from "@tauri-apps/plugin-clipboard-manager";

vi.mock("@tauri-apps/plugin-clipboard-manager", () => ({
  writeText: vi.fn(),
}));

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    notesForProject: vi.fn(),
    notesForTag: vi.fn(),
    renameProject: vi.fn(),
    deleteProject: vi.fn(),
    updateProjectDescription: vi.fn(),
    moveToTrash: vi.fn(),
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
  vi.mocked(api.notesForTag).mockResolvedValue([]);
  vi.mocked(api.renameProject).mockResolvedValue(undefined);
  vi.mocked(api.deleteProject).mockResolvedValue(undefined);
  vi.mocked(api.updateProjectDescription).mockResolvedValue(undefined);
  vi.mocked(api.moveToTrash).mockResolvedValue({ ok: true, filename: "a.md", trashed_path: "_trash/a.md" });
  vi.mocked(clipboard.writeText).mockResolvedValue(undefined);
});

function renderPane(props: Partial<React.ComponentProps<typeof ProjectsPane>> = {}) {
  return render(
    <ProjectsPane
      mode="projects"
      projects={[project({})]}
      selectedId="research"
      selectedTag={null}
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
    rerender(<ProjectsPane mode="projects" projects={[project({})]} selectedId={LOOSE_PROJECT_ID} selectedTag={null} />);
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
    expect(screen.getByText(/All\s*2\s*of your notes are loose/)).toBeTruthy();
    expect(screen.getByText("#project@name")).toBeTruthy();
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
    expect(screen.getByText("New captures are matched against this text — on this device, or a phone, if you use one.")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("shows the yellow empty variant when the description is blank", async () => {
    renderPane({ projects: [project({ description: "" })] });
    expect(await screen.findByText("Empty. Nothing to match new captures against yet.")).toBeTruthy();
  });

  it("a whitespace-only description counts as empty", async () => {
    renderPane({ projects: [project({ description: "   " })] });
    expect(await screen.findByText("Empty. Nothing to match new captures against yet.")).toBeTruthy();
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

describe("ProjectsPane — FR-21: copy-the-tag affordance (board: Fork 3 Option A)", () => {
  it("renders the exact #project@<name> tag and copies it via the clipboard-manager plugin, writing nothing to any note", async () => {
    renderPane({ projects: [project({ name: "kitchen-remodel" })], selectedId: "kitchen-remodel" });
    await screen.findByText("kitchen-remodel");
    expect(screen.getByText("project@kitchen-remodel")).toBeTruthy();

    const copyBtn = screen.getByRole("button", { name: "Copy tag #project@kitchen-remodel" });
    fireEvent.click(copyBtn);

    await vi.waitFor(() => expect(clipboard.writeText).toHaveBeenCalledWith("#project@kitchen-remodel"));
    // The chip's own click handler never calls any api.ts mutation — the
    // only writes this test's mocked surface would catch (rename/delete/
    // description/moveToTrash) must all stay untouched by a tag copy.
    expect(api.renameProject).not.toHaveBeenCalled();
    expect(api.deleteProject).not.toHaveBeenCalled();
    expect(api.updateProjectDescription).not.toHaveBeenCalled();
    expect(api.moveToTrash).not.toHaveBeenCalled();
  });

  it("swaps to a distinct copied state (icon + label, not color alone) after a successful copy", async () => {
    renderPane({ projects: [project({ name: "kitchen-remodel" })], selectedId: "kitchen-remodel" });
    const copyBtn = await screen.findByRole("button", { name: "Copy tag #project@kitchen-remodel" });
    fireEvent.click(copyBtn);
    await screen.findByRole("button", { name: "Tag copied" });
  });

  it("renders no chip for the loose head — a loose note has no project tag to copy", async () => {
    renderPane({ projects: [project({})], selectedId: LOOSE_PROJECT_ID });
    await screen.findByText("no project tag, nothing to set up");
    expect(screen.queryByRole("button", { name: /Copy tag/ })).toBeNull();
    expect(document.body.textContent).not.toContain("_loose");
  });

  it("renders no chip on the calm empty-vault head — no project is selected", async () => {
    renderPane({ projects: [], selectedId: LOOSE_PROJECT_ID });
    await screen.findByText("No projects yet");
    expect(screen.queryByRole("button", { name: /Copy tag/ })).toBeNull();
  });

  it("renders no chip in tag mode — a tag head is not a project head (spec §5.4)", async () => {
    renderPane({ mode: "tags", selectedTag: "reading", projects: [project({})] });
    await screen.findByText("reading");
    expect(screen.queryByRole("button", { name: /Copy tag/ })).toBeNull();
  });
});

describe("ProjectsPane — FR-05: descDraft anti-clobber (effect deliberately keyed on [selectedId, mode] only)", () => {
  it("a `projects` refresh that leaves selectedId/mode unchanged does not clobber an in-progress edit", async () => {
    const { rerender } = renderPane({
      projects: [project({ name: "research", description: "Original." })],
      selectedId: "research",
    });
    const textarea = (await screen.findByLabelText("Project description")) as HTMLTextAreaElement;
    expect(textarea.value).toBe("Original.");

    fireEvent.change(textarea, { target: { value: "Original. Still typing..." } });
    expect(textarea.value).toBe("Original. Still typing...");

    // A refresh lands (new `projects` array reference/content) while the
    // selection itself hasn't moved -- must not reset descDraft to the
    // server value and wipe what the user is mid-typing.
    rerender(
      <ProjectsPane
        mode="projects"
        projects={[project({ name: "research", description: "Original." })]}
        selectedId="research"
        selectedTag={null}
      />,
    );
    expect((screen.getByLabelText("Project description") as HTMLTextAreaElement).value).toBe(
      "Original. Still typing...",
    );
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

describe("ProjectsPane — tag mode (spec §5): fetch (trap 5, explicit limit)", () => {
  it("calls notesForTag with an explicit limit of 200, not notesForProject", async () => {
    renderPane({ mode: "tags", selectedId: null, selectedTag: "reading" });
    await vi.waitFor(() => expect(api.notesForTag).toHaveBeenCalledWith("reading", { limit: 200 }));
    expect(api.notesForProject).not.toHaveBeenCalled();
  });

  it("refetches when the selected tag changes", async () => {
    const { rerender } = renderPane({ mode: "tags", selectedId: null, selectedTag: "reading" });
    await vi.waitFor(() => expect(api.notesForTag).toHaveBeenCalledWith("reading", { limit: 200 }));
    rerender(<ProjectsPane mode="tags" projects={[project({})]} selectedId={null} selectedTag="invoice" />);
    await vi.waitFor(() => expect(api.notesForTag).toHaveBeenCalledWith("invoice", { limit: 200 }));
  });

  it("a namespace parent's trailing slash survives unstripped into the fetch call", async () => {
    renderPane({ mode: "tags", selectedId: null, selectedTag: "project/" });
    await vi.waitFor(() => expect(api.notesForTag).toHaveBeenCalledWith("project/", { limit: 200 }));
  });
});

describe("ProjectsPane — tag head (spec §5.4): not a project head", () => {
  it("shows the tag name and vault-wide count, no rename/delete/description editor", async () => {
    vi.mocked(api.notesForTag).mockResolvedValue([row({}), row({ path: "b.md", filename: "b.md" })]);
    renderPane({ mode: "tags", selectedId: null, selectedTag: "reading" });
    expect(await screen.findByText("2 notes across your vault")).toBeTruthy();
    expect(screen.getByText("reading")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Rename project" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete project" })).toBeNull();
    expect(screen.queryByLabelText("Project description")).toBeNull();
  });

  it("strips a namespace parent's trailing slash for display", async () => {
    renderPane({ mode: "tags", selectedId: null, selectedTag: "project/" });
    expect(await screen.findByText("project")).toBeTruthy();
    expect(screen.queryByText("project/")).toBeNull();
  });

  it("the head's count and the notes-head label both read rows.length -- this pane's own internal agreement (trap 2's pane-side half)", async () => {
    // This is the guarantee the gui/ code actually owns: BOTH numbers on
    // this pane come from the same in-memory `rows` state, so they cannot
    // disagree with EACH OTHER. It is not a claim that this number matches
    // the rail's /tags-derived count -- it can legitimately run one behind
    // for a note whose index pass hasn't caught up with a just-saved tag
    // (GET /search only returns captures.db rows filtered by the file
    // scan's membership, per index_writer.py:840-852 -- see
    // ProjectsView.tsx's tags-state comment). The pane deliberately shows
    // what it actually holds rather than echoing a sibling source.
    vi.mocked(api.notesForTag).mockResolvedValue([
      row({ path: "a.md", filename: "a.md" }),
      row({ path: "b.md", filename: "b.md" }),
      row({ path: "c.md", filename: "c.md" }),
    ]);
    renderPane({ mode: "tags", selectedId: null, selectedTag: "reading" });
    expect(await screen.findByText("3 notes across your vault")).toBeTruthy();
    expect(screen.getByText("3 notes")).toBeTruthy(); // the notes-head label, same number
  });
});

describe("ProjectsPane — tag mode per-row project chip (spec §5.3)", () => {
  it("shows the note's project as a chip, text + border (not rendered for project mode)", async () => {
    vi.mocked(api.notesForTag).mockResolvedValue([row({ path: "a.md", filename: "a.md", project: "kitchen-remodel" })]);
    renderPane({ mode: "tags", selectedId: null, selectedTag: "quote" });
    expect(await screen.findByText("kitchen-remodel")).toBeTruthy();
  });

  it("a loose note's chip reads 'loose', never the raw _loose sentinel (spec §2.2)", async () => {
    vi.mocked(api.notesForTag).mockResolvedValue([row({ path: "a.md", filename: "a.md", project: LOOSE_PROJECT_ID })]);
    renderPane({ mode: "tags", selectedId: null, selectedTag: "reading" });
    expect(await screen.findByText("loose")).toBeTruthy();
    expect(document.body.textContent).not.toContain(LOOSE_PROJECT_ID);
  });

  it("a null project also reads 'loose'", async () => {
    vi.mocked(api.notesForTag).mockResolvedValue([row({ path: "a.md", filename: "a.md", project: null })]);
    renderPane({ mode: "tags", selectedId: null, selectedTag: "reading" });
    expect(await screen.findByText("loose")).toBeTruthy();
  });

  it("project mode never renders a project chip on note rows", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([row({ path: "a.md", filename: "a.md", project: "research" })]);
    renderPane({ mode: "projects", selectedId: "research" });
    await screen.findByText("a.md");
    // "research" appears once, as the head name -- not a second time as a chip.
    expect(screen.getAllByText("research").length).toBe(1);
  });
});

describe("ProjectsPane — mode gating (spec §5.4): stale selectedId can't leak project UI into tag mode", () => {
  it("no description/rename/delete render in tag mode even when selectedId still names a real project", async () => {
    renderPane({ mode: "tags", projects: [project({ name: "research" })], selectedId: "research", selectedTag: "reading" });
    await vi.waitFor(() => expect(api.notesForTag).toHaveBeenCalled());
    expect(screen.queryByLabelText("Project description")).toBeNull();
    expect(screen.queryByRole("button", { name: "Rename project" })).toBeNull();
  });
});

describe("ProjectsPane — note delete (FR-04/FR-12 fix, Fork 1: 'shared across all three' board section)", () => {
  it("clicking a row's trash icon opens an inline confirm strip, no modal", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([row({ path: "a.md", filename: "note-a.md" })]);
    renderPane();
    await screen.findByText("note-a.md");
    fireEvent.click(screen.getByRole("button", { name: 'Move "note-a.md" to trash' }));
    expect(screen.getByText(/It stays recoverable for 30 days\./)).toBeTruthy();
    expect(api.moveToTrash).not.toHaveBeenCalled(); // opening the confirm never fires the mutation itself
  });

  it("Cancel dismisses the strip without calling moveToTrash", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([row({ path: "a.md", filename: "note-a.md" })]);
    renderPane();
    await screen.findByText("note-a.md");
    fireEvent.click(screen.getByRole("button", { name: 'Move "note-a.md" to trash' }));
    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByText(/It stays recoverable for 30 days\./)).toBeNull();
    expect(api.moveToTrash).not.toHaveBeenCalled();
  });

  it("Move to Trash calls moveToTrash(path), drops the row, and fires onNoteDeleted", async () => {
    const onNoteDeleted = vi.fn();
    vi.mocked(api.notesForProject).mockResolvedValue([
      row({ path: "a.md", filename: "note-a.md" }),
      row({ path: "b.md", filename: "note-b.md" }),
    ]);
    renderPane({ onNoteDeleted });
    await screen.findByText("note-a.md");
    fireEvent.click(screen.getByRole("button", { name: 'Move "note-a.md" to trash' }));
    fireEvent.click(screen.getByText("Move to Trash"));

    await vi.waitFor(() => expect(api.moveToTrash).toHaveBeenCalledWith("a.md"));
    await vi.waitFor(() => expect(onNoteDeleted).toHaveBeenCalledWith("a.md"));
    await vi.waitFor(() => expect(screen.queryByText("note-a.md")).toBeNull());
    expect(screen.getByText("note-b.md")).toBeTruthy(); // the other row survives
  });

  it("the note count (rows.length, spec §5.6) drops by one immediately on a successful delete — no refetch needed", async () => {
    vi.mocked(api.notesForProject).mockResolvedValue([
      row({ path: "a.md", filename: "note-a.md" }),
      row({ path: "b.md", filename: "note-b.md" }),
    ]);
    renderPane();
    expect(await screen.findByText("2 notes")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: 'Move "note-a.md" to trash' }));
    fireEvent.click(screen.getByText("Move to Trash"));
    await vi.waitFor(() => expect(screen.getByText("1 notes")).toBeTruthy());
  });

  it("a failed delete surfaces the error and leaves the row in place", async () => {
    vi.mocked(api.moveToTrash).mockRejectedValue(new Error("Failed to move note to trash"));
    vi.mocked(api.notesForProject).mockResolvedValue([row({ path: "a.md", filename: "note-a.md" })]);
    renderPane();
    await screen.findByText("note-a.md");
    fireEvent.click(screen.getByRole("button", { name: 'Move "note-a.md" to trash' }));
    fireEvent.click(screen.getByText("Move to Trash"));

    expect(await screen.findByText("Failed to move note to trash")).toBeTruthy();
    // Still there, nothing silently lost — appears twice (the row itself,
    // and the confirm strip's own bold mention of it) because a FAILED
    // delete deliberately leaves the confirm strip open to retry, unlike a
    // successful one which closes it.
    expect(screen.getAllByText("note-a.md").length).toBeGreaterThan(0);
  });

  it("switching the selected project closes any open confirm strip (same reset effect as rename/project-delete)", async () => {
    vi.mocked(api.notesForProject).mockImplementation(async (name) =>
      name === "research" ? [row({ path: "a.md", filename: "note-a.md" })] : [],
    );
    const { rerender } = renderPane({ projects: [project({ name: "research" }), project({ name: "kitchen-remodel" })] });
    await screen.findByText("note-a.md");
    fireEvent.click(screen.getByRole("button", { name: 'Move "note-a.md" to trash' }));
    expect(screen.getByText(/It stays recoverable for 30 days\./)).toBeTruthy();

    rerender(
      <ProjectsPane
        mode="projects"
        projects={[project({ name: "research" }), project({ name: "kitchen-remodel" })]}
        selectedId="kitchen-remodel"
        selectedTag={null}
      />,
    );
    expect(screen.queryByText(/It stays recoverable for 30 days\./)).toBeNull();
  });

  it("note delete is available in tag mode too — the row markup is shared with project mode", async () => {
    vi.mocked(api.notesForTag).mockResolvedValue([row({ path: "a.md", filename: "note-a.md", project: "research" })]);
    renderPane({ mode: "tags", selectedId: null, selectedTag: "reading" });
    await screen.findByText("note-a.md");
    expect(screen.getByRole("button", { name: 'Move "note-a.md" to trash' })).toBeTruthy();
  });
});

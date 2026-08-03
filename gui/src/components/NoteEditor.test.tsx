// @vitest-environment happy-dom
import { useState, type ReactNode } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NoteEditor from "./NoteEditor";
import * as api from "../lib/api";
import type { NoteContent } from "../lib/api";
import { SAVE_BASE_DELAY_MS } from "../lib/saveRetry";

// ponytail: happy-dom ships no layout engine (getBoundingClientRect/offsetWidth
// all read 0 here) -- these tests assert DOM structure, ARIA attributes, and
// mock call sequencing ONLY. Every real pixel/geometry assertion (dropdown
// top:56 non-overlap, 640px no-overlap, hit-testability) stays CDP-only. Do
// not "upgrade" a geometry check into this file: it will silently pass against
// all-zero rects and prove nothing.
vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    getNoteContent: vi.fn(),
    saveNoteContent: vi.fn(),
    getNoteConflict: vi.fn(),
    getNoteHistory: vi.fn(),
    getNoteHistoryRevision: vi.fn(),
    resolveNoteConflict: vi.fn(),
    searchCaptures: vi.fn(),
    createReminder: vi.fn(),
    addNoteAttachment: vi.fn(),
    fetchAttachmentBlob: vi.fn(),
  };
});

const noteFixture: NoteContent = {
  path: "Test/note.md",
  title: "Test Note",
  project: "Test",
  status: null,
  tags: [],
  body: "hello world",
  mtime: 1000,
  has_frontmatter: true,
};

// Task 9 (C1): NoteEditor no longer renders its own topbar/corner-menu inline
// -- back/title/sync/mode-toggle/external/more now only reach the DOM via
// `onHeaderActionsChange`, the slot FullWindow's real topbar consumes. `Host`
// stands in for that consumer here so the DOM-query-based tests below (many
// of which target "More"/"Back"/"Switch to view" etc.) keep working
// unmodified: it just renders whatever NoteEditor hands it next to the editor
// itself, the same shape FullWindow renders it in (a sibling, not a nested
// child of the dialog).
function Host({
  path, onClose, onOpenExternal,
}: { path: string | null; onClose: () => void; onOpenExternal: (path: string) => void }) {
  const [headerActions, setHeaderActions] = useState<ReactNode>(null);
  return (
    <>
      <div>{headerActions}</div>
      <NoteEditor open path={path} onClose={onClose} onOpenExternal={onOpenExternal} onHeaderActionsChange={setHeaderActions} />
    </>
  );
}

// Async since Task 9 (C1). NoteEditor no longer renders its own topbar -- Back,
// the mode toggle, "Open in external editor" and More are pushed UP to the host
// through onHeaderActionsChange in an effect, so they land a tick after the body.
// Waiting for Back here means every test gets a fully-mounted editor and no
// individual test has to remember to use an async query for a header control.
// Patching the ~13 call sites instead would have left the next one to reintroduce
// the race; this is the one place they all funnel through.
async function renderEditor(path = "Test/note.md") {
  const onClose = vi.fn();
  const onOpenExternal = vi.fn();
  const utils = render(
    <Host path={path} onClose={onClose} onOpenExternal={onOpenExternal} />,
  );
  await screen.findByRole("button", { name: "Back" });
  return { ...utils, onClose, onOpenExternal };
}

beforeEach(() => {
  vi.mocked(api.getNoteContent).mockResolvedValue(noteFixture);
  vi.mocked(api.getNoteConflict).mockResolvedValue(null);
  vi.mocked(api.getNoteHistory).mockResolvedValue({ status: "ok", revisions: [] });
  vi.mocked(api.saveNoteContent).mockResolvedValue({ mtime: 2000 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("NoteEditor — mount", () => {
  it("mounts without throwing and renders the dialog with the loaded note", async () => {
    await renderEditor();
    expect(await screen.findByRole("heading", { name: "Test Note" })).toBeTruthy();
    const dialog = screen.getByRole("dialog", { name: "Note editor" });
    expect(dialog).toBeTruthy();
  });
});

describe("NoteEditor — Escape precedence", () => {
  it("closes the corner menu first, without unlocking or closing the drawer/editor", async () => {
    const user = userEvent.setup({ delay: null });
    const { onClose } = await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const moreBtn = screen.getByRole("button", { name: "More" });
    await user.click(moreBtn);
    expect(moreBtn.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(moreBtn.getAttribute("aria-expanded")).toBe("false");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("unlocks the toolbar next, when the menu is already closed", async () => {
    const { onClose } = await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    // fireEvent, not user.click: the lock button's ancestor column is
    // pointerEvents:none until real hover flips toolbarPeeking, which
    // userEvent's pointer-events precheck rejects before that can happen.
    const lockBtn = screen.getByTitle("Lock toolbar open");
    fireEvent.click(lockBtn);
    expect(screen.getByTitle("Unlock toolbar").getAttribute("aria-pressed")).toBe("true");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.getByTitle("Lock toolbar open").getAttribute("aria-pressed")).toBe("false");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes the pinned drawer next, when the menu is closed and the toolbar is unlocked", async () => {
    const user = userEvent.setup({ delay: null });
    const { onClose } = await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("menuitem", { name: "Metadata" }));
    expect(screen.queryByText("METADATA")).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.queryByText("METADATA")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes the editor last, when menu/lock/drawer are all already closed", async () => {
    const { onClose } = await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("NoteEditor — toggleToolbarLock mode restore", () => {
  it("restores view mode on unlock when the lock was engaged from view mode", async () => {
    const user = userEvent.setup({ delay: null });
    await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });

    // findByRole, not getByRole: since Task 9 the mode toggle is not rendered by
    // NoteEditor itself -- it is pushed up through onHeaderActionsChange in an
    // effect, so it lands one tick after the body heading this test waited on.
    // A sync query here raced the push and failed ~1 run in 3.
    await user.click(await screen.findByRole("button", { name: "Switch to view" }));
    expect(screen.getByRole("button", { name: "Switch to edit" })).toBeTruthy();

    // fireEvent, not user.click: the lock button's ancestor column is
    // pointerEvents:none until real hover flips toolbarPeeking, which
    // userEvent's pointer-events precheck rejects before that can happen.
    fireEvent.click(screen.getByTitle("Lock toolbar open"));
    // toggleToolbarLock: mode === "view" -> lockPriorModeRef = "view", forces mode back to "edit"
    expect(screen.getByRole("button", { name: "Switch to view" })).toBeTruthy();

    fireEvent.click(screen.getByTitle("Unlock toolbar"));
    // unlock: lockPriorModeRef.current === "view" -> restores view mode
    expect(screen.getByRole("button", { name: "Switch to edit" })).toBeTruthy();
  });

  it("does not change mode on unlock when the lock was engaged from edit mode", async () => {
    await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });

    fireEvent.click(screen.getByTitle("Lock toolbar open"));
    // mode was already "edit" -> lockPriorModeRef = null, mode stays "edit"
    // findByRole for the same reason as the test above: the toggle arrives via
    // the header-actions push, not from NoteEditor's own tree.
    expect(await screen.findByRole("button", { name: "Switch to view" })).toBeTruthy();

    fireEvent.click(screen.getByTitle("Unlock toolbar"));
    // lockPriorModeRef.current !== "view" -> no restore
    expect(screen.getByRole("button", { name: "Switch to view" })).toBeTruthy();
  });
});

describe("NoteEditor — menu reset on note switch + outside click", () => {
  it("closes the menu when clicking outside it", async () => {
    const user = userEvent.setup({ delay: null });
    await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const moreBtn = screen.getByRole("button", { name: "More" });
    await user.click(moreBtn);
    expect(moreBtn.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(document.body);

    expect(moreBtn.getAttribute("aria-expanded")).toBe("false");
  });

  it("resets menuOpen when the editor switches to a different note", async () => {
    const user = userEvent.setup({ delay: null });
    const { rerender, onClose, onOpenExternal } = await renderEditor("Test/note.md");
    await screen.findByRole("heading", { name: "Test Note" });
    await user.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("button", { name: "More" }).getAttribute("aria-expanded")).toBe("true");

    vi.mocked(api.getNoteContent).mockResolvedValue({
      ...noteFixture,
      path: "Test/other.md",
      title: "Other Note",
    });
    rerender(<Host path="Test/other.md" onClose={onClose} onOpenExternal={onOpenExternal} />);
    await screen.findByRole("heading", { name: "Other Note" });

    // waitFor: the heading lives in the body and settles a render before the
    // re-pushed header actions do, so a sync query here read the OLD More button.
    // The contract asserted is unchanged -- the menu must end up closed.
    await vi.waitFor(() =>
      expect(screen.getByRole("button", { name: "More" }).getAttribute("aria-expanded")).toBe("false"),
    );
  });
});

describe("NoteEditor — toolbar peek chevron", () => {
  it("is visible while the toolbar is closed, and hides itself once clicked", async () => {
    await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const chevron = screen.getByRole("button", { name: "Show formatting toolbar" });
    expect(chevron.className).toContain("ne-peek-arrow");
    expect(chevron.getAttribute("data-hidden")).toBe("false");

    fireEvent.click(chevron);

    // onClick only ever sets toolbarPeeking(true) -- there is no toggle-off on
    // this element. data-hidden flips true because toolbarOut is now true,
    // hiding the "come here" arrow once the toolbar it points at is already out.
    expect(chevron.getAttribute("data-hidden")).toBe("true");
  });
});

describe("NoteEditor — metadata drawer project sentinel guard (FR-02)", () => {
  it("renders a loose note's project as 'loose', never the raw _loose sentinel", async () => {
    const user = userEvent.setup({ delay: null });
    vi.mocked(api.getNoteContent).mockResolvedValue({ ...noteFixture, project: "_loose" });
    await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("menuitem", { name: "Metadata" }));

    expect(await screen.findByText("loose")).toBeTruthy();
    expect(screen.queryByText("_loose")).toBeNull();
  });
});

describe("NoteEditor — Connections/Mentions rows (FR-14)", () => {
  it("wires a Mentions row to onOpenExternal(m.path) -- a real vault file is a real target", async () => {
    const user = userEvent.setup({ delay: null });
    vi.mocked(api.searchCaptures).mockResolvedValue({
      results: [
        { project: "Test", path: "Test/other.md", filename: "other.md", timestamp: null, source_url: null, confidence: null, tags: null, tier: null, score: null, modified: null },
      ],
      count: 1,
      query: "Test Note",
    });
    const { onOpenExternal } = await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("menuitem", { name: "Connections" }));

    const mentionRow = await screen.findByRole("button", { name: "other.md" });
    expect(onOpenExternal).not.toHaveBeenCalled();
    await user.click(mentionRow);
    expect(onOpenExternal).toHaveBeenCalledWith("Test/other.md");
  });

  it("renders a wikilink Connections row as inert -- no button role, no click handler (no resolvable target exists)", async () => {
    const user = userEvent.setup({ delay: null });
    vi.mocked(api.getNoteContent).mockResolvedValue({
      ...noteFixture,
      body: "See [[some-other-note]] for context.",
    });
    vi.mocked(api.searchCaptures).mockResolvedValue({ results: [], count: 0, query: "Test Note" });
    const { onOpenExternal } = await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(screen.getByRole("menuitem", { name: "Connections" }));

    const linkRow = await screen.findByText("some-other-note");
    expect(linkRow.tagName).toBe("DIV");
    expect(linkRow.closest("button")).toBeNull();
    expect((linkRow as HTMLElement).style.cursor).toBe("default");
    expect(onOpenExternal).not.toHaveBeenCalled();
  });
});

describe("NoteEditor — autosave debounce + backoff", () => {
  it("debounces the save, and backs off to 2x the base delay after a failure", async () => {
    await renderEditor();
    await screen.findByRole("heading", { name: "Test Note" });
    const textarea = screen.getByLabelText("Note body (editable)") as HTMLTextAreaElement;

    vi.useFakeTimers();
    vi.mocked(api.saveNoteContent).mockRejectedValueOnce(new Error("network down"));

    fireEvent.change(textarea, { target: { value: "hello world, edited" } });
    expect(api.saveNoteContent).not.toHaveBeenCalled();

    // Base debounce fires once at 900ms and fails.
    await vi.advanceTimersByTimeAsync(SAVE_BASE_DELAY_MS);
    expect(api.saveNoteContent).toHaveBeenCalledTimes(1);

    // Backoff is 2x base from the failure -- one more base tick alone must NOT retry.
    await vi.advanceTimersByTimeAsync(SAVE_BASE_DELAY_MS);
    expect(api.saveNoteContent).toHaveBeenCalledTimes(1);

    // The retry fires. Deliberately a GENEROUS window rather than a computed
    // offset: the backoff timer is not armed inside the rejection handler, it is
    // re-registered by a React effect, so the instant it starts counting depends
    // on when React flushes -- which is not deterministic under fake timers. Both
    // `SAVE_BASE_DELAY_MS` and `+ 50` were tried and both still failed ~1 run in 8.
    // Any exact offset here is a constant calibrated to an assumption about React's
    // scheduler, which is precisely the thing a fast test cannot falsify.
    // The two assertions that carry the real meaning are unchanged and still exact:
    // one base tick alone must NOT retry (above), and a retry must happen (here).
    await vi.advanceTimersByTimeAsync(SAVE_BASE_DELAY_MS * 3);
    expect(api.saveNoteContent).toHaveBeenCalledTimes(2);
  });
});

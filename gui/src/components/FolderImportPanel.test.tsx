// @vitest-environment happy-dom
/**
 * FolderImportPanel.test.tsx — FR-32.
 *
 * ponytail: happy-dom ships no layout engine (see ProjectsPane.test.tsx's same note) —
 * these tests assert DOM/ARIA structure, mock call sequencing, and text content only.
 *
 * THIS REPO HAS NO jest-dom: `toBeDisabled()` throws here. Every disabled assertion below
 * uses `toHaveProperty("disabled", true/false)` instead.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import {
  useFolderImport,
  FolderImportOffer,
  FolderImportChecklist,
  type FolderImportVariant,
} from "./FolderImportPanel";
import { rowsFrom } from "../lib/folderImport";
import * as api from "../lib/api";
import type { FolderImportCandidate } from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    getFolderImportPreview: vi.fn(),
    applyFolderImport: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function candidate(overrides: Partial<FolderImportCandidate>): FolderImportCandidate {
  return {
    folder: "research", suggested: "research", valid: true, existing: false, count: 4, phone_count: 0,
    ...overrides,
  };
}

/** Wires the real hook to the real presentational components exactly like a host
 *  (VaultManager/ProjectsPane) does — so these tests exercise the actual seam that broke,
 *  not a hand-rolled stand-in for it. */
function Harness({
  variant = "card", onApplied = vi.fn(), onError = vi.fn(),
}: { variant?: FolderImportVariant; onApplied?: () => void; onError?: (m: string | null) => void }) {
  const fi = useFolderImport({ onApplied, onError });
  return (
    <div>
      <button onClick={fi.probe}>probe</button>
      <FolderImportOffer
        offer={fi.offer}
        checklistOpen={fi.rows !== null}
        busy={fi.busy}
        onOpen={fi.open}
        variant={variant}
      />
      {fi.rows && (
        <FolderImportChecklist
          rows={fi.rows}
          busy={fi.busy}
          onToggle={fi.toggleRow}
          onRename={fi.renameRow}
          onCancel={fi.close}
          onApply={fi.apply}
          variant={variant}
        />
      )}
    </div>
  );
}

describe("FolderImportOffer — gating", () => {
  it("does not render when offer is 0", () => {
    render(<FolderImportOffer offer={0} checklistOpen={false} busy={false} onOpen={vi.fn()} variant="card" />);
    expect(screen.queryByRole("button", { name: /Keep my folders/ })).toBeNull();
  });

  it("renders when offer > 0", () => {
    render(<FolderImportOffer offer={3} checklistOpen={false} busy={false} onOpen={vi.fn()} variant="card" />);
    expect(screen.getByRole("button", { name: /Keep my folders/ })).toBeTruthy();
  });

  it("does not render while the checklist is already open, even with a positive offer", () => {
    render(<FolderImportOffer offer={3} checklistOpen busy={false} onOpen={vi.fn()} variant="strip" />);
    expect(screen.queryByRole("button", { name: /Keep my folders/ })).toBeNull();
  });
});

describe("FolderImportChecklist — FR-33 row disclosure", () => {
  /** Renders the checklist directly (no hook) so each row's meta text can be read in isolation.
   *  `rowsFrom` is the real mapper, so `name`/`valid` are derived exactly as the host derives them. */
  function renderRows(cands: FolderImportCandidate[]) {
    render(
      <FolderImportChecklist
        rows={rowsFrom(cands)}
        busy={false}
        onToggle={vi.fn()}
        onRename={vi.fn()}
        onCancel={vi.fn()}
        onApply={vi.fn()}
        variant="card"
      />,
    );
  }

  it("promises unconditionally in the intro — no move warning, because `dir` makes the folder the home", () => {
    renderRows([candidate({ folder: "Work", suggested: "Work" })]);
    expect(screen.getByText(/Your folders keep their names, and nothing moves/)).toBeTruthy();
    expect(screen.queryByText(/will still be offered a move later/)).toBeNull();
  });

  it("a sanitised folder states the tag and that the folder is unchanged", () => {
    renderRows([candidate({ folder: "My Notes", suggested: "My-Notes", valid: false })]);
    expect(screen.getByText(/tagged My-Notes, folder unchanged/)).toBeTruthy();
    expect(screen.queryByText(/move into it/)).toBeNull();
  });

  it("★ joining a project under a DIFFERENT name warns that the notes move — the one case that still moves files", () => {
    // `dir` is written on create only, never on join (vault_admin `_register`), so this folder's
    // notes really do move into the existing project's own home.
    renderRows([candidate({ folder: "My Notes", suggested: "Recipes", valid: false, existing: true })]);
    expect(screen.getByText(/joins existing project — these notes move into it/)).toBeTruthy();
  });

  it("joining a project of its own name is already home, so it carries no move warning", () => {
    renderRows([candidate({ folder: "Recipes", suggested: "Recipes", existing: true })]);
    expect(screen.getByText(/joins existing project/)).toBeTruthy();
    expect(screen.queryByText(/move into it/)).toBeNull();
  });
});

describe("useFolderImport + FolderImportChecklist — consent and apply", () => {
  it("ticking one of two folders and applying calls applyFolderImport with exactly that selection", async () => {
    vi.mocked(api.getFolderImportPreview).mockResolvedValue({
      count: 2,
      folders: [
        candidate({ folder: "research", suggested: "research", valid: true, count: 4 }),
        candidate({ folder: "kitchen-remodel", suggested: "kitchen-remodel", valid: true, count: 2 }),
      ],
    });
    vi.mocked(api.applyFolderImport).mockResolvedValue({ tagged: 4, registered: ["research"], skipped: [] });

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "probe" }));
    const offerBtn = await screen.findByRole("button", { name: /Keep my folders/ });
    fireEvent.click(offerBtn);

    // Both rows start ticked (both names are already valid) -- untick the one NOT under test
    // so the apply call's selection is unambiguous.
    const kitchenCheckbox = (await screen.findByText("kitchen-remodel")).parentElement!.querySelector(
      'input[type="checkbox"]',
    ) as HTMLInputElement;
    fireEvent.click(kitchenCheckbox); // untick

    fireEvent.click(screen.getByRole("button", { name: /Add tags to 4 notes/ }));

    await vi.waitFor(() =>
      expect(api.applyFolderImport).toHaveBeenCalledWith([{ folder: "research", name: "research" }]),
    );
  });

  it("a successful apply clears the checklist and fires onApplied", async () => {
    vi.mocked(api.getFolderImportPreview).mockResolvedValue({
      count: 1,
      folders: [candidate({ folder: "research", suggested: "research", valid: true, count: 4 })],
    });
    vi.mocked(api.applyFolderImport).mockResolvedValue({ tagged: 4, registered: ["research"], skipped: [] });
    const onApplied = vi.fn();

    render(<Harness onApplied={onApplied} />);
    fireEvent.click(screen.getByRole("button", { name: "probe" }));
    fireEvent.click(await screen.findByRole("button", { name: /Keep my folders/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Add tags to 4 notes/ }));

    await vi.waitFor(() => expect(onApplied).toHaveBeenCalled());
    expect(screen.queryByText("research")).toBeNull(); // checklist gone
    expect(screen.queryByRole("button", { name: /Keep my folders/ })).toBeNull(); // offer re-zeroed
  });

  it("an invalid folder name renders an editable, prefilled field, and Apply stays disabled until a valid ticked name exists", async () => {
    vi.mocked(api.getFolderImportPreview).mockResolvedValue({
      count: 1,
      folders: [candidate({ folder: "My Trip!", suggested: "", valid: false, count: 3 })],
    });

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "probe" }));
    fireEvent.click(await screen.findByRole("button", { name: /Keep my folders/ }));

    await screen.findByText("My Trip!");
    const nameInput = screen.getByPlaceholderText("project name") as HTMLInputElement;
    expect(nameInput.value).toBe(""); // the "nothing usable survives" case -- blank, never a guess

    const applyBtn = screen.getByRole("button", { name: /^Add tags to/ });
    expect(applyBtn).toHaveProperty("disabled", true); // nothing checked/valid yet

    const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(checkbox).toHaveProperty("disabled", true); // can't consent to an unusable name

    fireEvent.change(nameInput, { target: { value: "trip-japan" } });
    expect(applyBtn).toHaveProperty("disabled", true); // typed valid, but not yet ticked
    expect(checkbox).toHaveProperty("disabled", false); // now tickable

    fireEvent.click(checkbox);
    expect(applyBtn).toHaveProperty("disabled", false);
    expect(applyBtn.textContent).toMatch(/Add tags to 3 notes/);

    fireEvent.click(applyBtn);
    await vi.waitFor(() =>
      expect(api.applyFolderImport).toHaveBeenCalledWith([{ folder: "My Trip!", name: "trip-japan" }]),
    );
  });

  it("a failed probe is never silent -- it logs, but still leaves the offer at 0 (no button)", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(api.getFolderImportPreview).mockRejectedValue(new Error("network down"));

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "probe" }));

    await vi.waitFor(() => expect(consoleSpy).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Keep my folders/ })).toBeNull();
    consoleSpy.mockRestore();
  });
});

import { describe, it, expect } from "vitest";
import {
  FOLDER_CATALOG,
  DEFAULT_SELECTED,
  MAX_STARTER_FOLDERS,
  toggleFolderSelection,
  isFirstRun,
  nextStep,
  prevStep,
  totalVisibleSteps,
  visibleStepNumber,
  canAdvance,
  buildFoldersPayload,
  catalogDescription,
} from "./vaultSetup";

describe("toggleFolderSelection", () => {
  it("adds a folder not yet selected", () => {
    expect(toggleFolderSelection(["Work"], "Personal")).toEqual(["Work", "Personal"]);
  });

  it("removes a folder already selected", () => {
    expect(toggleFolderSelection(["Work", "Personal"], "Work")).toEqual(["Personal"]);
  });

  it("caps selection at MAX_STARTER_FOLDERS (5) -- selecting past the cap is a no-op", () => {
    const five = FOLDER_CATALOG.slice(0, 5).map((f) => f.name);
    expect(five).toHaveLength(MAX_STARTER_FOLDERS);
    const result = toggleFolderSelection(five, "Journal");
    expect(result).toEqual(five); // unchanged -- Journal never added
    expect(result).toHaveLength(MAX_STARTER_FOLDERS);
  });

  it("deselecting below the cap frees a slot for a new pick", () => {
    const five = FOLDER_CATALOG.slice(0, 5).map((f) => f.name);
    const four = toggleFolderSelection(five, five[0]);
    expect(four).toHaveLength(4);
    const withJournal = toggleFolderSelection(four, "Journal");
    expect(withJournal).toContain("Journal");
    expect(withJournal).toHaveLength(5);
  });

  it("DEFAULT_SELECTED is exactly the 5 user-named starter folders", () => {
    expect(DEFAULT_SELECTED).toEqual(["Work", "Personal", "Research", "Finance", "Tasks"]);
  });
});

describe("isFirstRun", () => {
  it("true when [vault] root is absent", () => {
    expect(isFirstRun({})).toBe(true);
    expect(isFirstRun({ vault: {} })).toBe(true);
    expect(isFirstRun({ vault: { root: "" } })).toBe(true);
  });

  it("false when a vault root is configured", () => {
    expect(isFirstRun({ vault: { root: "C:/Users/you/Vault" } })).toBe(false);
  });
});

describe("step navigation -- existing vault skips the folder step", () => {
  it("fresh vault: location -> folders -> ready", () => {
    expect(nextStep("location", false)).toBe("folders");
    expect(nextStep("folders", false)).toBe("ready");
    expect(prevStep("ready", false)).toBe("folders");
    expect(prevStep("folders", false)).toBe("location");
  });

  it("existing vault: location -> ready directly, folders never shown", () => {
    expect(nextStep("location", true)).toBe("ready");
    expect(prevStep("ready", true)).toBe("location");
  });

  it("totalVisibleSteps/visibleStepNumber fold the skipped step out of the count", () => {
    expect(totalVisibleSteps(false)).toBe(3);
    expect(totalVisibleSteps(true)).toBe(2);
    expect(visibleStepNumber("location", true)).toBe(1);
    expect(visibleStepNumber("ready", true)).toBe(2);
    expect(visibleStepNumber("location", false)).toBe(1);
    expect(visibleStepNumber("folders", false)).toBe(2);
    expect(visibleStepNumber("ready", false)).toBe(3);
  });
});

describe("canAdvance", () => {
  it("blocks the folders step with zero selections", () => {
    expect(canAdvance("folders", 0)).toBe(false);
    expect(canAdvance("folders", 1)).toBe(true);
  });

  it("never blocks location or ready", () => {
    expect(canAdvance("location", 0)).toBe(true);
    expect(canAdvance("ready", 0)).toBe(true);
  });
});

describe("buildFoldersPayload", () => {
  it("uses the catalog description when the user never edited it", () => {
    const payload = buildFoldersPayload(["Work"], {});
    expect(payload).toEqual([{ name: "Work", description: catalogDescription("Work") }]);
  });

  it("uses the user's edited description when present", () => {
    const payload = buildFoldersPayload(["Work"], { Work: "Custom routing text." });
    expect(payload).toEqual([{ name: "Work", description: "Custom routing text." }]);
  });

  it("falls back to the catalog description for a blank/whitespace edit", () => {
    const payload = buildFoldersPayload(["Work"], { Work: "   " });
    expect(payload).toEqual([{ name: "Work", description: catalogDescription("Work") }]);
  });

  it("preserves selection order and covers every catalog entry", () => {
    expect(FOLDER_CATALOG).toHaveLength(10);
    const names = ["Journal", "Work"];
    const payload = buildFoldersPayload(names, {});
    expect(payload.map((p) => p.name)).toEqual(names);
  });
});

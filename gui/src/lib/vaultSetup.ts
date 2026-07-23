/**
 * vaultSetup.ts
 * -------------
 * Pure step/selection logic for the first-run vault-setup wizard (ISS-002 /
 * P-WIZARD). No side effects, no fetches, no React — VaultSetup.tsx fetches,
 * commits, and renders; everything decidable from plain data lives here. See
 * sibling vaultSetup.test.ts.
 *
 * The 10-folder catalog is a SEED LIST only — picking from it just pre-fills
 * a folder name + starter routing description for POST /vault/setup to
 * create on disk. It never becomes a hardcoded category enum: models.py's
 * category enum is built live from whatever folders exist in the vault at
 * capture time (CLAUDE.md hard rule), same as any folder the user creates
 * by hand later in Library -> Vault.
 */

export interface CatalogFolder {
  name: string;
  description: string;
}

// Copy verbatim from INTEGRATION-FIX-PLAN-2026-07-22.md's P-WIZARD entry —
// Work/Personal/Research/Finance/Tasks are the user-named starter set,
// Ideas/Reading/Health/Projects/Journal are the agent-proposed remainder.
export const FOLDER_CATALOG: CatalogFolder[] = [
  { name: "Work", description: "Job, meetings, work projects, and professional documents." },
  { name: "Personal", description: "Personal life, household, and everyday notes." },
  { name: "Research", description: "Findings, sources, and deep-dive notes on topics you study." },
  { name: "Finance", description: "Money, bills, receipts, budgets, and investments." },
  { name: "Tasks", description: "To-dos, action items, and things to follow up on." },
  { name: "Ideas", description: "Sparks, brainstorms, and things to explore later." },
  { name: "Reading", description: "Articles, links, and things to read or watch." },
  { name: "Health", description: "Fitness, medical, wellbeing, and habits." },
  { name: "Projects", description: "Ongoing initiatives with a goal or deliverable." },
  { name: "Journal", description: "Daily entries, reflections, and logs." },
];

/** Mock's default preselection: the first 5 (the user-named set). */
export const DEFAULT_SELECTED = FOLDER_CATALOG.slice(0, 5).map((f) => f.name);

export const MAX_STARTER_FOLDERS = 5;

export function catalogDescription(name: string): string {
  return FOLDER_CATALOG.find((f) => f.name === name)?.description ?? "";
}

/** Toggle *name* in/out of *selected*, capped at *max* — selecting past the
 *  cap is a no-op (the mock disables the tile instead of erroring). */
export function toggleFolderSelection(
  selected: string[],
  name: string,
  max: number = MAX_STARTER_FOLDERS,
): string[] {
  if (selected.includes(name)) return selected.filter((n) => n !== name);
  if (selected.length >= max) return selected;
  return [...selected, name];
}

// ── First-run detection ──────────────────────────────────────────────────

/** Minimal shape of GET /config's `[vault]` section this predicate needs. */
export interface ConfigVaultShape {
  vault?: { root?: string };
}

/** True exactly when `[vault] root` is absent from config -- the server's
 *  own distinction between a configured root and a resolved-but-unset
 *  default (SettingsPanel.tsx already relies on the same absence check). */
export function isFirstRun(config: ConfigVaultShape): boolean {
  return !config.vault?.root;
}

// ── Step navigation (existing-vault-at-path skips the folder step) ───────

export type WizardStep = "location" | "folders" | "ready";

export function nextStep(step: WizardStep, existingVaultFound: boolean): WizardStep {
  if (step === "location") return existingVaultFound ? "ready" : "folders";
  return "ready";
}

export function prevStep(step: WizardStep, existingVaultFound: boolean): WizardStep {
  if (step === "ready") return existingVaultFound ? "location" : "folders";
  return "location";
}

/** Total number of steps actually shown to the user (mock's `paneCount()`). */
export function totalVisibleSteps(existingVaultFound: boolean): number {
  return existingVaultFound ? 2 : 3;
}

/** 1-indexed position of *step* among the steps actually shown (mock's
 *  "Step X of Y" footer note, which folds the skipped folder step out of
 *  the count on the existing-vault branch). */
export function visibleStepNumber(step: WizardStep, existingVaultFound: boolean): number {
  if (existingVaultFound) return step === "location" ? 1 : 2;
  return step === "location" ? 1 : step === "folders" ? 2 : 3;
}

export function canAdvance(step: WizardStep, selectedCount: number): boolean {
  if (step === "folders") return selectedCount > 0;
  return true;
}

// ── Building the POST /vault/setup payload ────────────────────────────────

export interface SetupFolderPayload {
  name: string;
  description: string;
}

/** *descriptions* holds any user edits keyed by folder name; falls back to
 *  the catalog's pre-written description for a name the user never touched
 *  (or picked but didn't edit). Every entry ships trimmed and non-empty so
 *  a fresh vault never has a description-less folder (ISS-002's root cause
 *  was exactly an empty category_descriptions dict reaching the LLM). */
export function buildFoldersPayload(
  selected: string[],
  descriptions: Record<string, string>,
): SetupFolderPayload[] {
  return selected.map((name) => {
    const edited = descriptions[name];
    const description = (edited && edited.trim()) || catalogDescription(name);
    return { name, description };
  });
}

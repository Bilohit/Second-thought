/**
 * FolderImportPanel.tsx — FR-32.
 *
 * FR-23 Option C ("keep my folders — add the tags") was wired into only ONE of the two
 * project-tidy confirm strips this product ships (VaultManager's full-window Vault panel).
 * `ProjectsPane` (the full-window Projects screen) grew its OWN, independent tidy-preview
 * probe that never called `getFolderImportPreview()`, so the offer never rendered there —
 * deleting/renaming a project from Vault ▸ Projects silently lost the repair entirely.
 *
 * The fix is this one shared module: a hook owning all of the import's state + API calls,
 * and two presentational components rendering it. Both hosts (VaultManager's bordered card,
 * ProjectsPane's full-bleed strip) call the SAME hook and render the SAME two components —
 * duplicating this UI a second time is exactly the condition that caused the bug, so it is
 * not an option here.
 *
 * THE ONLY PLACE THIS CLIENT WRITES A NOTE BODY OUTSIDE THE EDITOR is `apply()` below. It
 * runs only from the explicit per-folder confirmation `<FolderImportChecklist>` renders,
 * never automatically.
 */
import { useCallback, useState } from "react";
import type { CSSProperties } from "react";
import {
  getFolderImportPreview,
  applyFolderImport,
} from "../lib/api";
import {
  rowsFrom,
  rename as renameRow_,
  toggle as toggleRow_,
  selection,
  selectedNoteCount,
  type ImportRow,
} from "../lib/folderImport";
import { isValidProjectName, INVALID_NAME_MESSAGE } from "../lib/projectsView";
import { BTN_GHOST } from "./ui/styles";

// ── the hook ────────────────────────────────────────────────────────────────

export interface UseFolderImportOptions {
  /** Runs after a successful `apply()` — refetch whatever the host's own data is, then
   *  re-run the host's own tidy check (the tags just written are exactly what a pending
   *  tidy move was missing). */
  onApplied: () => void;
  /** Routed to the host's OWN error channel (`setActionError` in VaultManager,
   *  `setMutationError` in ProjectsPane) — never a third error surface. Both of those
   *  setters already accept `string | null`, so a host can pass its setter directly. */
  onError: (message: string | null) => void;
}

export interface UseFolderImportResult {
  /** How many untagged notes sit in named folders right now (0 = nothing to offer, so
   *  `<FolderImportOffer>` renders nothing). */
  offer: number;
  /** Non-null only while the per-folder checklist is open. */
  rows: ImportRow[] | null;
  busy: boolean;
  /** Best-effort probe — call this from the host's own tidy-preview check, the same
   *  moment that is the only honest place to offer this repair. NEVER silent on failure:
   *  a swallowed failure here makes the offer button simply not appear, indistinguishable
   *  from "nothing to import" — s140 lost a live-QA round to exactly that. */
  probe: () => void;
  /** Re-fetches (never reuses `offer`'s possibly-stale count) and opens the checklist. */
  open: () => Promise<void>;
  /** THE ONLY PLACE THIS CLIENT WRITES A NOTE BODY OUTSIDE THE EDITOR. Runs only from the
   *  explicit per-folder confirmation, never automatically. */
  apply: () => Promise<void>;
  /** Closes the checklist without applying anything. */
  close: () => void;
  toggleRow: (folder: string) => void;
  renameRow: (folder: string, name: string) => void;
}

export function useFolderImport({ onApplied, onError }: UseFolderImportOptions): UseFolderImportResult {
  const [offer, setOffer] = useState(0);
  const [rows, setRows] = useState<ImportRow[] | null>(null);
  const [busy, setBusy] = useState(false);

  const probe = useCallback(() => {
    getFolderImportPreview()
      .then((preview) => setOffer(preview.count))
      .catch((e) => console.error("[FolderImportPanel] folder-import preview failed:", e));
  }, []);

  const open = useCallback(async () => {
    onError(null);
    try {
      const preview = await getFolderImportPreview();
      setRows(rowsFrom(preview.folders));
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to read folders");
    }
  }, [onError]);

  const close = useCallback(() => setRows(null), []);

  const toggleRow = useCallback((folder: string) => {
    setRows((rs) => (rs ? toggleRow_(rs, folder) : rs));
  }, []);

  const renameRow = useCallback((folder: string, name: string) => {
    setRows((rs) => (rs ? renameRow_(rs, folder, name) : rs));
  }, []);

  const apply = useCallback(async () => {
    if (!rows) return;
    setBusy(true);
    onError(null);
    try {
      await applyFolderImport(selection(rows));
      setRows(null);
      setOffer(0);
      onApplied();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to import folder structure");
    } finally {
      setBusy(false);
    }
  }, [rows, onApplied, onError]);

  return { offer, rows, busy, probe, open, apply, close, toggleRow, renameRow };
}

// ── the two host skins ───────────────────────────────────────────────────────
//
// Two real callers, two real visual idioms (both shipped, both preserved byte-for-byte):
//  · "card"  — VaultManager's bordered surface-2 card (fontSize 11/12, BTN_GHOST buttons).
//  · "strip" — ProjectsPane's full-bleed border-bottom strip (fontSize 10/10.5, "pp-ghost"
//    buttons matching its own ghostBtnStyle/tidyPrimaryBtnStyle).

export type FolderImportVariant = "card" | "strip";

interface VariantStyle {
  container: CSSProperties;
  intro: CSSProperties;
  list: CSSProperties;
  row: CSSProperties;
  folderName: CSSProperties;
  meta: CSSProperties;
  nameInputValid: CSSProperties;
  nameInputInvalid: CSSProperties;
  actionsRow: CSSProperties;
  ghostBtn: CSSProperties;
  offerBtn: CSSProperties;
  primaryBtn: CSSProperties;
  btnClassName?: string;
}

const CARD_GHOST: CSSProperties = { ...BTN_GHOST, color: "var(--text-2)", fontSize: 12, padding: "5px 10px" };
const CARD_OFFER: CSSProperties = { ...BTN_GHOST, color: "var(--text-1)", fontSize: 12, padding: "5px 10px" };
const CARD_PRIMARY: CSSProperties = {
  padding: "5px 14px", fontSize: 12, fontWeight: 600, borderRadius: "var(--radius)",
  border: "1px solid var(--text-1)", background: "var(--bg)", color: "var(--text-1)", cursor: "pointer",
};

const STRIP_GHOST: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10, color: "var(--text-2)",
  border: "1px solid var(--border)", background: "var(--bg)", padding: "5px 9px", cursor: "pointer", fontFamily: "inherit",
};
const STRIP_OFFER: CSSProperties = { ...STRIP_GHOST, color: "var(--text-1)" };
const STRIP_PRIMARY: CSSProperties = { ...STRIP_GHOST, borderColor: "var(--text-1)", color: "var(--text-1)" };

const VARIANTS: Record<FolderImportVariant, VariantStyle> = {
  card: {
    container: {
      background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--radius)",
      padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8,
    },
    intro: { fontSize: 12, color: "var(--text-2)" },
    list: {
      display: "flex", flexDirection: "column", gap: 2, maxHeight: 160, overflowY: "auto",
      border: "1px solid var(--border)", background: "var(--bg)", padding: "4px 8px",
    },
    row: { display: "flex", alignItems: "center", gap: 8, fontSize: 11, padding: "3px 0" },
    folderName: {
      flex: "0 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
      whiteSpace: "nowrap", color: "var(--text-1)",
    },
    meta: { marginLeft: "auto", flex: "0 0 auto", color: "var(--text-3)", textAlign: "right" },
    nameInputValid: {
      flex: "0 1 130px", minWidth: 0, fontSize: 11, padding: "2px 6px", fontFamily: "inherit",
      background: "var(--surface-2)", color: "var(--text-1)", border: "1px solid var(--border)", borderRadius: "var(--radius)",
    },
    nameInputInvalid: {
      flex: "0 1 130px", minWidth: 0, fontSize: 11, padding: "2px 6px", fontFamily: "inherit",
      background: "var(--surface-2)", color: "var(--text-1)", border: "1px solid var(--red)", borderRadius: "var(--radius)",
    },
    actionsRow: { display: "flex", justifyContent: "flex-end", gap: 6 },
    ghostBtn: CARD_GHOST,
    offerBtn: CARD_OFFER,
    primaryBtn: CARD_PRIMARY,
    btnClassName: "btn-hover",
  },
  strip: {
    container: {
      flex: "0 0 auto", borderBottom: "1px solid var(--border)", background: "var(--ctl-face)",
      padding: "9px 16px", display: "flex", flexDirection: "column", gap: 8,
    },
    intro: { fontSize: 10.5, color: "var(--text-2)" },
    list: {
      display: "flex", flexDirection: "column", gap: 2, maxHeight: 160, overflowY: "auto",
      border: "1px solid var(--border)", background: "var(--bg)", padding: "4px 8px",
    },
    row: { display: "flex", alignItems: "center", gap: 8, fontSize: 10, padding: "3px 0" },
    folderName: {
      flex: "0 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
      whiteSpace: "nowrap", color: "var(--text-1)",
    },
    meta: { marginLeft: "auto", flex: "0 0 auto", color: "var(--text-3)", textAlign: "right" },
    nameInputValid: {
      flex: "0 1 130px", minWidth: 0, fontSize: 10, padding: "2px 6px", fontFamily: "inherit",
      background: "var(--ctl-face)", color: "var(--text-1)", border: "1px solid var(--border)",
    },
    nameInputInvalid: {
      flex: "0 1 130px", minWidth: 0, fontSize: 10, padding: "2px 6px", fontFamily: "inherit",
      background: "var(--ctl-face)", color: "var(--text-1)", border: "1px solid var(--red)",
    },
    actionsRow: { display: "flex", justifyContent: "flex-end", gap: 6 },
    ghostBtn: STRIP_GHOST,
    offerBtn: STRIP_OFFER,
    primaryBtn: STRIP_PRIMARY,
    btnClassName: "pp-ghost",
  },
};

// ── the offer button ─────────────────────────────────────────────────────────
//
// Design lock A1: the offer lives INSIDE the tidy strip's own action row, never a settings
// row a user never opens — both hosts render this as a sibling of their "Not now"/"Move
// files" buttons, not as a separate surface.

export interface FolderImportOfferProps {
  offer: number;
  /** True while the checklist is already open — the offer button is the OTHER answer to
   *  the same strip, not something that coexists with the checklist it opens. */
  checklistOpen: boolean;
  busy: boolean;
  onOpen: () => void;
  variant: FolderImportVariant;
}

export function FolderImportOffer({ offer, checklistOpen, busy, onOpen, variant }: FolderImportOfferProps) {
  if (offer <= 0 || checklistOpen) return null;
  const s = VARIANTS[variant];
  return (
    <button onClick={onOpen} disabled={busy} className={s.btnClassName} style={s.offerBtn}>
      Keep my folders — add the tags
    </button>
  );
}

// ── the per-folder checklist ─────────────────────────────────────────────────
//
// Per-folder consent: nothing applies without a tick and a click. An unusable folder name
// gets an EDITABLE field prefilled with a suggestion — never a dead end, never a silent
// rename.

export interface FolderImportChecklistProps {
  rows: ImportRow[];
  busy: boolean;
  onToggle: (folder: string) => void;
  onRename: (folder: string, name: string) => void;
  onCancel: () => void;
  onApply: () => void;
  variant: FolderImportVariant;
}

export function FolderImportChecklist({
  rows, busy, onToggle, onRename, onCancel, onApply, variant,
}: FolderImportChecklistProps) {
  const s = VARIANTS[variant];
  return (
    <div style={s.container}>
      <span style={s.intro}>
        {"Each folder becomes a project by adding one "}
        <strong style={{ color: "var(--text-1)" }}>#project@name</strong>
        {/* FR-33 made this an unconditional promise rather than a warning. A project name cannot
            contain a space (a `#hashtag` ends at the first whitespace, projects.py:27), so a folder
            `My Notes` is still TAGGED `My-Notes` -- but the registry now records `dir = "My Notes"`
            (contract §13.1 v3.2), so that folder IS the project's home and nothing is planned to
            move. The old copy warned about a move that no longer happens; a warning the product
            then contradicts is worse than none. The one case where files DO still move is a folder
            joining a project that already lives elsewhere -- said on that row, not here. */}
        {" line to the notes inside it. Your folders keep their names, and nothing moves."}
      </span>
      <div style={s.list}>
        {rows.length === 0 && (
          <span style={{ fontSize: 11, color: "var(--text-3)", padding: "4px 0" }}>
            No folders left to import — every note in a named folder already carries a project tag.
          </span>
        )}
        {rows.map((row) => (
          <div key={row.folder} style={s.row}>
            <input
              type="checkbox"
              checked={row.checked}
              disabled={!row.valid || busy}
              onChange={() => onToggle(row.folder)}
              style={{ flex: "0 0 auto", accentColor: "var(--text-1)" }}
            />
            <span style={s.folderName}>{row.folder}</span>
            {!isValidProjectName(row.folder) && (
              <input
                value={row.name}
                disabled={busy}
                placeholder="project name"
                onChange={(e) => onRename(row.folder, e.target.value)}
                style={row.valid ? s.nameInputValid : s.nameInputInvalid}
              />
            )}
            <span style={s.meta}>
              {row.count} {row.count === 1 ? "note" : "notes"}
              {row.phoneCount > 0 && ` · includes ${row.phoneCount} from your phone`}
              {/* FR-33: the ONLY case where this import still causes a file move. Joining a project
                  that already exists means the registry keeps ITS home -- `dir` is set on create
                  only, never on join, because overwriting it would relocate notes the user never
                  discussed (vault_admin.py's `_register`). So when the folder's name differs from
                  the project it joins, these notes really do move into that project's folder. A
                  folder joining a project of its OWN name is already home; no warning there.
                  ponytail: `existing` is computed against the SUGGESTED name at preview time and
                  is not re-checked after the user edits the field, so typing the name of an
                  existing project by hand shows no warning -- upgrade path is returning the
                  registry's names with the preview and testing `row.name` against them. */}
              {row.existing && (row.folder === row.name
                ? " · joins existing project"
                : " · joins existing project — these notes move into it")}
              {/* FR-32/FR-33: attached to the one folder it concerns, gated on the SAME condition
                  as the editable name field above, so it appears only where the app had to change
                  the name and never on an ordinary row. Now a statement of fact, not a caveat. */}
              {!isValidProjectName(row.folder) && !row.existing &&
                ` · tagged ${row.name || "…"}, folder unchanged`}
              {!row.valid && ` · ${INVALID_NAME_MESSAGE}`}
            </span>
          </div>
        ))}
      </div>
      <div style={s.actionsRow}>
        <button onClick={onCancel} disabled={busy} className={s.btnClassName} style={s.ghostBtn}>
          Cancel
        </button>
        <button
          onClick={onApply}
          disabled={busy || selectedNoteCount(rows) === 0}
          className={s.btnClassName}
          style={s.primaryBtn}
        >
          {busy ? "Adding…" : `Add tags to ${selectedNoteCount(rows)} notes`}
        </button>
      </div>
    </div>
  );
}

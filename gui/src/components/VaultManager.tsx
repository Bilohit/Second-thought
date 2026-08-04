/**
 * VaultManager.tsx
 * ----------------
 * Full-screen overlay for browsing and managing vault folders.
 *
 * Features
 *  · Lists every top-level directory under the vault root as a card
 *  · Shows per-folder .md file count
 *  · Create / rename / delete PROJECTS (registry entries, never notes)
 *  · Drill into a folder to see its .md files with sizes + dates
 *  · All mutations go through the Python server's /vault/* REST endpoints
 *
 * Renders as an opaque instrument face (var(--glass-bg), no blur) rather
 * than a decorative glass card — this is a full-window panel visited
 * deliberately, not a HUD floating over the live desktop. See DESIGN.md
 * §5 "Full-Window Panels".
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { openVaultPath } from "../lib/api";
import { BellIcon, ClockIcon, WarningTriangleIcon } from "./PillMenu/icons";
import {
  getVaultFolders,
  createProject,
  renameProject,
  deleteProject,
  updateProjectDescription,
  getVaultFolderFiles,
  getProvisional,
  getVaultConflicts,
  createReminder,
  getSyncIgnore,
  setSyncIgnore,
  moveToTrash,
  getTidyPreview,
  applyTidy,
  type VaultFolder,
  type VaultFile,
  type ProvisionalItem,
  type TidyMove,
} from "../lib/api";
import { mergeProvisional, type CanonicalNoteRow } from "../lib/provisional";
import { middleEllipsis } from "../lib/middleEllipsis";
import { describeTidyMove } from "../lib/projectsView";
import { useFolderImport, FolderImportOffer, FolderImportChecklist } from "./FolderImportPanel";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  INPUT_STYLE, BTN_GHOST, ROW_CARD, ROW_DIVIDER,
  focusRing, blurRing,
} from "./ui/styles";
import { MenuIcon } from "./PillMenu/icons";

// `_scratchpad` is a real vault folder (still returned by GET
// /vault/folders, by design) — this relabels it for display only. The
// underlying identity used for every API call (drill-in, delete, etc.)
// stays `cat.name` ("_scratchpad"); only the rendered text changes.
function folderDisplayName(name: string): string {
  // s114/D10: one name for the review queue across both shells. This surface said "Needs review",
  // the desktop panel said "Inbox", and the phone said "Needs review" — three surfaces, two words
  // for one concept (council/copy). "Inbox" is now the single term everywhere.
  return name === "_scratchpad" ? "Inbox" : name;
}

// ISS-026: budget the vault-path header to a single legible line at
// 125%/150% display scale instead of CSS `wordBreak: break-all` (which
// wrapped mid-word, e.g. "STORA/GE"). Char counts are a pragmatic estimate
// for the embedded (has flex room) vs. full-window (fixed max-width) header,
// not a pixel-measured value — the orchestrator's CDP pass at 736/613px is
// the actual verification of these numbers.
const PATH_MAX_CHARS_EMBEDDED = 56;
const PATH_MAX_CHARS_FULL = 26;

interface Props {
  visible: boolean;
  onClose: () => void;
  /** Set by App when a search result should open directly into a folder's file list. */
  openResult?: { project: string; path: string } | null;
  /** Called once openResult has been consumed, so App can clear it. */
  onConsumeOpenResult?: () => void;
  measureRef?: (el: HTMLDivElement | null) => void;
  embedded?: boolean;
  /** Compact Mode Menu Decoupling (B3): distinct from `embedded` — Full's
   *  LibraryView also passes `embedded`, so this is the flag that actually
   *  means "hosted inside a CompactShell panel." Hides the vault-root path
   *  string and moves the top-level action buttons (open folder / refresh /
   *  new project) out of this component's own header via
   *  `onHeaderActionsChange`, so CompactShell's header can render them
   *  instead of duplicating a second header row. Full-window usage never
   *  sets this, so its render is unaffected. */
  compactHeader?: boolean;
  /** Only consulted while `compactHeader` is true — receives the current
   *  action-button cluster (or `null` on unmount/target switch) so the
   *  caller can forward it into `CompactShell`'s `headerActions` slot. */
  onHeaderActionsChange?: (actions: React.ReactNode | null) => void;
  /** F-7 follow-up: opens a file in the full-window NoteEditor. Full-window
   *  only (FullWindow threads this from its own `setEditorPath`) — omitted
   *  in compact-mode usage, where rows keep the external-open behaviour. */
  onOpenNote?: (path: string) => void;
}

// ── Folder card ───────────────────────────────────────────────────────────────

interface FolderCardProps {
  cat: VaultFolder;
  onDrillIn: (name: string) => void;
  onRename: (name: string) => void;
  onEditDescription: (name: string, current: string | null) => void;
  confirming: boolean;
  onRequestDelete: (name: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (name: string, count: number) => void;
}

function FolderCard({
  cat, onDrillIn, onRename, onEditDescription,
  confirming, onRequestDelete, onCancelDelete, onConfirmDelete,
}: FolderCardProps) {
  const isSystem = cat.name.startsWith("_");
  const displayName = folderDisplayName(cat.name);

  return (
    <div
      className={confirming ? undefined : "row-hover-lift"}
      style={{
        ...ROW_CARD,
        display: "flex",
        flexDirection: "column",
        cursor: confirming ? "default" : "pointer",
      }}
      onClick={() => !confirming && onDrillIn(cat.name)}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, opacity: confirming ? 0.5 : 1, transition: "opacity 0.18s" }}>
        {/* Folder icon */}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={isSystem ? "var(--text-3)" : "var(--accent)"} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
        </svg>

        {/* Name + count + description. ISS-026: minWidth keeps the name
            readable (not squeezed to an unreadable stub like ".omni_c…")
            at 125%/150% display scale — it wins width priority over the
            (fixed-width) actions cluster and the vault-path header above. */}
        <div style={{ flex: "1 1 auto", minWidth: 72 }}>
          <div style={{
            fontSize: 12, fontWeight: 500,
            color: isSystem ? "var(--text-3)" : "var(--text-1)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {displayName}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 1 }}>
            {cat.file_count} {cat.file_count === 1 ? "note" : "notes"}
          </div>
          {cat.description && (
            <div style={{
              fontSize: 10,
              color: "color-mix(in srgb, var(--accent) 70%, var(--text-2))",
              marginTop: 3,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              maxWidth: "100%",
            }}>
              {cat.description}
            </div>
          )}
        </div>

        {/* Actions (stop click bubbling) */}
        <div
          style={{ display: "flex", gap: 2, flexShrink: 0, pointerEvents: confirming ? "none" : "auto" }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Edit description */}
          <button
            className="btn-hover"
            style={BTN_GHOST}
            title={cat.description ? "Edit description" : "Add LLM routing description"}
            aria-label={cat.description ? "Edit description" : "Add LLM routing description"}
            onClick={() => onEditDescription(cat.name, cat.description)}
          >
            {/* Pencil icon */}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
            </svg>
          </button>
          {/* Rename */}
          <button
            className="btn-hover"
            style={BTN_GHOST}
            title="Rename"
            aria-label="Rename project"
            onClick={() => onRename(cat.name)}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </button>
          {/* Delete */}
          <button
            className="btn-hover hover-danger"
            style={BTN_GHOST}
            title="Delete"
            aria-label="Delete project"
            onClick={() => onRequestDelete(cat.name)}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6l-1 14H6L5 6" />
              <path d="M10 11v6M14 11v6" />
              <path d="M9 6V4h6v2" />
            </svg>
          </button>
        </div>
      </div>

      {/* Inline delete confirmation — expands downward from this row */}
      {confirming && (
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            marginTop: 10,
            background: "color-mix(in srgb, var(--red) 8%, transparent)",
            border: "1px solid color-mix(in srgb, var(--red) 25%, var(--border))",
            borderRadius: "var(--radius)",
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
            animation: "fadeIn 0.2s cubic-bezier(0.16,1,0.3,1) both",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>
            Delete <strong style={{ color: "var(--text-1)" }}>{displayName}</strong>?
            {cat.file_count > 0 && (
              <> It contains <strong style={{ color: "var(--yellow)" }}>{cat.file_count} file{cat.file_count !== 1 ? "s" : ""}</strong>.</>
            )}
          </span>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
            <button
              onClick={onCancelDelete}
              className="btn-hover"
              style={{ ...BTN_GHOST, color: "var(--text-2)", fontSize: 12, padding: "5px 10px" }}
            >
              Cancel
            </button>
            <button
              onClick={() => onConfirmDelete(cat.name, cat.file_count)}
              style={{
                padding: "5px 14px", fontSize: 12, fontWeight: 600, borderRadius: "var(--radius)",
                border: "none", background: "var(--red)", color: "var(--on-accent)", cursor: "pointer",
              }}
            >
              {cat.file_count > 0 ? "Delete anyway" : "Delete"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── File list row ─────────────────────────────────────────────────────────────

// F-5: dashed ghost dot = local-only sync-ignore, matching the phone's visual
// language exactly (NoteRow.tsx T4 "ghost dot": dashed text-3 ring, transparent
// fill, 10px so the dashes stay legible) -- a filled state color would lie
// about a note that never syncs.
function GhostDot({ ignored, onClick }: { ignored: boolean; onClick: () => void }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      title={ignored ? "Sync-ignored — local only. Click to re-enable sync." : "Synced. Click to make this note local-only."}
      aria-label={ignored ? "Sync-ignored — local only. Click to re-enable sync." : "Synced. Click to make this note local-only."}
      aria-pressed={ignored}
      style={{
        width: 14, height: 14, flexShrink: 0, padding: 0,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        background: "none", border: "none", cursor: "pointer",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: 10, height: 10, borderRadius: "50%",
          border: `1.3px dashed var(--text-3)`,
          background: "transparent",
          opacity: ignored ? 1 : 0.3,
          transition: "opacity 0.15s",
        }}
      />
    </button>
  );
}

function FileRow({
  file, highlighted, hasConflict, ignored, rowsReady, confirmingDelete,
  onOpen, onRemind, onToggleIgnore, onRequestDelete, onCancelDelete, onConfirmDelete,
}: {
  file: VaultFile;
  highlighted?: boolean;
  hasConflict?: boolean;
  ignored?: boolean;
  /** ISS-036: false for the one render right after this list (re)populates —
   *  see the `rowsReady` effect in VaultManager for why the open handler is
   *  withheld until settled. */
  rowsReady: boolean;
  confirmingDelete?: boolean;
  onOpen?: (path: string) => void;
  onRemind?: (file: VaultFile) => void;
  onToggleIgnore?: (file: VaultFile) => void;
  onRequestDelete?: (file: VaultFile) => void;
  onCancelDelete?: () => void;
  onConfirmDelete?: (file: VaultFile) => void;
}) {
  const kb = (file.size_bytes / 1024).toFixed(1);
  const date = new Date(file.modified * 1000).toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
  const openEnabled = !!onOpen && rowsReady && !confirmingDelete;

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div
        className={confirmingDelete ? undefined : "row-hover-flat"}
        onClick={openEnabled ? () => onOpen!(file.path) : undefined}
        style={{
          ...ROW_DIVIDER,
          margin: "0 -6px",
          padding: "7px 6px",
          borderRadius: "var(--radius-sm)",
          cursor: openEnabled ? "pointer" : undefined,
          opacity: confirmingDelete ? 0.5 : 1,
          transition: "opacity 0.18s",
          // The highlight flash owns `background`/`transition` inline (and
          // therefore wins over the hover class's CSS) only while it's
          // actually playing — at rest those properties are left to
          // .row-hover-flat so the bold hover tint isn't shadowed by an
          // always-on inline background.
          ...(highlighted
            ? { background: "var(--accent-d)", transition: "background 0.6s ease-out" }
            : {}),
        }}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <span style={{ flex: 1, fontSize: 12, color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {file.name}
        </span>
        {hasConflict && (
          <span title="Conflicted copy exists" style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--red)", flexShrink: 0 }} />
        )}
        {onToggleIgnore && (
          <GhostDot ignored={!!ignored} onClick={() => onToggleIgnore(file)} />
        )}
        {/* Task 2.6: server-authoritative name-clash. hub_name is the note's
            STORED (suffixed) filename it would resolve to on the hub — shown
            as-is in the row's meta text, yellow, no left icon / row tint. */}
        {file.name_clash && (
          <span
            title={file.hub_name}
            style={{
              fontSize: 10, color: "var(--yellow)", whiteSpace: "nowrap",
              overflow: "hidden", textOverflow: "ellipsis",
              // Row is a single nowrap flex line (ROW_DIVIDER, gap 8, no wrap) —
              // this is the one variable-width addition to it, so it needs its
              // own shrink + cap or a long suffixed filename pushes the KB/date/
              // remind/warning-icon cluster past the row's right edge instead of
              // truncating in place.
              flexShrink: 1, minWidth: 0, maxWidth: 140,
            }}
          >
            {file.hub_name}
          </span>
        )}
        <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{kb} KB</span>
        <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{date}</span>
        {/* Wave 6 (O-8c): row-hover affordance — chevron nudges 2px on hover
            (150ms), riding the row's own .row-hover-flat recipe. */}
        {openEnabled && (
          <span aria-hidden="true" className="file-row-chevron" style={{ display: "inline-flex" }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 18l6-6-6-6" />
            </svg>
          </span>
        )}
        {onRemind && (
          <button
            className="btn-hover"
            style={{ ...BTN_GHOST, flexShrink: 0 }}
            title="Remind me"
            aria-label="Remind me"
            onClick={(e) => { e.stopPropagation(); onRemind(file); }}
          >
            <BellIcon size={12} />
          </button>
        )}
        {/* Bare warning triangle at the row's right edge — no text label, no tint. */}
        {file.name_clash && (
          <span
            role="img"
            aria-label="Filename clash — rename this note"
            title="Filename clash — rename this note"
            style={{ display: "inline-flex", flexShrink: 0, color: "var(--yellow)" }}
          >
            <WarningTriangleIcon size={12} />
          </span>
        )}
        {/* ISS-005: desktop delete affordance — moves the note into the
            existing 30-day trash (see moveToTrash in lib/api.ts). Restore
            plumbing already exists on the Trash tab. */}
        {onRequestDelete && (
          <button
            className="btn-hover hover-danger"
            style={{ ...BTN_GHOST, flexShrink: 0 }}
            title="Move to trash"
            aria-label="Move to trash"
            onClick={(e) => { e.stopPropagation(); onRequestDelete(file); }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6l-1 14H6L5 6" />
              <path d="M10 11v6M14 11v6" />
              <path d="M9 6V4h6v2" />
            </svg>
          </button>
        )}
      </div>

      {/* Inline delete confirmation — same pattern as FolderCard's. */}
      {confirmingDelete && (
        <div
          style={{
            marginTop: 4,
            marginBottom: 2,
            background: "color-mix(in srgb, var(--red) 8%, transparent)",
            border: "1px solid color-mix(in srgb, var(--red) 25%, var(--border))",
            borderRadius: "var(--radius)",
            padding: "8px 10px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            animation: "fadeIn 0.2s cubic-bezier(0.16,1,0.3,1) both",
          }}
        >
          <span style={{ fontSize: 11, color: "var(--text-2)" }}>
            Move <strong style={{ color: "var(--text-1)" }}>{file.name}</strong> to trash?
          </span>
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            <button
              onClick={onCancelDelete}
              className="btn-hover"
              style={{ ...BTN_GHOST, color: "var(--text-2)", fontSize: 11, padding: "4px 8px" }}
            >
              Cancel
            </button>
            <button
              onClick={() => onConfirmDelete?.(file)}
              style={{
                padding: "4px 10px", fontSize: 11, fontWeight: 600, borderRadius: "var(--radius)",
                border: "none", background: "var(--red)", color: "var(--on-accent)", cursor: "pointer",
              }}
            >
              Move to trash
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── F-6: inline "Remind me" prompt on a vault file row ────────────────────────

function RemindMePrompt({ file, onConfirm, onCancel }: { file: VaultFile; onConfirm: (whenIso: string) => void; onCancel: () => void }) {
  const [when, setWhen] = useState("");
  return (
    <div style={{
      background: "var(--surface-2)", border: "1px solid color-mix(in srgb, var(--accent) 30%, var(--border))",
      borderRadius: "var(--radius)", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8,
    }}>
      <span style={{ fontSize: 11, color: "var(--text-2)", letterSpacing: "0.04em" }}>
        Remind me about <strong style={{ color: "var(--text-1)" }}>{file.name}</strong>
      </span>
      <input
        autoFocus type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)}
        style={{ ...INPUT_STYLE, width: "100%", boxSizing: "border-box" }}
        onFocus={focusRing} onBlur={blurRing}
      />
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
        <button onClick={onCancel} className="btn-hover" style={{ ...BTN_GHOST, color: "var(--text-2)", fontSize: 12, padding: "5px 10px" }}>Cancel</button>
        <button
          onClick={() => when && onConfirm(when)}
          disabled={!when}
          style={{
            padding: "5px 14px", fontSize: 12, fontWeight: 600, borderRadius: "var(--radius)",
            border: "none", background: "var(--accent)", color: "var(--on-accent)",
            cursor: when ? "pointer" : "not-allowed", opacity: when ? 1 : 0.4,
          }}
        >
          Set reminder
        </button>
      </div>
    </div>
  );
}

// ── Provisional row (LAN overlay, contract §11) ────────────────────────────────
//
// Display-only, never-destructive: a provisional row is a staged copy of a
// note received over the LAN accelerator that Drive hasn't confirmed as
// canonical yet (see workspace CLAUDE.md "Shared locks" — LAN never writes
// canonical state). It carries a quiet var(--yellow) badge and offers no
// rename/delete affordance; it disappears on its own once the Drive-synced
// canonical copy supersedes it (mergeProvisional in lib/provisional.ts).
function ProvisionalRow({ item }: { item: ProvisionalItem }) {
  const staged = new Date(item.staged_at * 1000).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });

  return (
    <div
      style={{
        ...ROW_DIVIDER,
        margin: "0 -6px",
        padding: "7px 6px",
        borderRadius: "var(--radius-sm)",
      }}
    >
      {/* Clock icon — "staged, unconfirmed" */}
      <span style={{ display: "inline-flex", flexShrink: 0, color: "var(--yellow)" }}>
        <ClockIcon size={12} />
      </span>
      <span style={{ flex: 1, fontSize: 12, color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {item.note_id}
      </span>
      <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{item.device || "LAN"}</span>
      <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{staged}</span>
      <span
        title="Staged from a LAN peer — not yet confirmed by Drive"
        style={{
          fontSize: 9, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase",
          color: "var(--yellow)",
          background: "color-mix(in srgb, var(--yellow) 14%, transparent)",
          border: "1px solid color-mix(in srgb, var(--yellow) 35%, var(--border))",
          borderRadius: 2,
          padding: "1px 5px",
          flexShrink: 0,
        }}
      >
        Pending
      </span>
    </div>
  );
}

// ── Inline text input modal ───────────────────────────────────────────────────

function InlinePrompt({
  label,
  placeholder,
  initial,
  onConfirm,
  onCancel,
}: {
  label: string;
  placeholder: string;
  initial?: string;
  onConfirm: (v: string) => void;
  onCancel: () => void;
}) {
  const [val, setVal] = useState(initial ?? "");

  return (
    <div style={{
      background: "var(--surface-2)",
      border: "1px solid color-mix(in srgb, var(--accent) 30%, var(--border))",
      borderRadius: "var(--radius)",
      padding: "12px 14px",
      display: "flex",
      flexDirection: "column",
      gap: 8,
    }}>
      <span style={{ fontSize: 11, color: "var(--text-2)", letterSpacing: "0.04em" }}>{label}</span>
      <input
        autoFocus
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder={placeholder}
        style={{ ...INPUT_STYLE, width: "100%", boxSizing: "border-box" }}
        onFocus={focusRing}
        onBlur={blurRing}
        onKeyDown={(e) => {
          if (e.key === "Enter") onConfirm(val.trim());
          if (e.key === "Escape") onCancel();
        }}
      />
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
        <button
          onClick={onCancel}
          className="btn-hover"
          style={{ ...BTN_GHOST, color: "var(--text-2)", fontSize: 12, padding: "5px 10px" }}
        >
          Cancel
        </button>
        <button
          onClick={() => val.trim() && onConfirm(val.trim())}
          disabled={!val.trim()}
          style={{
            padding: "5px 14px", fontSize: 12, fontWeight: 600, borderRadius: "var(--radius)",
            border: "none", background: "var(--accent)", color: "var(--on-accent)",
            cursor: val.trim() ? "pointer" : "not-allowed", opacity: val.trim() ? 1 : 0.4,
            transition: "opacity 0.15s",
          }}
        >
          Confirm
        </button>
      </div>
    </div>
  );
}

// ── Description editor (textarea with char counter) ──────────────────────────

function DescriptionEditor({
  initial,
  onConfirm,
  onCancel,
}: {
  initial: string | null;
  onConfirm: (v: string | null) => void;
  onCancel: () => void;
}) {
  const MAX = 500;
  const [val, setVal] = useState(initial ?? "");
  const remaining = MAX - val.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <textarea
        autoFocus
        maxLength={MAX}
        rows={3}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder="e.g. Personal finance records, invoices, and budget notes."
        style={{
          ...INPUT_STYLE,
          width: "100%",
          boxSizing: "border-box",
          resize: "vertical",
          lineHeight: 1.5,
        }}
        onFocus={focusRing}
        onBlur={blurRing}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
          // Ctrl/Cmd+Enter to confirm
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onConfirm(val.trim() || null);
        }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 10, color: remaining < 50 ? "var(--yellow)" : "var(--text-3)" }}>
          {remaining} chars left
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          {val.trim() && (
            <button
              onClick={() => onConfirm(null)}
              className="btn-hover hover-danger"
              style={{ ...BTN_GHOST, color: "var(--text-3)", fontSize: 11, padding: "5px 8px" }}
              title="Clear description"
            >
              Clear
            </button>
          )}
          <button
            onClick={onCancel}
            className="btn-hover"
            style={{ ...BTN_GHOST, color: "var(--text-2)", fontSize: 12, padding: "5px 10px" }}
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(val.trim() || null)}
            style={{
              padding: "5px 14px", fontSize: 12, fontWeight: 600, borderRadius: "var(--radius)",
              border: "none", background: "var(--accent)", color: "var(--on-accent)",
              cursor: "pointer", transition: "opacity 0.15s",
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}


// ── Main VaultManager ─────────────────────────────────────────────────────────

type ModalState =
  | { kind: "none" }
  | { kind: "create" }
  | { kind: "rename"; name: string }
  | { kind: "editDescription"; name: string; current: string | null };

export default function VaultManager({ visible, onClose, openResult, onConsumeOpenResult, measureRef, embedded = false, compactHeader = false, onHeaderActionsChange, onOpenNote }: Props) {
  // Mounted+visible pattern (mirrors SettingsPanel): the panel stays mounted
  // while transitioning out so it can animate, but is removed from the DOM
  // once fully hidden so it can't eat clicks meant for the capture card.
  const [mounted, setMounted] = useState(visible);
  const wasVisible = useRef(visible);

  const [folders, setFolders] = useState<VaultFolder[]>([]);
  const [vaultRoot, setVaultRoot] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // LAN provisional overlay (contract §11) — display-only, never authoritative.
  // ponytail: no canonical note_id set is threaded in here yet (VaultFile
  // doesn't carry note_id), so mergeProvisional's dedup is a no-op today —
  // every staged row shows until list_provisional's own supersede/sweep
  // (LAN handler + TTL) clears it. Upgrade path: once a route surfaces
  // note_id-tagged canonical rows, pass them as mergeProvisional's first arg.
  const [provisionalItems, setProvisionalItems] = useState<ProvisionalItem[]>([]);

  const [drillCat, setDrillCat] = useState<string | null>(null);
  const [drillFiles, setDrillFiles] = useState<VaultFile[]>([]);
  const [drillLoading, setDrillLoading] = useState(false);
  const [highlightFile, setHighlightFile] = useState<string | null>(null);

  const [modal, setModal] = useState<ModalState>({ kind: "none" });
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingDeleteName, setConfirmingDeleteName] = useState<string | null>(null);
  // FR-23 Option A: project-tidy confirm/preview. Deliberately at this
  // top-level component, not inside FolderCard -- a delete/rename can leave
  // notes OUTSIDE the affected folder pending too (project_tidy.py's plan
  // covers the whole vault), and this has to keep showing across a drill-in/
  // drill-out or a folder-list refresh. `null` = nothing known pending.
  const [tidyPreview, setTidyPreview] = useState<TidyMove[] | null>(null);
  const [tidyBusy, setTidyBusy] = useState(false);
  // FR-32: the folder-structure import (FR-23 Option C) is now one shared hook
  // (FolderImportPanel.tsx) so this state/logic can never again exist in only one of the
  // two project-tidy hosts -- that was the bug. Kept beside the tidy state deliberately --
  // they are two answers to the same situation and share one strip.
  const folderImport = useFolderImport({
    onApplied: async () => {
      await load();
      // The tags just written are exactly what the pending tidy moves were missing, so the
      // tidy plan has to be recomputed -- most of it should now be empty.
      checkTidyPreview();
    },
    onError: setActionError,
  });
  // F-1: bulk conflict badge set (one request instead of one per row).
  const [conflictPaths, setConflictPaths] = useState<Set<string>>(new Set());
  // F-5: local-only sync-ignore set (vault-relative posix paths).
  const [ignoredRelPaths, setIgnoredRelPaths] = useState<Set<string>>(new Set());
  // F-6: inline "Remind me" prompt target for the currently drilled-in file list.
  const [remindTarget, setRemindTarget] = useState<VaultFile | null>(null);
  const [remindDone, setRemindDone] = useState<string | null>(null);
  // ISS-005: path of the file row whose inline "move to trash" confirm is open.
  const [deleteConfirmPath, setDeleteConfirmPath] = useState<string | null>(null);
  // ISS-036: gates FileRow's onClick until one animation frame after the
  // drilled-in list settles, closing a hit-test race where a click landing
  // right as the list replaces a "Loading…" placeholder (fast tab-switch +
  // immediate click) could land on the outgoing element instead of the row.
  const [rowsReady, setRowsReady] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getVaultFolders();
      setFolders(data.folders);
      setVaultRoot(data.vault_root);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load vault");
    } finally {
      setLoading(false);
    }
    // Provisional overlay is best-effort and non-blocking: a failure here
    // (e.g. no LAN accelerator ever staged anything) must never surface as
    // a vault-load error.
    try {
      const data = await getProvisional();
      setProvisionalItems(data.provisional);
    } catch {
      setProvisionalItems([]);
    }
    // F-1: same best-effort/non-blocking contract as the provisional overlay.
    try {
      const conflicts = await getVaultConflicts();
      setConflictPaths(new Set(conflicts.map((c) => c.path)));
    } catch {
      setConflictPaths(new Set());
    }
    // F-5: same best-effort/non-blocking contract.
    try {
      const ignored = await getSyncIgnore();
      setIgnoredRelPaths(new Set(ignored));
    } catch {
      setIgnoredRelPaths(new Set());
    }
  }, []);

  // Vault-relative posix path for a file, matching sync_ignore.py's own
  // normalization (strip the vault-root prefix, forward slashes).
  const toRelPath = useCallback((absPath: string): string => {
    const normAbs = absPath.replace(/\\/g, "/");
    const normRoot = vaultRoot.replace(/\\/g, "/").replace(/\/$/, "");
    return normAbs.startsWith(normRoot + "/") ? normAbs.slice(normRoot.length + 1) : normAbs;
  }, [vaultRoot]);

  const handleToggleIgnore = useCallback((file: VaultFile) => {
    const rel = toRelPath(file.path);
    const nextIgnored = !ignoredRelPaths.has(rel);
    setIgnoredRelPaths((cur) => {
      const next = new Set(cur);
      if (nextIgnored) next.add(rel); else next.delete(rel);
      return next;
    });
    setSyncIgnore(file.path, nextIgnored).catch(() => {
      // best-effort: revert local optimism on failure
      setIgnoredRelPaths((cur) => {
        const next = new Set(cur);
        if (nextIgnored) next.delete(rel); else next.add(rel);
        return next;
      });
    });
  }, [ignoredRelPaths, toRelPath]);

  const drillInto = useCallback(async (name: string, highlightPath?: string) => {
    setDrillCat(name);
    setDrillLoading(true);
    setDeleteConfirmPath(null);
    try {
      const data = await getVaultFolderFiles(name);
      setDrillFiles(data.files);
      if (highlightPath) {
        const target = highlightPath.split(/[\\/]/).pop();
        setHighlightFile(target ?? null);
      }
    } catch {
      setDrillFiles([]);
    } finally {
      setDrillLoading(false);
    }
  }, []);

  // ISS-036: only flip rowsReady on once the list has actually stopped
  // loading AND a frame has had a chance to paint it — a click that fires
  // in the same tick the list replaces the old view can otherwise hit-test
  // against the outgoing DOM and no-op.
  useEffect(() => {
    setRowsReady(false);
    if (drillLoading) return;
    const raf = requestAnimationFrame(() => setRowsReady(true));
    return () => cancelAnimationFrame(raf);
  }, [drillLoading, drillFiles]);

  const handleDeleteFile = useCallback(async (file: VaultFile) => {
    setActionError(null);
    try {
      await moveToTrash(file.path);
      setDeleteConfirmPath(null);
      setDrillFiles((cur) => cur.filter((f) => f.path !== file.path));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to move note to trash");
    }
  }, []);

  useEffect(() => {
    if (visible) {
      setMounted(true);
      load();
    }
  }, [visible, load]);

  // Reset stale drill-in/modal state on the visible: true -> false edge, so
  // reopening the panel never lands back in a previously-drilled folder.
  useEffect(() => {
    if (wasVisible.current && !visible) {
      setDrillCat(null);
      setDrillFiles([]);
      setModal({ kind: "none" });
      setActionError(null);
      setHighlightFile(null);
      setConfirmingDeleteName(null);
      setRemindTarget(null);
      setRemindDone(null);
      setDeleteConfirmPath(null);
    }
    wasVisible.current = visible;
  }, [visible]);

  // Honor a search-result deep link: drill straight into its folder and
  // briefly highlight the matching file once the listing loads.
  useEffect(() => {
    if (visible && openResult) {
      drillInto(openResult.project, openResult.path);
      onConsumeOpenResult?.();
    }
  }, [visible, openResult, drillInto, onConsumeOpenResult]);

  useEffect(() => {
    if (!highlightFile) return;
    const t = setTimeout(() => setHighlightFile(null), 1800);
    return () => clearTimeout(t);
  }, [highlightFile]);

  const handleTransitionEnd = () => {
    if (!visible) setMounted(false);
  };

  const handleCreate = async (name: string) => {
    setActionError(null);
    try {
      await createProject(name);
      setModal({ kind: "none" });
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to create");
    }
  };

  // FR-23 Option A: rename/delete no longer silently re-path files on the
  // server (project_tidy.py's tidy pass moves the WHOLE vault, not just the
  // affected project -- that silent full-vault sweep, with no confirm,
  // preview or undo, is the incident this exists to prevent). The registry
  // action below still happens right away; this only checks whether
  // anything is now pending a physical move and shows it. Never blocks on
  // this check failing -- an untidy-on-disk vault is still a correct one,
  // every surface resolves a note by its tag, never its folder.
  const checkTidyPreview = () => {
    getTidyPreview()
      .then((preview) => setTidyPreview(preview.count > 0 ? preview.moves : null))
      .catch(() => { /* best-effort; see comment above */ });
    // FR-23 Option C / FR-32: the same moment is the only honest place to offer the OTHER
    // repair. The tidy strip is telling the user their tree is about to flatten; "keep the
    // folders and tag them instead" belongs in that sentence, not in a settings row they
    // never open. `folderImport.probe()` is best-effort but never silent -- see its own doc.
    folderImport.probe();
  };

  const handleDeclineTidy = () => { setTidyPreview(null); folderImport.close(); };

  const handleApplyTidy = async () => {
    setTidyBusy(true);
    try {
      await applyTidy();
      setTidyPreview(null);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to move files");
    } finally {
      setTidyBusy(false);
    }
  };

  const handleRename = async (oldName: string, newName: string) => {
    setActionError(null);
    try {
      await renameProject(oldName, newName);
      setModal({ kind: "none" });
      if (drillCat === oldName) setDrillCat(newName);
      await load();
      checkTidyPreview();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to rename");
    }
  };

  const handleEditDescription = async (name: string, description: string | null) => {
    setActionError(null);
    try {
      await updateProjectDescription(name, description || null);
      setModal({ kind: "none" });
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to update description");
    }
  };

  // DELETE removes the REGISTRY ENTRY ONLY -- it never deletes, trashes, moves or
  // edits a note (contract 1.3), so there is no `force` for a non-empty folder any
  // more: the notes simply go loose. FR-23 Option A: the server no longer also
  // re-files them right here -- checkTidyPreview() below surfaces that as an
  // explicit, declinable confirm step instead (see its comment).
  const handleDelete = async (name: string) => {
    setActionError(null);
    try {
      await deleteProject(name);
      setConfirmingDeleteName(null);
      if (drillCat === name) setDrillCat(null);
      await load();
      checkTidyPreview();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to delete");
    }
  };

  const handleOpenVaultFolder = async () => {
    setActionError(null);
    try {
      await openVaultPath(vaultRoot);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to open vault folder");
    }
  };

  // Top-level action buttons — Full mode renders these inline in this
  // component's own header (unchanged below); compactHeader mode instead
  // forwards them to the caller so CompactShell's header can render them,
  // in place of this component's own (now-suppressed) duplicate row.
  const headerActionButtons = (
    <>
      {!drillCat && vaultRoot && (
        <button
          className="btn-hover"
          style={BTN_GHOST}
          title="Open vault folder"
          onClick={handleOpenVaultFolder}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            <path d="M2 10h20" />
          </svg>
        </button>
      )}
      <button
        className="btn-hover"
        style={BTN_GHOST}
        title="Refresh"
        onClick={() => drillCat ? drillInto(drillCat) : load()}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="23 4 23 10 17 10" />
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
        </svg>
      </button>
      {!drillCat && (
        <button
          className="btn-hover"
          style={{ ...BTN_GHOST, color: "var(--accent)" }}
          title="New project"
          onClick={() => { setActionError(null); setModal({ kind: "create" }); }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      )}
    </>
  );

  useEffect(() => {
    if (!compactHeader) return;
    onHeaderActionsChange?.(headerActionButtons);
    return () => onHeaderActionsChange?.(null);
    // headerActionButtons is rebuilt every render from these same values —
    // listing it would just be noise, and its closures (handleOpenVaultFolder
    // etc.) are always current at call time regardless of this array.
  }, [compactHeader, drillCat, vaultRoot, onHeaderActionsChange]);

  if (!mounted) return null;

  return (
    <div
      ref={measureRef}
      style={{
        ...(embedded
          ? { position: "relative", width: "100%", height: "100%", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }
          : { ...PANEL_FRAME, ...panelTransform(visible) }),
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
      onTransitionEnd={handleTransitionEnd}
    >
      {/* ── Header ───────────────────────────────────────────────────────── */}
      {/* compactHeader: this header div is otherwise empty (icon/title/vaultRoot
          and the close button all gate off in that mode, and the top-level
          action buttons are forwarded to CompactShell's headerActions slot
          instead) — render it only for the drill-in back button + folder
          title, which live only here and aren't lifted anywhere else. */}
      {(!compactHeader || drillCat) && (
        <div className={embedded ? "" : "drag-region"} style={PANEL_HEADER}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {drillCat ? (
              <button
                className="no-drag btn-hover"
                style={BTN_GHOST}
                onClick={() => setDrillCat(null)}
                title="Back"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
            ) : (
              !embedded && (
                <span style={{ color: "var(--text-2)", display: "flex" }} aria-hidden="true">
                  <MenuIcon target="vault" size={14} />
                </span>
              )
            )}
            {(drillCat || !embedded) && (
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>
                {drillCat ? folderDisplayName(drillCat) : "Vault"}
              </span>
            )}
            {/* ISS-026: single-line middle-ellipsis instead of CSS
                `wordBreak: break-all`, which wrapped mid-word ("STORA/GE")
                into the header action icons at 125%/150% display scale. */}
            {!compactHeader && !drillCat && vaultRoot && (
              <span
                title={vaultRoot}
                style={{
                  fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em",
                  whiteSpace: "nowrap", overflow: "hidden",
                  ...(embedded ? { flex: 1, minWidth: 0 } : { maxWidth: 160 }),
                }}
              >
                {middleEllipsis(vaultRoot, embedded ? PATH_MAX_CHARS_EMBEDDED : PATH_MAX_CHARS_FULL)}
              </span>
            )}
          </div>

          <div className="no-drag" style={{ display: "flex", gap: 4 }}>
            {/* Top-level action buttons: rendered inline here in Full mode;
                compactHeader mode forwards the same buttons up via the effect
                above instead (CompactShell's headerActions slot). */}
            {!compactHeader && headerActionButtons}
            {/* Close */}
            {!embedded && (
              <button
                className="icon-close-btn"
                title="Close"
                onClick={onClose}
              >
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="2" y1="2" x2="12" y2="12" />
                  <line x1="12" y1="2" x2="2" y2="12" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <div
        className="no-drag"
        style={{
          flex: 1,
          overflow: "auto",
          padding: "12px 16px",
          paddingTop: compactHeader ? 4 : undefined,   // 4px, user-approved
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {/* Inline modal: create or rename */}
        {(modal.kind === "create" || modal.kind === "rename") && (
          <InlinePrompt
            label={modal.kind === "create" ? "New project name" : `Rename "${modal.name}"`}
            placeholder={modal.kind === "create" ? "e.g. Research" : "New name"}
            initial={modal.kind === "rename" ? modal.name : ""}
            onConfirm={(v) => {
              if (modal.kind === "create") handleCreate(v);
              else handleRename(modal.name, v);
            }}
            onCancel={() => { setModal({ kind: "none" }); setActionError(null); }}
          />
        )}

        {/* Inline modal: edit description */}
        {modal.kind === "editDescription" && (
          <div style={{
            background: "var(--surface-2)",
            border: "1px solid color-mix(in srgb, var(--accent) 30%, var(--border))",
            borderRadius: "var(--radius)",
            padding: "12px 14px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
              </svg>
              <span style={{ fontSize: 11, color: "var(--text-2)", letterSpacing: "0.04em" }}>
                LLM routing description for <strong style={{ color: "var(--text-1)" }}>{modal.name}</strong>
              </span>
            </div>
            <DescriptionEditor
              initial={modal.current}
              onConfirm={(v) => handleEditDescription(modal.name, v)}
              onCancel={() => { setModal({ kind: "none" }); setActionError(null); }}
            />
          </div>
        )}

        {actionError && (
          <span style={{ fontSize: 11, color: "var(--red)", padding: "0 2px" }}>{actionError}</span>
        )}

        {/* FR-23 Option A: project-tidy confirm/preview strip. Appears only
            after a rename/delete leaves something pending (checkTidyPreview's
            count > 0) -- never automatically, and this is the only place a
            tidy move can be triggered from. Grayscale, not the red delete-
            confirm tint below: moving a file to match its own tag is a safe
            housekeeping step, not a destructive one -- this repo reserves
            color for real semantic state, never decoration. */}
        {tidyPreview && tidyPreview.length > 0 && (
          <div
            style={{
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "10px 12px",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 12, color: "var(--text-2)" }}>
              <strong style={{ color: "var(--text-1)" }}>{tidyPreview.length}</strong>
              {tidyPreview.length === 1 ? " note" : " notes"}
              {" — possibly from other projects too — will move into the folder its own tag already "}
              {"points to. No project changes, no body is edited; only where "}
              {tidyPreview.length === 1 ? "the file" : "the files"}
              {" sit."}
            </span>
            <div
              style={{
                display: "flex", flexDirection: "column", gap: 2, maxHeight: 110, overflowY: "auto",
                border: "1px solid var(--border)", background: "var(--bg)", padding: "4px 8px",
              }}
            >
              {tidyPreview.map((move) => {
                const d = describeTidyMove(move);
                return (
                  <div
                    key={`${move.from}->${move.to}`}
                    style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, padding: "2px 0" }}
                  >
                    <span style={{
                      flex: "0 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap", color: "var(--text-1)",
                    }}>
                      {d.file}
                    </span>
                    <span style={{ color: "var(--text-3)", flex: "0 0 auto" }}>{d.from} → {d.to}</span>
                  </div>
                );
              })}
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 6, flexWrap: "wrap" }}>
              <button
                onClick={handleDeclineTidy}
                disabled={tidyBusy}
                className="btn-hover"
                style={{ ...BTN_GHOST, color: "var(--text-2)", fontSize: 12, padding: "5px 10px" }}
              >
                Not now
              </button>
              {/* FR-23 Option C / FR-32: the other answer to the same situation -- keep the
                  tree and make it legitimate. Shared with ProjectsPane's identical strip
                  (FolderImportPanel.tsx) -- gates itself on offer>0 && checklist-not-open. */}
              <FolderImportOffer
                offer={folderImport.offer}
                checklistOpen={folderImport.rows !== null}
                busy={tidyBusy || folderImport.busy}
                onOpen={folderImport.open}
                variant="card"
              />
              <button
                onClick={handleApplyTidy}
                disabled={tidyBusy}
                className="btn-hover"
                style={{
                  padding: "5px 14px", fontSize: 12, fontWeight: 600, borderRadius: "var(--radius)",
                  border: "1px solid var(--text-1)", background: "var(--bg)", color: "var(--text-1)", cursor: "pointer",
                }}
              >
                {tidyBusy ? "Moving…" : `Move ${tidyPreview.length === 1 ? "file" : "files"}`}
              </button>
            </div>
          </div>
        )}

        {/* FR-23 Option C / FR-32: the per-folder import checklist, shared with
            ProjectsPane's identical checklist (FolderImportPanel.tsx). */}
        {folderImport.rows && (
          <FolderImportChecklist
            rows={folderImport.rows}
            busy={folderImport.busy}
            onToggle={folderImport.toggleRow}
            onRename={folderImport.renameRow}
            onCancel={folderImport.close}
            onApply={folderImport.apply}
            variant="card"
          />
        )}

        {/* Folder list */}
        {!drillCat && (
          <>
            {loading && (
              <div style={{ display: "flex", justifyContent: "center", padding: 20 }}>
                <span style={{ fontSize: 12, color: "var(--text-3)" }}>Loading…</span>
              </div>
            )}
            {error && (
              <span style={{ fontSize: 11, color: "var(--red)" }}>
                {error} — is the Python server running?
              </span>
            )}
            {!loading && !error && folders.length === 0 && (
              <span style={{ fontSize: 12, color: "var(--text-3)", textAlign: "center", paddingTop: 20 }}>
                No folders yet. Create a project to get started.
              </span>
            )}
            {folders.map((cat) => (
              <FolderCard
                key={cat.name}
                cat={cat}
                onDrillIn={drillInto}
                onRename={(name) => { setActionError(null); setModal({ kind: "rename", name }); }}
                onEditDescription={(name, current) => { setActionError(null); setModal({ kind: "editDescription", name, current }); }}
                confirming={confirmingDeleteName === cat.name}
                onRequestDelete={(name) => { setActionError(null); setConfirmingDeleteName(name); }}
                onCancelDelete={() => { setActionError(null); setConfirmingDeleteName(null); }}
                onConfirmDelete={(name) => handleDelete(name)}
              />
            ))}

            {/* LAN provisional overlay — staged, unconfirmed rows (contract §11).
                Quiet, non-destructive, always superseded by Drive canonical;
                see mergeProvisional (lib/provisional.ts) for the dedup rule. */}
            {mergeProvisional<CanonicalNoteRow>([], provisionalItems)
              .filter((row): row is ProvisionalItem & { provisional: true } => row.provisional)
              .map((row) => (
                <ProvisionalRow key={row.op_id} item={row} />
              ))}
          </>
        )}

        {/* Drill-in: file list */}
        {drillCat && (
          <>
            {drillLoading && (
              <div style={{ display: "flex", justifyContent: "center", padding: 20 }}>
                <span style={{ fontSize: 12, color: "var(--text-3)" }}>Loading…</span>
              </div>
            )}
            {!drillLoading && drillFiles.length === 0 && (
              <span style={{ fontSize: 12, color: "var(--text-3)", textAlign: "center", paddingTop: 20 }}>
                No notes here yet.
              </span>
            )}
            {remindTarget && (
              <RemindMePrompt
                file={remindTarget}
                onCancel={() => setRemindTarget(null)}
                onConfirm={(whenIso) => {
                  createReminder(remindTarget.path, remindTarget.name, whenIso)
                    .then(() => { setRemindDone(remindTarget.filename); setRemindTarget(null); setTimeout(() => setRemindDone(null), 2200); })
                    .catch((e) => setActionError(e instanceof Error ? e.message : "Failed to set reminder"));
                }}
              />
            )}
            {drillFiles.map((f) => (
              <FileRow
                key={f.filename}
                file={f}
                highlighted={highlightFile === f.filename}
                hasConflict={conflictPaths.has(f.path)}
                ignored={ignoredRelPaths.has(toRelPath(f.path))}
                rowsReady={rowsReady}
                confirmingDelete={deleteConfirmPath === f.path}
                onOpen={onOpenNote}
                onRemind={(file) => { setActionError(null); setRemindTarget(file); }}
                onToggleIgnore={handleToggleIgnore}
                onRequestDelete={(file) => { setActionError(null); setDeleteConfirmPath(file.path); }}
                onCancelDelete={() => { setActionError(null); setDeleteConfirmPath(null); }}
                onConfirmDelete={handleDeleteFile}
              />
            ))}
            {remindDone && (
              <span style={{ fontSize: 11, color: "var(--green)", padding: "2px 2px" }}>Reminder set for {remindDone}</span>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/**
 * VaultManager.tsx
 * ----------------
 * Full-screen overlay for browsing and managing vault category folders.
 *
 * Features
 *  · Lists every top-level directory under the vault root as a card
 *  · Shows per-folder .md file count
 *  · Create / rename / delete category folders (with non-empty guard)
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
import {
  getVaultCategories,
  createVaultCategory,
  renameVaultCategory,
  deleteVaultCategory,
  updateCategoryDescription,
  getVaultCategoryFiles,
  type VaultCategory,
  type VaultFile,
} from "../lib/api";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  INPUT_STYLE, BTN_GHOST, ROW_CARD, ROW_DIVIDER,
  focusRing, blurRing,
} from "./ui/styles";

interface Props {
  visible: boolean;
  onClose: () => void;
  /** Set by App when a search result should open directly into a category's file list. */
  openResult?: { category: string; path: string } | null;
  /** Called once openResult has been consumed, so App can clear it. */
  onConsumeOpenResult?: () => void;
  measureRef?: (el: HTMLDivElement | null) => void;
}

// ── Category card ─────────────────────────────────────────────────────────────

interface CategoryCardProps {
  cat: VaultCategory;
  onDrillIn: (name: string) => void;
  onRename: (name: string) => void;
  onEditDescription: (name: string, current: string | null) => void;
  confirming: boolean;
  onRequestDelete: (name: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (name: string, count: number) => void;
}

function CategoryCard({
  cat, onDrillIn, onRename, onEditDescription,
  confirming, onRequestDelete, onCancelDelete, onConfirmDelete,
}: CategoryCardProps) {
  const isSystem = cat.name.startsWith("_");

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

        {/* Name + count + description */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 12, fontWeight: 500,
            color: isSystem ? "var(--text-3)" : "var(--text-1)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {cat.name}
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
            Delete <strong style={{ color: "var(--text-1)" }}>{cat.name}</strong>?
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

function FileRow({ file, highlighted }: { file: VaultFile; highlighted?: boolean }) {
  const kb = (file.size_bytes / 1024).toFixed(1);
  const date = new Date(file.modified * 1000).toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });

  return (
    <div
      className="row-hover-flat"
      style={{
        ...ROW_DIVIDER,
        margin: "0 -6px",
        padding: "7px 6px",
        borderRadius: "var(--radius-sm)",
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
      <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{kb} KB</span>
      <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{date}</span>
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

export default function VaultManager({ visible, onClose, openResult, onConsumeOpenResult, measureRef }: Props) {
  // Mounted+visible pattern (mirrors SettingsPanel): the panel stays mounted
  // while transitioning out so it can animate, but is removed from the DOM
  // once fully hidden so it can't eat clicks meant for the capture card.
  const [mounted, setMounted] = useState(visible);
  const wasVisible = useRef(visible);

  const [categories, setCategories] = useState<VaultCategory[]>([]);
  const [vaultRoot, setVaultRoot] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [drillCat, setDrillCat] = useState<string | null>(null);
  const [drillFiles, setDrillFiles] = useState<VaultFile[]>([]);
  const [drillLoading, setDrillLoading] = useState(false);
  const [highlightFile, setHighlightFile] = useState<string | null>(null);

  const [modal, setModal] = useState<ModalState>({ kind: "none" });
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingDeleteName, setConfirmingDeleteName] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getVaultCategories();
      setCategories(data.categories);
      setVaultRoot(data.vault_root);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load vault");
    } finally {
      setLoading(false);
    }
  }, []);

  const drillInto = useCallback(async (name: string, highlightPath?: string) => {
    setDrillCat(name);
    setDrillLoading(true);
    try {
      const data = await getVaultCategoryFiles(name);
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

  useEffect(() => {
    if (visible) {
      setMounted(true);
      load();
    }
  }, [visible, load]);

  // Reset stale drill-in/modal state on the visible: true -> false edge, so
  // reopening the panel never lands back in a previously-drilled category.
  useEffect(() => {
    if (wasVisible.current && !visible) {
      setDrillCat(null);
      setDrillFiles([]);
      setModal({ kind: "none" });
      setActionError(null);
      setHighlightFile(null);
      setConfirmingDeleteName(null);
    }
    wasVisible.current = visible;
  }, [visible]);

  // Honor a search-result deep link: drill straight into its category and
  // briefly highlight the matching file once the listing loads.
  useEffect(() => {
    if (visible && openResult) {
      drillInto(openResult.category, openResult.path);
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
      await createVaultCategory(name);
      setModal({ kind: "none" });
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to create");
    }
  };

  const handleRename = async (oldName: string, newName: string) => {
    setActionError(null);
    try {
      await renameVaultCategory(oldName, newName);
      setModal({ kind: "none" });
      if (drillCat === oldName) setDrillCat(newName);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to rename");
    }
  };

  const handleEditDescription = async (name: string, description: string | null) => {
    setActionError(null);
    try {
      await updateCategoryDescription(name, description || null);
      setModal({ kind: "none" });
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to update description");
    }
  };

  const handleDelete = async (name: string, force: boolean) => {
    setActionError(null);
    try {
      await deleteVaultCategory(name, force);
      setConfirmingDeleteName(null);
      if (drillCat === name) setDrillCat(null);
      await load();
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

  if (!mounted) return null;

  return (
    <div
      ref={measureRef}
      style={{
        ...PANEL_FRAME,
        ...panelTransform(visible),
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
      onTransitionEnd={handleTransitionEnd}
    >
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="drag-region" style={PANEL_HEADER}>
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
          ) : null}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>
            {drillCat ? drillCat : "Vault"}
          </span>
          {!drillCat && vaultRoot && (
            <span style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 160 }}>
              {vaultRoot}
            </span>
          )}
        </div>

        <div className="no-drag" style={{ display: "flex", gap: 4 }}>
          {/* Open vault folder (only on top-level view, once we know the path) */}
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
          {/* Refresh */}
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
          {/* New folder (only on top-level view) */}
          {!drillCat && (
            <button
              className="btn-hover"
              style={{ ...BTN_GHOST, color: "var(--accent)" }}
              title="New category"
              onClick={() => { setActionError(null); setModal({ kind: "create" }); }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>
          )}
          {/* Close */}
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
        </div>
      </div>

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <div
        className="no-drag"
        style={{ flex: 1, overflow: "auto", padding: "12px 16px", display: "flex", flexDirection: "column", gap: 6 }}
      >
        {/* Inline modal: create or rename */}
        {(modal.kind === "create" || modal.kind === "rename") && (
          <InlinePrompt
            label={modal.kind === "create" ? "New category name" : `Rename "${modal.name}"`}
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

        {/* Category list */}
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
            {!loading && !error && categories.length === 0 && (
              <span style={{ fontSize: 12, color: "var(--text-3)", textAlign: "center", paddingTop: 20 }}>
                No categories found. Create one to get started.
              </span>
            )}
            {categories.map((cat) => (
              <CategoryCard
                key={cat.name}
                cat={cat}
                onDrillIn={drillInto}
                onRename={(name) => { setActionError(null); setModal({ kind: "rename", name }); }}
                onEditDescription={(name, current) => { setActionError(null); setModal({ kind: "editDescription", name, current }); }}
                confirming={confirmingDeleteName === cat.name}
                onRequestDelete={(name) => { setActionError(null); setConfirmingDeleteName(name); }}
                onCancelDelete={() => { setActionError(null); setConfirmingDeleteName(null); }}
                onConfirmDelete={(name, count) => handleDelete(name, count > 0)}
              />
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
            {drillFiles.map((f) => (
              <FileRow key={f.filename} file={f} highlighted={highlightFile === f.filename} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}

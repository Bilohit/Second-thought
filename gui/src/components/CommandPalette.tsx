/**
 * CommandPalette.tsx
 * ------------------
 * Zen-style Ctrl+K command palette.
 *
 * Commands
 *   capture   – trigger a new capture (sends Tauri event)
 *   search    – switch into full-text search mode (debounced FTS query)
 *   settings  – open settings panel
 *   vault     – open vault manager
 *   category  – jump to a specific vault category
 *
 * Keyboard
 *   Ctrl/Cmd+K  open / close
 *   ArrowUp/Down  navigate
 *   Enter         execute highlighted command / open highlighted result
 *   Tab/Shift+Tab cycle within the palette (focus trap; never escapes to the
 *                 capture card behind the backdrop)
 *   Escape        leave search mode, then close
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { emit } from "@tauri-apps/api/event";
import { searchCaptures, type SearchResult } from "../lib/api";

export type PaletteAction =
  | "capture"
  | "search"
  | "settings"
  | "vault"
  | "inbox"
  | "stats"
  | { kind: "category"; name: string }
  | { kind: "openResult"; category: string; path: string };

interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: string;
  action: PaletteAction;
  keywords: string[];
}

interface Props {
  open: boolean;
  categories: string[];
  onClose: () => void;
  onAction: (action: PaletteAction) => void;
}

// ── Static commands ─────────────────────────────────────────────────────────

const STATIC_COMMANDS: Command[] = [
  {
    id: "capture",
    label: "Capture clipboard",
    hint: "Run the capture pipeline now",
    icon: "⊕",
    action: "capture",
    keywords: ["capture", "clip", "save", "new"],
  },
  {
    id: "search",
    label: "Search vault",
    hint: "Full-text search across indexed notes",
    icon: "◎",
    action: "search",
    keywords: ["search", "find", "query", "fts"],
  },
  {
    id: "settings",
    label: "Settings",
    hint: "Ollama model, vault path, hotkey",
    icon: "◈",
    action: "settings",
    keywords: ["settings", "config", "preferences", "model", "hotkey"],
  },
  {
    id: "vault",
    label: "Vault manager",
    hint: "Browse categories and files",
    icon: "◧",
    action: "vault",
    keywords: ["vault", "files", "categories", "browse"],
  },
  {
    id: "inbox",
    label: "Inbox",
    hint: "Review captures awaiting approval",
    icon: "◫",
    action: "inbox",
    keywords: ["inbox", "review", "scratchpad", "approve", "discard"],
  },
  {
    id: "stats",
    label: "Statistics",
    hint: "Capture counts and recent activity",
    icon: "◔",
    action: "stats",
    keywords: ["stats", "statistics", "counts", "activity", "dashboard"],
  },
];

// ── Filtering ──────────────────────────────────────────────────────────────

function buildCommands(categories: string[]): Command[] {
  const catCmds: Command[] = categories.map((name) => ({
    id: `cat:${name}`,
    label: name,
    hint: "Jump to category",
    icon: "▸",
    action: { kind: "category", name },
    keywords: [name.toLowerCase(), "category", "folder"],
  }));
  return [...STATIC_COMMANDS, ...catCmds];
}

function filterCommands(commands: Command[], query: string): Command[] {
  const q = query.trim().toLowerCase();
  if (!q) return commands;
  return commands.filter(
    (c) =>
      c.label.toLowerCase().includes(q) ||
      c.keywords.some((k) => k.includes(q))
  );
}

function resultSnippet(r: SearchResult): string {
  return r.filename || r.source_url || r.path.split(/[\\/]/).pop() || r.path;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function CommandPalette({ open, categories, onClose, onAction }: Props) {
  const [mode, setMode]         = useState<"commands" | "search">("commands");
  const [query, setQuery]       = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [results, setResults]   = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const inputRef  = useRef<HTMLInputElement>(null);
  const listRef   = useRef<HTMLDivElement>(null);
  const panelRef  = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const commands  = buildCommands(categories);
  const filtered  = mode === "commands" ? filterCommands(commands, query) : [];

  // Reset on open; restore focus to the trigger on close.
  useEffect(() => {
    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement | null;
      setMode("commands");
      setQuery("");
      setResults([]);
      setSearchError(null);
      setActiveIdx(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      previousFocusRef.current?.focus();
    }
  }, [open]);

  // Clamp active index against whichever list is showing.
  useEffect(() => {
    const len = mode === "search" ? results.length : filtered.length;
    setActiveIdx((i) => Math.min(i, Math.max(0, len - 1)));
  }, [filtered.length, results.length, mode]);

  // Scroll active item into view
  useEffect(() => {
    const item = listRef.current?.querySelector(`[data-idx="${activeIdx}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  // Debounced FTS query while in search mode.
  useEffect(() => {
    if (mode !== "search") return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = query.trim();
    if (!q) {
      setResults([]);
      setSearching(false);
      setSearchError(null);
      return;
    }
    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchCaptures(q, { limit: 30 });
        setResults(res.results);
        setSearchError(null);
      } catch {
        setResults([]);
        setSearchError("Search failed — is the server running?");
      } finally {
        setSearching(false);
      }
    }, 150);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, mode]);

  const enterSearchMode = useCallback(() => {
    setMode("search");
    setQuery("");
    setResults([]);
    setActiveIdx(0);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);

  const execute = useCallback(
    (cmd: Command) => {
      if (cmd.action === "search") {
        enterSearchMode();
        return;
      }
      onClose();
      if (cmd.action === "capture") {
        emit("trigger-capture").catch(() => {});
      } else {
        onAction(cmd.action);
      }
    },
    [onClose, onAction, enterSearchMode]
  );

  const openResult = useCallback(
    (r: SearchResult) => {
      onClose();
      onAction({ kind: "openResult", category: r.category, path: r.path });
    },
    [onClose, onAction]
  );

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      // Focus trap: Tab/Shift+Tab cycle within the palette's focusable set.
      if (e.key === "Tab") {
        const root = panelRef.current;
        if (!root) return;
        const focusables = Array.from(
          root.querySelectorAll<HTMLElement>('input, [tabindex]:not([tabindex="-1"])')
        ).filter((el) => !el.hasAttribute("disabled"));
        if (focusables.length === 0) return;
        e.preventDefault();
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const current = document.activeElement as HTMLElement | null;
        if (e.shiftKey) {
          if (!current || current === first || !root.contains(current)) last.focus();
          else focusables[Math.max(0, focusables.indexOf(current) - 1)].focus();
        } else {
          if (!current || current === last || !root.contains(current)) first.focus();
          else focusables[Math.min(focusables.length - 1, focusables.indexOf(current) + 1)].focus();
        }
        return;
      }

      const len = mode === "search" ? results.length : filtered.length;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => Math.min(i + 1, len - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (mode === "search") {
          const r = results[activeIdx];
          if (r) openResult(r);
        } else {
          const cmd = filtered[activeIdx];
          if (cmd) execute(cmd);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        if (mode === "search") {
          setMode("commands");
          setQuery("");
          setActiveIdx(0);
          requestAnimationFrame(() => inputRef.current?.focus());
        } else {
          onClose();
        }
      }
    },
    [mode, filtered, results, activeIdx, execute, openResult, onClose]
  );

  if (!open) return null;

  return (
    /* Backdrop */
    <div
      role="dialog"
      aria-label="Command palette"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: 72,
        background: "var(--scrim)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
      }}
      onClick={onClose}
    >
      {/* Panel */}
      <div
        ref={panelRef}
        role={mode === "search" ? "dialog" : "combobox"}
        aria-expanded="true"
        aria-haspopup="listbox"
        aria-controls="palette-list"
        style={{
          width: 440,
          background: "var(--palette-bg)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-xl)",
          boxShadow: "var(--glass-shadow)",
          overflow: "hidden",
          animation: "paletteIn 0.12s cubic-bezier(0.16,1,0.3,1) forwards",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "12px 14px",
            gap: 10,
            borderBottom: "1px solid var(--border)",
          }}
        >
          {/* Magnifier */}
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--text-3)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            style={{ flexShrink: 0 }}
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>

          {mode === "search" && (
            <kbd
              aria-hidden="true"
              style={{
                fontSize: 10,
                color: "var(--accent)",
                background: "var(--accent-d)",
                border: "1px solid color-mix(in srgb, var(--accent) 25%, transparent)",
                borderRadius: "var(--radius-sm)",
                padding: "2px 5px",
                flexShrink: 0,
                letterSpacing: "0.03em",
              }}
            >
              search
            </kbd>
          )}

          <input
            ref={inputRef}
            type="text"
            role="searchbox"
            aria-label={mode === "search" ? "Search captured notes" : "Search commands"}
            aria-autocomplete="list"
            aria-activedescendant={
              mode === "search"
                ? results[activeIdx] ? `palette-result-${results[activeIdx].id}` : undefined
                : filtered[activeIdx] ? `palette-item-${filtered[activeIdx].id}` : undefined
            }
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActiveIdx(0); }}
            onKeyDown={handleKey}
            placeholder={mode === "search" ? "Search captured notes…" : "Search commands…"}
            style={{
              flex: 1,
              background: "none",
              border: "none",
              outline: "none",
              color: "var(--text-1)",
              fontSize: 14,
              fontFamily: "inherit",
              caretColor: "var(--accent)",
            }}
          />

          <kbd
            aria-label="Press Escape to close"
            style={{
              fontSize: 10,
              color: "var(--text-3)",
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              padding: "2px 5px",
              letterSpacing: "0.03em",
              flexShrink: 0,
            }}
          >
            esc
          </kbd>
        </div>

        {/* Results */}
        <div
          id="palette-list"
          role="listbox"
          ref={listRef}
          aria-label={mode === "search" ? "Search results" : "Commands"}
          style={{
            maxHeight: 300,
            overflowY: "auto",
            padding: "4px 0",
          }}
        >
          {mode === "search" ? (
            <>
              {!query.trim() && (
                <div role="status" style={{ padding: "20px 16px", textAlign: "center", fontSize: 13, color: "var(--text-3)" }}>
                  Type to search indexed notes
                </div>
              )}
              {query.trim() && searching && (
                <div role="status" style={{ padding: "20px 16px", textAlign: "center", fontSize: 13, color: "var(--text-3)" }}>
                  Searching…
                </div>
              )}
              {query.trim() && !searching && searchError && (
                <div role="status" style={{ padding: "20px 16px", textAlign: "center", fontSize: 13, color: "var(--red)" }}>
                  {searchError}
                </div>
              )}
              {query.trim() && !searching && !searchError && results.length === 0 && (
                <div role="status" style={{ padding: "20px 16px", textAlign: "center", fontSize: 13, color: "var(--text-3)" }}>
                  No indexed notes match "{query.trim()}"
                </div>
              )}
              {results.map((r, idx) => {
                const isActive = idx === activeIdx;
                return (
                  <div
                    key={r.id}
                    id={`palette-result-${r.id}`}
                    role="option"
                    aria-selected={isActive}
                    data-idx={idx}
                    onClick={() => openResult(r)}
                    onMouseEnter={() => setActiveIdx(idx)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 14px",
                      cursor: "pointer",
                      background: isActive
                        ? "var(--accent-d)"
                        : "transparent",
                      transition: "background 0.08s",
                    }}
                  >
                    <span
                      aria-hidden="true"
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.04em",
                        color: isActive ? "var(--accent)" : "var(--text-3)",
                        background: "var(--surface)",
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius-sm)",
                        padding: "2px 6px",
                        flexShrink: 0,
                        whiteSpace: "nowrap",
                      }}
                    >
                      {r.category}
                    </span>
                    <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {resultSnippet(r)}
                    </span>
                  </div>
                );
              })}
            </>
          ) : (
            <>
              {filtered.length === 0 && (
                <div
                  role="status"
                  style={{
                    padding: "20px 16px",
                    textAlign: "center",
                    fontSize: 13,
                    color: "var(--text-3)",
                  }}
                >
                  No commands match
                </div>
              )}

              {filtered.map((cmd, idx) => {
                const isActive = idx === activeIdx;
                return (
                  <div
                    key={cmd.id}
                    id={`palette-item-${cmd.id}`}
                    role="option"
                    aria-selected={isActive}
                    data-idx={idx}
                    onClick={() => execute(cmd)}
                    onMouseEnter={() => setActiveIdx(idx)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 14px",
                      cursor: "pointer",
                      background: isActive
                        ? "var(--accent-d)"
                        : "transparent",
                      transition: "background 0.08s",
                    }}
                  >
                    <span
                      aria-hidden="true"
                      style={{
                        width: 20,
                        textAlign: "center",
                        fontSize: 13,
                        color: isActive
                          ? "var(--accent)"
                          : "var(--text-3)",
                        flexShrink: 0,
                      }}
                    >
                      {cmd.icon}
                    </span>

                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span
                        style={{
                          fontSize: 13,
                          color: "var(--text-1)",
                          display: "block",
                        }}
                      >
                        {cmd.label}
                      </span>
                      {cmd.hint && (
                        <span
                          style={{
                            fontSize: 11,
                            color: "var(--text-3)",
                            display: "block",
                            marginTop: 1,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {cmd.hint}
                        </span>
                      )}
                    </span>

                    {isActive && (
                      <kbd
                        aria-hidden="true"
                        style={{
                          fontSize: 10,
                          color: "var(--accent)",
                          background: "var(--accent-d)",
                          border: "1px solid color-mix(in srgb, var(--accent) 25%, transparent)",
                          borderRadius: "var(--radius-sm)",
                          padding: "2px 5px",
                          flexShrink: 0,
                        }}
                      >
                        return
                      </kbd>
                    )}
                  </div>
                );
              })}
            </>
          )}
        </div>

        {/* Footer hint */}
        <div
          aria-hidden="true"
          style={{
            padding: "7px 14px",
            borderTop: "1px solid var(--border)",
            display: "flex",
            gap: 12,
            alignItems: "center",
          }}
        >
          {(mode === "search"
            ? [
                { key: "↑↓", label: "navigate" },
                { key: "↵", label: "open" },
                { key: "esc", label: "back" },
              ]
            : [
                { key: "↑↓", label: "navigate" },
                { key: "↵", label: "select" },
                { key: "esc", label: "close" },
              ]
          ).map(({ key, label }) => (
            <span key={key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <kbd
                style={{
                  fontSize: 9,
                  color: "var(--text-3)",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  padding: "1px 4px",
                }}
              >
                {key}
              </kbd>
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                {label}
              </span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

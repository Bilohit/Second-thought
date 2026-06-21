/**
 * SearchModal.tsx
 * ----------------
 * Minimal full-vault search overlay (Ctrl+K / toolbar magnifier icon).
 *
 * Replaces the old CommandPalette: same backdrop + centered panel styling,
 * but search-only — no command list, no mode toggle. Debounced FTS query
 * over `GET /search` (now indexes note body text, not just metadata).
 *
 * Keyboard
 *   Ctrl/Cmd+K    open / close
 *   ArrowUp/Down  navigate results
 *   Enter         open highlighted result
 *   Tab/Shift+Tab cycle within the panel (focus trap)
 *   Escape        close
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { searchCaptures, type SearchResult } from "../lib/api";

export type SearchAction = { kind: "openResult"; category: string; path: string };

interface Props {
  open: boolean;
  onClose: () => void;
  onAction: (action: SearchAction) => void;
}

function resultSnippet(r: SearchResult): string {
  return r.filename || r.source_url || r.path.split(/[\\/]/).pop() || r.path;
}

export default function SearchModal({ open, onClose, onAction }: Props) {
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Reset on open; restore focus to the trigger on close.
  useEffect(() => {
    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement | null;
      setQuery("");
      setResults([]);
      setSearchError(null);
      setActiveIdx(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      previousFocusRef.current?.focus();
    }
  }, [open]);

  // Clamp active index against the result list.
  useEffect(() => {
    setActiveIdx((i) => Math.min(i, Math.max(0, results.length - 1)));
  }, [results.length]);

  // Scroll active item into view
  useEffect(() => {
    const item = listRef.current?.querySelector(`[data-idx="${activeIdx}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  // Debounced FTS query.
  useEffect(() => {
    if (!open) return;
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
  }, [query, open]);

  const openResult = useCallback(
    (r: SearchResult) => {
      onClose();
      onAction({ kind: "openResult", category: r.category, path: r.path });
    },
    [onClose, onAction]
  );

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      // Focus trap: Tab/Shift+Tab cycle within the panel's focusable set.
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

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => Math.min(i + 1, results.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const r = results[activeIdx];
        if (r) openResult(r);
      } else if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    },
    [results, activeIdx, openResult, onClose]
  );

  if (!open) return null;

  return (
    /* Backdrop */
    <div
      role="dialog"
      aria-label="Search vault"
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

          <input
            ref={inputRef}
            type="text"
            role="searchbox"
            aria-label="Search captured notes"
            aria-autocomplete="list"
            aria-activedescendant={results[activeIdx] ? `search-result-${results[activeIdx].id}` : undefined}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActiveIdx(0); }}
            onKeyDown={handleKey}
            placeholder="Search captured notes…"
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
          id="search-list"
          role="listbox"
          ref={listRef}
          aria-label="Search results"
          style={{
            maxHeight: 300,
            overflowY: "auto",
            padding: "4px 0",
          }}
        >
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
                id={`search-result-${r.id}`}
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
                  background: isActive ? "var(--accent-d)" : "transparent",
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
          {[
            { key: "↑↓", label: "navigate" },
            { key: "↵", label: "open" },
            { key: "esc", label: "close" },
          ].map(({ key, label }) => (
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

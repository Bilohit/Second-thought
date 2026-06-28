/**
 * LookPanel.tsx
 * -------------
 * Dual-mode panel: "Search" (FTS keyword) and "Chat" (local RAG).
 * Mode is persisted in localStorage by App; the panel receives it as a prop
 * and calls onSelectMode — same pattern as displayMode in SettingsPanel.
 *
 * Search mode: lifts the FTS input + result list from SearchModal verbatim,
 *   but rendered inline (no modal backdrop). Result click → openFilePath + onClose.
 * Chat mode: scrollable transcript with citation chips via parseCitations,
 *   fixed-bottom composer.
 *
 * Frame is fixed-height (PANEL_FRAME fills height:100% from App). Both modes
 * share the same outer frame — toggling never resizes the window.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { searchCaptures, openFilePath, type SearchResult } from "../lib/api";
import { parseCitations } from "../lib/citations";
import { useLookChat } from "../hooks/useLookChat";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  BTN_GHOST,
} from "./ui/styles";

interface Props {
  mode: "search" | "chat";
  onSelectMode: (m: "search" | "chat") => void;
  visible: boolean;
  onClose: () => void;
  measureRef?: (el: HTMLDivElement | null) => void;
}

function resultSnippet(r: SearchResult): string {
  return r.filename || r.source_url || r.path.split(/[\\/]/).pop() || r.path;
}

export default function LookPanel({ mode, onSelectMode, visible, onClose, measureRef }: Props) {
  const [mounted, setMounted] = useState(visible);

  // Search state
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Chat state
  const { messages, streaming, ask, reset } = useLookChat();
  const [composer, setComposer] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);
  const composerInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (visible) {
      setMounted(true);
      if (mode === "search") {
        setQuery("");
        setResults([]);
        setSearchError(null);
        setActiveIdx(0);
        requestAnimationFrame(() => searchInputRef.current?.focus());
      } else {
        requestAnimationFrame(() => composerInputRef.current?.focus());
      }
    } else {
      reset();
    }
  }, [visible, mode, reset]);

  const handleTransitionEnd = () => {
    if (!visible) setMounted(false);
  };

  // Clamp active index when results change
  useEffect(() => {
    setActiveIdx((i) => Math.min(i, Math.max(0, results.length - 1)));
  }, [results.length]);

  // Scroll active item into view
  useEffect(() => {
    const item = listRef.current?.querySelector(`[data-idx="${activeIdx}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  // Debounced FTS query
  useEffect(() => {
    if (!visible || mode !== "search") return;
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
  }, [query, visible, mode]);

  // Auto-scroll transcript to bottom on new messages
  useEffect(() => {
    if (mode === "chat" && transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [messages, mode]);

  const openResult = useCallback((r: SearchResult) => {
    openFilePath(r.path);
    onClose();
  }, [onClose]);

  const handleSearchKey = useCallback((e: React.KeyboardEvent) => {
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
  }, [results, activeIdx, openResult, onClose]);

  const handleSend = useCallback(() => {
    const q = composer.trim();
    if (!q || streaming) return;
    ask(q);
    setComposer("");
  }, [composer, streaming, ask]);

  const handleComposerKey = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

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
      {/* Header */}
      <div className="drag-region" style={PANEL_HEADER}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>Look</span>
        <div className="no-drag" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Mode toggle */}
          <div
            role="tablist"
            aria-label="Look mode"
            style={{ display: "flex", gap: 2, background: "var(--surface)", borderRadius: "var(--radius)", padding: 2 }}
          >
            {(["search", "chat"] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                onClick={() => onSelectMode(m)}
                style={{
                  fontSize: 11,
                  padding: "4px 10px",
                  borderRadius: "var(--radius-sm)",
                  border: "none",
                  background: mode === m ? "var(--accent)" : "transparent",
                  color: mode === m ? "var(--on-accent)" : "var(--text-2)",
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                {m === "search" ? "Search" : "Chat"}
              </button>
            ))}
          </div>
          <button className="no-drag icon-close-btn" onClick={onClose} title="Close" style={BTN_GHOST}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="2" y1="2" x2="12" y2="12" />
              <line x1="12" y1="2" x2="2" y2="12" />
            </svg>
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="no-drag" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {mode === "search" ? (
          <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
            {/* Search input row */}
            <div style={{ display: "flex", alignItems: "center", padding: "12px 14px", gap: 10, borderBottom: "1px solid var(--border)" }}>
              <svg
                width="14" height="14" viewBox="0 0 24 24"
                fill="none" stroke="var(--text-3)" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round"
                aria-hidden="true" style={{ flexShrink: 0 }}
              >
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                ref={searchInputRef}
                type="text"
                role="searchbox"
                aria-label="Search captured notes"
                aria-autocomplete="list"
                aria-activedescendant={results[activeIdx] ? `lp-result-${results[activeIdx].id}` : undefined}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setActiveIdx(0); }}
                onKeyDown={handleSearchKey}
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
            </div>

            {/* Results */}
            <div
              id="lp-search-list"
              role="listbox"
              ref={listRef}
              aria-label="Search results"
              style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}
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
                    id={`lp-result-${r.id}`}
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
              style={{ padding: "7px 14px", borderTop: "1px solid var(--border)", display: "flex", gap: 12, alignItems: "center", flexShrink: 0 }}
            >
              {[
                { key: "↑↓", label: "navigate" },
                { key: "↵", label: "open" },
                { key: "esc", label: "close" },
              ].map(({ key, label }) => (
                <span key={key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <kbd style={{ fontSize: 9, color: "var(--text-3)", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "1px 4px" }}>
                    {key}
                  </kbd>
                  <span style={{ fontSize: 10, color: "var(--text-3)" }}>{label}</span>
                </span>
              ))}
            </div>
          </div>
        ) : (
          /* Chat mode */
          <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
            {/* Transcript */}
            <div
              ref={transcriptRef}
              style={{ flex: 1, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}
            >
              {messages.length === 0 && (
                <div style={{ textAlign: "center", fontSize: 13, color: "var(--text-3)", marginTop: 20 }}>
                  Ask anything about your vault
                </div>
              )}
              {messages.map((msg, i) => {
                const isUser = msg.role === "user";
                const isTyping = !isUser && streaming && msg.content === "" && i === messages.length - 1;
                return (
                  <div
                    key={i}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      alignItems: isUser ? "flex-end" : "flex-start",
                      gap: 4,
                    }}
                  >
                    <div
                      style={{
                        maxWidth: "88%",
                        padding: "8px 12px",
                        borderRadius: "var(--radius-xl)",
                        background: isUser ? "var(--accent)" : "var(--surface)",
                        color: isUser ? "var(--on-accent)" : "var(--text-1)",
                        fontSize: 13,
                        lineHeight: 1.5,
                      }}
                    >
                      {isTyping ? (
                        <span style={{ color: "var(--text-3)", fontSize: 16, letterSpacing: 2 }}>…</span>
                      ) : isUser ? (
                        msg.content
                      ) : (
                        parseCitations(msg.content).map((seg, j) => {
                          if ("text" in seg) return <span key={j}>{seg.text}</span>;
                          const src = msg.sources?.[seg.cite - 1];
                          return (
                            <button
                              key={j}
                              title={src ? `${src.category}/${src.filename}` : `Source ${seg.cite}`}
                              disabled={!src}
                              onClick={() => src && openFilePath(src.path)}
                              style={{
                                fontSize: 9,
                                verticalAlign: "super",
                                color: "var(--accent)",
                                border: "none",
                                background: "transparent",
                                cursor: src ? "pointer" : "default",
                                fontFamily: "inherit",
                                padding: "0 1px",
                              }}
                            >
                              [{seg.cite}]
                            </button>
                          );
                        })
                      )}
                    </div>
                    {/* Citation source chips for assistant messages */}
                    {!isUser && msg.sources && msg.sources.length > 0 && !isTyping && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, paddingLeft: 2 }}>
                        {msg.sources.map((src) => (
                          <button
                            key={src.n}
                            onClick={() => openFilePath(src.path)}
                            title={src.path}
                            style={{
                              fontSize: 9,
                              fontWeight: 600,
                              letterSpacing: "0.04em",
                              color: "var(--text-3)",
                              background: "var(--surface)",
                              border: "1px solid var(--border)",
                              borderRadius: "var(--radius-sm)",
                              padding: "2px 6px",
                              cursor: "pointer",
                              fontFamily: "inherit",
                            }}
                          >
                            [{src.n}] {src.category}/{src.filename}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Composer */}
            <div
              style={{
                padding: "10px 14px",
                borderTop: "1px solid var(--border)",
                display: "flex",
                gap: 8,
                alignItems: "center",
                flexShrink: 0,
              }}
            >
              <input
                ref={composerInputRef}
                type="text"
                aria-label="Ask a question about your vault"
                value={composer}
                onChange={(e) => setComposer(e.target.value)}
                onKeyDown={handleComposerKey}
                placeholder="Ask your vault…"
                disabled={streaming}
                style={{
                  flex: 1,
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  outline: "none",
                  color: "var(--text-1)",
                  fontSize: 13,
                  fontFamily: "inherit",
                  padding: "7px 10px",
                  caretColor: "var(--accent)",
                  opacity: streaming ? 0.5 : 1,
                }}
              />
              <button
                onClick={handleSend}
                disabled={streaming || !composer.trim()}
                aria-label="Send"
                style={{
                  background: "var(--accent)",
                  color: "var(--on-accent)",
                  border: "none",
                  borderRadius: "var(--radius)",
                  padding: "7px 12px",
                  fontSize: 12,
                  fontFamily: "inherit",
                  cursor: streaming || !composer.trim() ? "default" : "pointer",
                  opacity: streaming || !composer.trim() ? 0.4 : 1,
                  flexShrink: 0,
                }}
              >
                Send
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * LookPanel.tsx
 * -------------
 * Dual-mode panel: "Search" (FTS keyword) and "Chat" (local RAG).
 * useLookChat is lifted to App.tsx and passed as `lookChat` prop so messages
 * survive panel close/reopen within the same session.
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { searchCaptures, getSemanticSearch, openFilePath, syncVaultIndex, checkHealth, type SearchResult, type SemanticResult } from "../lib/api";
import { slideDirection } from "../lib/segmentedToggle";
import { parseCitations } from "../lib/citations";
import type { ChatMessage } from "../hooks/useLookChat";
import type { LookChatPersist } from "../App";
import { logger } from "../lib/logger";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  BTN_GHOST, BTN_SECONDARY, INPUT_STYLE,
} from "./ui/styles";
import { RefreshIcon, SendIcon, AlertIcon } from "./PillMenu/icons";
import { Toggle } from "./ui/Toggle";

interface LookChatHook {
  messages: ChatMessage[];
  streaming: boolean;
  ask: (q: string) => void;
  reset: () => void;
  retry: (index: number) => void;
  ignoreHistory: boolean;
  setIgnoreHistory: (enabled: boolean) => void;
}

interface Props {
  mode: "search" | "chat";
  onSelectMode: (m: "search" | "chat") => void;
  visible: boolean;
  onClose: () => void;
  measureRef?: (el: HTMLDivElement | null) => void;
  lookChat: LookChatHook;
  lookChatPersist: LookChatPersist;
  /** Full-window shell renders its own toggle in the topbar; suppress the inline one. */
  hideToggle?: boolean;
  embedded?: boolean;
  /** Full-window shell drives sync from its topbar button; use these instead of internal state. */
  externalSyncing?: boolean;
  externalSyncStatus?: string | null;
  /** Rendered inside a compact panel: tightened search/chat density (B — tight),
   *  compact-panel footer with 24px input snug to the bottom edge; Ignore history /
   *  Clear as a slim row directly above it. Full-window keeps the inline row and
   *  looser spacing. */
  compact?: boolean;
}

function resultSnippet(r: SearchResult): string {
  return r.filename || r.source_url || r.path.split(/[\\/]/).pop() || r.path;
}

function tierColor(tier: string | undefined): string {
  if (tier === "high") return "var(--green, #4ade80)";
  if (tier === "talk") return "var(--text-3)";
  return "var(--red, #f87171)";
}

function tierLabel(tier: string | undefined): string {
  if (tier === "high") return "Vault";
  if (tier === "talk") return "General knowledge";
  return "No vault match";
}

export default function LookPanel({ mode, onSelectMode, visible, onClose, measureRef, lookChat, lookChatPersist, hideToggle = false, embedded = false, externalSyncing, externalSyncStatus, compact = false }: Props) {
  const [mounted, setMounted] = useState(visible);

  // Directional content-swap: Search↔Chat slides by the toggle's index delta
  // (Search=0, Chat=1). Derived at render from the last-committed mode; the
  // keyed swap panel replays its slide-in animation on every change.
  const modeIndex = mode === "chat" ? 1 : 0;
  const prevModeIndexRef = useRef(modeIndex);
  const swapDir = slideDirection(prevModeIndexRef.current, modeIndex);
  useEffect(() => { prevModeIndexRef.current = modeIndex; }, [modeIndex]);

  // Search state
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  // F-10: semantic band beneath FTS results -- top-k related notes, deduped
  // against `results` by path so nothing shows twice.
  const [semanticResults, setSemanticResults] = useState<SemanticResult[]>([]);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Chat state (lifted — only composer is local)
  const { messages, streaming, ask, reset, retry, ignoreHistory, setIgnoreHistory } = lookChat;
  const [composer, setComposer] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);
  const composerInputRef = useRef<HTMLInputElement>(null);

  // Vault sync state
  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // LLM health — persistent offline banner (a per-message failure marker isn't enough signal)
  const [llmOffline, setLlmOffline] = useState(false);
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    const poll = async () => {
      const { llmStatus } = await checkHealth();
      if (!cancelled) setLlmOffline(llmStatus === "disconnected");
    };
    poll();
    const id = setInterval(poll, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, [visible]);

  useEffect(() => {
    if (visible) {
      setMounted(true);
      logger.info("look", "panel opened", { mode });
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
      logger.debug("look", "panel closed");
      if (lookChatPersist === "clear") reset();
    }
  }, [visible, mode, reset, lookChatPersist]);

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
      setSemanticResults([]);
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
      // Best-effort, never blocks/fails the FTS results above.
      getSemanticSearch(q, 5).then(setSemanticResults).catch(() => setSemanticResults([]));
    }, 150);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, visible, mode]);

  // Dedupe the semantic band against FTS hits by path (semantic paths are
  // vault-relative; FTS paths are absolute) -- never show the same note twice.
  const dedupedSemantic = semanticResults.filter((s) => {
    const relNorm = s.path.replace(/\\/g, "/");
    return !results.some((r) => r.path.replace(/\\/g, "/").endsWith(relNorm));
  });

  // Auto-scroll transcript to bottom on new messages
  useEffect(() => {
    if (mode === "chat" && transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [messages, mode]);

  const openResult = useCallback((r: SearchResult) => {
    logger.debug("look", "open search result", { path: r.path, category: r.category });
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

  const handleRefresh = useCallback(async () => {
    if (syncing) return;
    setSyncing(true);
    setSyncStatus(null);
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    try {
      const result = await syncVaultIndex();
      const total = result.added + result.removed + result.updated;
      setSyncStatus(
        total === 0
          ? `Index up to date — ${result.skipped} unchanged`
          : `Index updated: +${result.added} new, −${result.removed} removed, ${result.updated} changed, ${result.skipped} unchanged`
      );
    } catch (err) {
      setSyncStatus(`Sync failed — ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      setSyncing(false);
      syncTimerRef.current = setTimeout(() => setSyncStatus(null), 4000);
    }
  }, [syncing]);

  // cleanup sync timer on unmount
  useEffect(() => () => { if (syncTimerRef.current) clearTimeout(syncTimerRef.current); }, []);

  if (!mounted) return null;

  const effSyncing = embedded ? (externalSyncing ?? false) : syncing;
  const effSyncStatus = embedded ? (externalSyncStatus ?? null) : syncStatus;
  const syncFailed = effSyncStatus?.startsWith("Sync failed");

  return (
    <div
      ref={measureRef}
      style={{
        ...(embedded
          ? { position: "relative", width: "100%", height: "100%", border: "none", borderRadius: 0, background: "transparent" }
          : { ...PANEL_FRAME, ...panelTransform(visible) }),
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
      onTransitionEnd={handleTransitionEnd}
    >
      {/* Header — text-only title (no magnifier glyph); one spacing step of
          clear vertical space below via marginBottom, on top of the
          existing border-bottom divider. */}
      {!embedded && (
        <div className="drag-region" style={{ ...PANEL_HEADER, marginBottom: "var(--space-2)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>
              Look
            </span>
          </div>
          <div className="no-drag" style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {/* Mode toggle */}
            {!hideToggle && (
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
                    onClick={() => { logger.debug("look", "mode changed", { mode: m }); onSelectMode(m); }}
                    style={{
                      fontSize: 11,
                      padding: "4px 10px",
                      minWidth: 60,
                      textAlign: "center",
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
            )}
            {/* Refresh button */}
            <button
              className="btn-hover no-drag"
              onClick={handleRefresh}
              disabled={syncing}
              title="Sync vault index"
              aria-label="Sync vault index"
              style={{ ...BTN_GHOST, opacity: syncing ? 0.5 : 1 }}
            >
              <RefreshIcon size={13} />
            </button>
            <button className="no-drag icon-close-btn" onClick={onClose} title="Close" aria-label="Close">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="2" y1="2" x2="12" y2="12" />
                <line x1="12" y1="2" x2="2" y2="12" />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* LLM offline banner — persistent signal, not just a per-message failure marker */}
      {llmOffline && (
        <div role="status" aria-live="polite" style={{ fontSize: 12, color: "var(--red)", borderBottom: "1px solid var(--border)", textAlign: "center", padding: "6px 14px", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
          <AlertIcon size={12} />
          Model offline — Ollama unreachable
        </div>
      )}

      {/* Sync banner */}
      {effSyncing && (
        <div role="status" aria-live="polite" style={{ fontSize: 12, color: "var(--text-3)", borderBottom: "1px solid var(--border)", textAlign: "center", padding: "6px 14px" }}>
          Syncing vault index…
        </div>
      )}
      {!effSyncing && effSyncStatus && (
        <div role="status" aria-live="polite" style={{ fontSize: 12, color: syncFailed ? "var(--red)" : "var(--text-3)", borderBottom: "1px solid var(--border)", textAlign: "center", padding: "6px 14px" }}>
          {effSyncStatus}
        </div>
      )}

      {/* Body */}
      <div
        className="no-drag"
        style={{
          flex: 1, minHeight: 0, display: "flex", flexDirection: "column",
          opacity: effSyncing ? 0.45 : 1,
          pointerEvents: effSyncing ? "none" : undefined,
          transition: "opacity 0.15s",
        }}
      >
        {/* Directional content-swap stage: clips the horizontal slide, keyed
            per mode so the incoming branch replays its slide-in. */}
        <div
          className="seg-swap"
          style={{ position: "relative", flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}
        >
        <div
          key={mode}
          className="seg-swap-panel"
          style={{ "--swap-dir": swapDir, flex: 1, minHeight: 0, display: "flex", flexDirection: "column" } as CSSProperties}
        >
        {mode === "search" ? (
          <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            {/* Search input row */}
            <div style={{ display: "flex", alignItems: "center", padding: compact ? "6px 12px" : "12px 14px", gap: 10, borderBottom: "1px solid var(--border)" }}>
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
                  fontSize: INPUT_STYLE.fontSize,
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

              {/* F-10: Semantic band beneath FTS results — retrieve_related
                  top-k, deduped against the FTS hits above by path. */}
              {query.trim() && dedupedSemantic.length > 0 && (
                <div style={{ marginTop: 4 }}>
                  <div style={{
                    fontSize: 10, color: "var(--text-3)", textTransform: "uppercase",
                    letterSpacing: "0.08em", padding: "8px 14px 4px",
                    borderTop: "1px solid var(--border-2)",
                  }}>
                    Semantic
                  </div>
                  {dedupedSemantic.map((s) => (
                    <div
                      key={s.path}
                      role="button"
                      tabIndex={0}
                      onClick={() => { openFilePath(s.path); onClose(); }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          openFilePath(s.path);
                          onClose();
                        }
                      }}
                      style={{
                        display: "flex", alignItems: "flex-start", gap: 10,
                        padding: "9px 14px", cursor: "pointer",
                      }}
                      className="row-hover-flat"
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {s.path.split(/[\\/]/).pop()}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {s.excerpt}
                        </div>
                      </div>
                      <span style={{ fontSize: 10, color: "var(--text-3)", flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>
                        {Math.round(s.similarity * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          /* Chat mode */
          <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            {/* Transcript */}
            <div
              ref={transcriptRef}
              style={{ flex: 1, overflowY: "auto", padding: compact ? "8px 10px" : "12px 14px", display: "flex", flexDirection: "column", gap: compact ? 5 : 10 }}
            >
              {messages.length === 0 && (
                <div style={{ textAlign: "center", fontSize: 13, color: "var(--text-3)", marginTop: 20 }}>
                  Prefix <code style={{ fontSize: 11 }}>/talk</code> for general knowledge
                </div>
              )}
              {messages.map((msg, i) => {
                const isUser = msg.role === "user";
                const isTalk = msg.chatMode === "talk";
                const isTyping = !isUser && streaming && msg.content === "" && i === messages.length - 1;
                const isSearching = !isUser && msg.searching && i === messages.length - 1;
                const isFailed = !isUser && msg.failed === true;
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
                    {isUser && isTalk && (
                      <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: "0.06em", color: "var(--text-3)", paddingRight: 2 }}>
                        GENERAL
                      </span>
                    )}
                    <div
                      style={{
                        maxWidth: "88%",
                        padding: compact ? "5px 9px" : "8px 12px",
                        borderRadius: "var(--radius-xl)",
                        background: isUser
                          ? (isTalk ? "var(--surface)" : "var(--accent)")
                          : "var(--surface)",
                        color: isUser
                          ? (isTalk ? "var(--text-1)" : "var(--on-accent)")
                          : "var(--text-1)",
                        border: isUser && isTalk ? "1px dashed var(--border)" : "none",
                        fontSize: compact ? 12 : 13,
                        lineHeight: 1.5,
                      }}
                    >
                      {isSearching ? (
                        <span style={{ color: "var(--text-3)", fontSize: 13 }}>Searching vault…</span>
                      ) : isTyping ? (
                        <span style={{ color: "var(--text-3)", fontSize: 16, letterSpacing: 2 }}>…</span>
                      ) : isUser ? (
                        msg.content
                      ) : isFailed ? (
                        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <AlertIcon size={12} />
                          {msg.content}
                        </span>
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
                    {/* Retry — failed assistant messages only */}
                    {isFailed && !isSearching && !isTyping && msg.userQuery && (
                      <button
                        onClick={() => retry(i)}
                        disabled={streaming}
                        title="Retry"
                        aria-label="Retry failed message"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                          fontSize: 10,
                          color: "var(--text-3)",
                          background: "none",
                          border: "none",
                          padding: "0 2px",
                          cursor: streaming ? "default" : "pointer",
                          opacity: streaming ? 0.5 : 1,
                          fontFamily: "inherit",
                        }}
                      >
                        <RefreshIcon size={11} />
                        Retry
                      </button>
                    )}
                    {/* Confidence badge for assistant messages */}
                    {!isUser && !isSearching && msg.tier && msg.tier !== "none" && !isTyping && (
                      <div style={{
                        fontSize: 9,
                        fontWeight: 600,
                        letterSpacing: "0.04em",
                        color: tierColor(msg.tier),
                        paddingLeft: 2,
                      }}>
                        {msg.tier === "talk"
                          ? tierLabel(msg.tier)
                          : `${tierLabel(msg.tier)} · ${Math.round((msg.confidence ?? 0) * 100)}%`}
                      </div>
                    )}
                    {/* Citation source chips — vault answers only */}
                    {!isUser && !isTalk && msg.sources && msg.sources.length > 0 && !isTyping && !isSearching && (
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
            {compact ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 3, padding: "3px 6px 4px", flexShrink: 0 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div
                    title="When on, each message is sent without prior conversation context"
                    style={{ display: "flex", alignItems: "center", gap: 6 }}
                  >
                    <Toggle checked={ignoreHistory} onChange={setIgnoreHistory} label="Ignore history" />
                    <span style={{ fontSize: 10, color: "var(--text-3)" }}>Ignore history</span>
                  </div>
                  <button
                    type="button"
                    onClick={reset}
                    disabled={messages.length === 0}
                    title="Clear chat"
                    aria-label="Clear chat"
                    style={{
                      ...BTN_SECONDARY,
                      fontSize: 10,
                      padding: "3px 8px",
                      flexShrink: 0,
                      opacity: messages.length === 0 ? 0.4 : 1,
                      cursor: messages.length === 0 ? "default" : "pointer",
                    }}
                  >
                    Clear
                  </button>
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input
                    ref={composerInputRef}
                    type="text"
                    aria-label="Ask a question about your vault"
                    value={composer}
                    onChange={(e) => setComposer(e.target.value)}
                    onKeyDown={handleComposerKey}
                    placeholder="Ask your vault"
                    disabled={streaming}
                    style={{
                      flex: 1,
                      height: 24,
                      boxSizing: "border-box",
                      background: "var(--surface)",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius)",
                      outline: "none",
                      color: "var(--text-1)",
                      fontSize: 11,
                      fontFamily: "inherit",
                      padding: "0 10px",
                      caretColor: "var(--accent)",
                      opacity: streaming ? 0.5 : 1,
                    }}
                  />
                  <button
                    onClick={handleSend}
                    disabled={streaming || !composer.trim()}
                    aria-label="Send"
                    style={{
                      width: 24,
                      height: 24,
                      boxSizing: "border-box",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      background: "var(--accent)",
                      color: "var(--on-accent)",
                      border: "none",
                      borderRadius: "var(--radius)",
                      padding: 0,
                      cursor: streaming || !composer.trim() ? "default" : "pointer",
                      opacity: streaming || !composer.trim() ? 0.4 : 1,
                      flexShrink: 0,
                    }}
                  >
                    <SendIcon size={13} />
                  </button>
                </div>
              </div>
            ) : (
              <div
                style={{
                  padding: "10px 14px",
                  borderTop: "1px solid var(--border)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  flexShrink: 0,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div
                    title="When on, each message is sent without prior conversation context"
                    style={{ display: "flex", alignItems: "center", gap: 6 }}
                  >
                    <Toggle checked={ignoreHistory} onChange={setIgnoreHistory} label="Ignore history" />
                    <span style={{ fontSize: 10, color: "var(--text-3)" }}>Ignore history</span>
                  </div>
                  <span style={{ fontSize: 10, color: "var(--text-3)", flex: 1 }}>
                    {ignoreHistory ? "Standalone query — prior turns skipped" : "Follow-ups use recent chat context"}
                  </span>
                  <button
                    type="button"
                    onClick={reset}
                    disabled={messages.length === 0}
                    title="Clear chat"
                    aria-label="Clear chat"
                    style={{
                      ...BTN_SECONDARY,
                      fontSize: 10,
                      padding: "3px 8px",
                      flexShrink: 0,
                      opacity: messages.length === 0 ? 0.4 : 1,
                      cursor: messages.length === 0 ? "default" : "pointer",
                    }}
                  >
                    Clear
                  </button>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    ref={composerInputRef}
                    type="text"
                    aria-label="Ask a question about your vault"
                    value={composer}
                    onChange={(e) => setComposer(e.target.value)}
                    onKeyDown={handleComposerKey}
                    placeholder="Ask your vault"
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
        )}
        </div>
        </div>
      </div>
    </div>
  );
}

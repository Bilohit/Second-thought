/**
 * CompactLook.tsx
 * ---------------
 * Compact Mode Menu Decoupling, Task 2.3: FULL-parity Look (search/chat)
 * content for the capsule's `CompactShell` body. Wraps embedded `LookPanel`
 * with the same controls FullWindow's topbar exposes for the Look view —
 * search/chat toggle, ignore-history, clear, reload indexing — just laid
 * out as a compact toolbar row above the panel instead of inline in a
 * shared topbar. GATE-3: no feature is dropped, only re-flowed for 288px.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import LookPanel from "../LookPanel";
import type { useLookChat } from "../../hooks/useLookChat";
import type { LookChatPersist } from "../../App";
import { syncVaultIndex } from "../../lib/api";
import SegmentedToggle from "../ui/SegmentedToggle";
import { BTN_SECONDARY } from "../ui/styles";

interface Props {
  lookMode: "search" | "chat";
  onSelectLookMode: (m: "search" | "chat") => void;
  lookChat: ReturnType<typeof useLookChat>;
  lookChatPersist: LookChatPersist;
  onClose: () => void;
}

export default function CompactLook({ lookMode, onSelectLookMode, lookChat, lookChatPersist, onClose }: Props) {
  // ponytail: handleRefresh is hand-duplicated from FullWindow.tsx's own
  // copy (and LookPanel's internal one) rather than lifted into a shared
  // hook — three call sites, same 15-line pattern, deliberate per
  // CLAUDE.md's main.py/server.py duplication convention. Cap: if a fourth
  // Look surface shows up, extract a `useVaultSync()` hook then.
  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  useEffect(() => () => { if (syncTimerRef.current) clearTimeout(syncTimerRef.current); }, []);

  const { messages, reset, ignoreHistory, setIgnoreHistory } = lookChat;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minWidth: 0 }}>
      {/* Compact toolbar: search/chat toggle + reload on one row, ignore
          history + clear on a second — 288px is too narrow for FullWindow's
          single-row topbar layout. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "8px 10px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <SegmentedToggle
            ariaLabel="Look mode"
            options={[{ key: "search" as const, label: "Search" }, { key: "chat" as const, label: "Chat" }]}
            value={lookMode}
            onChange={onSelectLookMode}
          />
          <span style={{ flex: 1 }} />
          <button
            className="btn-hover"
            onClick={handleRefresh}
            disabled={syncing}
            title="Sync vault index"
            aria-label="Sync vault index"
            style={{ opacity: syncing ? 0.5 : 1, display: "flex", alignItems: "center", justifyContent: "center", background: "transparent", border: "none", cursor: "pointer", padding: 4, color: "var(--text-2)" }}
          >
            <svg
              width="13" height="13" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round"
            >
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </button>
        </div>
        {lookMode === "chat" && (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              onClick={() => setIgnoreHistory(!ignoreHistory)}
              aria-pressed={ignoreHistory}
              title="When on, each message is sent without prior conversation context"
              style={{
                ...BTN_SECONDARY,
                fontSize: 10,
                padding: "3px 8px",
                flexShrink: 0,
                background: ignoreHistory ? "var(--accent)" : (BTN_SECONDARY.background as string),
                color: ignoreHistory ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                border: ignoreHistory ? "1px solid var(--accent)" : (BTN_SECONDARY.border as string),
                fontWeight: ignoreHistory ? 600 : 400,
              }}
            >
              Ignore history
            </button>
            <span style={{ flex: 1 }} />
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
        )}
      </div>

      {/* Sync banner (mirrors LookPanel's own, driven externally so it sits
          above the compact toolbar's second row rather than the panel's
          suppressed header). */}
      {syncing && (
        <div style={{ fontSize: 11, color: "var(--text-3)", borderBottom: "1px solid var(--border)", textAlign: "center", padding: "5px 10px", flexShrink: 0 }}>
          Syncing vault index…
        </div>
      )}
      {!syncing && syncStatus && (
        <div style={{ fontSize: 11, color: syncStatus.startsWith("Sync failed") ? "var(--red)" : "var(--text-3)", borderBottom: "1px solid var(--border)", textAlign: "center", padding: "5px 10px", flexShrink: 0 }}>
          {syncStatus}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0 }}>
        <LookPanel
          visible
          mode={lookMode}
          onSelectMode={onSelectLookMode}
          onClose={onClose}
          lookChat={lookChat}
          lookChatPersist={lookChatPersist}
          hideToggle
          embedded
          externalSyncing={syncing}
          externalSyncStatus={syncStatus}
        />
      </div>
    </div>
  );
}

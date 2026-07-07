/**
 * CompactLook.tsx
 * ---------------
 * Compact Mode Menu Decoupling, Task 2.3: FULL-parity Look (search/chat)
 * content for the capsule's `CompactShell` body. Wraps embedded `LookPanel`
 * with the same controls FullWindow's topbar exposes for the Look view.
 * Task 5 restructure: the toggle + refresh no longer render a toolbar row
 * inside this component's own body — they're forwarded up into
 * `CompactShell`'s header row (next to the "Look" title) via the
 * `onHeaderActionsChange` slot, the same B-pattern as CompactInbox/
 * CompactVault. The sync banner still renders here, above LookPanel's own
 * body. Ignore-history/Clear now live in LookPanel's compact composer
 * footer (see LookPanel.tsx's `compact` branch).
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import LookPanel from "../LookPanel";
import type { useLookChat } from "../../hooks/useLookChat";
import type { LookChatPersist } from "../../App";
import { syncVaultIndex } from "../../lib/api";
import SegmentedToggle from "../ui/SegmentedToggle";
import { BTN_GHOST } from "../ui/styles";
import { ChatIcon, SearchIcon, RefreshIcon } from "../PillMenu/icons";

interface Props {
  lookMode: "search" | "chat";
  onSelectLookMode: (m: "search" | "chat") => void;
  lookChat: ReturnType<typeof useLookChat>;
  lookChatPersist: LookChatPersist;
  onClose: () => void;
  /** B-pattern (CompactInbox/CompactVault): toggle + refresh render in
   *  CompactShell's header row next to the "Look" title. */
  onHeaderActionsChange?: (actions: ReactNode | null) => void;
}

export default function CompactLook({ lookMode, onSelectLookMode, lookChat, lookChatPersist, onClose, onHeaderActionsChange }: Props) {
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

  useEffect(() => {
    onHeaderActionsChange?.(
      <>
        <SegmentedToggle
          ariaLabel="Look mode"
          options={[
            { key: "search" as const, label: "Search", icon: <SearchIcon size={12} /> },
            { key: "chat" as const, label: "Chat", icon: <ChatIcon size={12} /> },
          ]}
          value={lookMode}
          onChange={onSelectLookMode}
        />
        <button
          className="btn-hover"
          onClick={handleRefresh}
          disabled={syncing}
          title="Refresh index"
          aria-label="Refresh index"
          style={{ ...BTN_GHOST, flexShrink: 0, opacity: syncing ? 0.5 : 1, cursor: syncing ? "default" : "pointer" }}
        >
          <RefreshIcon size={13} />
        </button>
      </>
    );
    return () => onHeaderActionsChange?.(null);
  }, [lookMode, onSelectLookMode, syncing, handleRefresh, onHeaderActionsChange]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minWidth: 0 }}>
      {/* Sync banner (mirrors LookPanel's own, driven externally so it sits
          above the panel body rather than the panel's suppressed header). */}
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
          compact
          externalSyncing={syncing}
          externalSyncStatus={syncStatus}
        />
      </div>
    </div>
  );
}

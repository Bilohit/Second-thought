import { useCallback, useEffect, useRef, useState } from "react";
import { streamLookChat, type LookSource, type LookTier } from "../lib/api";
import { parseLookChatInput, type LookChatMode } from "../lib/lookChatCommands";
import { logger } from "../lib/logger";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  chatMode?: LookChatMode;
  sources?: LookSource[];
  confidence?: number;
  tier?: LookTier;
  searching?: boolean;  // true while waiting for first meta/sources event
  /** Assistant messages only: set when this reply is a failure (SSE error
   *  event or transport-level throw) rather than a real answer — drives the
   *  Retry affordance. A real field, not a string-prefix sentinel, so a
   *  vault answer can never accidentally look like a failure. */
  failed?: boolean;
  /** Assistant messages only: the raw user query that produced this reply,
   *  so a failed message can be retried without re-typing. */
  userQuery?: string;
}

const IGNORE_HISTORY_KEY = "omni-look-ignore-history";

export function getInitialIgnoreHistory(): boolean {
  try {
    return localStorage.getItem(IGNORE_HISTORY_KEY) === "1";
  } catch { /* ignore */ }
  return false;
}

export function setIgnoreHistoryPref(enabled: boolean): void {
  try {
    localStorage.setItem(IGNORE_HISTORY_KEY, enabled ? "1" : "0");
  } catch { /* ignore */ }
}

// ISS-016: chat turns used to be memory-only (bare useState) and vanished on
// every app restart with no warning. Persist them to localStorage -- same
// storage the ignoreHistory flag already uses -- so a restart keeps the
// conversation. When the history policy is "ignore history" the user has
// already opted out of carrying context forward, so a fresh session starts
// empty rather than restoring a transcript that policy says to disregard.
const CHAT_MESSAGES_KEY = "omni-look-chat-messages";

export function loadPersistedMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(CHAT_MESSAGES_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ChatMessage[]) : [];
  } catch {
    return [];
  }
}

export function savePersistedMessages(messages: ChatMessage[]): void {
  try {
    if (messages.length === 0) {
      localStorage.removeItem(CHAT_MESSAGES_KEY);
    } else {
      localStorage.setItem(CHAT_MESSAGES_KEY, JSON.stringify(messages));
    }
  } catch { /* ignore */ }
}

/** Pure: what the hook should start with on mount, given the persisted
 *  ignoreHistory setting. Split out so it's testable without a renderer. */
export function getInitialMessages(ignoreHistory: boolean): ChatMessage[] {
  return ignoreHistory ? [] : loadPersistedMessages();
}

/** Message text for a transport-level failure (network drop, aborted fetch, etc).
 *  Bare text — failure state itself lives on `ChatMessage.failed`, not in this string. */
export function formatChatFailure(err: unknown): string {
  return `Chat failed: ${err instanceof Error ? err.message : "connection lost"}`;
}

/** Pure: resolves what `retry(index)` should do — the stored query to re-ask,
 *  and the message list with the failed assistant turn (and its paired user
 *  turn) dropped so ask() re-pushes a clean pair. Returns null when `index`
 *  isn't a retryable assistant message (no stored userQuery). Split out from
 *  the hook so it's testable without a React renderer (repo has no jsdom). */
export function getRetryTarget(
  messages: ChatMessage[],
  index: number
): { query: string; truncated: ChatMessage[] } | null {
  const msg = messages[index];
  if (!msg || msg.role !== "assistant" || !msg.userQuery) return null;
  return { query: msg.userQuery, truncated: messages.slice(0, Math.max(0, index - 1)) };
}

export function useLookChat() {
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    getInitialMessages(getInitialIgnoreHistory())
  );
  const [streaming, setStreaming] = useState(false);
  const [ignoreHistory, setIgnoreHistoryState] = useState(getInitialIgnoreHistory);
  const abortRef = useRef<AbortController | null>(null);
  // Set synchronously before the async body so two fast submits can't both
  // pass the guard -- the `streaming` state flag is still stale for the
  // second call at that point. Mirrors useCapture.ts's inFlightRef.
  const askingRef = useRef(false);

  const setIgnoreHistory = useCallback((enabled: boolean) => {
    setIgnoreHistoryState(enabled);
    setIgnoreHistoryPref(enabled);
    logger.debug("look", "ignore history toggled", { enabled });
  }, []);

  const ask = useCallback((q: string) => {
    const { question, mode } = parseLookChatInput(q);
    if (!question || streaming || askingRef.current) return;
    askingRef.current = true;
    const history = ignoreHistory
      ? []
      : messages.map((m) => ({ role: m.role, content: m.content })).slice(-6);
    logger.info("look", "ask", {
      questionLen: question.length,
      historyTurns: history.length,
      ignoreHistory,
      mode,
    });
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question, chatMode: mode },
      { role: "assistant", content: "", sources: [], searching: true, chatMode: mode, userQuery: q },
    ]);
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    // `reset()` does setMessages([]) — an event still in flight would then
    // index into an empty array and throw, killing the stream loop. Bail out
    // instead: there is no longer a message for this stream to update.
    const updateLast = (patch: Partial<ChatMessage>) =>
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const n = [...prev]; n[n.length - 1] = { ...n[n.length - 1], ...patch }; return n;
      });
    (async () => {
      try {
        for await (const ev of streamLookChat(
          mode === "talk" ? `/talk ${question}` : question,
          history,
          ctrl.signal,
          ignoreHistory,
        )) {
          if (ev.kind === "meta") {
            updateLast({ confidence: ev.confidence, tier: ev.tier, searching: false });
          } else if (ev.kind === "sources") {
            updateLast({ sources: ev.sources, searching: false });
          } else if (ev.kind === "token") {
            setMessages((prev) => {
              if (prev.length === 0) return prev; // reset() raced this token
              const n = [...prev];
              const a = n[n.length - 1];
              n[n.length - 1] = { ...a, content: a.content + ev.text, searching: false };
              return n;
            });
          } else if (ev.kind === "error") {
            logger.warn("look", "chat assistant error shown to user", { message: ev.message });
            updateLast({ content: ev.message, searching: false, failed: true });
          }
        }
      } catch (err) {
        if (ctrl.signal.aborted) {
          logger.debug("look", "chat aborted");
        } else {
          logger.error("look", "chat failed", err);
          updateLast({ content: formatChatFailure(err), searching: false, failed: true });
        }
      } finally { askingRef.current = false; setStreaming(false); abortRef.current = null; }
    })();
  }, [messages, streaming, ignoreHistory]);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  // Persist once a turn settles, not on every streamed token -- writing the
  // whole transcript to localStorage per token would be a lot of redundant
  // I/O for a long answer. A crash mid-stream can still lose that one
  // in-flight turn; that's an acceptable ceiling for what ISS-016 asks for
  // (survive a normal app restart, not a mid-generation kill).
  useEffect(() => {
    if (streaming) return;
    savePersistedMessages(messages);
  }, [messages, streaming]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    askingRef.current = false;
    setMessages([]);
    setStreaming(false);
    logger.debug("look", "chat reset");
  }, []);

  /** Re-sends the user query stored on a failed assistant message. */
  const retry = useCallback((index: number) => {
    const target = getRetryTarget(messages, index);
    if (!target) return;
    logger.info("look", "retry", { index });
    setMessages(target.truncated);
    ask(target.query);
  }, [messages, ask]);

  return { messages, streaming, ask, reset, retry, ignoreHistory, setIgnoreHistory };
}

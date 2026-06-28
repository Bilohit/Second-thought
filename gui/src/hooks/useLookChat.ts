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

export function useLookChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [ignoreHistory, setIgnoreHistoryState] = useState(getInitialIgnoreHistory);
  const abortRef = useRef<AbortController | null>(null);

  const setIgnoreHistory = useCallback((enabled: boolean) => {
    setIgnoreHistoryState(enabled);
    setIgnoreHistoryPref(enabled);
    logger.debug("look", "ignore history toggled", { enabled });
  }, []);

  const ask = useCallback((q: string) => {
    const { question, mode } = parseLookChatInput(q);
    if (!question || streaming) return;
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
      { role: "assistant", content: "", sources: [], searching: true, chatMode: mode },
    ]);
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const updateLast = (patch: Partial<ChatMessage>) =>
      setMessages((prev) => { const n = [...prev]; n[n.length - 1] = { ...n[n.length - 1], ...patch }; return n; });
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
              const n = [...prev];
              const a = n[n.length - 1];
              n[n.length - 1] = { ...a, content: a.content + ev.text, searching: false };
              return n;
            });
          } else if (ev.kind === "error") {
            logger.warn("look", "chat assistant error shown to user", { message: ev.message });
            updateLast({ content: `⚠ ${ev.message}`, searching: false });
          }
        }
      } catch (err) {
        if (ctrl.signal.aborted) {
          logger.debug("look", "chat aborted");
        } else {
          logger.error("look", "chat failed", err);
        }
      } finally { setStreaming(false); abortRef.current = null; }
    })();
  }, [messages, streaming, ignoreHistory]);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setStreaming(false);
    logger.debug("look", "chat reset");
  }, []);

  return { messages, streaming, ask, reset, ignoreHistory, setIgnoreHistory };
}

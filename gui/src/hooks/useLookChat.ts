import { useCallback, useRef, useState } from "react";
import { streamLookChat, type LookSource } from "../lib/api";

export interface ChatMessage { role: "user" | "assistant"; content: string; sources?: LookSource[]; }

export function useLookChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback((q: string) => {
    const question = q.trim();
    if (!question || streaming) return;
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: question },
                                     { role: "assistant", content: "", sources: [] }]);
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    (async () => {
      try {
        for await (const ev of streamLookChat(question, history, ctrl.signal)) {
          if (ev.kind === "sources") {
            setMessages((prev) => { const n = [...prev]; n[n.length - 1] = { ...n[n.length - 1], sources: ev.sources }; return n; });
          } else if (ev.kind === "token") {
            setMessages((prev) => { const n = [...prev]; const a = n[n.length - 1]; n[n.length - 1] = { ...a, content: a.content + ev.text }; return n; });
          } else if (ev.kind === "error") {
            setMessages((prev) => { const n = [...prev]; n[n.length - 1] = { ...n[n.length - 1], content: `⚠ ${ev.message}` }; return n; });
          }
        }
      } catch { /* aborted or network — leave partial */ }
      finally { setStreaming(false); abortRef.current = null; }
    })();
  }, [messages, streaming]);

  const reset = useCallback(() => { abortRef.current?.abort(); setMessages([]); setStreaming(false); }, []);
  return { messages, streaming, ask, reset };
}

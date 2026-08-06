import { useState, useRef, useCallback } from "react";

export interface ToastItem {
  id: string;
  tone: "success" | "error" | "info";
  message: string;
  action?: { label: string; run: () => void };
  /** Mutually-exclusive alternatives — the toast renders these as a chip row and
   *  picking one dismisses the toast. Added for the reminder date-mention offer,
   *  where the note's `remind_at` holds exactly one instant so the surface has to
   *  be a single choice among the detected dates (DECISIONS §5 s148.6). `action`
   *  is the single-option case and stays the shape every other toast uses; when
   *  both are set `choices` wins. */
  choices?: { label: string; run: () => void }[];
  ttlMs?: number;
}

const TTL: Record<ToastItem["tone"], number> = { success: 3000, error: 5000, info: 4000 };

let _id = 0;
function nextId() { return String(++_id); }

export function useToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    const t = timers.current.get(id);
    if (t !== undefined) { clearTimeout(t); timers.current.delete(id); }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback((toast: Omit<ToastItem, "id">) => {
    const id = nextId();
    setToasts((prev) => [...prev, { ...toast, id }]);
    timers.current.set(id, setTimeout(() => {
      timers.current.delete(id);
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, toast.ttlMs ?? TTL[toast.tone]));
  }, []);

  return { toasts, pushToast, dismiss };
}

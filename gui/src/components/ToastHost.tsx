import type { ToastItem } from "../hooks/useToasts";
import Toast from "./Toast";

interface Props {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}

export default function ToastHost({ toasts, onDismiss }: Props) {
  if (toasts.length === 0) return null;
  return (
    <div
      role="region"
      aria-label="Notifications"
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

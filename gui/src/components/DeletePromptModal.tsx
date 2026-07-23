// ISS-005 C follow-up B (desktop): interactive UI for a held cross-device DELETE-PROMPT (contract §6
// case 2) — a peer soft-deleted a note this desktop still holds; delete_detect.py keeps BOTH copies
// until the user picks. Shows one prompt at a time (deletePromptQueue.ts queues the rest); the scrim
// tap and the explicit Close both dismiss — NEVER a delete — "keep both, re-prompt later": a dismiss
// never calls the resolve endpoint, so the held prompt resurfaces on the next fetch/mount.
//
// Fetch-on-mount only (matches VaultManager's best-effort/non-blocking load pattern) — no polling;
// the modal is not the primary surface for every desktop session, and the resolve calls themselves
// refresh the list. Motion: fadeIn (used the same way in Toast/VaultManager); the global
// prefers-reduced-motion rule in index.css collapses it to an instant appear, no branch needed here.
import { useEffect, useState } from "react";
import {
  getDeletePrompts,
  resolveDeletePrompt,
  type DeletePromptChoice,
  type DeletePromptItem,
} from "../lib/api";
import { nextDeletePrompt, pruneDismissed } from "../lib/deletePromptQueue";
import { WarningTriangleIcon, CloseIcon } from "./PillMenu/icons";

export default function DeletePromptModal() {
  const [prompts, setPrompts] = useState<DeletePromptItem[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = () => {
    getDeletePrompts()
      .then(setPrompts)
      .catch(() => setPrompts([])); // best-effort, non-blocking — same contract as VaultManager's conflict badge fetch
  };
  useEffect(load, []);

  const current = nextDeletePrompt(prompts, (p) => p.note_id, dismissed);
  if (!current) return null;

  const dismiss = () => {
    setDismissed((prev) => {
      const pruned = pruneDismissed(prompts, (p) => p.note_id, prev);
      pruned.add(current.note_id);
      return pruned;
    });
  };

  const resolve = (choice: DeletePromptChoice) => {
    setBusy(true);
    resolveDeletePrompt(current.note_id, choice)
      .then(load)
      .catch(() => { /* leave it queued; the user can retry from the same prompt */ })
      .finally(() => setBusy(false));
  };

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "color-mix(in srgb, black 35%, transparent)",
        zIndex: 50,
        animation: "fadeIn 0.2s cubic-bezier(0.16,1,0.3,1) both",
      }}
    >
      <div
        role="alertdialog"
        aria-label="Note deleted on your other device"
        style={{
          width: 360,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "16px 18px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
          <span style={{ color: "var(--yellow)", display: "flex", marginTop: 1 }}>
            <WarningTriangleIcon size={15} />
          </span>
          <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: "var(--text-1)", letterSpacing: "0.01em" }}>
            Deleted on your other device
          </span>
          <button
            onClick={dismiss}
            disabled={busy}
            aria-label="Dismiss — keep both copies for now"
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-3)", padding: 2, display: "flex" }}
          >
            <CloseIcon size={14} />
          </button>
        </div>

        <span style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.5 }}>
          This note was deleted on your other device. Delete it here too, or keep it?
        </span>
        {/* No title is available from GET /trash/delete-prompts (note_id/kind/first_seen only, by
            contract — this pass consumes the endpoint as-is, never rebuilds it), so the id itself is
            the best identifier surfaced here. */}
        <span style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "monospace" }}>
          {current.note_id}
        </span>

        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          <button
            onClick={() => resolve("delete_both")}
            disabled={busy}
            style={{
              flex: 1,
              background: "none",
              border: "1px solid var(--red)",
              borderRadius: "var(--radius-sm)",
              color: "var(--red)",
              fontFamily: "inherit",
              fontSize: 12,
              padding: "7px 0",
              cursor: busy ? "default" : "pointer",
            }}
          >
            Delete on both
          </button>
          <button
            onClick={() => resolve("keep_here")}
            disabled={busy}
            style={{
              flex: 1,
              background: "none",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-1)",
              fontFamily: "inherit",
              fontSize: 12,
              padding: "7px 0",
              cursor: busy ? "default" : "pointer",
            }}
          >
            Keep here
          </button>
        </div>
        {(() => {
          const remaining = prompts.filter((p) => !dismissed.has(p.note_id)).length - 1;
          return remaining > 0 ? (
            <span style={{ fontSize: 10, color: "var(--text-3)", textAlign: "center" }}>
              +{remaining} more waiting
            </span>
          ) : null;
        })()}
      </div>
    </div>
  );
}

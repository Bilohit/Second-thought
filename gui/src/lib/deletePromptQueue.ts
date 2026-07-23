// ISS-005 C follow-up B (desktop): pure queue-selection logic for the cross-device DELETE-PROMPT
// surface. getDeletePrompts() (lib/api.ts) returns every note currently held under an unresolved
// prompt — a peer deleted it, this desktop still holds it (contract §6 case 2, non-destructive). The
// modal shows ONE at a time; this module picks which one, without owning any fetch/state itself.
//
// Dismiss is NEVER a resolve — "keep both, re-prompt later": `dismissed` is purely session-local UI
// state. An id in it is skipped for the rest of this mount, but the underlying held prompt is
// untouched server-side, so it resurfaces on the next fetch/mount — never a silent delete.

export function nextDeletePrompt<T>(
  items: readonly T[],
  idOf: (item: T) => string,
  dismissed: ReadonlySet<string>,
): T | null {
  for (const item of items) {
    if (!dismissed.has(idOf(item))) return item;
  }
  return null;
}

// Drop any dismissed id no longer present in the live `items` list (resolved meanwhile), so a
// long-lived session doesn't grow this set unboundedly.
export function pruneDismissed<T>(
  items: readonly T[],
  idOf: (item: T) => string,
  dismissed: ReadonlySet<string>,
): Set<string> {
  const live = new Set(items.map(idOf));
  const next = new Set<string>();
  for (const id of dismissed) if (live.has(id)) next.add(id);
  return next;
}

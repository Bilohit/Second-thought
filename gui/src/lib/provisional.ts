/**
 * provisional.ts
 * ---------------
 * Pure merge of a canonical row list with the LAN provisional overlay
 * (contract §11 / N2 LAN-sync). Provisional rows are staged, unconfirmed
 * copies of notes received over the same-WiFi LAN accelerator -- Drive +
 * headRevisionId remains the sole canonical authority (see workspace
 * CLAUDE.md "Shared locks"). This module never writes anything; it only
 * decides which rows to surface and flags provisional ones so the caller
 * can render them quietly and non-destructively.
 *
 * A provisional row is superseded (hidden) the moment a canonical row with
 * the same note_id exists -- "LAN NEVER writes canonical state ... always
 * superseded by the Drive copy" (Global Constraints).
 */

/** Minimal shape any canonical row must satisfy to participate in the merge. */
export interface CanonicalNoteRow {
  note_id?: string;
}

/** Mirrors provisional_store.list_provisional()'s per-row metadata (server.py GET /provisional). */
export interface ProvisionalRow {
  op_id: string;
  note_id: string;
  body_hash: string;
  staged_at: number;
  device: string;
  modified: string;
  path: string;
}

export type DisplayRow<T extends CanonicalNoteRow> =
  | (T & { provisional: false })
  | (ProvisionalRow & { provisional: true });

/**
 * Merge canonical rows with the provisional overlay. Provisional rows whose
 * note_id already appears among canonical rows are dropped (Drive canonical
 * supersedes the LAN-staged copy). Canonical rows lacking a note_id can
 * never supersede a provisional row -- absent data, not a false match.
 */
export function mergeProvisional<T extends CanonicalNoteRow>(
  canonical: T[],
  provisional: ProvisionalRow[],
): DisplayRow<T>[] {
  const canonicalIds = new Set(
    canonical
      .map((row) => row.note_id)
      .filter((id): id is string => Boolean(id)),
  );

  const canonicalRows: DisplayRow<T>[] = canonical.map((row) => ({
    ...row,
    provisional: false as const,
  }));

  const provisionalRows: DisplayRow<T>[] = provisional
    .filter((row) => !canonicalIds.has(row.note_id))
    .map((row) => ({ ...row, provisional: true as const }));

  return [...canonicalRows, ...provisionalRows];
}

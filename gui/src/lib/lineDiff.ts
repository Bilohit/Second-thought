/**
 * lineDiff.ts — pure line-level diff for the F-1 conflict resolver's
 * two-column view (mock 06-conflict-resolver.html: unchanged lines plain,
 * "yours"-only additions green-tinted, "theirs"-only additions red-tinted,
 * blank placeholders keep the two columns visually aligned row-for-row).
 *
 * Classic LCS alignment (O(n*m) DP) -- note bodies are small (tens to a few
 * hundred lines), so this is simple and fast enough; no diff library needed.
 */

export type DiffRowKind = "same" | "local-only" | "remote-only";

export interface DiffRow {
  kind: DiffRowKind;
  local: string | null;   // null = blank placeholder on this side
  remote: string | null;
}

function lcsTable(a: string[], b: string[]): number[][] {
  const n = a.length;
  const m = b.length;
  const table: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  return table;
}

export function diffLines(local: string, remote: string): DiffRow[] {
  const a = local.split("\n");
  const b = remote.split("\n");
  const table = lcsTable(a, b);
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      rows.push({ kind: "same", local: a[i], remote: b[j] });
      i++; j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      rows.push({ kind: "local-only", local: a[i], remote: null });
      i++;
    } else {
      rows.push({ kind: "remote-only", local: null, remote: b[j] });
      j++;
    }
  }
  while (i < a.length) { rows.push({ kind: "local-only", local: a[i], remote: null }); i++; }
  while (j < b.length) { rows.push({ kind: "remote-only", local: null, remote: b[j] }); j++; }
  return rows;
}

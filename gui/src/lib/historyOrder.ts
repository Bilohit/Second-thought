import type { VaultCategory } from "./api";
/** Live "By Category" rows: folder names + current file counts straight from
 *  the vault listing (source of truth), newest-engagement order preserved by
 *  count desc. Replaces the /stats SQLite snapshot for this metric. */
export function liveCategoryCounts(
  cats: VaultCategory[],
): { category: string; count: number }[] {
  return cats
    .filter((c) => !c.name.startsWith("_"))
    .map((c) => ({ category: c.name, count: c.file_count }))
    .sort((a, b) => b.count - a.count);
}

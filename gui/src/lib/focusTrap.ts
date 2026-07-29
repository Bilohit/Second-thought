/**
 * focusTrap.ts
 * ------------
 * Pure cyclic-index math for keyboard focus trapping inside the pill menu
 * (P1-5). RadialMenu's arrow-key nav already wraps an index array with
 * `(idx + offset + len) % len`; the Tab-trap needs the exact same wrap for
 * both RadialMenu (id-keyed positions) and CapsuleMenu (plain index array) —
 * one function, two call sites, so it earns extraction instead of living
 * inline twice.
 */

/** Next index in a 0..count-1 ring, stepping by `direction` (+1 forward,
 *  -1 backward) and wrapping past either end. Returns -1 for an empty ring. */
export function cyclicIndex(current: number, count: number, direction: 1 | -1): number {
  if (count <= 0) return -1;
  return (current + direction + count) % count;
}

/**
 * menuTiming.ts
 * -------------
 * Shared stagger-delay math for the capsule bar (§4) and the radial fan
 * (§5) — one coordinated timeline instead of three independent transition
 * durations. Pure, no DOM/Tauri imports.
 */

/** Per-item transitionDelay (ms) for `count` items revealing across
 *  `totalWindowMs`, each taking `itemDurMs` to play, so the *last* item
 *  finishes at (or just before) `totalWindowMs` instead of `totalWindowMs +
 *  itemDurMs` — the bug where icons kept entering long after the bar/window
 *  had already settled. Evenly spaced from delay 0 (first) to
 *  `totalWindowMs - itemDurMs` (last), clamped to 0 if the window is shorter
 *  than one item's own duration. */
export function staggerDelays(count: number, totalWindowMs: number, itemDurMs: number): number[] {
  if (count <= 0) return [];
  if (count === 1) return [0];
  const maxDelay = Math.max(0, totalWindowMs - itemDurMs);
  const step = maxDelay / (count - 1);
  return Array.from({ length: count }, (_, i) => Math.round(step * i));
}

/** Returns each item's rank (0 = first to animate) by ascending `y` —
 *  top-to-bottom — ties broken by original index for stability. Shared by
 *  the radial stagger fix (§5) and reusable anywhere "visual top-to-bottom
 *  order" differs from array order. */
export function rankByY<T>(items: T[], yOf: (item: T) => number): number[] {
  const indices = items.map((_, i) => i);
  indices.sort((a, b) => yOf(items[a]) - yOf(items[b]) || a - b);
  const rank = new Array<number>(items.length);
  indices.forEach((originalIndex, sortedPosition) => { rank[originalIndex] = sortedPosition; });
  return rank;
}

/** Total exit duration: the longest-delayed item's delay + its own play time
 *  + a small buffer, so a window/overlay never hides mid-exit. Replaces the
 *  `ALL_TARGETS.length`-derived constant, which silently went stale if
 *  ordering/stagger logic changed without anyone updating it (§8.2). */
export function exitDurationMs(count: number, animMs: number, staggerMs: number, bufferMs: number): number {
  if (count <= 1) return animMs + bufferMs;
  return animMs + (count - 1) * staggerMs + bufferMs;
}

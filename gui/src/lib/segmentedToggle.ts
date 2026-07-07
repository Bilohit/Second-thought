/**
 * segmentedToggle.ts
 * ------------------
 * Pure math for `ui/SegmentedToggle`'s sliding active-pill indicator and the
 * directional content-swap that pairs with it. Equal-width segments (the
 * toggle lays its options out on a `repeat(n, 1fr)` grid), so the active pill
 * is exactly one segment wide and translates in whole-segment steps; the
 * content-swap direction is just the sign of the segment-index delta.
 *
 * Kept side-effect-free with a sibling `segmentedToggle.test.ts` per the
 * repo's lib/*.ts convention.
 */

/** CSS width for the active pill: one of `count` equal segments, measured
 *  inside the toggle's 2px padding box (2px each side ⇒ 4px removed). */
export function indicatorWidth(count: number): string {
  const n = Math.max(1, count);
  return `calc((100% - 4px) / ${n})`;
}

/** translateX for the active pill: whole-segment steps expressed as a
 *  percentage of the pill's own (one-segment) width. A missing/invalid active
 *  index (-1, e.g. `value` matches no option) clamps to 0 so the pill never
 *  translates off-screen. */
export function indicatorTransform(activeIndex: number): string {
  const i = activeIndex < 0 ? 0 : activeIndex;
  return `translateX(${i * 100}%)`;
}

/** Content-swap slide direction from the previous segment index to the next:
 *    +1  forward  — new content enters from the right and slides left,
 *    -1  backward — new content enters from the left,
 *     0  unchanged / first mount — plain fade, no horizontal travel.
 *  Consumed as a CSS `--swap-dir` custom property multiplied into the
 *  keyframe's start offset. */
export function slideDirection(oldIndex: number, newIndex: number): -1 | 0 | 1 {
  if (newIndex === oldIndex) return 0;
  return newIndex > oldIndex ? 1 : -1;
}

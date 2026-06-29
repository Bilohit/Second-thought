/**
 * Computes the {translateY, height} for an absolutely-positioned slider
 * that sits behind `count` equal-height flex:1 buttons stacked vertically
 * inside a container of `containerHeight`, separated by `gapPx` gaps.
 * Mirrors CaptureOverlay's horizontal nav-slider, but vertical and for
 * N equal-height slots instead of N fixed-width icon slots.
 */
export function railSliderRect(
  selectedIndex: number,
  count: number,
  containerHeight: number,
  gapPx: number,
): { translateY: number; height: number } | null {
  if (selectedIndex < 0 || selectedIndex >= count) return null;
  const totalGap = gapPx * (count - 1);
  const buttonHeight = (containerHeight - totalGap) / count;
  const translateY = selectedIndex * (buttonHeight + gapPx);
  return { translateY, height: buttonHeight };
}

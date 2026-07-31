/** Measured slider rect from a button inside a relative-positioned track. */
export function railSliderFromElement(
  button: HTMLElement,
): { translateY: number; height: number } {
  return { translateY: button.offsetTop, height: button.offsetHeight };
}

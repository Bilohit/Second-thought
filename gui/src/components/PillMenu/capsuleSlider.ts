import { CAPSULE_PAD_X } from "./CapsuleMenu";

/** Slider rect for the hovered item, bleeding over the capsule pad at the ends. */
export function sliderRect(offsetLeft: number, offsetWidth: number, idx: number, count: number) {
  const isFirst = idx === 0;
  const isLast = idx === count - 1;
  return {
    left: offsetLeft - (isFirst ? CAPSULE_PAD_X : 0),
    width: offsetWidth + (isFirst ? CAPSULE_PAD_X : 0) + (isLast ? CAPSULE_PAD_X : 0),
  };
}

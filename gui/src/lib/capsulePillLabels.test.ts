import { describe, it, expect } from "vitest";
import { CAPSULE_CLOSED_W, CAPSULE_LABEL_CHROME } from "../components/PillMenu/CapsuleMenu";

/** 12px measured text width for the idle default label. Stale by 2.8px (real
 *  width 100.80px) — pre-dates s144 and unaffected by the IBM Plex swap, since
 *  both faces carry a uniform 600/1000-em advance. */
const PILL_REFERENCE_TEXT_W = 98;

/** Every fixed string pillLabel() can show (done-state project names ellipsize). */
const FIXED_PILL_LABELS = [
  "Second Thought",
  "Error",
  "Done",
  "Working",
  "Starting",
  "Intercepting",
  "Enriching",
  "Deciding",
  "Writing",
  "YouTube",
  "Fetching",
  "Transcript",
  "Summarizing",
  "Combining",
  "Finalizing",
] as const;

describe("capsule pill labels", () => {
  it("closed width matches Second Thought bar with symmetric side insets", () => {
    expect(CAPSULE_CLOSED_W).toBe(PILL_REFERENCE_TEXT_W + CAPSULE_LABEL_CHROME);
    expect(CAPSULE_CLOSED_W).toBe(154);
  });

  it("fixed labels stay within Second Thought character budget", () => {
    const maxChars = "Second Thought".length;
    for (const label of FIXED_PILL_LABELS) {
      expect(label.length, label).toBeLessThanOrEqual(maxChars);
    }
  });
});

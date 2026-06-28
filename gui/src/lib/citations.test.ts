import { it, expect } from "vitest";
import { parseCitations } from "./citations";

it("splits inline [n] markers into cite segments", () => {
  const segs = parseCitations("Async IO is fast [1]. See also [2][3].");
  expect(segs).toEqual([
    { text: "Async IO is fast " },
    { cite: 1 },
    { text: ". See also " },
    { cite: 2 },
    { cite: 3 },
    { text: "." },
  ]);
});

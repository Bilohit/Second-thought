import { describe, expect, it } from "vitest";
import { staggerDelays, rankByY, exitDurationMs } from "./menuTiming";

describe("staggerDelays", () => {
  it("spaces delays so the last item finishes at totalWindowMs", () => {
    const delays = staggerDelays(6, 260, 120);
    expect(delays[0]).toBe(0);
    expect(delays[delays.length - 1]).toBe(140); // 260 - 120
    expect(delays.length).toBe(6);
    for (let i = 1; i < delays.length; i++) expect(delays[i]).toBeGreaterThanOrEqual(delays[i - 1]);
  });

  it("clamps to 0 when the window is shorter than one item's duration", () => {
    const delays = staggerDelays(3, 50, 120);
    expect(delays.every((d) => d === 0)).toBe(true);
  });

  it("returns a single 0 delay for one item", () => {
    expect(staggerDelays(1, 260, 120)).toEqual([0]);
  });

  it("returns empty for zero items", () => {
    expect(staggerDelays(0, 260, 120)).toEqual([]);
  });
});

describe("rankByY", () => {
  it("ranks ascending y as 0 (top) to n-1 (bottom)", () => {
    const items = [{ y: 50 }, { y: -80 }, { y: 0 }];
    const ranks = rankByY(items, (it) => it.y);
    expect(ranks).toEqual([2, 0, 1]); // item0(y50)->rank2, item1(y-80)->rank0, item2(y0)->rank1
  });

  it("breaks ties by original index", () => {
    const items = [{ y: 0 }, { y: 0 }];
    expect(rankByY(items, (it) => it.y)).toEqual([0, 1]);
  });
});

describe("exitDurationMs", () => {
  it("derives from the actual max stagger rank, not a hardcoded count", () => {
    expect(exitDurationMs(6, 260, 45, 80)).toBe(260 + 5 * 45 + 80);
  });

  it("handles a single item", () => {
    expect(exitDurationMs(1, 260, 45, 80)).toBe(340);
  });
});

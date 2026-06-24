import { describe, expect, it } from "vitest";
import { createSpring, stepSpring, retarget } from "./spring";

// Overdamped (damping > 2*sqrt(stiffness)) so a zero-velocity start can never
// overshoot — used to assert monotonic settling.
const OVERDAMPED = { stiffness: 200, damping: 40 };
// Underdamped — used to prove inertia/overshoot when seeded with velocity.
const UNDERDAMPED = { stiffness: 200, damping: 10 };

describe("spring", () => {
  it("monotonically approaches and settles within N steps from rest", () => {
    let s = createSpring(0, 100);
    let prevDist = Math.abs(s.pos - s.target);
    let steps = 0;
    while (!s.settled && steps < 1000) {
      s = stepSpring(s, 1 / 60, OVERDAMPED);
      const dist = Math.abs(s.pos - s.target);
      expect(dist).toBeLessThanOrEqual(prevDist + 1e-6);
      prevDist = dist;
      steps++;
    }
    expect(s.settled).toBe(true);
    expect(steps).toBeLessThan(1000);
    expect(Math.abs(s.pos - 100)).toBeLessThan(1);
  });

  it("settled becomes true and stays true", () => {
    let s = createSpring(0, 100);
    for (let i = 0; i < 500 && !s.settled; i++) s = stepSpring(s, 1 / 60, OVERDAMPED);
    expect(s.settled).toBe(true);
    const next = stepSpring(s, 1 / 60, OVERDAMPED);
    expect(next.settled).toBe(true);
    expect(next.pos).toBe(s.pos);
  });

  it("seeding a release velocity overshoots before settling (inertia)", () => {
    let s = createSpring(0, 100, 800); // flung past the target
    let overshot = false;
    for (let i = 0; i < 1000 && !s.settled; i++) {
      s = stepSpring(s, 1 / 60, UNDERDAMPED);
      if (s.pos > 100) overshot = true;
    }
    expect(overshot).toBe(true);
    expect(s.settled).toBe(true);
  });

  it("retarget keeps velocity and clears settled", () => {
    let s = createSpring(0, 100);
    for (let i = 0; i < 500 && !s.settled; i++) s = stepSpring(s, 1 / 60, OVERDAMPED);
    const moved = retarget(s, 50);
    expect(moved.settled).toBe(false);
    expect(moved.target).toBe(50);
  });

  it("clamps a huge dt so a stalled frame can't tunnel past the target", () => {
    const s = createSpring(0, 100, 0);
    const stepped = stepSpring(s, 5, OVERDAMPED); // 5s "frame" after a stall
    expect(Number.isFinite(stepped.pos)).toBe(true);
    expect(Math.abs(stepped.pos)).toBeLessThan(1000);
  });
});

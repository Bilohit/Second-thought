/**
 * spring.ts
 * ---------
 * Dependency-free critically-dampable spring/inertia integrator
 * (for_sonnet.md §2). Used for window-geometry motion (drag fling,
 * edge snap) where a CSS transition can't apply (Tauri windows aren't
 * DOM nodes). Pure — no DOM/Tauri imports — so it's unit-testable and
 * reusable for both x and y independently.
 */

export interface SpringState {
  pos: number;
  vel: number;
  target: number;
  settled: boolean;
}

export interface SpringConfig {
  /** Stiffness — higher = snappier pull toward target. */
  stiffness: number;
  /** Damping — higher = less overshoot/oscillation. */
  damping: number;
  /** |pos - target| and |vel| below these counts as settled. */
  restDistance?: number;
  restVelocity?: number;
}

const DEFAULT_REST_DISTANCE = 0.5; // px
const DEFAULT_REST_VELOCITY = 0.5; // px/s
/** Clamp dt so a stalled rAF (tab backgrounded, breakpoint) can't fling the
 *  spring across the screen in one giant step. */
const MAX_DT = 1 / 30;

export function createSpring(pos: number, target: number, vel = 0): SpringState {
  return { pos, vel, target, settled: false };
}

/** Advances the spring by `dt` seconds toward `state.target`, returning a new
 *  state (does not mutate the input). Critically/under-damped depending on
 *  `damping` relative to `stiffness` — typical inertia-fling feel comes from
 *  seeding `vel` non-zero via `createSpring(pos, target, releaseVelocity)`. */
export function stepSpring(state: SpringState, dt: number, config: SpringConfig): SpringState {
  if (state.settled) return state;
  const clampedDt = Math.min(Math.max(dt, 0), MAX_DT);
  const restDistance = config.restDistance ?? DEFAULT_REST_DISTANCE;
  const restVelocity = config.restVelocity ?? DEFAULT_REST_VELOCITY;

  const displacement = state.pos - state.target;
  const springForce = -config.stiffness * displacement;
  const dampingForce = -config.damping * state.vel;
  const accel = springForce + dampingForce;

  const vel = state.vel + accel * clampedDt;
  const pos = state.pos + vel * clampedDt;

  const settled = Math.abs(pos - state.target) < restDistance && Math.abs(vel) < restVelocity;

  return settled
    ? { pos: state.target, vel: 0, target: state.target, settled: true }
    : { pos, vel, target: state.target, settled: false };
}

/** Retargets a live (possibly still-moving) spring without resetting velocity
 *  — e.g. the snap target changes mid-fling because the pointer crossed a
 *  monitor boundary. */
export function retarget(state: SpringState, target: number): SpringState {
  return { ...state, target, settled: false };
}

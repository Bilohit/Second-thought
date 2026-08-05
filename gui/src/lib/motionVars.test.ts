// @vitest-environment happy-dom
// Guards the ONE seam that a redesign can break silently: the hand-tuned morph
// durations. These tests are deliberately dumb — they assert literal numbers —
// because their job is to make an accidental change loud, not to model anything.
//
// If a test here fails, the correct response is almost never "update the
// expected value". These are the user's tuned values; a diff means someone
// changed the feel of the pill. Only change a number here together with an
// explicit decision to retune that motion.
import { describe, it, expect } from "vitest";
import { CAPSULE_ANIM_MS, CAPSULE_ITEM_PLAY_MS } from "../components/PillMenu/CapsuleMenu";
import { PANEL_ANIM_MS, PANEL_EXIT_MS, PANEL_CONTENT_LIFT_MS } from "./compactPanel";
import { MOTION_VARS, PANEL_CLOSE_LAG_MS, applyMotionVars } from "./motionVars";

describe("frozen morph durations", () => {
  // Measured against the live release binary on 2026-08-06 and recorded in the
  // Phase 0 motion baseline. Every one of these is a value the user set by feel.
  it("holds the tuned values", () => {
    expect(CAPSULE_ANIM_MS).toBe(260);
    expect(CAPSULE_ITEM_PLAY_MS).toBe(180);
    expect(PANEL_ANIM_MS).toBe(300);
    expect(PANEL_EXIT_MS).toBe(360);
    expect(PANEL_CONTENT_LIFT_MS).toBe(140);
  });

  // index.css encoded this as a bare 100ms with a comment reading "never raise
  // that constant instead of this delay". The relationship is now arithmetic:
  // the bar shrink lags so that lag + shrink lands exactly on the panel exit.
  it("derives the close lag so the bar shrink lands on the panel exit", () => {
    expect(PANEL_CLOSE_LAG_MS).toBe(100);
    expect(PANEL_CLOSE_LAG_MS + CAPSULE_ANIM_MS).toBe(PANEL_EXIT_MS);
  });
});

describe("MOTION_VARS", () => {
  it("carries the TS constants verbatim, with the ms unit CSS requires", () => {
    expect(MOTION_VARS["--capsule-bar-ms"]).toBe(`${CAPSULE_ANIM_MS}ms`);
    expect(MOTION_VARS["--capsule-item-ms"]).toBe(`${CAPSULE_ITEM_PLAY_MS}ms`);
    expect(MOTION_VARS["--panel-anim-ms"]).toBe(`${PANEL_ANIM_MS}ms`);
    expect(MOTION_VARS["--panel-lift-delay-ms"]).toBe(`${PANEL_CONTENT_LIFT_MS}ms`);
    expect(MOTION_VARS["--panel-close-lag-ms"]).toBe(`${PANEL_CLOSE_LAG_MS}ms`);
  });

  // The island waits for its rect morph to settle before revealing content, so
  // its content delay is the rect duration itself — not an independent number.
  it("ties the island content delay to the rect-morph duration", () => {
    expect(MOTION_VARS["--island-content-delay-ms"]).toBe(`${PANEL_ANIM_MS}ms`);
  });

  it("emits a unit on every value, or CSS silently drops the declaration", () => {
    for (const [name, value] of Object.entries(MOTION_VARS)) {
      expect(value, `${name} must carry a ms unit`).toMatch(/^\d+ms$/);
    }
  });
});

describe("applyMotionVars", () => {
  it("writes every property onto the target element", () => {
    const el = document.createElement("div");
    applyMotionVars(el);
    for (const [name, value] of Object.entries(MOTION_VARS)) {
      expect(el.style.getPropertyValue(name)).toBe(value);
    }
  });

  it("is idempotent", () => {
    const el = document.createElement("div");
    applyMotionVars(el);
    const first = el.getAttribute("style");
    applyMotionVars(el);
    expect(el.getAttribute("style")).toBe(first);
  });
});

import { describe, expect, it } from "vitest";
import { monitorToInfo, resolveTargetMonitor, type MonitorInfo } from "./monitor";
import type { Monitor } from "@tauri-apps/api/window";

function fakeMonitor(opts: { name: string | null; x: number; y: number; w: number; h: number; scale: number }): Monitor {
  return {
    name: opts.name,
    size: { width: opts.w, height: opts.h } as Monitor["size"],
    position: { x: opts.x, y: opts.y } as Monitor["position"],
    workArea: {
      position: { x: opts.x, y: opts.y } as Monitor["position"],
      size: { width: opts.w - 80, height: opts.h - 80 } as Monitor["size"],
    },
    scaleFactor: opts.scale,
  };
}

describe("monitorToInfo", () => {
  it("converts physical px to logical px using the monitor's own scale factor", () => {
    const m = fakeMonitor({ name: "DISPLAY1", x: 0, y: 0, w: 3840, h: 2160, scale: 2 });
    const info = monitorToInfo(m, 0, m);
    expect(info.workArea).toEqual({ x: 0, y: 0, w: 1880, h: 1040, scale: 2 });
    expect(info.label).toBe("DISPLAY1 1920x1080 (primary)");
  });

  it("detects primary by matching position against primaryMonitor(), not array order", () => {
    const secondary = fakeMonitor({ name: "DISPLAY1", x: -1920, y: 0, w: 1920, h: 1080, scale: 1 });
    const primary = fakeMonitor({ name: "DISPLAY2", x: 0, y: 0, w: 1920, h: 1080, scale: 1 });
    // secondary is index 0 in the array (left-of-primary, negative origin) —
    // primary detection must not assume index 0 is primary.
    const info = monitorToInfo(secondary, 0, primary);
    expect(info.isPrimary).toBe(false);
    expect(monitorToInfo(primary, 1, primary).isPrimary).toBe(true);
  });

  it("falls back to an index-based id/label when the OS reports no name", () => {
    const m = fakeMonitor({ name: null, x: 0, y: 0, w: 1920, h: 1080, scale: 1 });
    const info = monitorToInfo(m, 2, null);
    expect(info.id).toBe("monitor-2");
    expect(info.label).toBe("Monitor 3 1920x1080");
    expect(info.isPrimary).toBe(false);
  });

  it("handles negative-origin monitors (left-of-primary) without sign errors", () => {
    const m = fakeMonitor({ name: "LEFT", x: -1920, y: -200, w: 1920, h: 1080, scale: 1.5 });
    const info = monitorToInfo(m, 0, null);
    expect(info.workArea.x).toBeCloseTo(-1280, 5);
    expect(info.workArea.y).toBeCloseTo(-133.33, 1);
  });
});

describe("resolveTargetMonitor", () => {
  const primary: MonitorInfo = { id: "mon-1", label: "Monitor 1 (primary)", isPrimary: true, workArea: { x: 0, y: 0, w: 1920, h: 1080, scale: 1 } };
  const secondary: MonitorInfo = { id: "mon-2", label: "Monitor 2", isPrimary: false, workArea: { x: 1920, y: 0, w: 2560, h: 1440, scale: 1 } };
  const monitors = [primary, secondary];

  it("returns null when the monitor list hasn't loaded yet", () => {
    expect(resolveTargetMonitor([], "mon-2")).toBeNull();
  });

  it("returns the selected monitor when it's present", () => {
    expect(resolveTargetMonitor(monitors, "mon-2")).toBe(secondary);
  });

  it("falls back to primary, silently, when the selected id is unplugged", () => {
    expect(resolveTargetMonitor(monitors, "mon-3-unplugged")).toBe(primary);
  });

  it("falls back to primary when no selection has been made", () => {
    expect(resolveTargetMonitor(monitors, null)).toBe(primary);
  });
});

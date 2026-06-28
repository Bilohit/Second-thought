import { describe, it, expect, beforeEach, vi } from "vitest";
import { isGeoDebugEnabled, setGeoDebugEnabled, geoClamp } from "./geoLog";
import { logger } from "./logger";

// No jsdom dep in this repo (vitest runs node env) — stub the minimal
// localStorage surface geoLog.ts actually touches (getItem/setItem).
beforeEach(() => {
  const store = new Map<string, string>();
  (globalThis as any).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => store.set(k, v),
    removeItem: (k: string) => store.delete(k),
  };
});

describe("geo debug toggle", () => {
  it("defaults to disabled with no localStorage key set", () => {
    expect(isGeoDebugEnabled()).toBe(false);
  });

  it("setGeoDebugEnabled(true) enables", () => {
    setGeoDebugEnabled(true);
    expect(isGeoDebugEnabled()).toBe(true);
  });

  it("setGeoDebugEnabled(false) disables", () => {
    setGeoDebugEnabled(true);
    setGeoDebugEnabled(false);
    expect(isGeoDebugEnabled()).toBe(false);
  });
});

describe("geoClamp throttling for hot tags", () => {
  const clampArgs = {
    windowTopLeftLogical: { x: 0, y: 0 },
    monitorBounds: { x: 0, y: 0, w: 100, h: 100 },
    pillW: 10,
    pillH: 10,
    margin: 0,
    result: { x: 0, y: 0 },
  };

  it("drops back-to-back drag.tick calls within the throttle window", () => {
    setGeoDebugEnabled(true);
    const spy = vi.spyOn(logger, "info").mockImplementation(() => {});
    geoClamp("drag.tick", clampArgs);
    geoClamp("drag.tick", clampArgs);
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it("does not throttle a non-hot tag like restore", () => {
    setGeoDebugEnabled(true);
    const spy = vi.spyOn(logger, "info").mockImplementation(() => {});
    geoClamp("restore", clampArgs);
    geoClamp("restore", clampArgs);
    expect(spy).toHaveBeenCalledTimes(2);
    spy.mockRestore();
  });
});

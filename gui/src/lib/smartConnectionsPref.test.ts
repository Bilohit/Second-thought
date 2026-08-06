// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  SMART_CONNECTIONS_KEY,
  getSmartConnectionsPref,
  setSmartConnectionsPref,
  useSmartConnectionsPref,
} from "./smartConnectionsPref";

// happy-dom (opted in via the pragma above, same convention as InboxPanel.test.tsx) gives this file
// a real `localStorage` and a real DOM for `renderHook`, unlike the plain-node default environment
// most lib/*.test.ts files run under (see geoLog.test.ts's manual stub for that case).
beforeEach(() => {
  localStorage.clear();
  setSmartConnectionsPref(false);
});

describe("getSmartConnectionsPref / setSmartConnectionsPref", () => {
  it("reflects the last value set", () => {
    setSmartConnectionsPref(true);
    expect(getSmartConnectionsPref()).toBe(true);
    setSmartConnectionsPref(false);
    expect(getSmartConnectionsPref()).toBe(false);
  });

  it("persists to localStorage under the unmigrated s152 key", () => {
    setSmartConnectionsPref(true);
    expect(localStorage.getItem(SMART_CONNECTIONS_KEY)).toBe("1");
    setSmartConnectionsPref(false);
    expect(localStorage.getItem(SMART_CONNECTIONS_KEY)).toBe("0");
  });
});

describe("useSmartConnectionsPref (cross-surface live sync)", () => {
  it("a set from one mounted reader is seen by another mounted reader — the whole point of the module", () => {
    // Stands in for BrowseStarsView and SettingsPanel each holding their own hook instance.
    const browseStars = renderHook(() => useSmartConnectionsPref());
    const settingsPanel = renderHook(() => useSmartConnectionsPref());

    expect(browseStars.result.current[0]).toBe(false);
    expect(settingsPanel.result.current[0]).toBe(false);

    // Settings flips it — BrowseStarsView must update without a fetch, remount, or prop plumbing.
    act(() => {
      settingsPanel.result.current[1](true);
    });

    expect(settingsPanel.result.current[0]).toBe(true);
    expect(browseStars.result.current[0]).toBe(true);

    // And the reverse direction, sky -> settings.
    act(() => {
      browseStars.result.current[1](false);
    });
    expect(settingsPanel.result.current[0]).toBe(false);
  });

  it("unmounting one reader does not affect the other's subscription", () => {
    const a = renderHook(() => useSmartConnectionsPref());
    const b = renderHook(() => useSmartConnectionsPref());
    a.unmount();
    act(() => {
      b.result.current[1](true);
    });
    expect(b.result.current[0]).toBe(true);
  });

  it("initializes from whatever was already persisted", () => {
    setSmartConnectionsPref(true);
    const { result } = renderHook(() => useSmartConnectionsPref());
    expect(result.current[0]).toBe(true);
  });
});

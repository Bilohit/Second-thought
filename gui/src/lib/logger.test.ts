import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SENSITIVE_KEY_RE } from "./logger";

// GUI-XX: the "OFF" log level silenced the window error/unhandledrejection
// handlers, so a real crash left zero trace in console or on disk. Fix:
// emit() gained an opt-in force parameter that bypasses the level gate for
// the boot banner + the two global handlers, and a stored "OFF" now floors
// to ERROR on load so existing installs recover without user action.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue(undefined),
}));

/** GUI-20: the redaction key pattern. The regression that motivated the last
 *  alternative is the LAN secretbox key, whose field is literally named `key`
 *  — the original pattern matched `api_key` but not `key`, so the one
 *  credential that can decrypt LAN traffic was logged in the clear. */
describe("SENSITIVE_KEY_RE", () => {
  it("still matches everything it matched before", () => {
    for (const k of [
      "secret", "gui_secret", "token", "accessToken", "password",
      "authorization", "api_key", "api-key", "apiKey", "cookie",
    ]) {
      expect(SENSITIVE_KEY_RE.test(k), k).toBe(true);
    }
  });

  it("matches a field named exactly `key`, and its qualified forms", () => {
    for (const k of ["key", "Key", "lan_key", "lan-key", "key.id", "shared key"]) {
      expect(SENSITIVE_KEY_RE.test(k), k).toBe(true);
    }
  });

  it("does not over-match unrelated words containing 'key'", () => {
    for (const k of ["monkey", "keyboard", "keywords", "hotkey", "turkey"]) {
      expect(SENSITIVE_KEY_RE.test(k), k).toBe(false);
    }
  });

  it("leaves ordinary field names alone", () => {
    for (const k of ["path", "count", "status", "project", "bytes"]) {
      expect(SENSITIVE_KEY_RE.test(k), k).toBe(false);
    }
  });

  it("is stateless across calls (no /g flag)", () => {
    expect(SENSITIVE_KEY_RE.test("key")).toBe(true);
    expect(SENSITIVE_KEY_RE.test("key")).toBe(true);
  });
});

describe("forced emit vs. the level gate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("initLogger's boot banner is forced through even at a level above INFO", async () => {
    const { logger, initLogger, LogLevel } = await import("./logger");
    const { invoke } = await import("@tauri-apps/api/core");
    logger.setLevel(LogLevel.ERROR); // banner is INFO — would normally be gated out
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => {});
    try {
      initLogger();
      expect(infoSpy).toHaveBeenCalled(); // console sink reached despite the gate
      await logger.flush();
      expect(invoke).toHaveBeenCalledWith(
        "append_log",
        expect.objectContaining({ line: expect.stringContaining("Logger initialized") }),
      );
    } finally {
      infoSpy.mockRestore();
    }
  });

  it("an unforced record below the current threshold is still dropped", async () => {
    const { logger, LogLevel } = await import("./logger");
    logger.setLevel(LogLevel.ERROR);
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
    try {
      logger.debug("test", "should not appear — below ERROR and not forced");
      expect(debugSpy).not.toHaveBeenCalled();
    } finally {
      debugSpy.mockRestore();
    }
  });
});

// FR-15: cold launch's health-check poll can race the Python child's own
// boot and fail once, self-correcting on the next 3s poll — that's expected
// and must not log at the same level as a real, ongoing outage (see
// lib/api.ts's checkHealth, the sole caller of errorUnlessStartup).
describe("errorUnlessStartup()", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("logs at WARN inside the post-boot grace window", async () => {
    const { logger, initLogger, LogLevel } = await import("./logger");
    logger.setLevel(LogLevel.INFO); // undo any level a prior test left behind
    vi.setSystemTime(0);
    initLogger(); // sets bootTime = now (0)
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      vi.setSystemTime(2000); // 2s after boot — still within the grace window
      logger.errorUnlessStartup("api", "health check failed — server unreachable");
      expect(warnSpy).toHaveBeenCalled();
      expect(errorSpy).not.toHaveBeenCalled();
    } finally {
      warnSpy.mockRestore();
      errorSpy.mockRestore();
    }
  });

  it("escalates to ERROR once the grace window has passed — a real outage is never silenced", async () => {
    const { logger, initLogger, LogLevel } = await import("./logger");
    logger.setLevel(LogLevel.INFO); // undo any level a prior test left behind
    vi.setSystemTime(0);
    initLogger(); // sets bootTime = now (0)
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      vi.setSystemTime(11_000); // past the 10s grace window
      logger.errorUnlessStartup("api", "health check failed — server unreachable");
      expect(errorSpy).toHaveBeenCalled();
      expect(warnSpy).not.toHaveBeenCalled();
    } finally {
      warnSpy.mockRestore();
      errorSpy.mockRestore();
    }
  });
});

describe("initialLevel()", () => {
  it("floors a stored OFF to ERROR on load", async () => {
    const original = (globalThis as any).localStorage;
    (globalThis as any).localStorage = {
      getItem: (key: string) => (key === "second-thought:log-level" ? "OFF" : null),
      setItem: () => {},
    };
    try {
      vi.resetModules();
      const mod = await import("./logger");
      expect(mod.logger.getLevel()).toBe(mod.LogLevel.ERROR);
    } finally {
      if (original === undefined) delete (globalThis as any).localStorage;
      else (globalThis as any).localStorage = original;
      vi.resetModules();
    }
  });
});

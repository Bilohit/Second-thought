/**
 * logger.ts — Comprehensive, verbose logging for the Second Thought GUI.
 *
 * Responsibilities
 *   • Execution tracking — trace/debug/info through the app's logic flow.
 *   • Error management   — global capture of uncaught errors & rejections,
 *                          formatted (incl. stack) and logged at ERROR, with
 *                          an immediate (non-debounced) flush attempt since
 *                          these often precede a crash/force-kill.
 *   • Performance        — `time()` / `withTiming()` helpers that log durations
 *                          and flag anything slower than SLOW_MS as a bottleneck.
 *   • Tauri integration  — every record goes to the dev console AND is appended
 *                          to a rotating file on disk via the Rust `append_log`
 *                          command. Outside Tauri (plain `vite dev`) the file
 *                          sink degrades silently to console-only.
 *
 * Live-logging practices honored here: leveled + filterable, structured single
 * line per record, async non-blocking file flush (batched), bounded in-memory
 * queue (drop-oldest, so a dead file sink can't grow without bound), never
 * throws into caller code, and redacts known-sensitive keys / truncates large
 * payloads before anything is serialized.
 */

import { invoke } from "@tauri-apps/api/core";

export enum LogLevel {
  TRACE = 10,
  DEBUG = 20,
  INFO = 30,
  WARN = 40,
  ERROR = 50,
  SILENT = 100,
}

const LEVEL_NAME: Record<number, string> = {
  [LogLevel.TRACE]: "TRACE",
  [LogLevel.DEBUG]: "DEBUG",
  [LogLevel.INFO]: "INFO",
  [LogLevel.WARN]: "WARN",
  [LogLevel.ERROR]: "ERROR",
};

/** Operations slower than this (ms) are logged as performance bottlenecks. */
const SLOW_MS = 800;

/** Max file-flush batch wait (ms). Keeps disk writes off the hot path. */
const FLUSH_INTERVAL_MS = 400;

/** Hard cap on buffered (not-yet-flushed) lines. Past this we drop the
 *  oldest rather than let a stalled/dead file sink grow memory unbounded. */
const MAX_QUEUE_LINES = 5000;

/** Sensitive-looking keys get their value replaced before anything is logged. */
const SENSITIVE_KEY_RE = /secret|token|password|authorization|api[_-]?key|cookie/i;

/** Long string values (e.g. base64 image/clipboard payloads) are truncated. */
const MAX_VALUE_LEN = 2000;

const LOCAL_STORAGE_KEY = "second-thought:log-level";

// Verbose by default; tighten via VITE_LOG_LEVEL=DEBUG|INFO|WARN|ERROR at
// build time, or at runtime via logger.setLevel() (persisted across restarts
// in localStorage, e.g. from a Settings toggle) — no rebuild required.
function initialLevel(): LogLevel {
  try {
    const stored = typeof localStorage !== "undefined" ? localStorage.getItem(LOCAL_STORAGE_KEY) : null;
    if (stored && stored.toUpperCase() in LogLevel) {
      return LogLevel[stored.toUpperCase() as keyof typeof LogLevel] as LogLevel;
    }
  } catch { /* localStorage unavailable (e.g. private mode) */ }

  const env = (import.meta as any)?.env?.VITE_LOG_LEVEL as string | undefined;
  if (env && env.toUpperCase() in LogLevel) {
    return LogLevel[env.toUpperCase() as keyof typeof LogLevel] as LogLevel;
  }
  return LogLevel.TRACE;
}

// Human-readable single line by default; NDJSON via VITE_LOG_FORMAT=json for
// machine-parseable querying (e.g. `jq` over the merged log).
function initialFormat(): "text" | "json" {
  const env = (import.meta as any)?.env?.VITE_LOG_FORMAT as string | undefined;
  return env?.toLowerCase() === "json" ? "json" : "text";
}

let currentLevel: LogLevel = initialLevel();
const logFormat: "text" | "json" = initialFormat();

/** Correlation ID for the in-flight capture run, if any (see useCapture). */
let currentRunId: string | null = null;
export function setRunId(id: string | null) {
  currentRunId = id;
}

// ── Redaction ────────────────────────────────────────────────────────────────

function truncateStr(s: string): string {
  if (s.length <= MAX_VALUE_LEN) return s;
  return `${s.slice(0, MAX_VALUE_LEN)}…[truncated ${s.length - MAX_VALUE_LEN} chars]`;
}

/** Recursively redacts sensitive keys and truncates oversized string values. */
function redactValue(key: string | null, value: unknown): unknown {
  if (key && SENSITIVE_KEY_RE.test(key)) return "[REDACTED]";
  if (typeof value === "string") return truncateStr(value);
  if (Array.isArray(value)) return value.map((v) => redactValue(null, v));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = redactValue(k, v);
    }
    return out;
  }
  return value;
}

function safeErrorData(err: Error): { name: string; message: string; stack?: string } {
  return {
    name: err.name,
    message: truncateStr(err.message),
    stack: err.stack ? truncateStr(err.stack) : undefined,
  };
}

// ── File sink (Tauri) ────────────────────────────────────────────────────────

let queue: string[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let fileSinkEnabled = true; // disabled after first failed invoke (browser dev)

/** Lines lost to either queue overflow or a failed flush — surfaced once via
 *  console.warn so a silently-disabled file sink doesn't go unnoticed. */
let droppedLineCount = 0;
let droppedWarningShown = false;

function noteDropped(n: number, reason: string) {
  droppedLineCount += n;
  if (droppedWarningShown) return;
  droppedWarningShown = true;
  console.warn(
    `[logger] ${reason} — ${droppedLineCount} log line(s) lost so far. ` +
      `File sink: ${fileSinkEnabled ? "still active" : "disabled, console-only from now on"}.`,
  );
}

function pushToQueue(line: string) {
  queue.push(line);
  if (queue.length > MAX_QUEUE_LINES) {
    queue.shift();
    noteDropped(1, `in-memory log queue exceeded ${MAX_QUEUE_LINES} lines`);
  }
  scheduleFlush();
}

function scheduleFlush() {
  if (!fileSinkEnabled || flushTimer) return;
  flushTimer = setTimeout(flush, FLUSH_INTERVAL_MS);
}

async function flush() {
  flushTimer = null;
  if (!queue.length || !fileSinkEnabled) return;
  const batch = queue.join("\n");
  const sentCount = queue.length;
  queue = [];
  try {
    await invoke("append_log", { line: batch });
  } catch {
    // Not in Tauri (or command unavailable): stop trying, keep console output.
    fileSinkEnabled = false;
    noteDropped(sentCount, "file sink flush failed");
  }
}

/** Cancels any pending debounced flush and flushes immediately — used on
 *  crash-adjacent paths (uncaught error, unhandled rejection, beforeunload)
 *  where waiting out FLUSH_INTERVAL_MS risks losing the line to a force-kill. */
function flushNow() {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  void flush();
}

// ── Core ─────────────────────────────────────────────────────────────────────

function fmtData(data?: unknown): string {
  if (data === undefined) return "";
  if (data instanceof Error) {
    const safe = safeErrorData(data);
    return ` | ${safe.name}: ${safe.message}${safe.stack ? "\n" + safe.stack : ""}`;
  }
  try {
    return ` | ${JSON.stringify(redactValue(null, data))}`;
  } catch {
    return ` | ${String(data)}`;
  }
}

function buildLine(level: LogLevel, scope: string, message: string, data?: unknown): string {
  const ts = new Date().toISOString();
  const name = LEVEL_NAME[level] ?? "LOG";

  if (logFormat === "json") {
    const safeData =
      data === undefined ? undefined
      : data instanceof Error ? safeErrorData(data)
      : redactValue(null, data);
    return JSON.stringify({ ts, level: name, scope, message, data: safeData, runId: currentRunId ?? undefined });
  }

  const runTag = currentRunId ? ` [run:${currentRunId}]` : "";
  return `${ts} [${name}] [${scope}]${runTag} ${message}${fmtData(data)}`;
}

// Re-entrancy guard: if formatting/console/invoke ever calls back into the
// logger (e.g. an instrumented console override), drop the nested call
// instead of recursing — a failure inside the logger must stay console-only.
let emitting = false;

function emit(level: LogLevel, scope: string, message: string, data?: unknown) {
  if (level < currentLevel) return;
  if (emitting) {
    console.error("[logger] re-entrant log call suppressed:", scope, message);
    return;
  }
  emitting = true;
  try {
    const line = buildLine(level, scope, message, data);

    // Console sink — pick the matching method so devtools filtering works.
    const c =
      level >= LogLevel.ERROR ? console.error
      : level >= LogLevel.WARN ? console.warn
      : level >= LogLevel.INFO ? console.info
      : console.debug;
    c(line);

    // File sink — batched.
    if (fileSinkEnabled) {
      pushToQueue(line);
    }
  } finally {
    emitting = false;
  }
}

export const logger = {
  setLevel(level: LogLevel) {
    currentLevel = level;
    try { localStorage.setItem(LOCAL_STORAGE_KEY, LEVEL_NAME[level] ?? "TRACE"); } catch { /* ignore */ }
  },
  getLevel(): LogLevel { return currentLevel; },

  trace(scope: string, msg: string, data?: unknown) { emit(LogLevel.TRACE, scope, msg, data); },
  debug(scope: string, msg: string, data?: unknown) { emit(LogLevel.DEBUG, scope, msg, data); },
  info(scope: string, msg: string, data?: unknown)  { emit(LogLevel.INFO, scope, msg, data); },
  warn(scope: string, msg: string, data?: unknown)  { emit(LogLevel.WARN, scope, msg, data); },
  error(scope: string, msg: string, data?: unknown) { emit(LogLevel.ERROR, scope, msg, data); },

  /**
   * Start a performance timer. Call the returned fn to log the elapsed time;
   * durations over SLOW_MS are flagged as bottlenecks at WARN.
   */
  time(scope: string, label: string): (extra?: unknown) => number {
    const t0 = performance.now();
    emit(LogLevel.TRACE, scope, `▶ ${label}`);
    return (extra?: unknown) => {
      const ms = Math.round(performance.now() - t0);
      const slow = ms >= SLOW_MS;
      emit(
        slow ? LogLevel.WARN : LogLevel.DEBUG,
        scope,
        `■ ${label} took ${ms}ms${slow ? " (SLOW — possible bottleneck)" : ""}`,
        extra,
      );
      return ms;
    };
  },

  /** Wrap an async fn with timing + error logging. */
  async withTiming<T>(scope: string, label: string, fn: () => Promise<T>): Promise<T> {
    const stop = this.time(scope, label);
    try {
      const out = await fn();
      stop();
      return out;
    } catch (err) {
      stop({ failed: true });
      emit(LogLevel.ERROR, scope, `✖ ${label} threw`, err);
      throw err;
    }
  },

  /** Force a synchronous-ish flush (best effort). */
  flush() { return flush(); },

  /** Count of log lines lost to queue overflow or a failed file-sink flush. */
  getDroppedCount() { return droppedLineCount; },
};

// ── Global error capture ──────────────────────────────────────────────────────

let handlersInstalled = false;

function installGlobalHandlers() {
  if (handlersInstalled || typeof window === "undefined") return;
  handlersInstalled = true;

  window.addEventListener("error", (e: ErrorEvent) => {
    emit(LogLevel.ERROR, "window", "Uncaught error", e.error ?? e.message);
    flushNow(); // don't wait out the debounce — this may precede a crash/force-kill
  });

  window.addEventListener("unhandledrejection", (e: PromiseRejectionEvent) => {
    emit(LogLevel.ERROR, "window", "Unhandled promise rejection", e.reason);
    flushNow();
  });

  // beforeunload is unreliable for force-kills, but still worth attempting —
  // it's free insurance for the ordinary "user closed the window" case.
  window.addEventListener("beforeunload", () => { flushNow(); });
}

/** Call once at app boot. Installs global handlers and logs the startup banner. */
export function initLogger() {
  installGlobalHandlers();
  logger.info("app", "Logger initialized", {
    level: LEVEL_NAME[currentLevel] ?? currentLevel,
    format: logFormat,
    userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "n/a",
  });
}

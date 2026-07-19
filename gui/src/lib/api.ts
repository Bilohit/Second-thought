/**
 * api.ts - HTTP client for the Second Thought Python FastAPI server (localhost:7070).
 */

import { openPath } from "@tauri-apps/plugin-opener";
import { getGuiSecret } from "./tauri";
import { logger } from "./logger";

/** Open a file or folder with the OS default handler (cross-platform host API). */
// ponytail: $HOME/** scope; tighten to the live vault root if a user keeps notes outside home
export async function openFilePath(path: string): Promise<void> { await openPath(path); }
export async function openVaultPath(path: string): Promise<void> { await openPath(path); }

const BASE = "http://localhost:7070";

function parseSseFrame(frame: string): { ev: string; data: string } | null {
  let ev = "message", data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) ev = line.slice(7).trim();
    if (line.startsWith("data: ")) data = line.slice(6).trim();
  }
  return data ? { ev, data } : null;
}

async function assertOk(r: Response, fallback: string): Promise<Response> {
  if (r.ok) return r;
  const body = await r.json().catch(() => ({} as { detail?: string }));
  throw new Error(body.detail ?? fallback);
}

/** Headers carrying the shared secret. Every route except /health requires this. */
async function authHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  const secret = await getGuiSecret();
  return {
    "X-Log-Level": String(logger.getLevel()),
    ...(secret ? { "X-Omni-Secret": secret } : {}),
    ...extra,
  };
}

export type ContentType = "text" | "url" | "image_b64" | "audio_b64";
export type StepName = "intercept" | "enrich" | "decide" | "write";
export type StepStatus = "active" | "done" | "error";

export interface StepEvent {
  kind: "step";
  step: StepName;
  status: StepStatus;
}

export interface ThinkingEvent {
  kind: "thinking";
  rationale: string;
  key_signals: string[];
  confidence: number;
  category: string;
}

export interface DoneEvent {
  kind: "done";
  path: string;
  category: string;
}

export interface ErrorEvent {
  kind: "error";
  message: string;
}

export interface DuplicateEvent {
  kind: "duplicate";
}

export interface JobEvent {
  kind: "job";
  job_id: string;
  jobKind: string;
  status: string;
}

export interface ReminderOfferEvent {
  kind: "reminder_offer";
  events: { when_iso: string; label: string }[];
  note_path: string;
}

export type CaptureEvent = StepEvent | ThinkingEvent | DoneEvent | ErrorEvent | DuplicateEvent | JobEvent | ReminderOfferEvent;

export interface Reminder {
  id: number;
  note_path: string;
  label: string;
  fire_at: string;
  status: string;
  delivery: string;
}

export interface JobStatus {
  job_id: string;
  status: string;
  kind: string;
  category: string | null;
  path: string | null;
  error: string | null;
  chunk_index: number | null;
  chunk_total: number | null;
  detail: string | null;
}

export interface VaultCategory {
  name: string;
  file_count: number;
  path: string;
  description: string | null;  // from .category.toml; null if not set
}

export interface VaultFile {
  name: string;
  filename: string;
  path: string;
  size_bytes: number;
  modified: number;
  /** Task 2.6: server-authoritative hub-upload naming (mobile_sync_agent's
   *  _resolve_hub_names run over the note's folder). `hub_name` is the
   *  resolved filename; `name_clash` is true iff this note is the suffixed
   *  loser of a same-folder title collision. Never recompute this in TS. */
  hub_name: string;
  name_clash: boolean;
}

export interface Config {
  vault?: { root?: string };
  ollama?: { model?: string; base_url?: string };
  gui?: { hotkey?: string };
  capture?: {
    confidence_threshold?: number;
    llm_scrutiny?: "relaxed" | "balanced" | "strict";
    ocr_fast_path_enabled?: boolean;
    ocr_text_min_chars?: number;
    auto_describe_new_folders?: boolean;
  };
  look?: {
    chat_system_prompt?: string;
  };
  reminders?: {
    delivery?: "app" | "os";
  };
  // GET /config returns the raw TOML document, so the whole section is absent until
  // something writes it — every field here is optional and the caller falls back to
  // omni_capture/config.py:SyncConfig's defaults, never to a guess.
  sync?: {
    enabled?: boolean;
    interval_minutes?: number;   // 0 = the `Never` sentinel; >0 clamps to >= 5
    sync_on_launch?: boolean;
    sync_after_capture?: boolean;
    mirror_captures?: boolean;
  };
}

export interface InboxItem {
  note_id: string;
  filename: string;
  path: string;
  category: string;
  size: number;
  modified: number;
}

export interface Stats {
  total: number;
  by_category: { category: string; count: number; pct: number }[];
  by_day: { date: string; count: number }[];
  recent: SearchResult[];
}

export interface SearchResult {
  id: number;
  timestamp: string;
  category: string;
  path: string;
  filename: string | null;
  source_url: string | null;
  confidence: number;
  tags: string;
}

export type LlmStatus = "loading" | "ready" | "disconnected";

export async function checkHealth(): Promise<{ serverOk: boolean; llmStatus: LlmStatus }> {
  const stop = logger.time("api", "GET /health");
  try {
    const r = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) });
    stop({ status: r.status });
    if (!r.ok) {
      logger.warn("api", "health check returned non-OK", { status: r.status });
      return { serverOk: false, llmStatus: "disconnected" };
    }
    const body = await r.json() as { ok: boolean; ready: boolean; model_ok: boolean | null };
    let llmStatus: LlmStatus;
    if (!body.ready || body.model_ok === null) llmStatus = "loading";
    else if (body.model_ok === false) llmStatus = "disconnected";
    else llmStatus = "ready";
    return { serverOk: true, llmStatus };
  } catch (err) {
    stop({ failed: true });
    logger.error("api", "health check failed — server unreachable at " + BASE, err);
    return { serverOk: false, llmStatus: "disconnected" };
  }
}

export async function* streamCapture(
  contentType: ContentType,
  content: string,
  signal?: AbortSignal,
  runId?: string,
): AsyncGenerator<CaptureEvent> {
  const stop = logger.time("api", "POST /capture stream");
  logger.info("api", "capture started", { contentType, bytes: content.length, runId });
  const response = await fetch(`${BASE}/capture`, {
    method: "POST",
    headers: await authHeaders({
      "Content-Type": "application/json",
      ...(runId ? { "X-Capture-Run-Id": runId } : {}),
    }),
    body: JSON.stringify({ content_type: contentType, content }),
    signal,
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "unknown error");
    stop({ status: response.status });
    logger.error("api", "capture request failed", { status: response.status, body: text });
    throw new Error(`Server returned ${response.status}: ${text}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  let eventCount = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) { stop({ events: eventCount }); break; }
    eventCount++;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      if (!frame.trim()) continue;
      const f = parseSseFrame(frame);
      if (!f) continue;
      const { ev: eventType, data: dataLine } = f;
      try {
        const parsed = JSON.parse(dataLine);
        if (eventType === "step") {
          yield { kind: "step", step: parsed.step, status: parsed.status } as StepEvent;
        } else if (eventType === "thinking") {
          yield {
            kind: "thinking",
            rationale: parsed.rationale ?? "",
            key_signals: parsed.key_signals ?? [],
            confidence: parsed.confidence ?? 0.9,
            category: parsed.category ?? "",
          } as ThinkingEvent;
        } else if (eventType === "done") {
          yield { kind: "done", path: parsed.path, category: parsed.category } as DoneEvent;
        } else if (eventType === "error") {
          yield { kind: "error", message: parsed.message } as ErrorEvent;
        } else if (eventType === "duplicate") {
          yield { kind: "duplicate" } as DuplicateEvent;
        } else if (eventType === "job") {
          yield {
            kind: "job",
            job_id: parsed.job_id,
            jobKind: parsed.kind ?? "",
            status: parsed.status ?? "queued",
          } as JobEvent;
        } else if (eventType === "reminder_offer") {
          yield {
            kind: "reminder_offer",
            events: parsed.events ?? [],
            note_path: parsed.note_path ?? "",
          } as ReminderOfferEvent;
        }
      } catch { /* skip malformed frames */ }
    }
  }
}

/** Thrown by getJobStatus so callers can branch on the HTTP status (e.g. 404
 *  meaning the job registry entry expired -- see job_ttl_seconds). */
export class HttpError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = "HttpError";
  }
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const r = await fetch(`${BASE}/jobs/${encodeURIComponent(jobId)}`, { headers: await authHeaders() });
  if (!r.ok) throw new HttpError("Failed to fetch job status", r.status);
  return r.json();
}

export async function getConfig(): Promise<Config> {
  const r = await fetch(`${BASE}/config`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to fetch config");
  return r.json();
}

/** Stable desktop device-id for the v3 pairing QR (contract §11.4). Matches what the desktop
 *  advertises over mDNS + writes into .sync/lan_endpoint.json, so the phone can bind discovery to
 *  this desktop. */
// ── Sync + Drive auth (E6) ──────────────────────────────────────────────────
//
// Two planes, and the types keep them apart: Drive is the canonical one (nothing syncs without
// it), LAN pairing is an accelerator handled separately in tauri.ts. Failure here is normal, not
// exceptional — an un-authorized Drive makes every pass return ok:false — so the run/connect calls
// return a discriminated outcome instead of throwing, and the caller must render each case.

export type SyncPassRow = {
  started: string;
  finished: string;
  duration_s: number;
  ok: boolean;
  error?: string;
  // run_pass() merges its own summary counts in; they vary by pass and are display-only.
  [k: string]: unknown;
};

export type SyncStatus = {
  enabled: boolean;
  running: boolean;
  last_pass: SyncPassRow | null;
  last_error: string | null;
  history: SyncPassRow[];
  // Absent when the scheduler never started — server.py returns a reduced literal in that case,
  // so this is genuinely optional, not just nullable.
  interval_minutes?: number;
};

export type DriveAuthStatus = {
  connected: boolean;
  client_secret_present: boolean;
  connecting: boolean;
};

/** `ran` includes a FAILED pass — read `row.ok`, never assume the outcome means success. */
export type SyncRunResult =
  | { outcome: "ran"; row: SyncPassRow }
  | { outcome: "busy" }          // 409: a pass is already running
  | { outcome: "unavailable" }   // 503: scheduler not started
  | { outcome: "disabled" };     // 403: [sync] enabled = false — the master switch is off

export type DriveConnectResult =
  | { outcome: "connected" }
  | { outcome: "no_client_secret" }  // 400: setup problem, retrying cannot fix it
  | { outcome: "busy" }              // 409: a consent is already open
  | { outcome: "failed"; error: string };

export async function getSyncStatus(): Promise<SyncStatus> {
  const r = await fetch(`${BASE}/sync/status`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to fetch sync status");
  return r.json();
}

export async function runSync(): Promise<SyncRunResult> {
  const r = await fetch(`${BASE}/sync/run`, { method: "POST", headers: await authHeaders() });
  // Three distinct codes, three distinct client states — the master kill is refused
  // server-side (403), not merely hidden in the UI.
  if (r.status === 403) return { outcome: "disabled" };
  if (r.status === 409) return { outcome: "busy" };
  if (r.status === 503) return { outcome: "unavailable" };
  if (!r.ok) throw new Error("Failed to start a sync pass");
  return { outcome: "ran", row: await r.json() };
}

export async function getDriveAuthStatus(): Promise<DriveAuthStatus> {
  const r = await fetch(`${BASE}/drive/auth/status`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to fetch Drive auth status");
  return r.json();
}

/** Opens a real browser consent window server-side; resolves only once the user finishes or
 *  abandons it, so callers must keep a pending state up for as long as it takes. */
export async function connectDrive(): Promise<DriveConnectResult> {
  const r = await fetch(`${BASE}/drive/auth/connect`, { method: "POST", headers: await authHeaders() });
  if (r.status === 400) return { outcome: "no_client_secret" };
  if (r.status === 409) return { outcome: "busy" };
  if (!r.ok) {
    const detail = await r.json().then((b) => b?.detail).catch(() => null);
    return { outcome: "failed", error: typeof detail === "string" ? detail : "Drive connect failed" };
  }
  return { outcome: "connected" };
}

export async function disconnectDrive(): Promise<void> {
  const r = await fetch(`${BASE}/drive/auth/disconnect`, { method: "POST", headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to disconnect Drive");
}

export async function getLanDeviceId(): Promise<string> {
  const r = await fetch(`${BASE}/lan/device-id`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to fetch device id");
  return (await r.json()).device as string;
}

export async function patchConfig(patch: {
  vault_root?: string;
  ollama_model?: string;
  ollama_base_url?: string;
  hotkey?: string;
  confidence_threshold?: number;
  llm_scrutiny?: "relaxed" | "balanced" | "strict";
  ocr_fast_path_enabled?: boolean;
  ocr_text_min_chars?: number;
  auto_describe_new_folders?: boolean;
  chat_system_prompt?: string;
  reminders_delivery?: "app" | "os";
  // [sync] — the server has accepted these since phase-5; the GUI had no consumer, which is why
  // Drive sync was only enablable by hand-editing config.toml (E6).
  sync_enabled?: boolean;
  sync_interval_minutes?: number;   // server clamps to >= 5
  sync_on_launch?: boolean;
  sync_after_capture?: boolean;
  sync_mirror_captures?: boolean;   // K-2: opt-in capture mirroring to the hub
}): Promise<void> {
  const r = await fetch(`${BASE}/config`, {
    method: "PATCH",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error("Failed to save config");
}

export async function getVaultCategories(): Promise<{ categories: VaultCategory[]; vault_root: string }> {
  const r = await fetch(`${BASE}/vault/categories`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to list vault categories");
  return r.json();
}

export async function createVaultCategory(name: string): Promise<void> {
  const r = await fetch(`${BASE}/vault/categories`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name }),
  });
  await assertOk(r, "Failed to create category");
}

export async function renameVaultCategory(oldName: string, newName: string): Promise<void> {
  const r = await fetch(`${BASE}/vault/categories/${encodeURIComponent(oldName)}`, {
    method: "PATCH",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ new_name: newName }),
  });
  await assertOk(r, "Failed to rename category");
}

export async function updateCategoryDescription(
  name: string,
  description: string | null,
): Promise<void> {
  const r = await fetch(
    `${BASE}/vault/categories/${encodeURIComponent(name)}/description`,
    {
      method: "PATCH",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ description }),
    },
  );
  await assertOk(r, "Failed to update description");
}

export async function deleteVaultCategory(name: string, force = false): Promise<void> {
  const r = await fetch(
    `${BASE}/vault/categories/${encodeURIComponent(name)}?force=${force}`,
    { method: "DELETE", headers: await authHeaders() },
  );
  await assertOk(r, "Failed to delete category");
}

export async function getVaultCategoryFiles(
  category: string,
): Promise<{ category: string; files: VaultFile[] }> {
  const r = await fetch(`${BASE}/vault/categories/${encodeURIComponent(category)}/files`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error("Failed to list files");
  return r.json();
}

export async function searchCaptures(
  q: string,
  opts?: { category?: string; since?: string; limit?: number },
): Promise<{ results: SearchResult[]; count: number; query: string }> {
  const stop = logger.time("look", "GET /search");
  logger.debug("look", "search query", { q, ...opts });
  const params = new URLSearchParams({ q });
  if (opts?.category) params.set("category", opts.category);
  if (opts?.since) params.set("since", opts.since);
  if (opts?.limit) params.set("limit", String(opts.limit));
  try {
    const r = await fetch(`${BASE}/search?${params.toString()}`, { headers: await authHeaders() });
    if (!r.ok) {
      stop({ status: r.status });
      logger.error("look", "search request failed", { status: r.status, q });
      throw new Error("Search failed");
    }
    const data = await r.json();
    stop({ count: data.count });
    logger.debug("look", "search results", { count: data.count, query: data.query });
    return data;
  } catch (err) {
    stop({ failed: true });
    logger.error("look", "search failed", err);
    throw err;
  }
}

export async function getStats(): Promise<Stats> {
  const r = await fetch(`${BASE}/stats`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to fetch stats");
  return r.json();
}

export async function getInbox(): Promise<{ inbox: InboxItem[]; count: number }> {
  const r = await fetch(`${BASE}/inbox`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to fetch inbox");
  return r.json();
}

export interface DigestStats { captured: number; touched: number; reminders_due: number; unrevisited: number; }

export async function getDigestToday(): Promise<DigestStats> {
  const r = await fetch(`${BASE}/digest/today`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to fetch digest");
  return r.json();
}

/** LAN provisional overlay row (contract §11) -- mirrors provisional_store.list_provisional(). */
export interface ProvisionalItem {
  op_id: string;
  note_id: string;
  body_hash: string;
  staged_at: number;
  device: string;
  modified: string;
  path: string;
}

export async function getProvisional(): Promise<{ provisional: ProvisionalItem[]; count: number }> {
  const r = await fetch(`${BASE}/provisional`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Failed to fetch provisional items");
  return r.json();
}

export async function approveInboxItem(noteId: string, targetCategory?: string): Promise<{ ok: boolean; path: string }> {
  const r = await fetch(`${BASE}/inbox/${encodeURIComponent(noteId)}/approve`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ target_category: targetCategory ?? null }),
  });
  await assertOk(r, "Failed to approve item");
  return r.json();
}

export async function suggestCategories(noteId: string): Promise<{ suggestions: string[] }> {
  const r = await fetch(`${BASE}/inbox/${encodeURIComponent(noteId)}/suggest-categories`, {
    headers: await authHeaders(),
  });
  await assertOk(r, "Failed to suggest categories");
  return r.json();
}

export async function discardInboxItem(noteId: string): Promise<void> {
  const r = await fetch(`${BASE}/inbox/${encodeURIComponent(noteId)}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  await assertOk(r, "Failed to discard item");
}

export async function listReminders(): Promise<Reminder[]> {
  const r = await fetch(`${BASE}/reminders`, { headers: await authHeaders() });
  await assertOk(r, "Failed to fetch reminders");
  const data = await r.json() as { reminders: Reminder[] };
  return data.reminders;
}

export async function createReminder(notePath: string, label: string, whenIso: string, notify = false): Promise<number> {
  const r = await fetch(`${BASE}/reminders`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ note_path: notePath, label, when_iso: whenIso, notify }),
  });
  await assertOk(r, "Failed to create reminder");
  const data = await r.json() as { id: number };
  return data.id;
}

export async function deleteReminder(id: number): Promise<void> {
  const r = await fetch(`${BASE}/reminders/${encodeURIComponent(String(id))}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  await assertOk(r, "Failed to delete reminder");
}

export interface LookSource { n: number; path: string; category: string; filename: string; snippet: string; }
export type LookTier = "high" | "none" | "talk";
export type LookChatEvent =
  | { kind: "meta"; confidence: number; tier: LookTier; answerable: boolean }
  | { kind: "sources"; sources: LookSource[] }
  | { kind: "token"; text: string }
  | { kind: "done" }
  | { kind: "error"; message: string };

// Mirrors vault_sync.SyncResult (server /vault/sync-index). The heal/re-embed fields are
// additive and currently ignored by the GUI; typed here so a future "index was corrupt and
// rebuilt" surfacing has the shape available (OF-20). Optional so an older server still typechecks.
export interface VaultSyncResult { added: number; removed: number; updated: number; skipped: number; reembedded?: number; healed?: boolean; vectors_healed?: boolean; dedup_rebuilt?: boolean; error?: string | null; }

export async function syncVaultIndex(): Promise<VaultSyncResult> {
  const res = await fetch(`${BASE}/vault/sync-index`, {
    method: "POST",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`sync-index ${res.status}`);
  return res.json();
}

export async function* streamLookChat(
  question: string,
  history: { role: string; content: string }[],
  signal?: AbortSignal,
  ignoreHistory = false,
): AsyncGenerator<LookChatEvent> {
  const stop = logger.time("look", "POST /look/chat stream");
  logger.info("look", "chat started", {
    questionLen: question.length,
    historyTurns: ignoreHistory ? 0 : history.length,
    ignoreHistory,
  });
  const response = await fetch(`${BASE}/look/chat`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ question, history: ignoreHistory ? [] : history, ignore_history: ignoreHistory }),
    signal,
  });
  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "unknown error");
    stop({ status: response.status });
    logger.error("look", "chat request failed", { status: response.status, body: text });
    throw new Error(`Server returned ${response.status}: ${text}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let tokenCount = 0;
  let sourceCount = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      stop({ tokenCount, sourceCount });
      logger.debug("look", "chat stream finished", { tokenCount, sourceCount });
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      if (!frame.trim()) continue;
      const f = parseSseFrame(frame);
      if (!f) continue;
      try {
        const p = JSON.parse(f.data);
        const ev = f.ev;
        if (ev === "meta") {
          logger.debug("look", "chat meta", { confidence: p.confidence, tier: p.tier });
          yield { kind: "meta", confidence: p.confidence ?? 0, tier: p.tier ?? "none", answerable: p.answerable ?? false };
        } else if (ev === "sources") {
          sourceCount = (p.sources ?? []).length;
          logger.debug("look", "chat sources", {
            count: sourceCount,
            paths: (p.sources ?? []).map((s: LookSource) => s.path),
          });
          yield { kind: "sources", sources: p.sources ?? [] };
        } else if (ev === "token") {
          tokenCount++;
          yield { kind: "token", text: p.text ?? "" };
        } else if (ev === "done") {
          logger.debug("look", "chat done event");
          yield { kind: "done" };
        } else if (ev === "error") {
          logger.error("look", "chat stream error", { message: p.message ?? "error" });
          yield { kind: "error", message: p.message ?? "error" };
        }
      } catch { /* skip malformed */ }
    }
  }
}

// -- Full-window note editor (F-7) -------------------------------------------

export interface NoteContent {
  path: string;
  title: string;
  category: string;
  status: string | null;
  tags: string[];
  body: string;
  mtime: number;
  has_frontmatter: boolean;
}

/** Thrown by saveNoteContent when the file changed on disk since it was
 *  read (see note_editor.py's mtime-guard) -- the caller must surface this
 *  and reload, never silently retry-clobber (body-sacred lock). */
export class NoteConflictError extends Error {
  currentMtime: number;
  currentBody: string;
  constructor(currentMtime: number, currentBody: string) {
    super("Note changed on disk since it was opened.");
    this.name = "NoteConflictError";
    this.currentMtime = currentMtime;
    this.currentBody = currentBody;
  }
}

export async function getNoteContent(path: string): Promise<NoteContent> {
  const r = await fetch(`${BASE}/note?${new URLSearchParams({ path }).toString()}`, {
    headers: await authHeaders(),
  });
  await assertOk(r, "Failed to load note");
  return r.json();
}

export async function saveNoteContent(path: string, body: string, expectedMtime: number): Promise<{ mtime: number }> {
  const r = await fetch(`${BASE}/note`, {
    method: "PUT",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ path, body, expected_mtime: expectedMtime }),
  });
  if (r.status === 409) {
    const payload = await r.json().catch(() => ({} as { detail?: { current_mtime?: number; current_body?: string } }));
    const detail = payload.detail ?? {};
    throw new NoteConflictError(detail.current_mtime ?? expectedMtime, detail.current_body ?? "");
  }
  await assertOk(r, "Failed to save note");
  return r.json();
}

// -- F-3: version history (Drive revisions) ----------------------------------

export type NoteHistoryStatus = "ok" | "offline" | "not_synced";

export interface NoteRevision {
  id: string;
  modified_time: string | null;
  size: number;
  author: string | null;
  current: boolean;
}

export async function getNoteHistory(path: string): Promise<{ status: NoteHistoryStatus; revisions: NoteRevision[] }> {
  const r = await fetch(`${BASE}/note/history?${new URLSearchParams({ path }).toString()}`, {
    headers: await authHeaders(),
  });
  await assertOk(r, "Failed to load history");
  return r.json();
}

export async function getNoteHistoryRevision(path: string, revisionId: string): Promise<{ body: string }> {
  const r = await fetch(`${BASE}/note/history/revision?${new URLSearchParams({ path, revision_id: revisionId }).toString()}`, {
    headers: await authHeaders(),
  });
  await assertOk(r, "Failed to load revision");
  return r.json();
}

// -- F-4: tags browser --------------------------------------------------------

export interface TagNode {
  tag: string;
  count: number;
  recent: string[];
  children: TagNode[];
}

export async function getTagTree(): Promise<{ tags: TagNode[] }> {
  const r = await fetch(`${BASE}/tags`, { headers: await authHeaders() });
  await assertOk(r, "Failed to load tags");
  return r.json();
}

// -- F-1: conflict resolver (desktop) -----------------------------------------

export interface NoteConflict {
  conflict_path: string;
  local_body: string;
  remote_body: string;
  remote_device: string | null;
  remote_modified: string | null;
  local_mtime: number;
}

export type ConflictResolveAction = "both" | "mine" | "theirs";

export async function getNoteConflict(path: string): Promise<NoteConflict | null> {
  const r = await fetch(`${BASE}/note/conflict?${new URLSearchParams({ path }).toString()}`, {
    headers: await authHeaders(),
  });
  await assertOk(r, "Failed to check conflict");
  const data = await r.json() as { conflict: NoteConflict | null };
  return data.conflict;
}

// expectedMtime is the NoteConflict.local_mtime read when the diff was opened;
// "theirs" overwrites the note body so the server guards on it and 409s
// (NoteConflictError) if the note was edited on disk since — reload, don't clobber.
export async function resolveNoteConflict(
  path: string,
  conflictPath: string,
  action: ConflictResolveAction,
  expectedMtime?: number,
): Promise<void> {
  const r = await fetch(`${BASE}/note/conflict/resolve`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ path, conflict_path: conflictPath, action, expected_mtime: expectedMtime }),
  });
  if (r.status === 409) {
    const detail = (await r.json().catch(() => ({}))).detail ?? {};
    throw new NoteConflictError(detail.current_mtime ?? expectedMtime ?? 0, detail.current_body ?? "");
  }
  await assertOk(r, "Failed to resolve conflict");
}

export interface VaultConflictEntry { path: string; conflict_path: string; title: string; }

export async function getVaultConflicts(): Promise<VaultConflictEntry[]> {
  const r = await fetch(`${BASE}/vault/conflicts`, { headers: await authHeaders() });
  await assertOk(r, "Failed to check vault conflicts");
  const data = await r.json() as { conflicts: VaultConflictEntry[] };
  return data.conflicts;
}

// -- F-2: Trash (desktop) ------------------------------------------------------

export interface TrashItem {
  filename: string;
  title: string;
  category: string;
  deleted_at: number;
  purge_at: number;
}

export async function getTrash(): Promise<TrashItem[]> {
  const r = await fetch(`${BASE}/trash`, { headers: await authHeaders() });
  await assertOk(r, "Failed to list trash");
  const data = await r.json() as { items: TrashItem[] };
  return data.items;
}

export async function restoreFromTrash(filename: string): Promise<{ ok: boolean; category: string; path: string }> {
  const r = await fetch(`${BASE}/trash/restore`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ filename }),
  });
  await assertOk(r, "Failed to restore note");
  return r.json();
}

// -- F-5: per-note sync-ignore (desktop-local) ---------------------------------

export async function getSyncIgnore(): Promise<string[]> {
  const r = await fetch(`${BASE}/sync/ignore`, { headers: await authHeaders() });
  await assertOk(r, "Failed to load sync-ignore list");
  const data = await r.json() as { ignored: string[] };
  return data.ignored;
}

export async function setSyncIgnore(path: string, ignored: boolean): Promise<string[]> {
  const r = await fetch(`${BASE}/sync/ignore`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ path, ignored }),
  });
  await assertOk(r, "Failed to update sync-ignore");
  const data = await r.json() as { ignored: string[] };
  return data.ignored;
}

// -- F-10: semantic search band ------------------------------------------------

export interface SemanticResult {
  path: string;
  similarity: number;
  excerpt: string;
  category: string | null;
}

export async function getSemanticSearch(q: string, limit = 5): Promise<SemanticResult[]> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  const r = await fetch(`${BASE}/search/semantic?${params.toString()}`, { headers: await authHeaders() });
  if (!r.ok) return [];
  const data = await r.json() as { results: SemanticResult[] };
  return data.results;
}

// -- F-13 (desktop half): attachments ------------------------------------------

/** URL for inline display (image `<img src>` / audio `<audio src>`) — the
 *  browser/webview issues this GET itself, so no auth header is attached;
 *  matches how other file surfaces (openFilePath) already work locally. */
export function attachmentUrl(notePath: string, filename: string): string {
  const params = new URLSearchParams({ path: notePath, filename });
  return `${BASE}/note/attachment?${params.toString()}`;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

export async function addNoteAttachment(
  path: string,
  file: File,
  expectedMtime: number,
): Promise<{ filename: string; mtime: number }> {
  const buf = new Uint8Array(await file.arrayBuffer());
  const r = await fetch(`${BASE}/note/attachment`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      path,
      filename: file.name,
      data_b64: bytesToBase64(buf),
      expected_mtime: expectedMtime,
    }),
  });
  if (r.status === 409) {
    const payload = await r.json().catch(() => ({} as { detail?: { current_mtime?: number; current_body?: string } }));
    const detail = payload.detail ?? {};
    throw new NoteConflictError(detail.current_mtime ?? expectedMtime, detail.current_body ?? "");
  }
  await assertOk(r, "Failed to attach file");
  return r.json();
}

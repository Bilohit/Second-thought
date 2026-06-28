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

export type ContentType = "text" | "url" | "image_b64";
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

export type CaptureEvent = StepEvent | ThinkingEvent | DoneEvent | ErrorEvent | DuplicateEvent | JobEvent;

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

export async function checkHealth(): Promise<boolean> {
  const stop = logger.time("api", "GET /health");
  try {
    const r = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) });
    stop({ status: r.status });
    if (!r.ok) logger.warn("api", "health check returned non-OK", { status: r.status });
    return r.ok;
  } catch (err) {
    stop({ failed: true });
    logger.error("api", "health check failed — server unreachable at " + BASE, err);
    return false;
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

export interface LookSource { n: number; path: string; category: string; filename: string; snippet: string; }
export type LookTier = "high" | "none" | "talk";
export type LookChatEvent =
  | { kind: "meta"; confidence: number; tier: LookTier; answerable: boolean }
  | { kind: "sources"; sources: LookSource[] }
  | { kind: "token"; text: string }
  | { kind: "done" }
  | { kind: "error"; message: string };

export interface VaultSyncResult { added: number; removed: number; updated: number; skipped: number; }

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

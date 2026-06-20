/**
 * api.ts - HTTP client for the Second Thought Python FastAPI server (localhost:7070).
 */

import { getGuiSecret } from "./tauri";
import { logger } from "./logger";

const BASE = "http://localhost:7070";

/** Headers carrying the shared secret. Every route except /health requires this. */
async function authHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  const secret = await getGuiSecret();
  return secret ? { "X-Omni-Secret": secret, ...extra } : { ...extra };
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
      let eventType = "message";
      let dataLine = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) eventType = line.slice(7).trim();
        if (line.startsWith("data: ")) dataLine = line.slice(6).trim();
      }
      if (!dataLine) continue;
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
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to create category");
  }
}

export async function renameVaultCategory(oldName: string, newName: string): Promise<void> {
  const r = await fetch(`${BASE}/vault/categories/${encodeURIComponent(oldName)}`, {
    method: "PATCH",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ new_name: newName }),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to rename category");
  }
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
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to update description");
  }
}

export async function deleteVaultCategory(name: string, force = false): Promise<void> {
  const r = await fetch(
    `${BASE}/vault/categories/${encodeURIComponent(name)}?force=${force}`,
    { method: "DELETE", headers: await authHeaders() },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to delete category");
  }
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
  const params = new URLSearchParams({ q });
  if (opts?.category) params.set("category", opts.category);
  if (opts?.since) params.set("since", opts.since);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const r = await fetch(`${BASE}/search?${params.toString()}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error("Search failed");
  return r.json();
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
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to approve item");
  }
  return r.json();
}

export async function discardInboxItem(noteId: string): Promise<void> {
  const r = await fetch(`${BASE}/inbox/${encodeURIComponent(noteId)}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to discard item");
  }
}

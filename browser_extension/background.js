/**
 * background.js — Second Thought Service Worker (Manifest V3)
 *
 * Responsibilities:
 *   1. Register a right-click context menu entry ("Send to Second Thought").
 *   2. Handle the context-menu click: POST {url, title, selection} to the
 *      local Second Thought /share endpoint and show a badge result.
 *   3. Expose a message listener so popup.js can also trigger a capture.
 */

const DEFAULT_SERVER = "http://localhost:7070";
const ENDPOINT = "/share";

// ── Context menu ─────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "second-thought-selection",
    title: "Send selection to Second Thought",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "second-thought-page",
    title: "Send page to Second Thought",
    contexts: ["page", "link"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url       = info.linkUrl || info.pageUrl || tab?.url || "";
  const title     = tab?.title || "";
  const selection = info.selectionText || "";
  await _sendToSecondThought({ url, title, selection });
});

// ── Message listener (from popup.js) ─────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "CAPTURE") {
    _sendToSecondThought(msg.payload).then(sendResponse);
    return true; // keep channel open for async response
  }
});

// ── Core sender ───────────────────────────────────────────────────────────────

async function _sendToSecondThought({ url, title, selection }) {
  const { serverUrl = DEFAULT_SERVER, secret = "" } =
    await chrome.storage.sync.get(["serverUrl", "secret"]);

  const headers = { "Content-Type": "application/json" };
  if (secret) headers["X-Omni-Secret"] = secret;

  try {
    const resp = await fetch(`${serverUrl}${ENDPOINT}`, {
      method: "POST",
      headers,
      body: JSON.stringify({ url, title, selection }),
    });

    if (!resp.ok) {
      const text = await resp.text();
      _setBadge("✗", "#e53e3e");
      return { ok: false, error: text };
    }

    // Consume the SSE stream to find the final "done" or "error" event.
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let result = null;
    let buffer = "";
    let eventName = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep the (possibly incomplete) last line for next read

      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          try {
            const parsed = JSON.parse(line.slice(5).trim());
            if (eventName === "step") {
              chrome.runtime.sendMessage({ type: "STEP", step: parsed.step, status: parsed.status }).catch(() => {});
            }
            if (eventName === "job") result = { ok: true, queued: true, jobId: parsed.job_id, kind: parsed.kind };
            if (eventName === "duplicate") result = { ok: true, duplicate: true };
            if (parsed.path) result = { ok: true, path: parsed.path, category: parsed.category };
            if (parsed.message) result = { ok: false, error: parsed.message };
          } catch (_) {}
        } else if (line === "") {
          eventName = "";
        }
      }
    }

    if (result?.ok) {
      _setBadge("✓", "#38a169");
    } else {
      _setBadge("✗", "#e53e3e");
    }
    return result || { ok: false, error: "No response from server" };

  } catch (err) {
    _setBadge("✗", "#e53e3e");
    return { ok: false, error: String(err) };
  }
}

function _setBadge(text, color) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
  // Auto-clear badge after 4 seconds.
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
}

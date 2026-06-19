/**
 * popup.js — Second Thought Extension Popup
 *
 * Loads the current tab URL + selected text, lets the user edit the
 * selection, then fires a capture via the background service worker.
 */

const $ = (id) => document.getElementById(id);

const STEPS = ["intercept", "enrich", "decide", "write"];

// ── Initialise ────────────────────────────────────────────────────────────────

async function init() {
  // Load current tab URL
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.url) $("page-url").value = tab.url;

  // Try to get selected text from the page
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.getSelection()?.toString() || "",
    });
    if (result) $("selection").value = result;
  } catch (_) { /* restricted pages */ }

  // Load saved settings
  const { serverUrl = "http://localhost:7070", secret = "" } =
    await chrome.storage.sync.get(["serverUrl", "secret"]);
  $("server-url").value = serverUrl;
  $("secret-input").value = secret;

  // Check server reachability
  try {
    const resp = await fetch(`${serverUrl}/health`, {
      headers: secret ? { "X-Omni-Secret": secret } : {},
    });
    if (resp.ok) $("dot").classList.add("connected");
  } catch (_) {}
}

// ── Capture ───────────────────────────────────────────────────────────────────

$("btn-capture").addEventListener("click", async () => {
  const url       = $("page-url").value.trim();
  const selection = $("selection").value.trim();
  const title     = document.title || "";

  if (!url) {
    setStatus("No URL detected for this page.", "err");
    return;
  }

  $("btn-capture").disabled = true;
  $("steps").style.display = "block";
  STEPS.forEach(s => setStep(s, "pending"));
  setStatus("Sending to Second Thought…");

  const response = await chrome.runtime.sendMessage({
    type: "CAPTURE",
    payload: { url, title, selection },
  });

  $("btn-capture").disabled = false;

  if (response?.ok) {
    setStatus(`✓ Captured → ${response.category || "vault"}`, "ok");
  } else {
    setStatus(`✗ ${response?.error || "Unknown error"}`, "err");
  }
});

// ── Settings ──────────────────────────────────────────────────────────────────

$("btn-settings").addEventListener("click", () => {
  const panel = $("settings-panel");
  panel.style.display = panel.style.display === "none" ? "block" : "none";
});

$("btn-save").addEventListener("click", async () => {
  const serverUrl = $("server-url").value.trim() || "http://localhost:7070";
  const secret    = $("secret-input").value.trim();
  await chrome.storage.sync.set({ serverUrl, secret });
  setStatus("Settings saved.", "ok");
  $("settings-panel").style.display = "none";
});

// ── SSE step tracker (via background messages) ────────────────────────────────

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "STEP")    setStep(msg.step, msg.status);
  if (msg.type === "DONE")    setStatus(`✓ ${msg.category}`, "ok");
  if (msg.type === "ERROR")   setStatus(`✗ ${msg.message}`, "err");
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function setStep(name, status) {
  const el = $(`step-${name}`);
  if (!el) return;
  el.className = `step-row ${status}`;
}

function setStatus(msg, cls = "") {
  const el = $("status");
  el.textContent = msg;
  el.className = cls;
}

// ── Boot ──────────────────────────────────────────────────────────────────────
init();

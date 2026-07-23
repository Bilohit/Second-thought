/**
 * loopback.js — GUI-03: the one place that decides whether a configured
 * `serverUrl` is allowed to receive the X-Omni-Secret.
 *
 * The settings form takes a free-text server URL, and background.js attaches
 * X-Omni-Secret to whatever it names. `manifest.json`'s host_permissions
 * (`http://localhost:7070/*`) already blocks most of the damage, but it fails
 * as an opaque network error rather than a stated refusal, and it is one
 * manifest edit away from not being a boundary at all. Validate explicitly.
 *
 * Loaded by both entry points (importScripts in the MV3 service worker, a
 * plain <script> in popup.html) so there is exactly one implementation — the
 * extension has no build step, so this is the only way to share it.
 */

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

/** True iff `raw` is an http(s) URL pointing at this machine's loopback interface. */
function isLoopbackUrl(raw) {
  let u;
  try {
    u = new URL(raw);
  } catch (_) {
    return false;
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return false;
  // Credentials in the authority (`http://localhost@evil.com/`) are the classic
  // way to make a URL *read* as loopback while resolving elsewhere.
  if (u.username || u.password) return false;
  return LOOPBACK_HOSTS.has(u.hostname.toLowerCase());
}

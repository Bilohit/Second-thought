/**
 * pathGuard.ts — containment check for paths handed to the OS opener.
 *
 * `openFilePath` passes a server-returned path straight to Tauri's
 * `openPath`, which launches it with the OS default handler. The Tauri
 * capability scope (`$HOME/**`) is the outer fence; this is the inner one:
 * only paths under the live vault root are openable, so a path that reached
 * the UI from anywhere other than the vault can never be launched.
 *
 * Pure and platform-agnostic: separators are normalised, comparison is
 * case-insensitive (Windows is the shipping target and its filesystem is), and
 * containment is checked on a separator boundary so `/vault-backup` is not
 * treated as living inside `/vault`.
 */

/** Normalise separators, strip a trailing separator, and casefold. */
function normalize(p: string): string {
  const slashed = p.replace(/\\/g, "/").replace(/\/+$/, "");
  return slashed.toLowerCase();
}

/**
 * True when `path` is `root` itself or lies beneath it.
 *
 * Returns false for an empty root or path, and for any path containing a `..`
 * segment — resolving those is the OS's job, and a traversal that survives to
 * this point is exactly what the check exists to reject.
 */
export function isInsideRoot(root: string, path: string): boolean {
  if (!root || !path) return false;
  const r = normalize(root);
  const p = normalize(path);
  if (!r || !p) return false;
  if (p.split("/").includes("..")) return false;
  return p === r || p.startsWith(r + "/");
}

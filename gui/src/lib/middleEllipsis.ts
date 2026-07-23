/**
 * middleEllipsis.ts — pure single-line middle-truncation for long paths.
 *
 * ISS-026: the vault-root path header previously relied on CSS
 * `wordBreak: "break-all"` to fit a narrow header at 125%/150% display
 * scale, which wraps mid-word ("STORA/GE") across two lines instead of
 * eliding. This truncates the middle of the string by character count so
 * the start (drive/root) and end (leaf folder — the most identifying part
 * of a vault path) both stay legible on a single line.
 */

/**
 * Truncate `text` to at most `maxChars` characters, removing a middle
 * span and replacing it with a single ellipsis. The head keeps one more
 * character than the tail when the remainder is odd, favoring the more
 * recognizable path start.
 *
 * Returns `text` unchanged when it already fits or `maxChars` is too
 * small to do anything useful (<= 1): unabbreviated is more useful than
 * misleadingly cut. `maxChars <= 0` is treated as "no limit" is wrong —
 * callers pass a real budget, so an implausible one degrades to no-op
 * rather than throwing.
 */
export function middleEllipsis(text: string, maxChars: number): string {
  if (maxChars <= 1 || text.length <= maxChars) return text;
  const ELLIPSIS = "…";
  const keep = maxChars - ELLIPSIS.length;
  if (keep <= 0) return ELLIPSIS;
  const headLen = Math.ceil(keep / 2);
  const tailLen = Math.floor(keep / 2);
  return text.slice(0, headLen) + ELLIPSIS + (tailLen > 0 ? text.slice(text.length - tailLen) : "");
}

// ponytail: fixed 10-min cap; move to config.toml [whisper] if users hit it.
export const MAX_RECORDING_MS = 10 * 60_000;
export function shouldAutoStop(elapsedMs: number): boolean { return elapsedMs >= MAX_RECORDING_MS; }
export function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

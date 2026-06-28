/** Strip optional `/strict` prefix (case-insensitive) from Look chat input. */
export function parseStrictPrefix(input: string): { question: string; strict: boolean } {
  const q = input.trim();
  if (!q.toLowerCase().startsWith("/strict")) {
    return { question: q, strict: false };
  }
  const rest = q.slice("/strict".length).trimStart();
  return { question: rest, strict: true };
}

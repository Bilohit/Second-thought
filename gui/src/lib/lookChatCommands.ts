export type LookChatMode = "vault" | "talk";

const TALK_PREFIX = "/talk";

/** Parse Look chat input: default vault (strict RAG); `/talk` enables general knowledge. */
export function parseLookChatInput(input: string): { question: string; mode: LookChatMode } {
  const q = input.trim();
  if (!q.toLowerCase().startsWith(TALK_PREFIX)) {
    return { question: q, mode: "vault" };
  }
  const rest = q.slice(TALK_PREFIX.length).trimStart();
  return { question: rest, mode: "talk" };
}

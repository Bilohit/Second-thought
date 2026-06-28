export type Segment = { text: string } | { cite: number };
const CITE = /\[(\d+)\]/g;
export function parseCitations(answer: string): Segment[] {
  const out: Segment[] = [];
  let last = 0, m: RegExpExecArray | null;
  CITE.lastIndex = 0;
  while ((m = CITE.exec(answer))) {
    if (m.index > last) out.push({ text: answer.slice(last, m.index) });
    out.push({ cite: Number(m[1]) });
    last = m.index + m[0].length;
  }
  if (last < answer.length) out.push({ text: answer.slice(last) });
  return out;
}

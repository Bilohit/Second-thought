/**
 * jsonGuard.ts — the smallest possible shape check for parsed JSON responses.
 *
 * `api.ts` asserts response bodies with `as {...}`, which is a compile-time
 * claim and nothing more: a malformed or unexpected body flows straight into
 * React state, and the crash surfaces far from the endpoint that caused it.
 *
 * This is deliberately NOT a schema validator (no zod — repo doctrine bans the
 * dependency, and full validation of ~40 endpoints is not the job). It only
 * answers the one question that matters at the boundary: "is the container the
 * shape I am about to iterate/spread?" It is applied where a wrong answer
 * corrupts state — the array-returning endpoints — not everywhere.
 */

/** True for a non-null, non-array object. */
export function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * Read `field` off a `{ [field]: T[] }` envelope, returning `fallback` (default
 * `[]`) when the body is not an object or the field is not an array.
 */
export function arrayField<T>(body: unknown, field: string, fallback: T[] = []): T[] {
  if (!isObj(body)) return fallback;
  const v = body[field];
  return Array.isArray(v) ? (v as T[]) : fallback;
}

/** Narrow a body that must itself be an array. */
export function asArray<T>(body: unknown, fallback: T[] = []): T[] {
  return Array.isArray(body) ? (body as T[]) : fallback;
}

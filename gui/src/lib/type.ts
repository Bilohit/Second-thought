/**
 * type.ts
 * -------
 * The shared type scale (DECISIONS §5 s145) — Option B, the V2 mock's own
 * ladder: five text steps plus three display steps, in px. Half-steps
 * (7.5 / 8.5 / 9.5 / 10.5 / 11.5 / 12.5 / 13.5) are banned outright — see
 * the decision for the distribution rationale.
 *
 * This module is the DEFINITION only. 350 of this repo's 358 font sizings
 * are inline `fontSize: N` in TSX (only 8 live in `index.css`, and the repo
 * has zero Tailwind text classes), so the scale has to exist twice: as
 * these named exports for inline-style call sites, and as the matching
 * `--fs-*` custom properties in `index.css` for the CSS sites. The
 * `type.test.ts` sibling asserts the two stay numerically identical.
 *
 * `phone/src/lib/tokens.ts` vendors this exact ladder by hand as
 * `font.scale` — keeping the two in lockstep is a manual contract, the same
 * as the `--mono`/`--track` typeface pair (typeface.test.ts). Note the
 * phone ALSO still exports an older `font.size` whose `label` and `body`
 * are different numbers under the same names; the two are deliberately not
 * merged until Phase 4 migrates the last call site off `font.size`.
 *
 * No call site migrates here. Migration is per-surface, Phase 3+ — this
 * file only defines the scale.
 */

// Text steps
export const micro = 9;
export const label = 10;
export const body = 11;
export const read = 12;
export const lead = 13;

// Display steps
export const title = 16;
export const display = 20;
export const hero = 22;

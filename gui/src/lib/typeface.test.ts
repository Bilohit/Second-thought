import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";

/** The typeface + tracking pair is identity, not styling (DECISIONS §5 s144), and it is vendored
 *  by hand into `phone/src/lib/tokens.ts`. Nothing else asserts it: a reverted token or a stray
 *  hardcoded font stack would ship green. These read the real files rather than importing, because
 *  the values live in CSS and in an import list, not in TypeScript. */

const read = (p: string) => readFileSync(resolve(process.cwd(), p), "utf8");
const css = read("src/index.css");
const main = read("src/main.tsx");

describe("typeface tokens", () => {
  test("--mono is IBM Plex Mono with a monospace fallback chain", () => {
    const decl = css.match(/--mono:\s*([^;]+);/);
    expect(decl, "--mono must be declared at :root").not.toBeNull();
    expect(decl![1]).toContain('"IBM Plex Mono"');
    expect(decl![1]).toContain("monospace");
  });

  test("--track carries the V2 mock's +0.01em", () => {
    expect(css).toMatch(/--track:\s*0\.01em\s*;/);
  });

  test("the root rule consumes both tokens instead of hardcoding a face", () => {
    const rule = css.match(/html,\s*body,\s*#root\s*\{[^}]*\}/);
    expect(rule, "the html/body/#root rule must exist").not.toBeNull();
    expect(rule![0]).toContain("font-family: var(--mono)");
    expect(rule![0]).toContain("letter-spacing: var(--track)");
  });

  test("exactly the three bundled weights are imported, and Geist is gone", () => {
    const weights = [...main.matchAll(/@fontsource\/ibm-plex-mono\/(\d+)\.css/g)].map((m) => m[1]);
    expect(weights).toEqual(["400", "500", "600"]);
    expect(main).not.toContain("geist-mono");
  });

  test("no stray hardcoded Geist stack survives anywhere in the stylesheet", () => {
    expect(css).not.toMatch(/font-family:[^;]*Geist/);
  });
});

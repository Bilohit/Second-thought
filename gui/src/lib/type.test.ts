import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";
import * as type from "./type";

/** The shared type scale (DECISIONS §5 s145) has to exist twice: as the named
 *  exports in type.ts (350 of the desktop's 358 sizings are inline `fontSize:`
 *  in TSX) and as `--fs-*` custom properties in index.css (the 8 CSS sites).
 *  Nothing else asserts the two ladders agree — the same drift risk
 *  typeface.test.ts guards for --mono/--track. This reads the real
 *  stylesheet rather than importing, because the CSS side lives in CSS. */

const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

const NAMES = ["micro", "label", "body", "read", "lead", "title", "display", "hero"] as const;

const BANNED_HALF_STEPS = [7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5];

function cssVarPx(name: string): number | null {
  const decl = css.match(new RegExp(`--fs-${name}:\\s*([\\d.]+)px\\s*;`));
  return decl ? Number(decl[1]) : null;
}

describe("type scale (DECISIONS §5 s145)", () => {
  test("exports exactly the eight named steps at the decided values", () => {
    expect(type.micro).toBe(9);
    expect(type.label).toBe(10);
    expect(type.body).toBe(11);
    expect(type.read).toBe(12);
    expect(type.lead).toBe(13);
    expect(type.title).toBe(16);
    expect(type.display).toBe(20);
    expect(type.hero).toBe(22);
  });

  test.each(NAMES)("index.css declares --fs-%s matching the TS export", (name) => {
    const cssValue = cssVarPx(name);
    expect(cssValue, `--fs-${name} must be declared at :root`).not.toBeNull();
    expect(cssValue).toBe(type[name]);
  });

  test("no exported value is a banned half-step", () => {
    for (const name of NAMES) {
      expect(BANNED_HALF_STEPS).not.toContain(type[name]);
    }
  });
});

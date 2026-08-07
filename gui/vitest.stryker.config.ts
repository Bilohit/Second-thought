import { defineConfig, mergeConfig } from "vitest/config";
import base from "./vitest.config";

// Stryker-only vitest config (check.py tier 3, `gui:mutants`). It exists so the mutation
// runner's timeout can be relaxed WITHOUT relaxing it for `npm test` — the tier-2 gate keeps
// vitest's default 5000ms per-test ceiling exactly as it was.
//
// Why it is needed: stryker instruments every file matched by `mutate` (4915 mutants across 68
// files) and runs vitest with "perTest" coverage analysis. That overhead is >12x on CPU-bound
// tests. `fanLayout.test.ts`'s "unifiedFan — G1 no chip off-screen" sweeps a dense position grid
// (every 80px across four screen sizes x 7 chip counts x 2 fan styles); all 18 tests in that file
// finish in 395ms un-instrumented and it alone blew the 5000ms default under instrumentation,
// failing stryker's DRY RUN — so gui:mutants died before mutating anything and had never once
// run to completion.
//
// The ceiling below is a harness allowance, not a product budget: nothing about what the tests
// ASSERT changes here, and the un-instrumented 5000ms ceiling still guards the real suite.
export default mergeConfig(
  base,
  defineConfig({
    test: { testTimeout: 60_000, hookTimeout: 60_000 },
  }),
);

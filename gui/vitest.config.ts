import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Test environment lives here, not in per-file docblocks. Before this config a `.test.tsx`
// without `// @vitest-environment happy-dom` ran silently in node and could not render.
// ponytail: the 17 existing docblocks are now redundant but harmless — delete them
// opportunistically when touching those files for another reason, not in a churn pass.
export default defineConfig({
  plugins: [react()],
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    environment: "happy-dom",
  },
});

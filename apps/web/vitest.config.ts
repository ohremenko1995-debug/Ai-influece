import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // Workspace packages ship TypeScript source, so vitest resolves them the same
      // way Next does rather than looking for build output.
      "@influenceros/ui": fileURLToPath(new URL("../../packages/ui/src/index.ts", import.meta.url)),
      "@influenceros/types": fileURLToPath(
        new URL("../../packages/types/src/index.ts", import.meta.url),
      ),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});

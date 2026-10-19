import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.c7.ts", "test/**/*.v2.ts"],
  },
});

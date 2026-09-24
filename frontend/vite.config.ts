import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // The backend allows exactly this origin (CORS_ALLOW_ORIGINS: localhost and 127.0.0.1 on
    // 5174). strictPort: if 5174 is taken, fail instead of moving to a port the API refuses.
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: { modules: { classNameStrategy: "non-scoped" } },
    restoreMocks: true,
  },
});

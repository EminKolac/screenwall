import { defineConfig, devices } from "@playwright/test";

const PORT = 5175;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  workers: 2,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    locale: "tr-TR",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" } },
  ],
  // Every e2e run talks to the in-browser mock backend, never to a real server.
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: BASE_URL,
    env: { VITE_MOCK: "1" },
    reuseExistingServer: false,
    timeout: 90_000,
  },
});

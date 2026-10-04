import { defineConfig, devices } from "@playwright/test";

// End-to-end, accessibility (NFR-6) and browser-matrix (NFR-11) tests against the running stack.
//   docker compose up -d && curl -X POST "localhost:8002/internal/dev/seed?count=60"
//   cd web && npx playwright test                    # all browsers
//   npx playwright test --project=chromium           # one
// E2E_BASE_URL defaults to the nginx web container (:3000), which proxies /api to the gateway like production.
// NFR-11 asks for the last two versions of Chrome, Safari, Firefox and Edge: Playwright pins current engines;
// Edge is Chromium-based and runs when E2E_EDGE=1 (needs Microsoft Edge installed).
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  // One worker per browser keeps the gateway's per-IP sign-in rate limit (10/min) out of the way.
  workers: process.env.CI ? 2 : 3,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    { name: "mobile-chrome", use: { ...devices["Pixel 7"] } },
    { name: "mobile-safari", use: { ...devices["iPhone 14"] } },
    ...(process.env.E2E_EDGE ? [{ name: "edge", use: { ...devices["Desktop Edge"], channel: "msedge" } }] : []),
  ],
});

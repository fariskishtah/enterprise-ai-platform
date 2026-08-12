import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173";
const localServerPort = new URL(baseURL).port || "5173";
const browserChannel = process.env.E2E_BROWSER_CHANNEL;
const video = process.env.E2E_DISABLE_VIDEO ? "off" : "retain-on-failure";

export default defineConfig({
  expect: { timeout: 5_000 },
  forbidOnly: Boolean(process.env.CI),
  fullyParallel: true,
  outputDir: "test-results",
  reporter: process.env.CI
    ? [["line"], ["html", { open: "never", outputFolder: "playwright-report" }]]
    : "list",
  retries: process.env.CI ? 1 : 0,
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
    video,
  },
  webServer: process.env.E2E_EXTERNAL_SERVER
    ? undefined
    : {
        command: `npm run dev -- --host 127.0.0.1 --port ${localServerPort} --strictPort`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        url: baseURL,
      },
  workers: process.env.CI ? 1 : undefined,
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(browserChannel ? { channel: browserChannel } : {}),
      },
    },
    {
      name: "firefox",
      use: devices["Desktop Firefox"],
    },
    {
      name: "webkit",
      use: devices["Desktop Safari"],
    },
  ],
});

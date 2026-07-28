import { defineConfig, devices } from "@playwright/test"

const revision =
  process.env.GITHUB_SHA?.trim() ||
  process.env.TEST_REVISION?.trim() ||
  "local"

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "**/*.pw.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  outputDir: `test-results/${revision}`,
  reporter: [
    ["line"],
    [
      "html",
      {
        open: "never",
        outputFolder: `playwright-report/${revision}`,
      },
    ],
  ],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:3128",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "bun tests/browser/fixture/apv2-server.ts",
      url: "http://127.0.0.1:3130/__fixture/state",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command:
        "bunx next dev tests/browser/fixture --hostname 127.0.0.1 --port 3128",
      url: "http://127.0.0.1:3128",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        NEXT_PUBLIC_AGENT_API_URL: "http://127.0.0.1:3130",
        NEXT_PUBLIC_AGENT_ASSISTANT_ID: "agent",
      },
    },
  ],
})

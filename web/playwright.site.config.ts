import { defineConfig, devices } from "@playwright/test"

const revision =
  process.env.GITHUB_SHA?.trim() ||
  process.env.TEST_REVISION?.trim() ||
  "local"
const localBaseUrl = "http://127.0.0.1:3129"
const siteBaseUrl = process.env.SITE_BASE_URL?.trim() || localBaseUrl

export default defineConfig({
  testDir: "./tests/site",
  testMatch: "**/*.pw.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: {
    timeout: 8_000,
  },
  outputDir: `test-results/site/${revision}`,
  reporter: [
    ["line"],
    [
      "html",
      {
        open: "never",
        outputFolder: `playwright-site-report/${revision}`,
      },
    ],
  ],
  use: {
    baseURL: siteBaseUrl,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    colorScheme: "light",
  },
  projects: [
    {
      name: "site-desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
      },
    },
    {
      name: "site-mobile",
      use: {
        ...devices["Pixel 7"],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
  webServer:
    siteBaseUrl === localBaseUrl
      ? {
          command:
            "bun run prebuild && bunx next dev --hostname 127.0.0.1 --port 3129",
          url: localBaseUrl,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            AUTH_SECRET: "site-browser-test-auth-secret-site-browser-test",
            AUTH_ALLOWED_EMAILS: "owner@example.com",
            AUTH_GITHUB_ID: "site-browser-test-github-id",
            AUTH_GITHUB_SECRET: "site-browser-test-github-secret",
            AUTH_GOOGLE_ID: "site-browser-test-google-id",
            AUTH_GOOGLE_SECRET: "site-browser-test-google-secret",
            NEXT_PUBLIC_AGENT_ANONYMOUS_ENABLED: "false",
          },
        }
      : undefined,
})

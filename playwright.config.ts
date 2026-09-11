import { defineConfig, devices } from "@playwright/test";

const integrationTest = /dashboard\.integration\.spec\.ts/;
const testApiUrl = "http://127.0.0.1:8123";

export default defineConfig({
  testDir: "./tests/frontend",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: integrationTest,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chrome",
      testIgnore: integrationTest,
      use: { ...devices["Pixel 7"] },
    },
    {
      name: "integration",
      testMatch: integrationTest,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "uv run python tests/frontend/support_api.py",
      url: `${testApiUrl}/health`,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: false,
      env: { NEXT_PUBLIC_PROMS_API_URL: testApiUrl },
    },
  ],
});

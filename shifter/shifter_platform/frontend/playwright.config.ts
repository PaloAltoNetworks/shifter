import { defineConfig, devices } from "@playwright/test";

// Playwright drives one end-to-end happy path against a running Django + built
// SPA stack (RISK_REGISTER_SPA_ENABLED=1). The stack is started outside this
// config (CI job / local `manage.py runserver`); point SPA_E2E_BASE_URL at it.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: process.env.SPA_E2E_BASE_URL ?? "http://localhost:8000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});

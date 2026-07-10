import { expect, test } from "@playwright/test";

/**
 * End-to-end happy path: list -> create -> detail.
 *
 * Preconditions (see frontend/README.md):
 *  - SPA_E2E_BASE_URL points at a running Django + built SPA stack with
 *    RISK_REGISTER_SPA_ENABLED=1.
 *  - The browser context is an authenticated staff session with risk-register
 *    access. When the stack requires login, provide the session to Playwright
 *    via `storageState` (playwright.config.ts / a global setup).
 */
test("staff user can create a risk and view its detail", async ({ page }) => {
  await page.goto("/risk-register/");

  await expect(page.getByRole("heading", { level: 1, name: "Risks" })).toBeVisible();

  await page.getByRole("link", { name: "New risk" }).click();
  await page.getByLabel(/Title/).fill("E2E smoke risk");
  await page.getByLabel(/Description/).fill("Created by the Playwright happy-path test.");
  await page.getByRole("button", { name: "Create risk" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "E2E smoke risk" })).toBeVisible();
});

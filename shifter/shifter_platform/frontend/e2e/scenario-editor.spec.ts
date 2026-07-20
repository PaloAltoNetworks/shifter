import { expect, test } from "@playwright/test";

/**
 * End-to-end happy path: list -> create -> detail.
 *
 * Preconditions (see frontend/README.md):
 *  - SPA_E2E_BASE_URL points at a running Django + built SPA stack with
 *    PLATFORM_SPA_ENABLED=1 and SCENARIO_EDITOR_SPA_ENABLED=1.
 *  - The browser context is an authenticated session with CMS authoring
 *    (threat-research) access. When the stack requires login, provide the
 *    session to Playwright via `storageState` (playwright.config.ts / a global
 *    setup).
 */
test("authoring user can create a scenario and view its detail", async ({ page }) => {
  await page.goto("/scenario-editor/");

  await expect(page.getByRole("heading", { level: 1, name: "Scenarios" })).toBeVisible();

  await page.getByRole("link", { name: "New scenario" }).click();
  await page.getByLabel("Scenario ID").fill("e2e-smoke-lab");
  await page.getByLabel("Name", { exact: true }).first().fill("E2E smoke lab");
  await page.getByLabel("Description").fill("Created by the Playwright happy-path test.");
  await page.getByLabel("Name", { exact: true }).nth(1).fill("Attacker");
  await page.getByRole("button", { name: "Create scenario" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "E2E smoke lab" })).toBeVisible();
});

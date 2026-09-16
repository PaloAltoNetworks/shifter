// Login / authenticated boot / auth-revocation against the real Django-hosted
// SPA. Exercises the server-side login redirect, a successful authenticated
// session bootstrap, and session revocation on logout.

import { test, expect, type Page } from "@playwright/test";

import { ACTORS } from "../support/actors";

async function devLogin(page: Page, email: string): Promise<void> {
  await page.goto("/dev-login/");
  await page.fill("input[name=email]", email);
  await page.selectOption("select[name=user_type]", "standard");
  await Promise.all([
    page.waitForURL((url) => !url.pathname.startsWith("/dev-login")),
    page.click("button[type=submit]"),
  ]);
}

test("anonymous SPA navigation redirects to the login page", async ({ browser }) => {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  await page.goto("/mission-control");
  await expect(page).toHaveURL(/dev-login/);
  await context.close();
});

test.describe("as an authenticated standard user", () => {
  test.use({ storageState: ACTORS.standard.state });

  test("boots the SPA and loads the session bootstrap", async ({ page }) => {
    const bootstrap = page.waitForResponse(
      (r) => r.url().includes("/api/v1/bootstrap/") && r.request().method() === "GET",
    );
    await page.goto("/mission-control");
    expect((await bootstrap).status()).toBe(200);
    await expect(page).not.toHaveURL(/dev-login/);
  });
});

test("logout revokes the session so the SPA redirects to login again", async ({ browser }) => {
  // A dedicated throwaway session so revoking it does not poison the shared
  // storageState sessions the other journeys reuse.
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();

  await devLogin(page, "e2e-logout@example.com");
  await page.goto("/mission-control");
  await expect(page).not.toHaveURL(/dev-login/);

  await page.goto("/dev-logout/");
  await page.goto("/mission-control");
  await expect(page).toHaveURL(/dev-login/);

  await context.close();
});

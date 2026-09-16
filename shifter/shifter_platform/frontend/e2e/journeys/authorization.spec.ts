// Authorization: a non-staff actor is denied a staff-only surface both by the
// advisory client route gate AND — authoritatively — by the backend. Per the
// #1526 preflight, a client "Access denied" is not proof of backend
// authorization, so this journey asserts the real API 403 as well.

import { test, expect } from "@playwright/test";

import { ACTORS } from "../support/actors";

test.use({ storageState: ACTORS.standard.state });

test("a standard user is denied the staff audit surface (client + backend)", async ({ page }) => {
  // Advisory client route gate.
  await page.goto("/administer/audit");
  await expect(page.getByText("Access denied")).toBeVisible();

  // Authoritative backend denial (the client gate is advisory only).
  const response = await page.request.get("/api/v1/audit/");
  expect(response.status()).toBe(403);
});

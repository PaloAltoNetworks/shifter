// Shared-audit read-only history (the maintained "history" journey). The audit
// feed is staff-session-only; rows are produced by real activity (the actor
// logins write ROLE_SYNC audits, workspace lifecycle writes CREATE/rename/archive).

import { test, expect } from "@playwright/test";

import { ACTORS } from "../support/actors";

test.use({ storageState: ACTORS.staff.state });

test("staff can read the administrative audit history", async ({ page }) => {
  await page.goto("/administer/audit");

  await expect(page.getByRole("heading", { name: "Audit" })).toBeVisible();
  await expect(page.getByText("Access denied")).toHaveCount(0);
  // Real activity has already produced audit rows, so the feed is not empty.
  await expect(page.getByText("No audit events yet")).toHaveCount(0);
  await expect(page.getByRole("table")).toBeVisible();
});

// Workspace lifecycle (the maintained create/rename/archive/restore journey,
// replacing the retired Risk Register CRUD per ADR-045). Drives the real org
// console UI end to end through normal session/CSRF and DRF services; the staff
// actor's administrable organization is established by the seed_e2e command.

import { test, expect } from "@playwright/test";

import { ACTORS } from "../support/actors";

test.use({ storageState: ACTORS.staff.state });

test("create, rename, archive, and restore a workspace", async ({ page }) => {
  const name = `E2E Workspace ${Date.now()}`;
  const renamed = `${name} renamed`;

  await page.goto("/administer/organization/workspaces");

  // Create.
  await page.getByRole("button", { name: "Create workspace" }).click();
  const createDialog = page.getByRole("dialog");
  await createDialog.getByLabel("Workspace name").fill(name);
  await createDialog.getByRole("button", { name: "Create", exact: true }).click();

  // The new workspace lands in the list; open its detail.
  const listLink = page.getByRole("link", { name });
  await expect(listLink).toBeVisible();
  await listLink.click();
  // The scope layout resolves the freshly created workspace (its principal
  // context was invalidated by the create); the detail h1 shows its name.
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await expect(page.getByText("Workspace not found")).toHaveCount(0);

  // Rename.
  await page.getByLabel("Name", { exact: true }).fill(renamed);
  await page.getByRole("button", { name: "Rename" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();

  // Archive (confirmed) -> the card flips to the restore action.
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Archive", exact: true }).click();
  await expect(page.getByRole("button", { name: "Restore", exact: true })).toBeVisible();

  // Restore (confirmed) -> the card flips back to the archive action.
  await page.getByRole("button", { name: "Restore", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Restore", exact: true }).click();
  await expect(page.getByRole("button", { name: "Archive", exact: true })).toBeVisible();
});

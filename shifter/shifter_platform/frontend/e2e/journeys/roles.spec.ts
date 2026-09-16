// Role landings (#2080 participant/organizer breadth): each role reaches its own
// authenticated workspace against the real backend — the session bootstraps, the
// SPA is not bounced to login, the advisory route gate does not deny the role,
// and the destination page's own heading renders (proving the intended surface
// loaded, not the SPA not-found fallback that also renders under the shell).

import { test, expect } from "@playwright/test";

import { ACTORS } from "../support/actors";

const LANDINGS = [
  { role: "CTF organizer", actor: ACTORS.organizer, path: "/ctf/admin", heading: "CTF operations" },
  // No CTF event is seeded, so the participant lands on the expected empty state.
  { role: "CTF participant", actor: ACTORS.participant, path: "/ctf", heading: "Event Home" },
  { role: "threat-research author", actor: ACTORS.threat, path: "/scenario-editor", heading: "Scenarios" },
] as const;

for (const { role, actor, path, heading } of LANDINGS) {
  test(`${role} reaches its authenticated workspace`, async ({ browser }) => {
    const context = await browser.newContext({ storageState: actor.state });
    const page = await context.newPage();

    const bootstrap = page.waitForResponse(
      (r) => r.url().includes("/api/v1/bootstrap/") && r.request().method() === "GET",
    );
    await page.goto(path);
    expect((await bootstrap).status()).toBe(200);
    await expect(page).not.toHaveURL(/dev-login/);
    await expect(page.getByText("Access denied")).toHaveCount(0);

    // Destination-specific readiness oracle: the intended page rendered, not the
    // wildcard not-found page (which also renders beneath the bootstrapped shell).
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Page not found" })).toHaveCount(0);

    await context.close();
  });
}

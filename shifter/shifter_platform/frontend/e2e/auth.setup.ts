// Auth setup project: establishes each synthetic actor's real Django session
// through the dev_login form (normal CSRF + session cookie) and saves its
// storageState for the journey specs. This is the only place that logs in, so
// journeys start already-authenticated as their actor.
//
// storageState files hold a synthetic session cookie for the ephemeral job-local
// database. They carry a live credential, so the directory is created private to
// the current user (0700), each file is written 0600, a pre-existing symlink at
// the target is refused, and global-teardown removes the directory after the run
// (ADR-055-R7). They are gitignored and never uploaded as CI artifacts.

import { chmodSync, lstatSync, mkdirSync, rmSync } from "node:fs";

import { test as setup, expect } from "@playwright/test";

import { ACTORS, AUTH_DIR } from "./support/actors";

for (const [name, actor] of Object.entries(ACTORS)) {
  setup(`authenticate ${name}`, async ({ page }) => {
    await page.goto("/dev-login/");
    await page.fill("input[name=email]", actor.email);
    await page.selectOption("select[name=user_type]", actor.userType);
    await Promise.all([
      page.waitForURL((url) => !url.pathname.startsWith("/dev-login")),
      page.click("button[type=submit]"),
    ]);
    // The redirect target is an authenticated SPA page, not the login form.
    expect(new URL(page.url()).pathname).not.toContain("dev-login");

    mkdirSync(AUTH_DIR, { recursive: true });
    chmodSync(AUTH_DIR, 0o700);
    // Refuse to follow a pre-existing symlink at the target path (a planted
    // symlink could redirect the credential write elsewhere).
    try {
      if (lstatSync(actor.state).isSymbolicLink()) {
        rmSync(actor.state);
      }
    } catch {
      // No existing entry: nothing to guard against.
    }
    await page.context().storageState({ path: actor.state });
    chmodSync(actor.state, 0o600);
  });
}

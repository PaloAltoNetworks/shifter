// Browser accessibility scans (ADR-055-R2/R3/R4). For each registered surface x
// viewport, this establishes the actor's session, renders the real Django-hosted
// SPA, asserts the intended surface is present/ready, runs @axe-core/playwright
// (scoped to the SPA mount) with the WCAG 2.2 A/AA tag set, and compares the
// observed exact-finding set to the committed baseline for that (surface,
// project). New or resolved findings fail; unexpected axe "incomplete" results
// fail; the cross-PR non-growth of the baseline is enforced by the adr_guard
// accessibility-baseline check. Authenticated traces are never uploaded (R7).
//
// Scope: the scan targets `#root` (the SPA the SPA matrix owns). Django-rendered
// page chrome (cookie notice, etc.) is a separate ADR-055 surface kind and is
// not part of the SPA matrix.

import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "@playwright/test";

import { ACTORS } from "../support/actors";
import { AXE_WCAG_TAGS, SURFACES, THEME, VIEWPORTS, type Viewport } from "./matrix";
import { fingerprintKeys, projectId } from "./fingerprint";

const SPA_ROOT = "#root";
// The baseline is the exact set of privacy-safe fingerprints for enrolled debt.
// It is created only when there is debt to enroll (ADR-055-R4); an absent file is
// the implicit empty set (every surface must scan clean).
const baselinePath = fileURLToPath(new URL("./baseline.json", import.meta.url));
const baseline: string[] = existsSync(baselinePath) ? JSON.parse(readFileSync(baselinePath, "utf8")) : [];

for (const surface of SURFACES) {
  for (const viewport of Object.keys(VIEWPORTS) as Viewport[]) {
    test(`a11y: ${surface.id} [${viewport}]`, async ({ browser }) => {
      const context = await browser.newContext({
        storageState: ACTORS[surface.actor].state,
        viewport: VIEWPORTS[viewport],
      });
      const page = await context.newPage();
      try {
        await page.goto(surface.route);
        // Readiness/identity oracle: the intended surface/state rendered, not a
        // redirect, blank mount, or the not-found fallback (ADR-055-R3).
        const readyLocator =
          surface.readyKind === "alert"
            ? page.getByRole("alert").filter({ hasText: surface.ready })
            : page.getByRole("heading", { name: surface.ready, exact: true });
        await expect(readyLocator.first()).toBeVisible();

        const results = await new AxeBuilder({ page }).include(SPA_ROOT).withTags([...AXE_WCAG_TAGS]).analyze();
        // Fail closed: a scan that executed zero rules is not a passing surface.
        expect(
          results.passes.length + results.violations.length + results.incomplete.length,
          "axe executed no rules for this surface",
        ).toBeGreaterThan(0);
        // Unexpected "incomplete" (indeterminate) results cannot pass (R3/R4).
        // Bounded, privacy-safe diagnostics: rule ids only, never DOM/HTML.
        const incompleteRules = [...new Set(results.incomplete.map((r) => r.id))].sort();
        expect(incompleteRules, `unexpected axe incomplete result(s) on ${surface.id} [${viewport}]`).toEqual([]);

        const project = projectId(viewport, THEME);
        const observed = fingerprintKeys(surface.id, project, results);
        const expected = baseline.filter((key) => key.startsWith(`${surface.id}|${project}|`)).sort();
        // Exact-finding comparison (ADR-055-R4): a new finding or a stale
        // (resolved-but-still-baselined) entry both fail.
        expect(observed).toEqual(expected);
      } finally {
        await context.close();
      }
    });
  }
}

// Fail-closed reconciliation of the accessibility surface matrix against the
// canonical SPA route table (ADR-055-R3, SPA source). Every top-level route
// group registered in router.tsx must either be covered by at least one matrix
// entry or be explicitly excluded with a reason here, and every matrix entry
// must resolve to a real route group (no stale entries). A new route group with
// no coverage fails this test until it is scanned or explicitly excluded.
//
// Django human-facing routes and mkdocs pages are the other ADR-055-R3 sources;
// their reconciliation + browser scanning is the documented extension of this
// same matrix seam (tracked with the ADR-055 rollout), not a second runner.

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { router } from "@/router";
import { SURFACES } from "../../e2e/a11y/matrix";

// The committed accessibility baseline (absent = the implicit empty set).
// Resolved from the package root (vitest cwd), not import.meta.url, which is
// not a file:// URL under the vitest transform.
const baselinePath = resolve("e2e/a11y/baseline.json");
const baseline: string[] = existsSync(baselinePath) ? JSON.parse(readFileSync(baselinePath, "utf8")) : [];

interface RouteNode {
  readonly path?: string;
  readonly index?: boolean;
  readonly children?: readonly RouteNode[];
}

// Route groups intentionally not (yet) in the browser-axe matrix, each with a
// reason. Removing coverage for a listed group keeps the gate honest; adding a
// new group without coverage OR an entry here fails reconciliation.
const EXCLUDED_GROUPS: Record<string, string> = {
  "": "Home renders a per-user greeting (dynamic heading); covered by component/vitest-axe tests.",
  ctf: "Participant CTF surfaces require a seeded active event; deferred to event-seeding follow-up.",
  "raes-image-registry": "Single authoring surface; enroll in a follow-up (extends this matrix).",
};

function topLevelGroups(): string[] {
  const root = (router.routes as readonly RouteNode[])[0];
  const groups: string[] = [];
  for (const child of root.children ?? []) {
    if (child.path === "*") continue; // the not-found catch-all is a state, covered below
    groups.push(child.index ? "" : (child.path ?? ""));
  }
  return groups;
}

/** The router group a matrix route resolves to (longest matching group wins). */
function resolveGroup(route: string, groups: readonly string[]): string | undefined {
  const path = route.replace(/^\//, "");
  const matches = groups.filter((g) => g !== "" && (path === g || path.startsWith(`${g}/`)));
  return matches.sort((a, b) => b.length - a.length)[0];
}

describe("accessibility surface matrix reconciliation", () => {
  const groups = topLevelGroups();
  const covered = new Set(SURFACES.map((s) => resolveGroup(s.route, groups)).filter(Boolean) as string[]);

  it("covers or explicitly excludes every SPA route group (fail-closed)", () => {
    const unowned = groups.filter((g) => !covered.has(g) && !(g in EXCLUDED_GROUPS));
    expect(unowned, `route group(s) missing an a11y matrix entry or exclusion: ${unowned.join(", ")}`).toEqual([]);
  });

  it("registers the not-found state", () => {
    expect(SURFACES.some((s) => s.id === "not-found")).toBe(true);
  });

  it("has no stale matrix entries (every entry resolves to a real route group or the not-found state)", () => {
    const stale = SURFACES.filter((s) => s.id !== "not-found" && s.id !== "workspace-not-found")
      .filter((s) => resolveGroup(s.route, groups) === undefined)
      .map((s) => s.id);
    expect(stale, `matrix entries not resolving to a route group: ${stale.join(", ")}`).toEqual([]);
  });

  it("does not exclude a group that is actually covered", () => {
    const redundant = Object.keys(EXCLUDED_GROUPS).filter((g) => covered.has(g));
    expect(redundant, `excluded groups that are covered (drop the exclusion): ${redundant.join(", ")}`).toEqual([]);
  });

  it("has no orphaned baseline fingerprints (each belongs to a registered surface)", () => {
    // ADR-055-R4: a removed surface must not leave stale baseline debt. Every
    // committed fingerprint's surface id must belong to a currently registered
    // matrix surface.
    const surfaceIds = new Set(SURFACES.map((s) => s.id));
    const orphans = baseline.map((key) => key.split("|")[0]).filter((id) => !surfaceIds.has(id));
    expect([...new Set(orphans)], `baseline fingerprints for unregistered surfaces: ${orphans.join(", ")}`).toEqual([]);
  });
});

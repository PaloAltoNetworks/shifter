// Privacy-safe accessibility fingerprints (ADR-055-R4). A fingerprint carries
// only the stable surface/state id, the execution project (browser:viewport:theme),
// the axe rule id, the sorted WCAG tags, and a normalized target — never rendered
// HTML, user data, tokens, or response bodies. The baseline is the exact set of
// these fingerprint keys; the gate compares sets, never counts.

import type { AxeResults } from "axe-core";

/** A single fingerprint rendered as a stable, sortable key string. */
export function fingerprintKeys(surfaceId: string, project: string, results: AxeResults): string[] {
  const keys: string[] = [];
  for (const violation of results.violations) {
    const wcag = violation.tags
      .filter((tag) => tag.startsWith("wcag"))
      .sort()
      .join(",");
    for (const node of violation.nodes) {
      keys.push([surfaceId, project, violation.id, wcag, normalizeTarget(node.target)].join("|"));
    }
  }
  return [...new Set(keys)].sort();
}

/** Execution-project component of a fingerprint: browser + viewport + theme. */
export function projectId(viewport: string, theme: string): string {
  return `chromium:${viewport}:${theme}`;
}

/** Normalize an axe target selector so it is stable across runs: drop
 * positional `:nth-child` and digit runs (dynamic ids/indices) that would make
 * an otherwise-identical finding look new. Frame path is preserved via `>>>`. */
function normalizeTarget(target: unknown): string {
  const parts = (Array.isArray(target) ? target : [target]).map((segment) => String(segment));
  return parts
    .join(" >>> ")
    .replace(/:nth-child\(\d+\)/g, "")
    .replace(/\d+/g, "#");
}

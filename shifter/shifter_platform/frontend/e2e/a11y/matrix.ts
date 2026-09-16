// ADR-055 accessibility surface/state matrix (the R3 seam). One package-owned
// data model of the registered browser-accessibility surfaces: each entry is a
// stable surface/state id, a canonical SPA route reference, the synthetic actor
// whose session renders it, a readiness/identity oracle (a heading that proves
// the intended surface rendered, not a redirect/blank/error), and the source
// path that owns remediation. Adding a route/role/viewport extends this data,
// not the runner.

import type { ActorName } from "../support/actors";

export type Viewport = "desktop" | "narrow";

/** Chromium desktop + a narrow/reflow viewport (ADR-055-R2 PR tier). */
export const VIEWPORTS: Record<Viewport, { readonly width: number; readonly height: number }> = {
  desktop: { width: 1280, height: 800 },
  narrow: { width: 390, height: 844 },
};

/** WCAG 2.0/2.1/2.2 A/AA tags supported by the pinned axe engine (ADR-055-R2). */
export const AXE_WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] as const;

/** The theme dimension of a fingerprint's execution project (SPA defaults dark). */
export const THEME = "dark";

export interface A11ySurface {
  /** Stable surface/state id (part of every fingerprint; never a live record). */
  readonly id: string;
  /** Canonical SPA route reference reconciled against router.tsx. */
  readonly route: string;
  /** Synthetic actor whose storageState renders the surface. */
  readonly actor: ActorName;
  /** Text proving the intended surface/state rendered before scanning. */
  readonly ready: string;
  /** Whether the readiness text is a page heading (default) or an alert. */
  readonly readyKind?: "heading" | "alert";
  /** Source path responsible for remediation. */
  readonly remediation: string;
}

export const SURFACES: readonly A11ySurface[] = [
  {
    id: "mission-control-dashboard",
    route: "/mission-control",
    actor: "standard",
    ready: "Ranges",
    remediation: "src/features/mission-control/RangeDashboardPage.tsx",
  },
  {
    id: "workspace-list",
    route: "/administer/organization/workspaces",
    actor: "staff",
    ready: "Workspaces",
    remediation: "src/features/administer/organization/WorkspaceListPage.tsx",
  },
  {
    id: "audit",
    route: "/administer/audit",
    actor: "staff",
    ready: "Audit",
    remediation: "src/features/administer/AuditPage.tsx",
  },
  {
    id: "ctf-admin-dashboard",
    route: "/ctf/admin",
    actor: "organizer",
    ready: "CTF operations",
    remediation: "src/features/ctf/admin/AdminDashboardPage.tsx",
  },
  {
    id: "scenario-editor-list",
    route: "/scenario-editor",
    actor: "threat",
    ready: "Scenarios",
    remediation: "src/features/scenario-editor/ScenarioListPage.tsx",
  },
  {
    // Denied-state surface: an ordinary user hitting a staff route sees the
    // advisory access-denied state (backend stays authoritative).
    id: "access-denied",
    route: "/administer/audit",
    actor: "standard",
    ready: "Access denied",
    remediation: "src/app/RootLayout.tsx",
  },
  {
    // Error-state surface: a well-formed but unknown workspace UUID renders the
    // destructive "Workspace not found" alert. Covers the destructive Alert
    // variant's contrast deterministically without seeding.
    id: "workspace-not-found",
    route: "/administer/organization/workspaces/00000000-0000-0000-0000-000000000000",
    actor: "staff",
    ready: "Workspace not found",
    readyKind: "alert",
    remediation: "src/features/administer/organization/WorkspaceScopeLayout.tsx",
  },
  {
    // Not-found state for an unknown client route under a host-served prefix.
    id: "not-found",
    route: "/mission-control/__not_found__",
    actor: "standard",
    ready: "Page not found",
    remediation: "src/components/not-found.tsx",
  },
] as const;

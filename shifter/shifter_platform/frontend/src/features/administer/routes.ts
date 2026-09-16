/**
 * Administer workspace client-route paths (#1373).
 *
 * The workspace runs under the unified platform router (basename `/`) at the
 * `/administer` prefix. Django admin stays at `/admin/` and is never linked from
 * here as a SPA-native workflow. Keeping the prefix in one place means a future
 * re-mount changes one file.
 */
export const ADMINISTER_BASE = "/administer";

export const usersListPath = (): string => ADMINISTER_BASE;
export const userPath = (id: number | string): string => `${ADMINISTER_BASE}/users/${id}`;
export const costPath = (): string => `${ADMINISTER_BASE}/cost`;
export const platformSettingsPath = (): string => `${ADMINISTER_BASE}/settings`;
// Administrator audit / activity history (#1947, PLAT-240). Deployment-global and
// staff-only; deliberately a top-level Administer surface, not workspace-scoped.
export const auditPath = (): string => `${ADMINISTER_BASE}/audit`;

/**
 * Organization/workspace admin console (#1938, PLAT-231). The console shell hangs
 * off `/administer/organization`; the selected workspace is expressed as its
 * public UUID in the route, never an internal id. Child paths are route *slots*
 * for the later per-capability slices (PLAT-232–240); keeping them here means a
 * future re-mount changes one file.
 */
export const ORGANIZATION_BASE = `${ADMINISTER_BASE}/organization`;

export const organizationPath = (): string => ORGANIZATION_BASE;
// The organization settings surface (#1939, PLAT-232) selects its target
// organization by public UUID. Without a UUID it resolves to the chooser, which
// lists the principal's reachable organizations (or opens the only one).
export const organizationSettingsPath = (organizationUuid?: string): string =>
  organizationUuid ? `${ORGANIZATION_BASE}/settings/${organizationUuid}` : `${ORGANIZATION_BASE}/settings`;
export const organizationWorkspacesPath = (): string => `${ORGANIZATION_BASE}/workspaces`;
export const workspaceScopePath = (workspaceUuid: string): string =>
  `${ORGANIZATION_BASE}/workspaces/${workspaceUuid}`;
export const workspaceSurfacePath = (workspaceUuid: string, surface: string): string =>
  `${ORGANIZATION_BASE}/workspaces/${workspaceUuid}/${surface}`;

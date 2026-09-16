/**
 * Organization admin console surface manifest and selection resolution (#1938,
 * PLAT-231). This slice owns the shell, routing, switcher, context, and
 * capability-aware navigation only; each surface here is a route *slot* whose
 * behavior lands with its own issue (PLAT-232–240).
 *
 * `requiredAnyOperation`, when present, lists `WorkspaceOperation` codes the
 * selected workspace's role must permit for the surface to be enabled in the
 * in-console navigation: the surface opens when the role permits ANY one of
 * them. It is advisory presentation only: the server derives capabilities
 * centrally and every endpoint reauthorizes. TypeScript must never compare role
 * strings to reconstruct policy.
 */
import type { PrincipalWorkspaceContext } from "@/api/types";

/** A workspace-scoped console slot, optionally gated on workspace capabilities. */
export interface WorkspaceSurface {
  readonly key: string;
  readonly label: string;
  /**
   * Advisory capability codes; the surface is shown when the role permits any of
   * them. Absent means "always shown (later slice)".
   */
  readonly requiredAnyOperation?: readonly string[];
}

/** Workspace-scoped slots reached under a selected workspace UUID. */
export const WORKSPACE_SURFACES: readonly WorkspaceSurface[] = [
  // Membership admits either roster access (owner/admin) or self-service leave
  // (every member): a `member` lacks `read_members` but may still open the
  // surface to view its own membership and leave (#1941, PLAT-234). The gate
  // stays a capability predicate, never a role-code shortcut.
  { key: "membership", label: "Membership", requiredAnyOperation: ["read_members", "leave_workspace"] },
  { key: "invitations", label: "Invitations", requiredAnyOperation: ["read_invitations"] },
  { key: "users", label: "Users" },
  // Range scoping is owner/admin scope administration (#1944, PLAT-237); the
  // gate is advisory presentation only, and the server reauthorizes every call.
  { key: "range-scoping", label: "Range scoping", requiredAnyOperation: ["list_range_scope_bindings"] },
  { key: "policy", label: "Policy" },
  { key: "quota", label: "Quota" },
  // Audit is intentionally NOT a workspace-scoped surface (#1947, PLAT-240): the
  // audit store is deployment-global with no per-row workspace scope, so a
  // workspace-nested entry would falsely imply the switcher scopes/authorizes the
  // feed. The administrator audit history lives at the top-level /administer/audit.
];

/** True when the selected workspace's advisory capabilities permit the surface. */
export function surfaceEnabled(surface: WorkspaceSurface, selected: PrincipalWorkspaceContext | null): boolean {
  if (!surface.requiredAnyOperation) return true;
  const capabilities = selected?.capabilities ?? [];
  return surface.requiredAnyOperation.some((operation) => capabilities.includes(operation));
}

/**
 * Resolve the selected workspace from a route UUID against the loaded contexts.
 *
 * - An exact UUID match wins.
 * - A missing route UUID falls back to the first (deterministically ordered)
 *   workspace so the console always opens on a real workspace.
 * - An *invalid or stale* supplied UUID never silently becomes another workspace
 *   (in particular never the personal one): it resolves to `null` so the caller
 *   renders an honest "workspace not found" state instead of leaking a different
 *   tenant's scope.
 * - No workspaces at all resolves to `null` (honest empty state).
 */
export function resolveSelectedWorkspace(
  contexts: readonly PrincipalWorkspaceContext[],
  workspaceUuid: string | undefined,
): PrincipalWorkspaceContext | null {
  if (contexts.length === 0) return null;
  if (workspaceUuid === undefined) return contexts[0];
  return contexts.find((ctx) => ctx.workspace_uuid === workspaceUuid) ?? null;
}

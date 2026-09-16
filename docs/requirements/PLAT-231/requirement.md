---
id: PLAT-231
title: "Organization/workspace administration console shell"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
created_at: 2026-08-01T17:36:46.302686Z
updated_at: 2026-08-01T17:41:19.898009Z
---

# PLAT-231: Organization/workspace administration console shell

## Statement

The SPA shall provide a staff-gated organization/workspace administration console as a first-class navigation area, with client-side routing, a workspace context/switcher backed by a current-principal context endpoint that returns the caller's organization, workspaces, and workspace roles, and a persistent full-page escape hatch to Django admin. The console shell shall be feature-flag gated and shall host the organization, workspace, membership, invitation, user-lifecycle, range-scoping, policy, quota, and audit surfaces as child routes.

## Rationale

The workspace tenancy layer (PLAT-2011, program #1321) is API-only; the SPA exposes none of it. A shared shell provides the routing, principal context, and navigation the per-capability admin slices hang off, and preserves the existing Django-admin escape hatch already present in the SPA nav.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1938`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/views.py` (PrincipalWorkspaceContextView, current-principal context endpoint)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_context.py` (list_actor_workspace_contexts, read-only principal-context projection)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/serializers.py` (PrincipalWorkspaceContextSerializer)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/urls.py` (/api/v1/workspaces/context/ route)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/administer/organization/OrganizationConsoleLayout.tsx` (Organization console shell layout (query, switcher, context, states))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/administer/organization/WorkspaceContext.tsx` (Selected-workspace context provider)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/administer/organization/WorkspaceSwitcher.tsx` (Workspace switcher (public-UUID URL selection))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/api/principalContext.ts` (usePrincipalContext hook (paginated context aggregation))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/router.tsx` (Organization console route subtree + slots)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/app/nav.ts` (Organization nav entry (staff, administer_spa) + Django admin escape hatch)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_context_api.py` (Principal-context endpoint DRF boundary tests (staff gate, token rejection, projection))
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_context.py` (Principal-context service projection tests (multi-org, capabilities, side-effect-free))
- TESTS → TEST `shifter/shifter_platform/frontend/src/features/administer/organization/OrganizationConsole.test.tsx` (Console shell/switcher/scope tests (deep-link, capability-aware nav, empty/denied states))
- TESTS → TEST `shifter/shifter_platform/frontend/src/app/nav.test.ts` (Nav visibility tests (Organization entry gated; Django admin persists))

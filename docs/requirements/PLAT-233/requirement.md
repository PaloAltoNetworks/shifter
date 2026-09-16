---
id: PLAT-233
title: "Workspace lifecycle management"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
created_at: 2026-08-01T17:36:56.293306Z
updated_at: 2026-08-01T17:41:19.898022Z
---

# PLAT-233: Workspace lifecycle management

## Statement

The platform shall provide workspace lifecycle APIs (create, list/search, rename, archive/restore, and owner transfer) scoped to the caller's organization and authorized through the existing workspace role seam, plus an SPA surface to list, create, and administer workspaces. The personal compatibility workspace invariant (one personal workspace per user, no shared deployment-global default) shall be preserved, and archival shall not delete ranges bound to the workspace.

## Rationale

Membership APIs exist but there is no way to create or manage the workspaces themselves except Django admin and migrations. Workspace lifecycle is the core of a usable shared-infrastructure admin layer, and it must respect the personal-workspace compatibility invariant from PLAT-2011.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1940`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_lifecycle.py` (Transactional workspace lifecycle service: create/list/rename/archive/restore/transfer; last-owner + personal-workspace invariants; reversible archived_at marker)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/lifecycle_views.py` (Session-authorized DRF workspace lifecycle API under /api/v1/workspaces/)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_workspace.py` (archived_at reversible archive marker; archival never cascades to bound ranges)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/roles.py` (Workspace lifecycle operations and role matrix (owner/admin read/rename/archive/restore; owner-only transfer))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/administer/organization/WorkspaceListPage.tsx` (SPA workspace list/search/create surface)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/administer/organization/WorkspaceDetailPage.tsx` (SPA workspace detail/admin surface: rename, archive/restore, owner transfer)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_lifecycle.py` (Lifecycle service behavior, authorization, and invariant tests (last-owner, no range cascade, personal protection))
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_lifecycle_api.py` (Lifecycle DRF boundary tests (admission, org-admin/workspace-role authorization, opaque denials))

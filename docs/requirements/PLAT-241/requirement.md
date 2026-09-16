---
id: PLAT-241
title: "Admin layer stays cloud-agnostic and uses proven components"
status: ACTIVE
type: CONSTRAINT
priority: MUST
created_at: 2026-08-01T17:37:46.207763Z
updated_at: 2026-08-01T17:41:19.898058Z
---

# PLAT-241: Admin layer stays cloud-agnostic and uses proven components

## Statement

The organization/workspace administration layer shall function identically on AWS and GCP deployments, with no cloud-specific assumptions in the SPA or the shared platform/API layer; cloud-specific behavior shall live behind the existing provider seams. The layer shall rely on proven, existing components - Django authentication/session, DRF, the existing workspace role seam and shared.audit, signed-token email for invitations, and the generated OpenAPI types and TanStack Query data layer in the SPA - rather than hand-rolling authentication, authorization, audit, or egress enforcement. Deep or rarely used administration shall remain reachable through the Django admin escape hatch rather than duplicated in the SPA.

## Rationale

The user requires a cloud-agnostic admin layer (AWS and GCP) that leans on proven components and cloud-native patterns instead of hand-rolled mechanisms. Capturing this as a cross-cutting constraint linked to every admin-layer issue makes it a durable acceptance criterion rather than per-issue prose.

## Traceability

- CONSTRAINS → GITHUB_ISSUE `1938`
- CONSTRAINS → GITHUB_ISSUE `1939`
- CONSTRAINS → GITHUB_ISSUE `1940`
- CONSTRAINS → GITHUB_ISSUE `1941`
- CONSTRAINS → GITHUB_ISSUE `1942`
- CONSTRAINS → GITHUB_ISSUE `1943`
- CONSTRAINS → GITHUB_ISSUE `1944`
- CONSTRAINS → GITHUB_ISSUE `1945`
- CONSTRAINS → GITHUB_ISSUE `1946`
- CONSTRAINS → GITHUB_ISSUE `1947`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/views.py` (Reuses DRF, IsStaffSession, and the workspace service seam; no cloud-specific branch)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_context.py` (Read-only projection via workspaces.services facade + central role policy (no hand-rolled authz))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/app/nav.ts` (Reuses the central nav registry + Django-admin escape hatch; no cloud-specific assumptions)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/api/principalContext.ts` (Reuses the shared fetch client, generated OpenAPI types, and TanStack Query; identical on AWS/GCP)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_organization_api.py` (Proves session-only auth via shared DRF seam; no cloud-specific branch (AWS/GCP identical))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/lifecycle_views.py` (Session-only auth via shared DRF seam + workspaces.services role policy; no cloud-specific branch (AWS/GCP identical))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/api/workspaces.ts` (Reuses the shared apiFetch client, generated OpenAPI types, and TanStack Query; identical on AWS/GCP)

---
id: PLAT-232
title: "Organization profile and settings surface"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
created_at: 2026-08-01T17:36:51.541608Z
updated_at: 2026-08-01T17:41:19.898017Z
---

# PLAT-232: Organization profile and settings surface

## Statement

The platform shall expose an organization read/update API keyed by the organization's immutable uuid and an SPA settings surface through which an organization administrator can view and edit organization profile fields (display name, description, and display/branding and organization-level defaults). Public surfaces shall accept and emit only the organization uuid, never its integer primary key.

## Rationale

The Organization model exists but has no API or UI; administrators of a shared-infrastructure deployment need a place to set organization identity and defaults. Keeping the uuid as the only public identifier follows the enumeration-resistance posture already established on the tenancy models.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1939`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_organization.py` (Org profile read/update + authority seam (uuid-keyed, opaque denial, atomic locked update, strict audit))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/views.py` (GET/PATCH /organizations/<uuid>/ + administrable list; session-only; uuid-only wire)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_organization_membership.py` (Persisted org-admin authority model (ADR-048))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/administer/organization/OrganizationSettingsPage.tsx` (SPA organization settings chooser + editor (authority-driven, PATCH mask))
- IMPLEMENTS → ADR `ADR-048` (Organization administrator authority (persisted org-admin role + superuser override))
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_organization.py` (Service authority, opaque denial, PATCH mask, superuser override, strict audit, validation)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_organization_api.py` (DRF boundary: uuid-only, 403 opaque, token rejected, unknown/invalid-field 400)
- TESTS → TEST `shifter/shifter_platform/frontend/src/features/administer/organization/OrganizationSettingsPage.test.tsx` (SPA editor load/save/PATCH-mask/field-error/forbidden + chooser selection)

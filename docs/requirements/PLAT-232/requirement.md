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

During S1, the platform shall retain the existing organization read/update API and SPA settings surface for legacy organizations. The API shall use the organization's immutable UUID publicly and authorize profile edits through explicit organization-administrator membership or the audited superuser override; integer primary keys remain internal. The new account hierarchy shall place organizations only beneath team or enterprise accounts, never individual accounts, and creating a default organization shall grant no administrator role. Account/principal runtime authority remains on the legacy path until the coordinated S8 cutover.


ADR-066 S4 clarification: principal-aware account administration, membership/ownership
facts, scoped profile/lifecycle commands and canonical DRF/browser adapters are
prepared without replacing production routes or legacy authority. The coordinated
S8 activation in #2321 binds these paths and maps historical facts. Prepared
Django-admin writes are disabled in favor of the canonical validated commands.

## Rationale

Organization profile management remains useful for shared team and enterprise accounts. ADR-066 places organizations beneath a typed account and removes the earlier assumption that every individual has a personal organization. The account schema and legacy settings runtime coexist only as dormant S1 structure and unchanged legacy authority; the S8 activation must converge account ancestry and principal membership across every access path.

## Traceability

- IMPLEMENTS → ADR `docs/adr/066-account-principal-resource-scope.md` (Typed account hierarchy)
- DOCUMENTS → DOCUMENTATION `docs/architecture/organization-profile-settings-preflight-1939.md` (Organization settings activation boundary)
- IMPLEMENTS → GITHUB_ISSUE `2314` (Organization account ancestry and default creation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_organization.py` (Organization account binding and default marker)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_account.py` (Organization ancestry and no implicit grant)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_account_hierarchy.py` (Individual denial and organization default invariants)
- IMPLEMENTS → GITHUB_ISSUE `1939`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_organization.py` (Org profile read/update + authority seam (uuid-keyed, opaque denial, atomic locked update, strict audit))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/views.py` (GET/PATCH /organizations/<uuid>/ + administrable list; session-only; uuid-only wire)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_organization_membership.py` (Persisted org-admin authority model (ADR-048))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/administer/organization/OrganizationSettingsPage.tsx` (SPA organization settings chooser + editor (authority-driven, PATCH mask))
- IMPLEMENTS → ADR `ADR-048` (Organization administrator authority (persisted org-admin role + superuser override))
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_organization.py` (Service authority, opaque denial, PATCH mask, superuser override, strict audit, validation)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_organization_api.py` (DRF boundary: uuid-only, 403 opaque, token rejected, unknown/invalid-field 400)
- TESTS → TEST `shifter/shifter_platform/frontend/src/features/administer/organization/OrganizationSettingsPage.test.tsx` (SPA editor load/save/PATCH-mask/field-error/forbidden + chooser selection)

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_policy_profiles.py` (S4 prepared administration; activation remains coordinated)

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/policy_profile_views.py` (S4 prepared administration; activation remains coordinated)

- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_policy_profiles.py` (S4 prepared administration; activation remains coordinated)

- TESTS → TEST `shifter/shifter_platform/frontend/src/features/administer/accounts/AccountAdministrationPage.test.tsx` (S4 prepared administration; activation remains coordinated)

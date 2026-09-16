---
id: PLAT-2011
title: "Organization/workspace tenancy boundary above range ownership"
status: ACTIVE
type: CONSTRAINT
priority: MUST
created_at: 2026-07-26T16:31:32.402253Z
updated_at: 2026-07-26T21:30:40.607851Z
---

# PLAT-2011: Organization/workspace tenancy boundary above range ownership

## Statement

The platform shall provide an organization/workspace tenancy layer above user-owned ranges, owned by a single bounded domain that is the sole owner of Organization, Workspace, and WorkspaceMembership persistence and authorization. An organization shall own workspaces; a workspace shall hold at most one membership per user with a closed role code; and a range shall retain its existing user/request owner identity while additionally carrying a validated opaque workspace binding on CMS request intent, the CMS range projection, and the Engine range. No other layer shall import the tenancy models or hold a cross-layer ForeignKey to them. The compatibility default shall be per user - every pre-existing user-owned range shall resolve to its owner's personal workspace under a personal organization with an owner membership, never a deployment-global default - and existing lifecycle, admission, remote-access, CTF, and API behavior shall remain unchanged. Identity-provider group and claim integration shall remain a future verified, allowlisted adapter into this domain rather than a role authority in the data model.

## Rationale

Shifter is sized for a university or research lab to run as shared infrastructure, and for multi-org hosting operators downstream, but ranges are currently owned only by an individual Django user. Establishing the tenancy boundary contract-first - as an ADR plus the data model - before membership (#1326) and range scoping (#1327) prevents each of those from inventing its own tenancy shape. Anchoring it on a requirement gives the new domain classification, the layer/FK boundary enforcement (ADR-046-R1 via layer-imports and cross-layer-model-imports), and the per-user compatibility invariant durable traceability. The per-user personal workspace, rather than a shared default, is what keeps single-user installs behaviorally identical while leaving no single-tenant assumption baked into the schema, and it must not preclude the tenant isolation model tracked by #324.

## Traceability

- IMPLEMENTS → ADR `docs/adr/index.yaml` (ADR-046: organization/workspace tenancy is a domain boundary above range ownership)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_organization.py` (Organization model)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_workspace.py` (Workspace model (organization FK, unique personal_for_user))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_membership.py` (WorkspaceMembership model (unique per workspace+user, closed role))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_authorization.py` (Workspace authorization seam (immutable result, indistinguishable denials))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_personal.py` (Per-user personal workspace provisioning (the compatibility default))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/migrations/0002_backfill_personal_workspaces.py` (Per-user personal organization/workspace/owner-membership backfill)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/migrations/0039_backfill_workspace_bindings.py` (CMS range binding backfill with ownership-divergence guards)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/migrations/0040_workspace_binding_required.py` (CMS workspace bindings made non-null)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/migrations/0042_workspace_binding_required.py` (Engine range workspace binding made non-null)
- IMPLEMENTS → CONFIG `scripts/check_layer_imports/layer_imports.yaml` (workspaces classified as a domain layer; facade-only access enforced)
- DOCUMENTS → DOCUMENTATION `docs/technical/shifter_platform/workspaces.md` (Workspaces domain technical documentation)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_models.py` (Tenancy model invariants (organization FK, unique membership, one personal workspace))
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_services.py` (Authorization seam and per-user personal workspace resolution)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_backfill_migration_schema.py` (Upgrade proven against the real historical schema (unbound rows bound, none left))
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_range_workspace_binding.py` (Range scope binding across all three ownership projections; rehome semantics)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_range_workspace_persistence.py` (Engine seams persist the exact scope and refuse a missing binding)
- IMPLEMENTS → GITHUB_ISSUE `1325` (ADR + data model: organization/workspace layer above user-owned ranges)
- IMPLEMENTS → PULL_REQUEST `1863` (feat(platform): add organization/workspace tenancy above range ownership)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/roles.py` (Closed workspace role-to-operation policy)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/api/views.py` (Workspace membership lifecycle API boundary)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_memberships.py` (Transactional workspace membership lifecycle and strict audit)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/migrations/0003_alter_workspacemembership_role_and_more.py` (Closed membership role database constraint migration)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services/_range_access.py` (Workspace-authorized interactive range access facade)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/services/_queries.py` (Exact request-and-workspace-correlated range projection)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api/principals.py` (Neutral active principal resolution for session and token requests)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services/_range_workspace.py` (CMS workspace authorization seam for range operations)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_memberships.py` (Workspace membership lifecycle, authority, invariants, and audit tests)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_api.py` (Workspace membership API authorization, scope, and error-contract tests)
- TESTS → TEST `shifter/shifter_platform/tests/integration/engine/test_consumers_integration.py` (Range consumer and CMS correlation integration tests)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_queries.py` (CTF range correlation and membership-revocation query tests)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_vpn_profile_api.py` (Workspace membership revocation at VPN secret-delivery boundary)
- DOCUMENTS → DOCUMENTATION `docs/features/workspaces.md` (Workspace membership roles user documentation)
- IMPLEMENTS → GITHUB_ISSUE `1326` (Workspace membership and roles)
- DOCUMENTS → DOCUMENTATION `docs/architecture/workspace-membership-roles-preflight-1326.md` (Workspace membership roles architecture preflight)
- IMPLEMENTS → PULL_REQUEST `1916` (feat(platform): add workspace membership roles)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services/_range_create.py` (Workspace-authorized range launch facade (optional selection, admission seam, lock-safe reauth))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services/_raes_range_create.py` (RAES-native launch path threads the same workspace selection and admission seam)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/services/_range_backend_binding.py` (Engine idempotent-create workspace-binding replay guard (ADR-046-R9))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/ranges.py` (Mission Control launch command accepts and maps the optional public workspace selection)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_range_workspace_selection.py` (Workspace selection, lock-safe reauthorization, and launch-admission seam behavior)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_range_workspace_scoping.py` (Cross-workspace denial across every interactive range lifecycle surface)
- DOCUMENTS → DOCUMENTATION `docs/architecture/range-workspace-scoping-preflight-1327.md` (Range workspace scoping architecture preflight (ADR-046-R9/R10))
- IMPLEMENTS → PULL_REQUEST `1931` (feat(platform): scope range launches to workspaces)

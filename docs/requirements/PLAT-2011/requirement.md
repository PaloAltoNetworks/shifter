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

The platform shall provide a stable typed Account root above Organization and Workspace in the bounded workspaces domain. Individual accounts shall own resources directly without organization or workspace subdivisions; team and enterprise accounts shall have a default organization, and every organization shall have a default workspace, with additional subdivisions permitted. Organization and Workspace public and internal IDs shall be preserved where ancestry is valid. New account membership shall target a stable principal and shall never arise merely from default creation; existing organization and workspace memberships retain their durable rows until the coordinated S8 cutover. The shared scope contract and owning-domain schema shall require explicit account scope with valid optional organization/workspace ancestry for new account-scoped resources; installation scope shall be explicit rather than inferred from absent customer IDs. Existing workspace-bound rows retain their scalar scope and owner identity until S8. Owning domains shall retain scalar scope references without cross-layer model imports or ForeignKeys. Ambiguous historical personal-workspace and ownership evidence shall block the coordinated S8 cutover without deletion or guessed reassignment.


ADR-066 S4 clarification: principal-aware account administration, membership/ownership
facts, scoped profile/lifecycle commands and canonical DRF/browser adapters are
prepared without replacing production routes or legacy authority. The coordinated
S8 activation in #2321 binds these paths and maps historical facts. Prepared
Django-admin writes are disabled in favor of the canonical validated commands.

## Rationale

The earlier per-user personal organization/workspace compatibility rule in ADR-046 cannot represent an individual without invented subdivisions. ADR-066 supersedes that rule while retaining the workspaces domain boundary, validated scalar references, and durable organization/workspace IDs. S1 adds the new schema, contracts, and mapping checks; S8 is the single production activation point for new authority and final scope enforcement.

## Traceability

- IMPLEMENTS → ADR `docs/adr/index.yaml` (ADR-046: organization/workspace tenancy is a domain boundary above range ownership)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_organization.py` (Organization model)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_workspace.py` (Workspace model (organization FK, unique personal_for_user))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_membership.py` (WorkspaceMembership model (unique per workspace+user, closed role))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_authorization.py` (Workspace authorization seam (immutable result, indistinguishable denials))
- IMPLEMENTS → ADR `docs/adr/066-account-principal-resource-scope.md` (Supersedes the personal-workspace default and defines account scope)
- DOCUMENTS → DOCUMENTATION `docs/architecture/account-principal-scope-preflight-2314.md` (S1 account and principal architecture boundaries)
- IMPLEMENTS → GITHUB_ISSUE `2314` (Account, hierarchy, principal, and mapping implementation slice)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_account.py` (Stable typed Account and explicit principal membership)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/services/_account.py` (Type-correct defaults and exact ancestry resolution)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/identity_mapping.py` (Fail-closed classification of historical hierarchy and membership)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/migrations/0010_account_accountmembership_organization_is_default_and_more.py` (Forward account hierarchy schema)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/management/models.py` (Independent human and service principals with exact provider bindings)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/management/principals.py` (Principal lifecycle and bind-once provider identities)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/management/services.py` (Public principal service facade)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/management/migrations/0014_principal_providerbinding_and_more.py` (Forward principal and binding schema)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/management/migrations/0015_map_human_principals.py` (Durable user and complete provider-tuple mapping)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/management/migrations/0016_provider_binding_immutability.py` (Database-level binding immutability)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/identity_scope.py` (Explicit principal and resource scope contracts)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/migrations/0025_alter_auditlog_entity_type.py` (Audit vocabulary for account and principal mutations)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/models/provisioning.py` (Explicit account scope alongside retained workspace binding)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/models/range.py` (Explicit account scope on CMS range projection)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/migrations/0052_rangeinstance_account_id_and_more.py` (Forward CMS resource scope schema)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/models/_range.py` (Explicit account scope on Engine range)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/migrations/0087_range_account_id_range_organization_id_and_more.py` (Forward Engine resource scope schema)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/event.py` (Explicit account scope on CTF events)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/communication.py` (Explicit account scope on communication campaigns)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/migrations/0062_remove_ctfevent_ctf_event_public_registration_scoped_and_more.py` (Forward CTF resource scope schema)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_account_hierarchy.py` (Account hierarchy and ancestry constraints)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_legacy_account_mapping.py` (Legacy personal and shared organization mapping blockers)
- TESTS → TEST `shifter/shifter_platform/tests/management/test_principals.py` (Independent service lifecycle and provider-binding collision/immutability)
- TESTS → TEST `shifter/shifter_platform/tests/management/test_principal_mapping.py` (Exact legacy identity mapping and ambiguous-row blocker)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_identity_scope.py` (Principal reference and scope shape rejection)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_account_scope_schema.py` (Explicit scope persistence)
- IMPLEMENTS → CONFIG `scripts/check_layer_imports/layer_imports.yaml` (workspaces classified as a domain layer; facade-only access enforced)
- DOCUMENTS → DOCUMENTATION `docs/technical/shifter_platform/workspaces.md` (Workspaces domain technical documentation)
- DOCUMENTS → DOCUMENTATION `docs/technical/shifter_platform/management.md` (Principal identity technical documentation)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_models.py` (Tenancy model invariants (organization FK, unique membership, one personal workspace))
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_services.py` (Authorization seam and per-user personal workspace resolution)
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_backfill_migration_schema.py` (Upgrade proven against the real historical schema (unbound rows bound, none left))
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_range_workspace_binding.py` (Range scope binding across all three ownership projections; rehome semantics)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_raes_range_workspace_persistence.py` (Engine RAES seam persists exact scope and refuses a missing binding)
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
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services/_raes_range_create.py` (RAES-native launch path threads the same workspace selection and admission seam)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/services/_range_backend_binding.py` (Engine idempotent-create workspace-binding replay guard (ADR-046-R9))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/ranges.py` (Mission Control launch command accepts and maps the optional public workspace selection)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_raes_range_workspace_binding.py` (RAES launch retains exact workspace scope across CMS and Engine)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_range_workspace_scoping.py` (Cross-workspace denial across every interactive range lifecycle surface)
- DOCUMENTS → DOCUMENTATION `docs/architecture/range-workspace-scoping-preflight-1327.md` (Range workspace scoping architecture preflight (ADR-046-R9/R10))
- IMPLEMENTS → PULL_REQUEST `1931` (feat(platform): scope range launches to workspaces)

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/workspaces/models/_ownership.py` (S4 prepared administration; activation remains coordinated)

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services/_policy_range_scope.py` (S4 prepared administration; activation remains coordinated)

- TESTS → TEST `shifter/shifter_platform/tests/cms/test_policy_range_scope.py` (S4 prepared administration; activation remains coordinated)

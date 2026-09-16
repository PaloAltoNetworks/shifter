# Organization/workspace layer preflight

Issue: #1325, "ADR + data model: organization/workspace layer above user-owned ranges"

This note records architecture guardrails for the implementation. It is not an
implementation plan and does not add application code or migrations.

## Decision

Adopt ADR-046. Add one bounded `workspaces` domain app, classified as a domain
layer, to own the three requested entities. `workspace` in this note means the
new tenancy domain only. It is unrelated to the existing SPA navigation areas,
Terraform staging directories, or cloud-provider tenants.

```text
Organization 1 --- * Workspace 1 --- * WorkspaceMembership * --- 1 auth.User
                                  |                 (one role code)
                                  |
      CMS Request / CMS RangeInstance / Engine Range
                    (validated scalar workspace_id)
                                  |
                           Workspace.id
```

The workspace service is the authorization seam. It returns a small immutable
authorization result (workspace internal ID, public UUID, organization ID and
effective membership role), never an ORM model for another layer to mutate.
CMS resolves that result before it reserves a range; Engine persists the bound
ID supplied by trusted CMS orchestration. This preserves ADR-001: CMS/Engine do
not import workspace models or use cross-layer foreign keys.

### Data model contract

| Entity | Required persisted facts | Invariants / boundary |
| --- | --- | --- |
| `Organization` | internal integer primary key, immutable public UUID, display name, timestamps | Owns workspaces. It is a tenancy grouping, not an OIDC issuer, cloud account/project, Django group, or range network boundary. |
| `Workspace` | internal integer primary key, immutable public UUID, organization FK, display name, timestamps, nullable one-to-one `personal_for_user` | The organization FK is intra-domain and non-null. A non-null `personal_for_user` marks that user's compatibility workspace; public APIs accept UUIDs, never internal IDs. |
| `WorkspaceMembership` | workspace FK, auth-user FK, closed role code, timestamps | DB uniqueness on `(workspace, user)`. `owner` is required for compatibility rows; the role vocabulary and permission matrix beyond that are owned by #1326, not copied into Django groups or API scopes. |
| range/request bindings | `workspace_id` integer on `cms.Request`, `cms.RangeInstance`, and `engine.Range` | Opaque scalar references because cross-layer FKs are prohibited. CMS request intent is the launch-source binding; CMS RangeInstance is a projection; Engine Range is the realized-range binding. They are not independently editable ownership fields. |

The internal integer plus public UUID shape deliberately follows the existing
range-style split. It lets the current `shared.audit.AuditEvent.entity_id: int`
and internal orchestration keep their canonical shape while preventing public
API callers from selecting a workspace by enumerable internal primary key.

Do not add an `owner_user` to `Workspace`: it duplicates membership. A
workspace creation service creates its initial owner membership in the same
transaction. It must prevent removal/demotion of the last owner with a locked
membership query. Database uniqueness proves one membership row per user; the
last-owner invariant is a transactional service invariant, not an unreviewed
trigger or signal side effect.

`Range.user`, `cms.Request.user`, and `cms.RangeInstance.user_id` remain the
range's user-owner/actor facts. A membership is workspace-level authorization,
not a grant to use every member's remote access. Existing per-range terminal,
Guacamole, VPN, CTF participant/event, source, and lifecycle checks remain
mandatory. This keeps the model compatible with the isolation work tracked by
#324: organizational scope changes neither provider resource ownership nor
network, remote-access, egress, or cross-range isolation controls.

## Compatibility and migration guardrails

Every existing user-owned range must resolve to that user's personal workspace,
under a personal organization, with an `owner` membership. There must never be
one shared `Default`, `Personal`, or deployment organization used as a fallback
for all accounts. New single-user launches resolve the same personal workspace
inside the single workspace service; the existing user-owned range APIs and
their per-user active-range admission stay behaviorally unchanged in #1325.

The migration must use the repository's additive/backfill/prove pattern:

- New binding columns begin nullable; after historical bindings are populated
  and verified, they become non-null for new rows. Do not use a model default
  that assigns one tenant to every historical row.
- Historical model access uses `apps.get_model`. Create organization, personal
  workspace, and owner membership atomically and idempotently per user. A
  migration must not depend on application startup signals.
- Reconcile `engine.Range.user`, `cms.Request.user`, and
  `cms.RangeInstance.user_id` through the established request/range linkage.
  A missing, mismatched, or ambiguous active ownership chain is a deployment
  blocker reported without credentials or user email; it is not permission to
  guess a workspace or hard-delete/state-edit a live range.
- Preserve the current `RangeInstance` active-range constraint
  `(user_id, range_source)` and `Range.get_active_for_user()` behavior. A
  change to per-workspace quotas/admission is #1327's explicit policy decision,
  not an accidental consequence of adding a column.
- Existing CTF event/team/participant memberships and range-source projection
  stay separate. CTF rows may receive the user's personal workspace binding for
  storage compatibility, but no CTF event becomes a workspace and no workspace
  membership grants CTF visibility or access.
- Owner reassignment already has one CMS-to-Engine transactional facade in
  `cms.services._range_reassign`. It must either require a target user who is
  authorized in the existing workspace or invoke a separately authorized,
  audited workspace-rehoming operation that moves all three bindings together.
  It must never retain the old scope by accident after changing `Range.user`.

Migration proof must cover a clean install, an upgrade with existing
Mission-Control and CTF ranges, a pre-existing owner reassignment, idempotent
backfill, active-range constraint preservation, and loud rejection of divergent
legacy evidence. Reuse the existing explicit migration-test and
`makemigrations --check` conventions; do not test migration behavior solely by
mocking services.

## Identity and authorization

The canonical identity key remains `UserProfile`'s verified `(issuer, subject)`
binding, owned by `management.services.bind_provider_identity` and established
by `config.oidc.ShifterOIDCBackend` / `config.identity_platform`. #1325 adds no
OIDC setting, claim parser, group mapping table, provider API call, or automatic
membership synchronization.

The future integration seam is after those adapters have verified the token and
bound the user. A provider-group-to-organization mapping may later be added only
as an allowlisted, deployment-configured adapter with provenance, revocation,
strict audit, and a single workspace-service write path. It must not:

- Treat a provider group name, email domain, `custom:user_type`, or arbitrary
  claim as a workspace UUID or a role value.
- Reuse `auth.Group`, `UserProfile.cognito_groups`, or the CTF Organizer signal
  as the workspace membership store.
- Permit a user-controlled claim to elevate a local membership, or revoke a
  locally assigned membership without an explicit provenance rule.

For future `/api/v1` endpoints, the role check is additive to authentication:
session users and API-token `created_by` principals must each resolve an active
workspace membership after `IsAuthenticatedSessionOrApiToken` and an exact,
new scope from `shared.api_tokens.scopes`. A token scope never represents a
workspace role and wildcard scopes remain forbidden. Input workspace UUIDs
belong in DRF serializers; service code resolves them to internal IDs and does
not trust a body/path integer.

## Cross-cutting concerns to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Layering and model ownership | `scripts/check_layer_imports/layer_imports.yaml`, `.importlinter`, `management/management/commands/check_model_fks.py` | Classify `workspaces`; expose only `workspaces.services`; use scalar bindings in CMS/Engine. |
| Range ownership, admission, and projection | `cms.services._range_create`, `_range_queries`, `_range_reassign`, `engine.services`, `engine.models.Range` | Preserve current user ownership and source admission; put workspace resolution at the existing CMS facade, not views or provisioner code. |
| Identity | `config.oidc`, `config.identity_platform`, `management.services` identity bind/resolve, `config.organizer_authority` | Only consume already verified identity; keep workspace authority independent of existing CTF group synchronization. |
| HTTP auth, scopes, validation | `config._drf_settings`, `shared.api.permissions`, `shared.api_tokens.authentication`, `shared.api_tokens.scopes`, DRF serializers | Reuse session/token gates and exact scope registry; validate public UUIDs once at the boundary. |
| Error envelope | `shared.api.errors.api_exception_handler` and `api_error_response` | Return canonical sanitized `error` envelopes with request IDs; never expose membership existence, database constraints, claim data, or raw exceptions. |
| Transactions and concurrency | `transaction.atomic`, `select_for_update`, DB unique constraints, `cms.services._range_reassign` | Serialize membership/owner changes and range rehoming; translate named constraint conflicts at the service boundary. |
| Audit and logging | `shared.audit`, `shared.audit.vocabulary`, `RequestIDMiddleware`, `shared.log_sanitize` | Add workspace/membership vocabulary only with a real mutation surface; use strict audit for authority/rehome changes and sanitized, low-cardinality logs. |
| Migrations and deployment | existing `RunPython` migration tests, `manage.py makemigrations --check`, deploy-owned `manage.py migrate --noinput` | Use historical models and forward-safe data checks; do not add a bootstrap script, direct SQL runbook, or a second migration runner. |

## Security and whole-repository gates

The implementation crosses these layers and must satisfy all of them:

- **Identity/auth:** OIDC and Identity Platform adapters retain their existing
  issuer, audience, authorized-party, subject, and verified-email validation.
  Workspace resolution starts with the resulting Django user; it never parses
  unverified claims in a view, migration, worker, or provider task.
- **HTTP policy:** canonical DRF authentication, permission, scope, serializer,
  schema, CSRF/session, and throttling behavior stay in force. Scope workspace
  resource queries before serialization so unauthorized callers neither list
  nor receive details of another workspace/range. Do not add an ad-hoc JSON
  route, `csrf_exempt`, browser token storage, or custom error hierarchy.
- **Persistence:** intra-domain FKs, unique membership, non-null workspace
  organization, immutable public UUIDs, `select_for_update`, and the existing
  range/user projection transaction are the enforcement layers. Scalar
  cross-layer references require the workspace service to validate existence,
  membership, and lifecycle before persistence; a future delete/rehome service
  must check every bound range rather than relying on database cascade.
- **Errors and observability:** use `shared.api.errors`, request IDs,
  `shared.audit`, and `shared.log_sanitize`. Error bodies and logs may contain
  stable codes and sanitized correlation, not raw SQL/IntegrityError text,
  emails, ID tokens, headers, group lists, token values, membership rosters, or
  remote-access data.
- **Configuration and secrets:** #1325 needs no environment variable. If later
  identity mapping requires non-secret configuration, parse it in the existing
  split-settings owner (normally `_oidc_settings`), regenerate
  `config/env-manifest.json`, and update the applicable AWS/GCP/Helm runtime
  renderer. Secrets remain in the existing secret-hydration surfaces, never in
  claim-mapping env dumps, migrations, logs, URLs, command argv, or artifacts.
- **OS/process/runtime:** the data model and migration invoke no provider CLI,
  shell, task runner, Terraform, Kubernetes, or network policy change. Existing
  deploy-owned migration execution remains the only migration runner; no range
  or workspace data enters process argv. Infrastructure validators are out of
  scope unless the implementation later edits those assets.
- **Repository controls:** adding an app requires `INSTALLED_APPS`, layer
  classification, `.importlinter`, migration drift, ADR guard, Ruff, and the
  relevant Django test suite to pass. The production migration path is already
  run once by the deploy workflow; do not weaken it or alter its credentials.

The extensibility seam is the one workspace authorization result and service
facade: it accepts an actor, public workspace UUID, requested operation, and
optionally a trusted range binding; it returns the effective membership fact or
a classified denial. #1326 can extend its role-to-operation policy and #1327
can make queries/admission workspace-aware without adding model imports,
changing public identifiers, or reinterpreting user ownership. Future provider
group mapping calls this same seam after verification.

## Gotchas, anti-patterns, and non-goals

- Do not call an organization a cloud tenant, range VPC, event, CTF team, API
  token audience, or SPA workspace. Those boundaries remain independent.
- Do not use a global default workspace, nullable forever workspace bindings,
  a JSON list of user IDs, a user-owned range's `user_id` as an implicit
  workspace, or a free-form role string without central validation.
- Do not duplicate membership validation in serializers, views, CMS, Engine,
  CTF, provisioner payloads, frontend state, or provider labels. The workspace
  service authorizes; existing domains enforce their own resource rules.
- Do not leak range existence through an unscoped lookup, enumerate internal
  workspace IDs in public URLs, use workspace membership as remote-access
  authorization, or omit audit/locking from membership and rehome mutations.
- Do not silently repair mismatched historical ownership or widen the current
  active-range quota. Use normal lifecycle recovery or an explicit operator
  decision before migration continuation.
- No organization lifecycle/deletion policy, invitations, SCIM, OIDC group
  synchronization, public workspace API, role matrix, quota redesign, range
  sharing, cloud-account/project tenancy, network/isolation change, CTF model
  migration, provider payload change, or frontend workspace is decided here.

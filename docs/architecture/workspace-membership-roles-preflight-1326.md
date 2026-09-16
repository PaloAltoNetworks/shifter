# Workspace membership and roles preflight

Issue: #1326, "Workspace membership and roles"

This note fixes the architecture boundary for membership lifecycle and
authorization on the model delivered by #1325. It is not an implementation
plan and adds no application code, API route, or migration.

## Decision

Extend the existing `workspaces` domain and its public `workspaces.services`
facade. Do not add a second membership store.

The initial roles are closed, workspace-scoped values:

- `owner`: the protected authority established for personal workspaces and the
  only role allowed to grant or revoke ownership;
- `admin`: may administer non-owner memberships in that workspace;
- `member`: may use that workspace for operations on resources the existing
  product policies already allow the user to own or access.

There is no organization role and no `OrganizationMembership` in this
iteration. An organization's member set may be projected as the union of its
workspace memberships for an authorized read, but that projection grants no
authority. In particular, do not encode `org_admin` on a
`WorkspaceMembership`, infer it from membership in one workspace, or copy the
same row into every workspace. A future organization-wide administrator is a
separate authority source and needs an explicit ADR amendment.

This keeps #1326 on the three-entity model accepted by ADR-046:

```text
Organization 1 --- * Workspace 1 --- * WorkspaceMembership * --- 1 auth.User
                                  |             owner/admin/member
                                  |
                 CMS Request / RangeInstance / Engine Range
                           (scalar workspace_id)
```

### Fixed role boundaries

The exact operation codes live only in `workspaces.roles.WorkspaceOperation`
and the role-to-operation matrix lives only beside them. Callers ask whether an
actor may perform an operation; they never compare role strings.

| Capability | owner | admin | member | Additional invariant |
| --- | --- | --- | --- | --- |
| Read/use the workspace for the actor's own allowed ranges | yes | yes | yes | Existing range ownership, source, state, participant-channel, and remote-access checks remain additive. |
| Read the membership roster | yes | yes | no | A member may read only their own effective membership. |
| Add/remove a member or admin | yes | yes | no | An exact duplicate add may be idempotent; it must never become an implicit role change. |
| Change `member` and `admin` roles | yes | yes | no | The target cannot be an owner. |
| Grant, demote, or remove an owner | yes | no | no | At least one locked owner must remain. |
| Leave the workspace | yes | yes | yes | An owner may leave only when another owner remains. |

`is_staff`, `is_superuser`, Django groups, identity-provider groups, API-token
scopes, CTF organizer status, and provider claims do not imply a workspace
role. Platform break-glass administration remains a separately authenticated
operator/database concern; it is not a hidden bypass in the public service or
API.

The role check never broadens resource access. A workspace admin does not gain
SSH, RDP, VPN, Guacamole, lifecycle, or visibility access to another member's
range. Conversely, user ownership alone is no longer sufficient for an
interactive operation on a workspace-bound range: the actor must still hold a
role that permits the requested workspace operation. Removing a membership
therefore revokes future interactive use without silently rehoming or deleting
the user's ranges; existing server-owned expiry and cleanup continue against
the trusted persisted binding.

### Personal-workspace compatibility

The `personal_for_user` workspace and that user's `owner` membership are a
compatibility invariant, not ordinary editable membership data:

- the personal owner cannot leave, be removed, or be demoted;
- another user cannot be added to a personal workspace;
- `resolve_personal_workspace` must validate the persisted owner membership,
  not synthesize an `owner` result when the row is absent or changed;
- lazy personal-workspace creation remains the clean-install/default path, so a
  single-user deployment needs no role bootstrap command, fixture, environment
  variable, or manual database edit.

Do not "repair" a malformed existing personal membership during an unrelated
request. Fail closed with bounded diagnostics; migrations or an explicit
operator repair own historical correction.

## Membership lifecycle boundary

The public workspace service owns list/self-read, add-existing-user,
change-role, remove, and leave commands. A command receives the authenticated
actor, a public workspace UUID (or a trusted internal binding), the target user
identity where applicable, an operation code, and request-attributed audit
context. It returns immutable scalar projections, never ORM objects.

`invite/add` in #1326 means adding an existing Shifter account. Pending
invitations for an email address, invitation tokens, account provisioning, and
email delivery are not part of this iteration. Do not label an add operation as
an invitation or send a best-effort email that suggests a durable invitation
exists. A later pre-registration invitation flow needs its own expiring,
single-use token model, secret-delivery threat model, revocation, and email
contract.

Serializer validation and domain validation have different jobs:

- DRF serializers shape-check the UUID, target user ID, role choice, and
  bounded request body.
- The workspace service revalidates the closed role, actor/target relationship,
  personal-workspace rule, owner/admin authority, and last-owner invariant.
- The database retains `(workspace, user)` uniqueness and must enforce the
  closed role set with a check constraint; model `choices` and `full_clean()`
  alone are not a persistence boundary.

Mutation is atomic. Lock the workspace as the stable per-workspace mutex before
locking/reading its affected memberships, so two concurrent owner removals or
role changes cannot each observe a different last owner. Translate the named
unique/check constraints into bounded domain outcomes; never return raw
`IntegrityError` or database text.

Use one public workspace service error contract with stable classified codes.
Keep `WorkspaceAuthorizationError`'s non-enumerating behavior for absent
workspace, absent membership, and insufficient role. Do not create a parallel
DRF exception hierarchy inside the domain; the API boundary maps safe service
outcomes to the shared error envelope.

## Service-layer enforcement coverage

Every interactive operation on a row with a persisted `workspace_id` must pass
the workspace authorization service after authentication and before effects or
secret retrieval. A check in a DRF view, template, SPA, or WebSocket consumer is
defence in depth, not the authoritative check.

| Surface | Canonical incumbent | Required boundary |
| --- | --- | --- |
| Membership reads and commands | `workspaces.services`, `workspaces.roles` | Resolve one membership and operation through the domain policy; all writes are locked, atomic, and strict-audited. |
| Range launch and owner reassignment | `cms.services._range_create`, `_raes_range_create`, `_range_reassign`, `_range_workspace` | Reuse the existing workspace result and `LAUNCH_RANGE` / `REASSIGN_RANGE` operations. Do not accept an internal workspace ID from HTTP or resolve roles in Engine. |
| Owned range reads/history/lease | `cms.services._range_queries`, `_range_lease` | Scope by existing owner/source rules and authorize the row's persisted binding before returning a projection or changing a lease. |
| Pause/resume/cancel/destroy | `cms.services._range_lifecycle`, `_range_destroy` | Authorize the bound workspace in the CMS service before status mutation or Engine dispatch; preserve existing state and ownership checks. |
| VPN delivery | `cms.services._range_vpn` | Keep this facade as the product-neutral owner/workspace check before Engine retrieves provider material. |
| Terminal, SSH/RDP, and Guacamole | `engine.services._terminal`, `mission_control.consumers`, `_guacamole_session_builders` | Engine remains authoritative for range owner, READY state, declared channel, host key, and secret resolution, but remains workspace-model agnostic. Current user-facing Engine-direct calls need a CMS service authorization facade (or an equivalent layer-compliant service owner) before Engine access; a consumer/view-only role check is insufficient. |
| CTF participant operations | `ctf.services`/bridges plus the CMS facades | CTF event/team/participant authority remains separate and additive. Use the bound participant user for workspace authorization; a workspace role never grants CTF authority. |
| System lifecycle and callbacks | `expire_due_ranges`, Engine/provisioner callbacks, reconciliation handlers | Trusted system operations use persisted correlation and existing system policy, not a synthetic human role. Revocation must not prevent expiry, cleanup, or result reconciliation. |

This split preserves ADR-001 and ADR-046: CMS may consume
`workspaces.services`; Engine must not import workspace models or roles, and
other layers must not duplicate membership queries. The existing
`shared.range_visibility` and Engine participant-channel gates remain necessary
but do not substitute for membership authorization.

Tests must drive the real service and database across every role/capability
boundary, including denial after membership removal. Tests at the API layer
also prove session and token principals reach the same service decision. Mock
call assertions alone do not prove enforcement. The direct Engine-access
surfaces above are a known bypass until they are routed through a
service-authorized facade; #1326 must not be declared complete while an
interactive caller can reach them without the role check.

## API and contract boundary

The membership surface joins the canonical `/api/v1/` DRF API. Reuse:

- bearer-first `ApiTokenAuthentication` followed by `SessionAuthentication`;
- `IsAuthenticatedSessionOrApiToken`, with an active actor resolved from the
  session user or `ApiToken.created_by`;
- exact `workspaces:membership:read` and
  `workspaces:membership:write` scopes registered in
  `shared.api_tokens.scopes` and enforced with `require_scope`;
- explicit command serializers and read projections, not writable
  `ModelSerializer`s or a generic CRUD `ModelViewSet`;
- `PlatformAutoSchema`, `extend_schema`, the committed
  `openapi/v1.json`, and generated frontend `src/api/schema.d.ts`;
- `shared.api.errors.api_exception_handler` /
  `api_error_response` for every error response.

The current committed `openapi/v1.json` contains no workspace-membership
paths. #1329 supplies the publication and compatibility machinery, not an
already-authored membership wire shape. The runtime DRF routes and explicit
serializers must therefore be the source for an additive contract regeneration;
do not invent an undocumented route and do not hand-edit the JSON artifact.

An API-token scope only admits the HTTP operation. The token's active
`created_by` user must independently hold the required workspace role. Do not
mint a token with a workspace role, put a workspace UUID in a scope string, or
allow an unowned/service token with no user to mutate membership.

Authorize the workspace before resolving or returning a roster. Unknown
workspace, non-member, and insufficient-role outcomes remain indistinguishable.
After that gate, validation/conflict responses may distinguish an invalid role,
an unchanged add, a missing target membership, a protected personal workspace,
or the last-owner conflict without exposing another workspace. Responses
contain public workspace UUIDs and the minimum user/membership fields needed by
the contract; provider issuer/subject, provider groups, token identifiers,
credentials, and raw claims are never serialized.

The active-user resolution currently lives feature-locally as
`mission_control.api.permissions.mission_control_actor_user`. Do not copy that
session-versus-token logic into a second app. Promote the neutral behavior to a
shared API principal helper and retain Mission Control compatibility through
that one implementation.

## Audit, logging, and observability

Reuse `shared.audit` and its single vocabulary/event shape. Add the minimum
entity vocabulary needed to identify a workspace membership; use the existing
generic `CREATE`, `UPDATE`, and `DELETE` actions rather than inventing a second
membership action taxonomy.

Every actual membership or role mutation writes a strict audit event inside the
same transaction. An audit failure rolls the authority change back. Record the
membership's internal ID, workspace internal ID, target user ID, previous/new
role as applicable, actor type/ID, trusted source IP, user agent, and request
ID. Do not record an email address, display name, public/provider identity,
token, header, membership roster, or raw request body. Idempotent no-ops do not
pretend a change occurred.

Operational logs use `shared.log_sanitize`, internal numeric IDs or bounded
fingerprints, and low-cardinality reason/operation codes. The public error body
uses stable safe codes plus the `RequestIDMiddleware` correlation ID. Never log
or return raw ORM objects, SQL/constraint text, UUID probes, email lookup input,
Authorization headers, cookies, or remote-access material.

## Security and whole-repository layers

The design passes through these layers:

- **Identity verification:** `config.oidc`, `config.identity_platform`, and
  `management.services.bind_provider_identity` remain the only issuer,
  audience, authorized-party, subject, and verified-email/bind-once gates.
  Workspace code receives the resulting Django user and never parses claims.
- **Account admission:** `CTFAccountBoundaryMiddleware`, active-user checks,
  API-token revocation/expiry, and the token's `created_by` binding stay in
  force. Temporary CTF-account route restrictions are not replaced by a role.
- **HTTP shape and policy:** DRF authentication, session CSRF, exact token
  scope, explicit serializers, role service, and canonical throttling/schema
  behavior all run. No ad-hoc JSON view, `csrf_exempt`, wildcard scope, or
  frontend-only guard is permitted.
- **Persistence:** intra-domain FKs, immutable public UUIDs, membership
  uniqueness, a role check constraint, `transaction.atomic`, and
  `select_for_update` enforce durable invariants. CMS/Engine bindings remain
  non-null opaque scalars and no cross-layer FK or cascade is added.
- **Resource authorization:** workspace role is additive to the existing
  range-owner, product source, lifecycle state, CTF participant/event,
  declared-channel, and secret-reference gates. A pass at one layer never
  bypasses the next.
- **Errors and observability:** `shared.api.errors`, `shared.audit`,
  `RequestIDMiddleware`, trusted proxy attribution, and
  `shared.log_sanitize` bound all outward diagnostics and mutation records.
- **Configuration/secrets:** the add-existing-account design requires no new
  environment variable, provider claim mapping, invitation secret, email
  setting, or secret-manager value. Therefore `config/env-manifest.json`,
  AWS/GCP/Helm renderers, and secret hydration do not change.
- **OS/process/runtime:** no membership value, email, token, or role is placed
  in process arguments, shell commands, environment dumps, provider labels, or
  task payloads. The change is portal/DB/API-local; Terraform, Kubernetes,
  network policy, IAM, worker queues, and provisioner contracts are out of
  scope.
- **Repository controls:** preserve `scripts/check_layer_imports`,
  `.importlinter`, model-FK checks, migration drift, OpenAPI drift/breaking
  checks, generated frontend types, ADR guard, Ruff, and real Django tests.

The extensibility seam is the existing
`authorize_workspace(actor, workspace, operation)` contract plus the central
operation matrix. A future role adds one closed value and matrix row; a future
organization-wide authority may contribute an explicitly sourced effective
grant behind the same authorization call. Neither change requires callers to
inspect role strings, import models, change public workspace identifiers, or
reinterpret API-token scopes.

## Gotchas and anti-patterns

- Do not add `OrganizationMembership`, `org_admin`, per-workspace copies of an
  organization role, or an organization-wide override in #1326.
- Do not equate owner/admin/member with Django staff/superuser, `auth.Group`,
  CTF organizer/participant, user type, provider groups, API-token scopes, or
  cloud IAM roles.
- Do not let a workspace admin operate another member's range, and do not let
  range ownership bypass a revoked workspace membership.
- Do not mutate memberships through Django signals, model `save()` overrides,
  admin-only direct ORM writes, serializers, views, or provider adapters.
- Do not check only at route/view/consumer level or import workspace policy into
  Engine. Route interactive Engine-direct access through an authorized service
  boundary.
- Do not accept internal workspace IDs from HTTP, expose a global membership
  roster, vary an opaque authorization error by workspace existence, or return
  raw database errors.
- Do not leave role validity to `choices`, count owners without locks, allow an
  admin to mutate an owner, or silently change role during an add retry.
- Do not remove/demote the personal owner, add collaborators to a personal
  workspace, auto-repair authority during a request, or create a deployment
  global default workspace.
- Do not implicitly destroy/rehome ranges on member removal or treat system
  cleanup as a human role operation.
- Do not create invitation-token, email, SCIM, OIDC-group-sync, policy-editor,
  or bespoke per-deployment role machinery under the label of membership.

## Non-goals

- Organization-level membership/roles and organization lifecycle.
- Pending/pre-registration invitations, account creation, or email delivery.
- Workspace creation, deletion, transfer, or a role editor.
- Workspace selection, shared-range visibility, admin access to another
  member's range, per-workspace quota/admission, or range sharing; those require
  the separately reviewed workspace-query/admission policy.
- SCIM or provider-group synchronization and claim-to-role mapping.
- Changes to CTF membership, remote-access semantics, catalogs, NGFW/platform
  infrastructure, cloud tenancy, network isolation, provider payloads,
  Terraform, Kubernetes, IAM, or deployment configuration.

# Shifter Workspaces

Organization/workspace tenancy above user-owned ranges.

Governing decision: [ADR-046](../../adr/index.yaml). Design guardrails:
[organization/workspace preflight](../../architecture/organization-workspace-preflight-1325.md),
[membership/roles preflight](../../architecture/workspace-membership-roles-preflight-1326.md),
[range-scoping preflight](../../architecture/range-workspace-scoping-preflight-1327.md),
and [administration-console preflight](../../architecture/organization-workspace-admin-console-preflight-1938.md).

## What this domain is for

A university, research lab, or hosting operator runs one Shifter deployment as
shared infrastructure. An organization owns workspaces, a workspace has members
with roles, and a range is scoped to a workspace in addition to its individual
owner. Multi-organization deployments use the same model, so no single-tenant
assumption is baked into the schema.

An organization is *only* a grouping of workspaces and members. It is not an
OIDC issuer, a cloud account or project, a Django `auth.Group`, a CTF event, an
API-token audience, an SPA navigation area, a Terraform workspace, or a range
network boundary.

## Models

| Model | Purpose |
|-------|---------|
| `Organization` | Tenancy grouping that owns workspaces; carries the editable profile (`name`, `description`, `support_email`, `support_url`) |
| `Workspace` | Scope that holds members and owns range scope; belongs to exactly one organization |
| `WorkspaceMembership` | One user's role in one workspace |
| `OrganizationMembership` | One user's organization-level role (ADR-048); the persisted organization authority seam |

Invariants enforced in the database:

- a workspace belongs to exactly one organization (non-null FK);
- a workspace name is unique within its organization;
- a user has at most one membership per workspace;
- membership role is one of `owner`, `admin`, or `member`;
- a user has at most one *personal* workspace (`personal_for_user` is unique);
- a user has at most one organization membership per organization, and its role
  is the closed `OrganizationRole` vocabulary (initially `admin`).

Both `Organization` and `Workspace` carry an internal integer primary key and an
immutable public `uuid`. Internal orchestration and the integer
`shared.audit` entity id use the primary key; public surfaces accept and emit
only the UUID, so callers cannot enumerate tenants by counting primary keys.

A workspace has no `owner_user` column. Ownership is a membership row, so there
is one place authority is recorded.

## Service interface

`workspaces.services` is the only module other layers may import. They must not
import `workspaces.models`, and they must not hold a ForeignKey to a workspace
(ADR-001-R2 forbids cross-layer FKs).

| Function | Purpose |
|----------|---------|
| `resolve_personal_workspace(user)` | Return the user's personal workspace, creating it on first use |
| `authorize_workspace(actor, workspace_uuid, operation)` | Authorize against an untrusted, externally supplied workspace UUID |
| `authorize_bound_workspace(actor, workspace_id, operation)` | Authorize against a trusted, already-persisted internal binding |
| `authorize_launch_workspace_locked(actor, workspace_id, operation)` | Authorize a bound scope under the workspace mutex; run inside the reservation transaction so membership cannot be revoked mid-launch |
| `get_self_membership(actor, workspace_uuid)` | Return the actor's minimum membership projection |
| `list_workspace_memberships(actor, workspace_uuid)` | Return the roster to an owner or admin |
| `add_workspace_member(...)` | Add an existing active account with a closed role |
| `change_workspace_member_role(...)` | Change a role under the owner boundary |
| `remove_workspace_member(...)` | Remove another member while retaining an owner |
| `leave_workspace(...)` | Remove the actor's own non-personal membership |
| `get_organization_profile(actor, organization_uuid)` | Return the organization profile projection, authorized by org-admin membership or superuser (ADR-048) |
| `update_organization_profile(actor, organization_uuid, changes, *, audit)` | Atomically apply a partial profile update under the same authority, strict-audited |

Authorization functions return a frozen `WorkspaceAuthorization` (workspace
ID, public UUID, organization ID, role) and never an ORM instance. Membership
queries and commands return frozen minimum projections.

`engine.services.rebind_range_workspace_by_request` is the Engine half of the
rehoming operation; CMS owns the decision and calls it so the Engine range's
scope moves with the CMS projections.

Denials raise
`WorkspaceAuthorizationError` with a single message. A missing workspace, a
non-membership, and a role that does not permit the operation are deliberately
indistinguishable, because the difference is a tenant-enumeration oracle.

Membership commands lock the workspace as their transaction mutex and recheck
the actor's live grant while locked. They retain at least one owner, reserve
owner changes to owners, protect personal-workspace ownership, and write a
strict audit record in the same transaction.

## Role policy and API

The closed role policy is owned in `workspaces.roles`; callers ask the service
about an operation and do not compare role strings themselves. All roles can
act on their own workspace-bound resources, subject to the existing range
owner, source, lifecycle, CTF, and remote-access checks. Owners and admins can
manage the roster, but only owners can grant or revoke ownership.

Organization-level authority is a **separate** accepted model (ADR-048), not a
workspace role. `OrganizationMembership` holds an org-scoped `admin` role and is
the only source of organization authority; it is never derived from a workspace
role, Django staff/groups or model permissions, provider claims, API-token
scopes, or cloud roles (ADR-046-R8/R12). A Django `is_superuser` is the sole
platform-operator override—able to read/update any organization, audited
distinctly—while `is_staff` alone grants nothing. Each personal organization
seeds its personal-workspace owner as its bootstrap admin (at
`resolve_personal_workspace` creation and by the #1939 backfill), after which
authority is read from the persisted membership. See
[`org-workspace-admin-console.md`](./org-workspace-admin-console.md) for the
organization profile API and settings surface.

The DRF routes are mounted below `/api/v1/workspaces/{workspace_uuid}/`. Reads
require the exact `workspaces:membership:read` API-token scope and changes
require `workspaces:membership:write`. Session authentication and API-token
scope checks establish the actor but never replace the service-layer role
check. The API returns minimum projections and the shared sanitized error
envelope.

## How ranges are scoped

`cms.Request`, `cms.RangeInstance`, and `engine.Range` each carry a scalar
`workspace_id` column. It is a soft reference, matching the existing
`RangeInstance.range_id` / `user_id` and `UserProfile.active_ctf_event_id`
convention, because cross-layer ForeignKeys are prohibited.

The CMS range-create facade resolves and authorizes the scope once, then carries
it beside the `RequestSpec`—the same shape as the `backend_admission` binding—so Engine persists it in the range's create transaction. Engine never resolves
or authorizes a workspace itself.

An interactive launch may select a workspace by supplying its **public UUID**
(`workspace_uuid`) on the launch command; omission binds the launcher's personal
compatibility workspace, so existing single-user clients are unchanged. Only the
public UUID is accepted—an internal integer, role, organization ID, or name is
never trusted from HTTP—and a malformed, unknown, unauthorized, or non-member
selection is denied with the single non-enumerating message rather than falling
back to the personal workspace. Because a shared-workspace membership can be
revoked concurrently, the reservation reauthorizes the resolved scope under the
workspace row mutex (`authorize_launch_workspace_locked`) and holds that lock
across the request/range insert, so a removal committing mid-launch cannot leave
a range scoped where its owner cannot reach it. A single pre-reservation
workspace launch-admission seam (`admit_workspace_launch`) that both the
cyberscript and RAES paths pass through is the one attachment point for a future
durable per-workspace quota or effective workspace egress policy; the initial
policy admits with no additional limit and does not change the
`(user_id, range_source)` active-range constraint. Engine idempotent create is
defense in depth: a create replay whose `workspace_id` differs from the persisted
range is refused as a binding conflict rather than silently reused.

`Range.user`, `cms.Request.user`, and `cms.RangeInstance.user_id` remain the
range's owner. **Workspace membership is workspace-level authorization only: it
grants no SSH, RDP, VPN, Guacamole, or CTF access to another member's range.**

Every interactive CMS operation on a persisted range binding also asks the
workspace service for `read_range`, `manage_range`, or `access_range`.
Collection reads omit ranges whose membership has been revoked; point and
mutation operations return a non-enumerating denial. Mission Control reaches
terminal, SSH, and RDP through CMS's authorized facade before Engine resolves
credentials. System-attributed expiry and provider callbacks bypass this human
role gate so cleanup cannot be stranded by membership removal.

Reassigning a range's owner requires the new owner to be a member of the range's
workspace, so a range is never left scoped to a tenant its owner cannot reach.
For a handover that legitimately crosses tenants—a pre-provisioned CTF spare
range being given to a participant—the caller asks for it explicitly with
`reassign_range_owner(..., rehome=True)`, and the range's scope moves to the new
owner across all three projections inside the reassignment transaction.
Rehoming is never implicit.

The invariant is enforced in two places, not by convention:

- **The database.** All three columns are non-null with no default
  (`cms.0040_workspace_binding_required`,
  `engine.0042_workspace_binding_required`). An unscoped range is not a
  reachable state. A default would let a creation path persist a placeholder
  tenant, which is what the constraint exists to prevent.
- **The Engine creation boundary.** `engine.services.create_range` and
  `create_raes_range` take `workspace_id` as a required argument and refuse a
  missing one, so a caller that forgets it fails loudly at the seam rather than
  at an integrity error deep in a transaction.

The columns were introduced nullable so historical rows could be validated and
backfilled without a default silently assigning one tenant to everyone, then
made mandatory once that completed.

## Compatibility

Every user owns one personal workspace inside its own personal organization. The
`0002_backfill_personal_workspaces` migration creates them for existing accounts
and the CMS/Engine backfills bind existing ranges to their owner's workspace, so
a single-user install behaves exactly as before.

There is deliberately **no shared deployment-wide "Default" organization**. A
global default would make every install single-tenant by construction and would
have to be unpicked before a second tenant could exist.

The backfill proves historical ownership evidence is consistent before it writes
anything: if a range projection disagrees with its request, or CMS and Engine
disagree about who owns a range, the migration stops with a diagnostic naming
the row (never an email or credential) rather than guessing a tenant. The
non-null migrations run after it, so an upgrade that could not resolve a row
fails there instead of silently leaving it unscoped.

The upgrade is tested against the real historical schema
(`tests/workspaces/test_backfill_migration_schema.py`): it migrates the database
back to the nullable state, seeds genuinely unbound rows, and migrates forward.
That is the only way to exercise the path, since the current models can no longer
express an unbound row.

## What stays deployment-global

Tenancy scopes principals and range ownership. It does not scope platform
configuration or catalog. These remain deployment-global and do not acquire a
workspace binding as a side effect of this layer (ADR-046-R7):

- the scenario catalog and RAES package sources;
- the agent, operating-system, instance-type, and app catalogs;
- NGFW instances and platform network/infrastructure;
- cloud provider, range-backend, and deployment settings, including the
  environment manifest;
- identity-provider configuration and the API-token scope registry;
- the durable audit store;
- feature flags;
- CTF events, teams, and participants, which stay a separate membership model.

Each of these carries platform-operator authority rather than tenant authority,
so scoping any of them to a workspace needs its own decision. A workspace-level
policy surface—the zero-egress range posture in issue #1171, for example—is
added by an explicit decision on that surface, never inherited from here.

## Identity provider integration

Not implemented. The integration point is decided: provider group and claim
mapping happens *after* the existing `config.oidc` / `config.identity_platform`
adapters have verified issuer, audience, authorized party, subject, and verified
email and bound the Django user—the same position `config.organizer_authority`
occupies for CTF organizer authority. Any future mapping must be an allowlisted,
deployment-configured adapter with membership provenance, revocation, and strict
audit, writing through the workspace service. A provider group name is external
evidence, never a workspace UUID or a role code, and `auth.Group` /
`UserProfile.cognito_groups` are never the membership store.

# Organization/workspace admin console

The admin console (issue #1938, PLAT-231) is an SPA shell over the existing
workspace tenancy layer (ADR-046). It adds one read-only API and the client
shell, routing, workspace context, and switcher; it introduces no organization
authority model, no persisted workspace selection, and no new feature flag. The
binding boundaries are recorded in ADR-046-R11 and
[`organization-workspace-admin-console-preflight-1938.md`](../../architecture/organization-workspace-admin-console-preflight-1938.md).

## Current-principal context API

`GET /api/v1/workspaces/context/` returns the caller's existing workspace
memberships as a read-only projection: for each membership, the organization
(public UUID and name), the workspace (public UUID, name, and personal marker),
the caller's role, and the `WorkspaceOperation` codes that role permits.

- **Domain.** The view lives in the `workspaces` app
  (`workspaces/api/views.py:PrincipalWorkspaceContextView`) and reads through the
  service facade (`workspaces.services.list_actor_workspace_contexts`). No
  `config`, `management`, or frontend code imports workspace models or queries
  memberships directly.
- **Authorization.** Staff-session only. The bearer-first authentication chain
  parses an invalid token fail-closed before session fallback, and
  `IsStaffSession` rejects any valid platform token (including one owned by a
  staff user); the console read is deliberately not token-capable. Staff
  admission and per-workspace authority are additive and independent.
- **Capabilities.** Advertised capabilities are derived centrally from the
  role-to-operation policy (`workspaces.roles.role_permits`), so no consumer
  re-derives authority from a role string. They are advisory display data; every
  resource endpoint reauthorizes the operation it performs.
- **Side-effect free.** The GET reads existing rows with one bounded
  `select_related` query. It never creates or repairs tenancy state (it never
  calls `resolve_personal_workspace`), so a staff caller with no membership
  receives an empty page. The result is multi-organization-safe and paginated
  with the canonical page-number pagination.
- **Contract.** The serializer is authoritative; the generated OpenAPI
  (`openapi/v1.json`) and TypeScript types (`frontend/src/api/schema.d.ts`) are
  regenerated with `npm run gen:api`.

## SPA shell

The shell reuses the existing `/administer` area and the `administer_spa`
rollout; the Django host already serves `/administer/*` deep links when the flag
is on.

- **Routing.** An `organization` subtree under the `administer` route group
  (`frontend/src/router.tsx`), with path builders in
  `frontend/src/features/administer/routes.ts`. Organization-level slots sit
  under `/administer/organization`; workspace-scoped slots sit under
  `/administer/organization/workspaces/:workspaceUuid`.
- **Selection.** The selected workspace is the public-UUID route parameter,
  resolved against the context query by `resolveSelectedWorkspace`
  (`features/administer/organization/surfaces.ts`). A missing selection falls
  back to the first workspace; an invalid or stale UUID resolves to a
  "not found" state and never silently becomes another (or the personal)
  workspace. TanStack Query owns the server snapshot; the React context
  (`WorkspaceContext.tsx`) and the URL are not authority.
- **Navigation.** The "Organization" entry is registered in the central
  navigation contract (`frontend/src/app/nav.ts`), staff-gated and
  `administer_spa`-gated. The in-console section navigation is capability-aware
  (`surfaceEnabled`): sections whose required `WorkspaceOperation` the role does
  not permit are shown disabled. The membership surface is the deliberate
  exception to a single-operation gate: `member` lacks `read_members` but may
  read its own membership and leave, so it opens in a self-service state when
  either server-advertised capability applies; it never derives that access from
  a role code. The Django admin escape hatch remains an unflagged external entry
  at `/admin/`, outside this subtree. See
  [`workspace-membership-spa-preflight-1941.md`](../../architecture/workspace-membership-spa-preflight-1941.md).
- **Slots.** Later child surfaces are route slots rendering a placeholder
  (`ConsoleSlotPage`) until their owning issues (PLAT-236–239) land. The
  organization settings, workspace lifecycle, membership, and invitation slots
  are now real surfaces (see below and the invitation design note).

## Organization profile & settings (issue #1939, PLAT-232)

The first console surface to replace a placeholder. It adds an organization
authority model and a UUID-keyed read/update API for the organization profile.
The binding boundaries are recorded in ADR-048, ADR-046-R12, and
[`organization-profile-settings-preflight-1939.md`](../../architecture/organization-profile-settings-preflight-1939.md).

### Organization authority (ADR-048)

ADR-046-R8 left the tenancy layer with no organization-wide role. ADR-048 is the
separately accepted authority model ADR-046-R12 requires:

- **Persisted role.** `OrganizationMembership` (`workspaces/models/_organization_membership.py`)
  is a `(organization, user, role)` row with a closed, database-checked
  `OrganizationRole` vocabulary (initially `admin`), owned by the `workspaces`
  domain and reachable only through `workspaces.services`.
- **Never derived.** Read/update authority is resolved only from an `admin`
  membership for that organization—never from a `WorkspaceRole`, Django
  `is_staff`/groups, Django model permissions, identity-provider claims,
  API-token scopes, or cached client capabilities.
- **Superuser override.** A Django `is_superuser` is the sole platform-operator
  override: it may read/update any organization, recorded distinctly in audit
  (`superuser_override`). `is_staff` without superuser or an admin membership is
  denied. The override lives in the service, not as an HTTP-layer permission
  shortcut.
- **Bootstrap.** Each personal organization (ADR-046-R4) seeds its personal
  workspace owner as its bootstrap admin—once, at `resolve_personal_workspace`
  creation and by the idempotent backfill
  (`workspaces/migrations/0005_backfill_organization_admins.py`). Authority is
  read from the row afterwards, never re-inferred from the workspace role.

### Profile API

`GET`/`PATCH /api/v1/workspaces/organizations/<uuid>/`
(`workspaces/api/views.py:OrganizationProfileView`) read and partially update
the profile (`name`, `description`, `support_email`, `support_url`).

- **Identifiers.** The organization is addressed by its immutable public `uuid`;
  the integer primary key never appears on the wire.
- **Discovery.** `GET /api/v1/workspaces/organizations/`
  (`OrganizationListView`) is the authority-owned list of organizations the
  caller may administer—a superuser sees all, everyone else sees only their
  `admin`-membership organizations. Discovery is never derived from workspace
  reachability (`list_administrable_organizations`).
- **Authorization.** Enforced in `workspaces.services.get_organization_profile` /
  `update_organization_profile`. A missing organization, an organization outside
  the actor's authority, and insufficient authority return one opaque `403`, so
  the endpoint is not a tenant-enumeration oracle.
- **Domain validation.** `update_organization_profile` validates unknown fields,
  lengths, a non-blank name, and email/URL formats in the service
  (`_validate_changes`), so the invariants hold for every facade caller, not only
  the HTTP serializer path (ADR-046-R12).
- **Session-only.** The bearer-first chain refuses an invalid token fail-closed;
  `IsAuthenticatedSession` rejects any valid platform token. Token access would
  require new exact scopes and is out of scope.
- **Serializers.** Explicit read and partial-update serializers (no writable
  `ModelSerializer`); unknown fields are rejected, and `EmailField`/`URLField`
  bound and format-check the input at the HTTP boundary.
- **Update semantics.** `update_organization_profile` is atomic: it
  `select_for_update`s the organization, re-checks authority under the lock,
  writes only fields whose value actually changed (absent is unchanged, empty
  string clears), and emits one strict `shared.audit` event
  (`AuditEntityType.ORGANIZATION`) carrying the changed field *names*, the
  internal organization id, and the `superuser_override` flag—never the field
  values—in the same transaction. A no-op change writes nothing and records no
  audit event.
- **Contract.** Regenerated into `openapi/v1.json` and
  `frontend/src/api/schema.d.ts` via `npm run gen:api`.

### SPA settings surface

`features/administer/organization/OrganizationSettingsPage.tsx` replaces the
settings slot with a chooser (`/administer/organization/settings`) and an editor
(`/administer/organization/settings/:organizationUuid`). The chooser lists the
organizations the caller may administer from the authority-owned list endpoint
(`useAdministrableOrganizations`), links each to its editor by public UUID, and
opens the only one directly; selection is never inferred from workspace context.
The editor uses the shared `useOrganizationProfile`/`useUpdateOrganizationProfile`
hooks (`frontend/src/api/organization.ts`), submits only fields changed from the
loaded snapshot (the PATCH mask, so a stale form cannot revert a concurrent
edit), surfaces server field errors from the shared `ApiError` envelope, and
never compares roles client-side.

## Workspace lifecycle (issue #1940, PLAT-233)

The second console surface to replace a placeholder. It adds the workspace
create/list/rename/archive/restore/owner-transfer lifecycle behind the existing
`workspaces.services` facade. The binding boundaries are recorded in ADR-046,
ADR-048, and
[`workspace-lifecycle-preflight-1940.md`](../../architecture/workspace-lifecycle-preflight-1940.md).

### Two distinct authorities

Lifecycle deliberately keeps organization authority and workspace authority
separate (ADR-046-R8, ADR-048), never conflating them:

- **Create and list** are organization-authorized. They resolve the target
  organization by public UUID through `resolve_administrable_organization`
  (`workspaces/services/_organization.py`), which reuses the ADR-048 `admin`
  `OrganizationMembership` seam (or the recorded superuser override). Authority
  is never derived from a workspace role, Django staff/groups, model
  permissions, identity claims, or API-token scopes.
- **Read detail, rename, archive, restore, and transfer** are authorized by the
  workspace role seam for that exact public workspace UUID, via new
  `WorkspaceOperation` codes (`read_workspace`, `rename_workspace`,
  `archive_workspace`, `restore_workspace`, `transfer_ownership`). The
  operation-to-role mapping lives only in `workspaces.roles.ROLE_OPERATIONS`:
  owner and admin may read/rename/archive/restore; `transfer_ownership` is
  owner-only. `create_workspace` seeds the creator as `OWNER` in the same
  transaction, so a create-then-manage flow works without a separate grant.

### Service (`workspaces/services/_lifecycle.py`)

- **Transactional and locked.** Each mutation locks the workspace row and
  re-checks the live grant under the lock (reusing
  `_memberships._lock_workspace_and_actor`), performs the change, and writes one
  strict, request-attributed `shared.audit` event (`AuditEntityType.WORKSPACE`)
  in the same transaction, so an audit-write failure rolls the mutation back.
  Audit records internal integer IDs, the action, and bounded state/field
  *names* only—never the workspace or organization display name.
- **Archive is a reversible marker.** A nullable `Workspace.archived_at`
  timestamp; archive sets it, restore clears it. It never deletes, rehomes, or
  cascades to the scalar `workspace_id` range bindings in CMS/Engine (those are
  `IntegerField`s, not foreign keys). List defaults to active-only with an
  explicit `include_archived` filter.
- **Invariants.** Names stay unique within the organization (DB constraint;
  `IntegrityError` is classified as `name_taken`, not surfaced raw). Owner
  transfer promotes the target's existing active membership to `OWNER` and
  demotes the acting owner to `ADMIN` in one atomic command, preserving the
  last-owner invariant throughout. Personal compatibility workspaces are
  rejected from every lifecycle mutation (`personal_workspace_protected`).
- **Opaque denials.** A malformed UUID, an unknown workspace/organization, and
  an unauthorized one all raise the same opaque denial, so the surface is not a
  tenant-enumeration oracle.

### Lifecycle API

Mounted under `/api/v1/workspaces/` (`workspaces/api/views.py`,
`workspaces/api/urls.py`):

- `GET/POST /api/v1/workspaces/`: list (`?organization=<uuid>&include_archived=&search=`) or create.
- `GET/PATCH /api/v1/workspaces/<uuid>/`: detail or rename.
- `POST /api/v1/workspaces/<uuid>/archive/`, `.../restore/`, `.../transfer/`.

- **Session-only, service-seam authorized.** Like the organization profile
  endpoints (ADR-048, PLAT-232), the lifecycle views use
  `IsAuthenticatedSession` with a bearer-first chain that refuses a valid
  platform token; domain authority is enforced inside `workspaces.services`.
  The console `/administer` route stays staff-gated at the SPA level for
  defense-in-depth, but a non-staff organization admin can drive the API for
  their own organization—`IsStaffSession` is deliberately *not* used here, so
  workspace authority is not collapsed into Django staff.
- **Serializers.** Explicit read (`WorkspaceSerializer`) and command
  (`CreateWorkspaceSerializer`, `RenameWorkspaceSerializer`,
  `TransferWorkspaceOwnershipSerializer`) serializers; the public workspace and
  organization UUIDs only on the wire. Bounded service outcomes map through the
  shared error envelope (`name_taken`→409, invalid name→400,
  `personal_workspace_protected`→409, `membership_not_found`→404, authorization
  →opaque 403).
- **Contract.** Regenerated into `openapi/v1.json` and
  `frontend/src/api/schema.d.ts` via `npm run gen:api`.

### SPA lifecycle surface

`features/administer/organization/WorkspaceListPage.tsx` replaces the workspaces
slot (organization-scoped list, search, include-archived toggle, and create),
and `WorkspaceDetailPage.tsx` renders the workspace-scope overview (rename,
archive/restore with a confirm dialog, and owner transfer). Both use the shared
`frontend/src/api/workspaces.ts` TanStack Query hooks (one typed client and
query-key family; mutations never auto-retry and invalidate the affected
caches), address workspaces by public UUID only, and never compare roles
client-side.

## Workspace membership & roles (issue #1941, PLAT-234)

The third console surface to replace a placeholder, and the first that is
**SPA-only**: it adds no endpoint, serializer, role, migration, or provider
change. The membership API, the closed role vocabulary, the fail-closed
role-to-operation policy, and the last-owner/personal-workspace/self-removal
invariants all already exist server-side from the ADR-046 tenancy layer. The
binding boundary is recorded in
[`workspace-membership-spa-preflight-1941.md`](../../architecture/workspace-membership-spa-preflight-1941.md);
PLAT-241 (cloud-agnostic, proven components) is satisfied without a new note
because the surface is same-origin session traffic through the existing SPA data
layer with no provider branch.

### Consumed contract (unchanged)

The surface consumes the existing membership endpoints under
`/api/v1/workspaces/` (`workspaces/api/views.py`, `workspaces/api/urls.py`):

- `GET/POST /api/v1/workspaces/<uuid>/memberships/`: roster or add-existing-account.
- `POST /api/v1/workspaces/<uuid>/memberships/<user_id>/role/`: change role.
- `POST /api/v1/workspaces/<uuid>/memberships/<user_id>/remove/`: remove another member.
- `POST /api/v1/workspaces/<uuid>/memberships/leave/`: leave.
- `GET /api/v1/workspaces/<uuid>/membership/`: the caller's own membership.

Members are addressed by the server-provided `user_id` the roster projection
exposes; the closed `WorkspaceRoleEnum` (`owner`, `admin`, `member`) is rendered
as membership data and as the generated request enum only. The caller's advisory
`capabilities` come from the console's already-loaded `PrincipalWorkspaceContext`
(`workspaces.roles`), so the client never re-derives authority from a role code.

### SPA membership surface

`features/administer/organization/WorkspaceMembershipPage.tsx` replaces the
membership slot and consumes the shared `frontend/src/api/memberships.ts`
TanStack Query hooks (one typed client and a `membershipKeys` family keyed by
public workspace UUID; mutations never auto-retry). It renders in two
capability-driven modes:

- **Roster mode** (`read_members`, owner/admin): a table of members with add,
  change-role, remove, and leave actions, each gated on the matching advertised
  capability (`add_member`, `change_member_role`, `remove_member`,
  `leave_workspace`). The caller's own row offers **Leave** rather than
  **Remove**, so self-removal always uses the dedicated leave endpoint.
- **Self-service mode** (`leave_workspace` without `read_members`, member): an
  honest card showing the caller's own role and a leave action, with no roster.

The navigation gate (`surfaces.ts`) admits the surface for either capability, so
a member reaches self-service leave; it is an any-of capability predicate, never
a role-string shortcut.

The **last-owner invariant** is shown from roster state (when exactly one owner
remains, that owner's remove and demote are disabled and the caller's leave is
disabled, with a plain explanation), but the server stays authoritative: the
surface handles `409 last_owner_required` (and `owner_authority_required`,
`use_leave_operation`, `personal_workspace_protected`, `membership_exists`,
`member_add_failed`, `invalid_role`) as typed `ApiError` outcomes through the
shared envelope, because a concurrent change can move the roster between render
and submit. A visible action is never treated as a grant.

Cache invalidation follows the API contract: roster mutations invalidate the
roster, and a self role change or a leave additionally invalidate the self
membership and the principal context (`principalContextKeys`), because the
caller's capabilities and the console's selected-workspace validity can change.

## Workspace network egress policy (issue #1945, PLAT-238)

The zero-egress (no-NAT) range posture (#1171, ADR-026) is delivered as a
workspace-level policy. It reuses the one canonical vocabulary,
`installation.range_egress.RangeEgressMode`; a workspace stores only the
contextual subset `status-quo` (inherit the deployment baseline) or `none`
(zero egress), never CIDRs or provider configuration (ADR-017-R5).

### Backend spine

- **Persistence.** `Workspace.egress_policy` is a closed scalar with a database
  `CheckConstraint` and a compatibility default of `status-quo`. A central
  `WorkspaceOperation.SET_EGRESS_POLICY` (owner or admin) drives the locked,
  audited `workspaces.services.set_workspace_egress_policy`, which records the
  old and new mode and is a no-op when unchanged.
- **Launch resolution.** The effective mode is resolved under the workspace
  reservation mutex in `cms.services._range_workspace` (ADR-046-R10), so the
  pinned decision reflects the policy as of the reservation, not a racy
  pre-reservation read. Both launch families (cyberscript and RAES) consume the
  one verdict.
- **Range ownership and replay.** The effective mode is pinned on
  `engine.Range.egress_mode` in the create transaction before dispatch, and an
  idempotent replay that names a different mode is rejected (ADR-017-R5).
- **Transport.** The pinned mode travels in both operation-input families,
  validated against the closed vocabulary. A newer producer always emits it; an
  older queued input without it resolves to `status-quo` (never a silent
  weakening, because `none` is always explicit), and an unknown value fails
  closed at the wire.

### Provider realization

Enforcement uses each cloud's native primitives behind the existing provider
seams; the provisioner never reads workspace state.

- **AWS.** `terraform_vars` maps the pinned mode to the runtime route-table
  bridge: `none` yields no participant default route, NAT, or internet-gateway
  path and no S3 endpoint association; `status-quo` inherits the deployment
  baseline. The deployment-owned `RANGE_EGRESS_MODE` never overrides a pinned
  decision.
- **GCP.** A `none` range-cell forces the firewall egress-deny (no public-web or
  allow-CIDR lane) and, decisively, omits the Cloud NAT entirely: egress is
  range-owned. The provisioner creates a range-scoped Cloud Router and Cloud NAT
  (`LIST_OF_SUBNETWORKS`) for a non-`none` range and creates none for a `none`
  range, so a zero-egress subnet carries no NAT path at all. A firewall deny
  alone is not that guarantee (ADR-026-R6).
- **Backend capability gate.** A `none` launch fails closed on a backend that
  cannot prove native no-NAT support. GDC stays excluded under ADR-030.

### Configuration baseline

A `status-quo` workspace inherits the deployment baseline. That inheritance is
realized at the provider today: the AWS runtime reads the deployment-declared
`RANGE_EGRESS_MODE`, so a deployment-wide `none` posture still reaches a
`status-quo` workspace's ranges. GCP has no deployment-wide `none` baseline (its
operator posture is the allow-CIDR and profile lanes), so a `status-quo` GCP
range keeps the existing routed posture. Binding the normalized baseline into
CMS so `status-quo` pins the concrete mode at reservation time is a bounded
follow-up with no behavioral difference today; the workspace `none` selection is
the per-workspace zero-egress mechanism and is fully resolved and pinned.

### GCP Cloud NAT migration

The shared range VPC previously enrolled every subnet in one Cloud NAT
(`ALL_SUBNETWORKS_ALL_IP_RANGES`), which is incompatible with a per-range `none`
subnet. It now uses `LIST_OF_SUBNETWORKS` driven by the
`shared_range_nat_subnetwork_self_links` variable (default empty), so in steady
state it enrolls no range subnets and egress is range-owned. The variable is a
controlled cutover bridge: during a migration an operator may temporarily list
existing pre-migration range subnets to preserve their egress until they are
drained onto per-range NAT. Range jobs never patch this shared object
concurrently. The regional router, NAT, and address quota supporting per-range
NAT is a deployment capacity concern to validate for the declared range count.

## Workspace resource quotas (issue #1946, PLAT-239)

Per-workspace resource quotas are tenant-entitlement policy owned by the
`workspaces` domain, distinct from Engine provider-capacity accounting, API
throttling, billing, and the per-`(user, range_source)` active-range constraint
(ADR-046-R10, `docs/architecture/workspace-resource-quotas-preflight-1946.md`).
The initial closed resources are `concurrent_ranges` and `member_seats`. A
missing policy means unlimited, which preserves prior behavior. Enforcement mode
reuses the `shared.capacity.EnforcementMode` terms only: `advisory` is a soft cap
(warn, record, admit) and `enforcing` is a hard cap (record, block).

### Data model

Three `workspaces` models (migration `0009`):

- `WorkspaceQuotaPolicy` is the configured limit and mode for a
  `(workspace, resource)`, with a `revision` bumped on each change and closed
  vocabulary check constraints.
- `WorkspaceQuotaDecision` is append-only evidence of every configured-policy
  evaluation, pinning the policy limit, mode, revision, usage before the delta,
  outcome, reason code, actor, and correlation key.
- `WorkspaceQuotaReservation` is a durable, idempotent open reservation for
  count-based resources. An open reservation (`released_at` is null) is the
  authoritative concurrent-range usage; the unique
  `(workspace, resource, correlation_key)` constraint makes reserve and release
  idempotent under event redelivery.

### Authoring and read authority

Policy authoring is a superuser-only composition-root authority through
`workspaces.services.set_workspace_quota_policy` (never inferred from a workspace
or organization role, `is_staff`, a model permission, or a token scope), exposed
only through the superuser-only Django administration escape hatch (PLAT-241).
The read surface `workspace_quota_usage` is authorized by the existing
`WorkspaceOperation.READ_WORKSPACE` (owner or admin) and is served read-only at
`GET /api/v1/workspaces/{uuid}/quota/`.

### Enforcement

- **Member seats.** `WorkspaceMembership` rows are the canonical usage. The seat
  delta is evaluated once in the locked `_insert_workspace_membership`, the single
  insert path shared by direct add and invitation acceptance. Pending invitations
  do not consume a seat; role changes and idempotent re-adds do not re-decide.
- **Concurrent ranges.** The evaluation and open reservation are committed under
  the workspace reservation mutex in `cms.services._range_launch_common`
  (`_reserve_active_range_slot`), keyed on the pre-minted request UUID, so an
  active-range collision or any persistence failure rolls the reservation back
  with the range. The reservation is released only on terminal `FAILED`/`DESTROYED`
  convergence in `cms.handlers.range_events.apply_range_status` (and on immediate
  dispatch failure), never at `DESTROYING` or CMS soft delete. The
  `reconcile_range_events` backstop reuses the same convergent release.

Every enforcement primitive re-acquires the workspace row mutex so its usage count
is race-safe regardless of caller, proven under real PostgreSQL contention in
`tests/workspaces/test_quota_concurrency_postgres.py`. A hard rejection commits its
decision evidence without committing the denied action: the primitive raises a
bounded control-flow signal without writing, and the caller records the rejection
after its transaction unwinds, then maps it to a stable error. A hard
concurrent-range exhaustion is a `409 Conflict` (`WorkspaceLaunchQuotaExceeded`),
distinct from an authorization `403` and a request-rate `429`; a hard seat exhaustion is a
`409` (`workspace_member_seats_exhausted`). A soft-cap overage and every hard-cap
block also emit a strict `shared.audit` `quota_applied` event so the deployment
audit history shows when a cap applied.

### Upgrade backfill

A CMS data migration (`cms/0043`, dependent on `workspaces/0009` to keep the
migration graph acyclic) backfills one open reservation per pre-existing
non-terminal range projection, including hidden `DESTROYING` rows, so enabling a
hard cap immediately after upgrade cannot undercount live infrastructure. It fails
loudly on inconsistent workspace/request evidence and is idempotent on re-run.

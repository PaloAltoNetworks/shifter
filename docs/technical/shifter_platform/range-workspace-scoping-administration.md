# Range-to-workspace scoping administration (technical)

This note describes the implementation of range-to-workspace scoping
administration (PLAT-237, issue #1944): an administrative query that lists the
ranges scoped to a workspace, and a command that reassigns a range's workspace
scope. It is constrained by PLAT-241 (cloud-agnostic, proven components) and the
architecture preflight at
`docs/architecture/range-workspace-scoping-administration-preflight-1944.md`.

## What is administered

A range's workspace binding is the scalar `workspace_id` copied from CMS request
intent to the CMS range projection and the Engine range. It is a soft reference,
not a cross-layer ForeignKey (ADR-001-R2, ADR-046). This feature administers that
one fact. It never changes the range owner, source, lifecycle, lease, or access.

## Authority

Two new closed `WorkspaceOperation` values in `workspaces/roles.py`,
`LIST_RANGE_SCOPE_BINDINGS` and `REBIND_RANGE_WORKSPACE`, are granted to the
owner and admin roles only, in a dedicated `_RANGE_SCOPE_ADMIN_OPERATIONS` set.
They are deliberately distinct from `READ_RANGE` (own-range access) and
`REASSIGN_RANGE` (ownership handover): scope administration is cross-owner
administrative authority, not additive per-range access, so a plain member never
receives it (ADR-046-R14).

The HTTP surface is staff-session-only through `IsStaffSession`, and the workspace
operation is checked in addition. The two are conjunctive: a staff session alone
grants no scope authority, and a non-staff workspace owner cannot call the API.
The bearer-first authentication chain rejects platform API tokens.

`workspaces.services.authorize_range_rebind` is the tenancy-domain authority seam.
It resolves the target public UUID, locks the source and target workspace rows in
deterministic id order under the same mutex the membership and lifecycle services
use, rechecks the actor's rebind authority in both scopes, rejects an archived
target, and requires the unchanged range owner's membership in the target. Every
failure raises one opaque `WorkspaceAuthorizationError` so the surface is not a
tenant-enumeration oracle.

## Service and persistence boundary

CMS owns the query and the command because it owns request intent and the range
projection and is the only layer permitted to import both `engine.services` and
`workspaces.services` (ADR-001). The seam lives in
`cms/services/_range_workspace_admin.py`.

`list_range_scope_bindings(actor, *, workspace_uuid)` authorizes the actor for
`LIST_RANGE_SCOPE_BINDINGS` on the workspace and returns an ordered queryset of
its range projections for the API to paginate. An explicit DRF serializer exposes
a bounded projection (request correlation UUID, owner id, source, status,
scenario, timestamps, and a derived `is_reassignable`); it is never a
`ModelSerializer`, and it exposes no internal id, range specification, address,
credential, or ORM object.

`rebind_range_workspace(actor, *, request_id, target_workspace_uuid, audit)` runs
one `transaction.atomic` block that:

1. locks and uniquely resolves the CMS Request and its one RangeInstance and
   confirms they carry the same expected source scope;
2. fails closed for a range that is not Mission Control sourced (see below);
3. pre-checks the actor's authority on the source scope, then calls
   `authorize_range_rebind` for the authoritative pair authorization under both
   workspace mutexes;
4. calls `engine.services.rebind_range_workspace_by_request` with expected-source
   compare-and-set semantics; and
5. moves the two CMS projections to the target and writes one strict,
   request-attributed `shared.audit` event with the internal ids and the old and
   new scope, or rolls everything back.

Moving to the current consistent binding is an authorized idempotent no-op that
writes no mutation audit. A missing, duplicate, or disagreeing projection, a
concurrent move, or an Engine binding that is neither the expected source nor the
target is a bounded conflict, never a silent repair or a last-writer-wins
overwrite.

## Engine compare-and-set

`engine.services.rebind_range_workspace_by_request` was changed from an
unconditional bulk update to an expected-source compare-and-set. It takes a row
lock, resolves exactly one Engine range for the request, and returns a
`RangeWorkspaceRebindOutcome` (`UPDATED`, `UNCHANGED`, `NOT_FOUND`, or
`SOURCE_MISMATCH`); a duplicate projection raises `RangeProjectionIntegrityError`.
The Engine still never resolves or authorizes a workspace (ADR-046-R1). The one
existing caller, the owner-rehome path in `cms/services/_range_reassign.py`, now
passes the expected current binding and treats a non-success outcome as a
rollback, so that path becomes compare-and-set safe without changing its
behavior.

## Domain-owned aggregates fail closed

A range that belongs to an immutable domain-owned workspace aggregate, such as an
ADR-051 capture-the-flag event, cannot be moved independently. There is no
layering-legal way for CMS to validate such a move: CMS may not import `ctf`, the
provenance label `range_source` is not aggregate membership, and no
capture-the-flag validation seam exists yet. Following ADR-046-R14, the command
administers Mission Control ranges only and refuses any other range with a bounded
outcome. When a capture-the-flag owned validation seam exists, the command can be
extended to defer to it rather than refuse.

## API surface

Both routes live under the CMS API at `/api/v1/cms/`:

- `GET workspaces/<uuid:workspace_uuid>/range-scoping/` lists the ranges scoped to
  a workspace, paginated. An unknown or unauthorized workspace returns one opaque
  404.
- `POST ranges/<uuid:request_id>/workspace/` reassigns a range's scope. The body
  is a closed `{ "target_workspace_uuid": "<uuid>" }`. The classified
  `RangeScopeAdminError` maps to a bounded status: 404 for a range that is absent
  or whose source the actor may not administer, and an opaque 409 for a
  target-ineligible, conflict, or not-reassignable outcome. A malformed target
  UUID is a 400 at the serializer.

The committed OpenAPI contract (`openapi/v1.json`) and the generated frontend
types (`frontend/src/api/schema.d.ts`) are regenerated with `npm run gen:api`.

## SPA surface

The `range-scoping` console slot renders
`frontend/src/features/administer/organization/WorkspaceRangeScopingPage.tsx`. It
lists the ranges through the `frontend/src/api/rangeScoping.ts` TanStack Query
hooks and offers a reassignment dialog whose target options are the workspaces the
caller administers. The nav slot is gated on the advisory
`list_range_scope_bindings` capability; the SPA never reconstructs role policy,
addresses workspaces and ranges by public UUID, and relies on the server to
reauthorize and to enforce the target's state and the owner's membership.

## Cloud neutrality

Reassignment is a database control-plane action. It reads and writes no secret,
dispatches no provider work, and does not re-evaluate egress, capacity, or
placement, so AWS and GCP deployments receive identical behavior.

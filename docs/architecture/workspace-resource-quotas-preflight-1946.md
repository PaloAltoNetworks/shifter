# Workspace resource quotas and usage preflight

Issue: #1946, "Org/workspace admin: workspace quotas & usage"

Status: pre-implementation guidance

Date: 2026-09-03

Requirements: PLAT-239 (implements), PLAT-241 (constrains)

This note fixes the repository-wide boundaries for workspace quota policy,
enforcement, decision evidence, and the read-only SPA surface. It does not
implement quotas and is not an implementation plan.

## Decision

Workspace quota is tenant entitlement policy owned by the existing
`workspaces` domain. It is not provider headroom, billing, request throttling,
the per-user active-range rule, or a cloud quota. The initial closed resource
codes are `concurrent_ranges` and `member_seats`; policy is explicit typed
persistence keyed by `(workspace, resource)`, not fields in a generic settings
JSON document.

Each policy carries a non-negative integer limit and the existing
`shared.capacity.EnforcementMode` vocabulary: `advisory` is the soft cap and
`enforcing` is the hard cap. Reusing that two-value vocabulary does not reuse
Engine capacity policy, reason codes, models, partitions, or provider readers.
A missing policy means unlimited compatibility behavior and must be projected
explicitly as such; upgrades do not invent a deployment-wide default limit.

Policy changes apply to subsequent decisions. Lowering a limit below current
usage does not evict members, destroy ranges, or rewrite history. Every quota
decision pins the resource, policy limit/mode/revision, usage before the
requested delta, outcome, bounded reason code, trusted action/source, stable
domain correlation key, and time. Decision rows are append-only domain evidence. The
shared audit row for a warning or rejection is a cross-cutting projection of
that evidence, not a second quota ledger.

Quota policy is a platform guardrail, so workspace membership authority must
not be able to raise or remove it. The PLAT-239 SPA/API surface is read-only for
usage and decision history. Policy authoring belongs in the existing Django
admin escape hatch and must call a separate superuser-only
`workspaces.services` command with strict audit; a writable stock `ModelAdmin`
that saves policy rows directly is not an authority boundary. Policy-write
authority must not be inferred from `is_staff`, a workspace role, organization
role, Django model permission, API-token scope, provider claim, or cloud IAM. A
broader delegated quota-admin policy is a separate authority decision.

## Enforcement and consistency boundaries

The two initial resources share policy/result vocabulary but not accounting
mechanics.

### Member seats

`WorkspaceMembership` rows are the canonical usage. Both add-existing-member
and invitation acceptance already converge on
`workspaces.services._memberships._insert_workspace_membership` while holding
the workspace row mutex. Evaluate the seat delta there, after detecting an
idempotent existing membership and before inserting a new one. Invitation
issuance does not consume a seat; acceptance does. Role changes, resends, and
removals must not create a second counter.

The workspace lock serializes membership creation, invitation acceptance,
policy changes, and the count, so a database count is race-safe in this path.
The membership uniqueness and closed-role constraints remain independent
backstops. Personal-workspace bootstrap and workspace-owner creation remain
compatibility invariants; quota policy must never create an ownerless
workspace.

### Concurrent ranges

`cms.services._range_workspace.admit_workspace_launch` and
`_range_launch_common._reserve_active_range_slot` are the only attachment
point. The pre-minted request UUID is the idempotency/correlation key. The
authoritative quota decision and an admitted range's open quota reservation
must be written while holding the same workspace mutex as locked launch
reauthorization, before the CMS request/range reservation commits. Every
product source and trusted instantiation purpose passes this seam; callers do
not count ranges in views, CTF, Engine, or the provisioner.

An unlocked `RangeInstance` count is only a friendly observation and is not
enforcement. `RangeInstance`'s partial unique constraint remains the separate
per-`(user_id, range_source)` rule. Engine `CapacityAssessment`,
`CapacityReservation`, and `CapacityDraw` remain physical event/provider
capacity under ADR-047 and must not be populated with workspace IDs or quota
policy.

An open workspace reservation, not `RangeInstance.deleted_at`, is the
concurrent-range usage source. The current destroy path soft-deletes its CMS
projection at `DESTROYING`, before provider resources are gone; releasing at
that point would undercount real concurrency. Release is idempotent and occurs
only on terminal `FAILED`/`DESTROYED` convergence, or immediately when dispatch
fails before an Engine lifecycle can finish. The existing range-event handler
and `reconcile_range_events` share `apply_range_status`; quota release belongs
on that convergent path so redelivery and lost-event recovery close the same
reservation. Pause does not release it.

The migration must backfill one open reservation for every pre-existing
non-terminal CMS range projection, including `DESTROYING` rows already hidden
by the default soft-delete manager. Use historical models and a stable,
namespaced correlation derived from request UUID or legacy range-instance ID,
and fail loudly on conflicting workspace/request evidence. Otherwise enabling
a hard cap immediately after upgrade undercounts live infrastructure.

Keep the migration graph and runtime boundary one-way: create quota tables in a
`workspaces` schema migration, then perform any CMS-derived backfill in a CMS
data migration that depends on that schema migration, following the existing
historical `apps.get_model` workspace-binding migrations. Store only scalar CMS
correlation, never a cross-layer foreign key or runtime model import. Do not
make a `workspaces` migration depend on the current CMS leaf and then require a
CMS migration to depend back on it.

### Durable rejection and warning semantics

All configured-policy evaluations are recorded, including hard rejections.
Do not raise from inside a transaction that would roll back the rejection row.
The quota service returns a bounded verdict; the caller commits a rejected
decision with no membership/range/reservation mutation, then maps the verdict
to the typed domain/API error. An advisory overage commits the decision and the
requested mutation/reservation together and returns a typed warning. A normal
admission commits its decision with the action.

The client-visible `X-Request-ID` remains trace/audit attribution only:
`RequestIDMiddleware` deliberately preserves a caller-supplied value, so it is
not reservation or replay authority. Concurrent-range idempotency uses the
server-minted request UUID and a database identity that includes workspace and
resource. Membership idempotency remains the existing membership uniqueness
and invitation-generation state; do not reinterpret an HTTP request ID as a
membership command key.

For range launch, an unrelated active-range constraint or other persistence
failure rolls back the tentative quota decision/reservation with the CMS
reservation: quota was not the final admitting policy in that failed action.
After a successful reservation, dispatch failure retains the original decision
but releases its open quota reservation idempotently.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Domain ownership | ADR-001; ADR-046; `.importlinter`; `scripts/check_layer_imports/layer_imports.yaml`; `check_model_fks` | Quota policy, decisions, and reservations live in `workspaces`; other layers use `workspaces.services` and scalar IDs only. |
| Workspace authority | `WorkspaceOperation.READ_WORKSPACE`, `ROLE_OPERATIONS`, `authorize_workspace`, workspace row mutex | Reuse the existing owner/admin administrative-detail read; do not add an equivalent `READ_QUOTA` operation or compare roles in views/TypeScript. Policy write is a distinct superuser-only service authority. |
| Membership mutations | `_memberships._insert_workspace_membership`; invitation acceptance; membership DB constraints | Enforce the seat delta once in the common locked insert. Pending invitations and role changes are not seats. |
| Range admission | `_range_workspace.WorkspaceLaunchAdmission`, `admit_workspace_launch`, `_reserve_active_range_slot`, RAES create/dispatch | Move authoritative evaluation into the locked reservation transaction and use the pre-minted request UUID. Do not add a second launch path. |
| Range lifecycle | `RangeInstance`, `apply_range_status`, `reconcile_range_events`, terminal soft-delete vocabulary | Release reservations on converged terminal state, not destroy request or `deleted_at`; reuse reconciliation as the lost-event backstop. |
| Capacity conventions | `shared.capacity` immutable verdict/enforcement shapes; Engine hold/draw/release concurrency tests | Reuse bounded-verdict and idempotent-ledger lessons only. Tenant entitlement remains outside Engine capacity tables and provider inventories. |
| Validation | explicit DRF serializers; service validators; model choices/check/unique constraints | HTTP owns primitive shape, service owns business rules for every caller, database owns race-proof invariants. Reject booleans, negatives, unknown resource/mode codes, and unknown fields. |
| Errors | typed workspace errors; `WorkspaceLaunchDenied`/`CMSError`; `_WorkspaceAPIError`; `shared.api.errors`; `ApiErrorSerializer` | Add bounded quota codes to the existing mapping. Hard exhaustion is a 409 conflict, not 403 authorization or 429 request-rate throttling. Never string-match it. |
| Audit and logging | `shared.audit`; `RequestIDMiddleware`; request attribution helpers; `shared.log_sanitize` | Extend the canonical audit vocabulary if quota needs a distinct action; strict-audit policy changes and applied limits with bounded codes/internal IDs. Keep tenant names, emails, UUID probes, raw SQL, and exception/provider payloads out. |
| Deep administration | `/admin/`; `workspaces.admin`; service-backed admin precedents | Keep policy authoring out of the SPA/public API and route superuser admin changes through the audited service command; never grant raw model saves. |
| API contract | `/api/v1/workspaces/{uuid}/`; drf-spectacular; `openapi/v1.json`; generated `schema.d.ts` and `types.ts` aliases | Public UUID only, read-only scalar projections, canonical pagination, and regenerated types. No hand-written DTO or enum. |
| SPA | quota route placeholder; `surfaces.ts`; `api/client.ts`; `queryClient.ts`; existing cards, progress, alert, skeleton, table | Replace the placeholder, gate presentation on server-derived capability, use TanStack Query, and preserve same-origin CSRF/request IDs and mutation no-retry behavior. |
| Upgrade/concurrency proof | workspace historical-migration tests; `test_range_create_concurrency.py`; invitation PostgreSQL concurrency test; Engine capacity draw tests | Prove real PostgreSQL overlap, hard/soft boundaries, idempotent retry/release, and live-range backfill. SQLite-only tests cannot prove row-lock behavior. |

## Cross-cutting security and runtime layers

1. **Identity and account binding.** Existing OIDC/Identity Platform issuer,
   audience, authorized-party, subject, and verified-email checks establish the
   Django user. `CTFAccountBoundaryMiddleware` continues to deny temporary
   accounts outside their exact participant surfaces. Invitation acceptance
   keeps its signed-fragment staging, fresh `VerifiedIdentity`, email match,
   one-time generation, and active-account gates before the common seat check.
2. **HTTP authentication and authorization.** The quota admin read uses the
   bearer-first `ApiTokenAuthentication`, `SessionAuthentication` chain and
   `IsStaffSession`, then `workspaces.services` reauthorizes the exact public
   UUID for the existing `READ_WORKSPACE` operation. A valid platform token is
   still refused; adding a token scope is not implicit. Launch and membership
   APIs retain their current session/token scopes and actor gates, with quota
   enforced again in services.
3. **Browser protections.** The existing SPA host, secure session cookie,
   `CsrfViewMiddleware`, same-origin fetch, CSP, referrer/permissions policy,
   and request-ID propagation remain in force. Limits, decisions, and
   capabilities are server data, never local/session-storage authority.
4. **Input and domain validation.** DRF validates UUIDs, bounded pagination,
   and primitive command shapes. The workspaces service independently validates
   resource, non-negative integer limit/delta, enforcement mode, correlation
   grammar, and authority. Database unique/check constraints are the final
   backstop. Client-side checks are presentation only.
5. **Persistence and races.** `transaction.atomic`, the workspace
   `select_for_update` mutex, membership uniqueness, quota policy uniqueness,
   idempotent `(workspace, resource, correlation)` reservation identity,
   non-negative amounts, and named constraints carry enforcement. Hard denial
   must commit evidence without committing the denied action. Cross-layer FKs
   and runtime ORM imports remain forbidden.
6. **Error envelopes and leakage.** Authorization denials stay opaque and
   non-enumerating. Quota conflicts expose only stable resource/outcome/reason
   codes and the caller-authorized workspace's safe usage/limit facts through
   `{"error": ...}`; never database errors, policy blobs, membership lists,
   provider figures, stack traces, or internal IDs.
7. **Audit and observability.** The append-only quota decision is the detailed
   source of truth; warnings/rejections also emit a canonical strict shared
   audit event in the same transaction so the deployment-wide Administer audit
   view sees when a cap applied. Audit failure must roll back the applied-limit
   decision/action rather than silently lose required evidence. Logs carry
   internal workspace/request correlation plus closed resource/outcome codes.
   Do not label metrics with workspace UUID/name or add a provider metrics
   pipeline for this slice.
8. **Configuration and secrets.** Per-workspace state belongs in the database,
   not `.shifter.yaml`, `config/_runtime_env.py`, `config/_env_manifest.py`,
   `config/env-manifest.json`, Django settings, environment, feature flags,
   Terraform, Helm, Kubernetes ConfigMaps/Secrets, or cloud secret stores. This
   feature handles no credential and therefore adds no env-binding shape for
   those validators to accept. Existing API/session/database secrets stay on
   their current binding paths and never enter quota state.
9. **OS/process/provider exposure.** No quota policy, usage, workspace identity,
   or decision enters process argv, task environment, RAES/scenario payloads,
   launch events, provisioner Jobs, provider labels, Terraform variables, guest
   metadata, or files. Enforcement completes in the portal database before
   dispatch, so AWS and GCP use the identical path and need no adapter branch.
10. **Repository gates.** Changes must pass Django/Ruff/mypy tests, layer/FK
    checks, OpenAPI compatibility and generated-type drift, frontend
    ESLint/TypeScript/Vitest/axe/build tests, historical migration and PostgreSQL
    concurrency evidence, and `adr_guard`. No workflow or guardrail weakening
    is part of PLAT-239.

## Extensibility seam

The extension parameter is a closed quota resource code plus an integer delta
and stable, domain-minted correlation key. Durable reservation identity is
`(workspace, resource, correlation)`, not the browser request ID. Each resource
maps once, inside `workspaces.services`, to its canonical usage owner and
reservation behavior:
membership rows for `member_seats`, open quota reservations for
`concurrent_ranges`. `WorkspaceLaunchAdmission` continues to carry authorized
workspace, individual owner, server-derived source, trusted purpose, and the
request UUID, so a future source/purpose-specific policy does not edit every
caller or leak tenant policy to Engine/provider code.

A later count-based resource can extend the closed resource registry and supply
one authoritative usage/reservation strategy. A weighted, time-windowed,
inherited, or money-denominated limit is not safely represented by pretending
it is another integer count; it needs an explicit contract. Do not add a
free-form expression evaluator, generic policy JSON, or provider callback now.

## Gotchas and anti-patterns

- Do not count CMS rows without a lock, cache usage as authority, or release a
  range slot at `DESTROYING`/soft delete.
- Do not put workspace quota in Engine capacity declarations/reservations,
  cloud service quotas, portal saturation metrics, API throttles, billing, or
  the `(user_id, range_source)` active-range constraint.
- Do not enforce seats only in the membership API and miss invitation
  acceptance, token callers, bootstrap paths, or concurrent inserts.
- Do not reserve pending invitations as seats or derive seats from roles.
- Do not raise a hard denial inside an atomic block that rolls back its decision
  evidence, and do not persist a reservation for a rejected action.
- Do not let a soft cap silently admit: return a typed warning and record the
  applied decision. Do not turn a hard cap into a warning when persistence,
  policy, or usage resolution fails.
- Do not let workspace owners/admins edit away a platform guardrail, reuse the
  egress-policy operation, or treat staff visibility as quota-write authority.
- Do not expose internal IDs, hand-copy resource/mode/outcome enums into the
  SPA, or reconstruct quota state from audit prose.
- Do not add `READ_QUOTA` when `READ_WORKSPACE` already expresses the same
  owner/admin read authority, and do not use caller-supplied `X-Request-ID` as
  an idempotency or reservation key.
- Do not create a second workspace schema, role matrix, exception hierarchy,
  audit store, API client, cache/store, launch workflow, status vocabulary,
  reconciliation job, provider adapter, or cloud-specific policy.
- Do not N+1 count usage/authorize history rows, return unbounded decision
  history, poll aggressively, or imply the browser snapshot is real-time.

## Non-goals and implementation boundaries

- Billing, price/cost allocation, provider placement, autoscaling, or cloud
  account/project/service-quota management.
- Organization-level inherited/default quotas, pooled quotas across workspaces,
  role-specific seats, pending-invitation reservations, or per-scenario limits.
- Automatic eviction, range teardown, membership removal, or retroactive
  mutation when a policy is lowered.
- Changing individual range ownership/access, CTF event/team/participant
  authority, workspace range sharing, active-range uniqueness, leases, or
  egress policy.
- A public quota-policy CRUD surface, API-token quota-admin scope, new feature
  flag, deployment setting, provider SDK, worker queue, or OS/provisioner
  contract.
- Real-time push usage, alerting, exports, forecasting, historical billing, or
  replacing the deployment-global audit page.

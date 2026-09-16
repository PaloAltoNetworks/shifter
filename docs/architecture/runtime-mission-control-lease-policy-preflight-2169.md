# Runtime Mission Control lease policy preflight (#2169)

Status: pre-implementation guidance. Date: 2026-09-14.

Contract: GitHub issue #2169 is authoritative; no Ground Control requirement is
attached. This note resolves the issue's open architecture decisions. It is not
an implementation plan and does not claim the runtime settings surface ships.
Issue #27 remains the baseline lease design; this note supersedes only its
tenant-hierarchy non-goal and its assumption that every policy value is fixed by
a process rollout.

## Decisions

### One policy contract, one runtime overlay

`settings.mission_control_leases` remains the validated, provider-neutral
deployment baseline and the fallback when no runtime tenant row exists. The
standalone Shifter deployment is the tenant (ADR-011-R6); do not add a generic
`Tenant`, settings registry, key/value table, or JSON settings bag for four
fields.

A CMS-owned singleton runtime tenant policy is a complete replacement of the
four baseline fields: `initial_days`, `extension_days`, `maximum_days`, and
`extensions_enabled`. It is not a floor. An authenticated platform superuser can
raise or lower it, within the canonical `MAX_LEASE_DAYS` safety bound, without a
redeploy. An explicit reset operation removes the runtime replacement and makes
the currently deployed baseline effective again. Absence is fallback; explicit
nulls, partial rows, blank values, and implicit deletion semantics are invalid.
Changing `shifter.yaml` while a runtime tenant row exists does not override that
row, and the settings projection must show baseline, runtime value, effective
value, source, and revision so this precedence is visible.

Persist explicit typed columns and a revision/timestamps, with database checks
for the local invariants and the existing
`shared.mission_control_lease.MissionControlLeasePolicy` as the only semantic
contract. Do not copy the deployment baseline into the database in a migration:
that would turn fallback into stale state. Serializer fields and ORM columns are
boundary adapters, not new policy schemas, and must use the shared field names,
constants, units, and validation.

### RBAC groups select policy; workspaces do not

The group layer binds policy rows to stable, policy-eligible Django `auth.Group`
primary keys. Only committed membership in an eligible group participates.
`CTF Participant` and any future group whose membership can be driven by a
self-service claim are ineligible, so `custom:user_type` cannot loosen or select
lease policy indirectly. Provider claim strings in `UserProfile.cognito_groups`,
OIDC claims, session copies, workspace/organization roles, CTF teams/events,
staff flags, cloud IAM groups, and group names supplied by a caller are not
policy membership. A future automated group synchronizer must explicitly define
admin-controlled provenance and eligibility; the default is ineligible.

A group policy is also one complete `MissionControlLeasePolicy`; a missing row
inherits the tenant. It may choose different defaults, but its
`maximum_days` and `initial_days` must not exceed the current effective tenant
maximum. `extension_days` retains #27's established saturating semantics: it is
positive and finite but may exceed the remaining lifetime because the mutation
always applies `min(current + increment, maximum_expires_at)`.

Users may hold several RBAC groups, so “most-specific wins” needs a deterministic
tie rule. Fold every matching configured group policy restrictively:

- `initial_days`, `extension_days`, and `maximum_days` are the minimum matching
  values;
- `extensions_enabled` is logical AND; and
- the resolved values are bounded again by the effective tenant maximum and
  validated by the canonical policy type.

Unconfigured groups contribute nothing. This meet rule has no priority field and
cannot be bypassed by adding a second, looser group. Admin writes lock in a
consistent order (tenant singleton, then group-policy rows). A group write is
validated against the locked tenant. A tenant replacement or reset that would
invalidate a persisted child policy is rejected with a conflict until the child
is changed; do not silently clamp/rewrite children or retain a dormant value that
unexpectedly reappears later.

Every replacement/reset command carries the scope revision the administrator
read. A small, scope-specific revision fence survives removal of the policy row,
so reset/recreation cannot reuse an earlier revision (the ABA case). The service
compares it under the row lock and returns a conflict for a stale revision, so
two browser sessions cannot silently overwrite each other. Revision zero denotes
a scope with no prior runtime mutation; after reset, the fallback projection
retains the newly advanced revision. It is not a wildcard.

This is policy selection, not authorization. Group membership never grants
Mission Control launch, another user's range, workspace membership, or remote
access. Existing `shared.auth`, workspace, owner, API-token, source, lifecycle,
and participant gates still decide whether an operation is allowed. General
RBAC membership management and provider-to-group synchronization are outside
this issue; do not add either as a side effect of the policy editor.

### The range generation is the owner-override record

Do not add an owner-settings table or accept owner-selected timestamps,
increments, initial durations, maximums, or enable switches. The bounded
per-range owner control is the existing empty-body
`POST /api/v1/mission-control/range/extend/`: each successful call advances the
current persisted `RangeInstance.expires_at` by the generation's server-selected
`extension_days`, saturating at its immutable `maximum_expires_at`.
`RangeInstance` already is the per-range persistence required by the issue.

The three resolved duration values are snapshotted when a Mission Control user
lease is first assigned, on both cold creation and warm claim. Later tenant,
group, group-membership, or deployment-duration changes never rewrite an
existing generation's `expires_at`, `maximum_expires_at`, or `extension_days`.
The effective `extensions_enabled` value remains a live admission restriction,
as #27 requires: tenant and current matching group switches are re-resolved on
each extension attempt and can deny an old generation, but they never change its
bounds or stop cleanup. A membership change can therefore affect future launch
resolution and the live switch only; it cannot enlarge an existing generation's
persisted ceiling.

If a later requirement genuinely needs owner-selected duration, it needs a
separately reviewed, versioned settings command and persistence contract. It
must not be smuggled into the launch or extend body under this issue.

### One authoritative resolution/assignment seam

Extend `cms.services._range_lease`; do not create a policy service in
Mission Control, management, workspaces, Engine, or a provider adapter. A CMS
resolver takes the normalized deployment baseline and an already-authenticated
owner, reads the runtime tenant policy plus the owner's committed group-policy
rows, and returns one immutable canonical policy plus bounded provenance
(source and revisions/group IDs, never claim payloads or group rosters).
`build_range_lease` remains the sole deadline arithmetic function and CTF bypass.

Resolution must occur inside the transaction that first assigns the lease, not
before it. The current cold path builds the lease before
`_reserve_active_range_slot`, and the warm path carries a prebuilt lease into
`_run_atomic_claim`; both must move the authoritative read into their existing
locked persistence transactions. A warm miss creates no generation and may
resolve again in the cold reservation. The committed generation is authoritative,
not a preview computed earlier by the view or SPA.

Policy and group-membership reads must be taken once for that resolution; do not
perform field-by-field or provider-specific reads. Mutations and resolution use
the same lock order. The database invariants and final canonical validation must
make any concurrent mixed observation safe and bounded. PostgreSQL concurrency
tests are required; SQLite cannot prove row-lock behavior.

The persisted range fields are the enforcement snapshot. Add the resolved
duration values and bounded policy provenance to the existing successful launch
audit state rather than storing another policy object in `range_spec`, Engine,
the RAES plan, or provider state. Runtime policy mutation is strict-audited in
the same transaction as the row/revision change; a failed audit rolls the change
back. Existing owner-extension and system-expiry audits remain authoritative.

### API, UI, and provider delivery

The administrator surface belongs in the existing Administer composition route
(`config.api_administer` / `/api/v1/administer/`) and the existing
`PlatformSettingsPage`, while all behavior and persistence stay behind the
public `cms.services` facade. It is a session-only, superuser-authorized surface:
keep `ApiTokenAuthentication` before `SessionAuthentication`, then
`IsStaffSession`, and repeat the superuser check in the CMS command. Do not add
an API-token scope for tenant-wide cost/access policy in this issue. Use explicit
read/command serializers, full replacement plus explicit reset commands with an
`expected_revision`, the shared error envelope, request attribution, and strict
audit. Do not use a writable `ModelSerializer` or expose Django's settings object.

The owner-facing UI continues to consume the server-derived `RangeLease`
projection and `can_extend`, and uses the existing `useExtendRange` empty-body
mutation. The admin UI consumes generated OpenAPI types through the existing
TanStack Query/API client conventions. `openapi/v1.json` and
`frontend/src/api/schema.d.ts` are generated artifacts, never hand-edited; UI
capabilities are advisory and every command reauthorizes server-side.

Runtime values live in the shared application database, so AWS and GCP need no
new provider setting, Terraform variable, Helm value, ConfigMap key, Job input,
or rollout controller. Both consume the same CMS resolver. The existing
`MISSION_CONTROL_LEASE_POLICY_JSON` installation/render path remains necessary
as the fallback producer on both providers. A mutable database value must never
be written back to `shifter.yaml` or copied into process environment.

## Cross-cutting incumbents and required reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Policy contract | `shared/mission_control_lease/policy.py` | Reuse the exact four fields, strict Pydantic validation, defaults, units, upper bound, JSON adapter, and saturating-increment semantics. Do not create admin/group DTO enums or a second validator. |
| Deployment fallback | `installation/mission_control_lease.py`, `installation.render.render_mission_control_lease_env`, AWS/GCP runtime inventories and renderers, `config/_mission_control_lease_settings.py` | Keep `shifter.yaml` validation and both provider deliveries unchanged in authority: they produce the normalized fallback only. Present malformed env still fails startup. |
| Persistence and migrations | `cms.models.RangeInstance`, CMS migrations 0037/0044, named constraints, Django additive migration conventions | CMS owns typed runtime policy rows and generation snapshots. Add constraints and migrations without rewriting existing deadlines or seeding a stale baseline. |
| Launch/claim seam | `cms.services._range_lease`, `_raes_range_create`, `_range_launch_common._reserve_active_range_slot`, `_warm_pool_claim` | Resolve once in the transaction that assigns the lease. Cold and warm paths consume the same resolver/arithmetic; CTF continues to supply its event deadline. |
| Owner authorization | `MissionControlAPIView`, `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `_range_write_permission`, participant lifecycle guard, `authorize_range_workspace(..., MANAGE_RANGE)` | Preserve authenticated actor resolution, exact token scope, CSRF, participant denial, owner/source filtering, workspace authorization, and locked recheck. Empty extend bodies remain mandatory. |
| Admin authorization | `config.api_administer`, `ApiTokenAuthentication` before `SessionAuthentication`, `IsStaffSession`, superuser-only quota/ownership precedents | Session and CSRF only, with a CMS service-level superuser recheck. SPA visibility is not authority; staff alone, model permission alone, group membership, or a token never suffices. Policy targets exclude the self-service `CTF Participant` group. |
| Transactions | `transaction.atomic`, `select_for_update`, singleton/one-policy-per-group constraints, existing workspace/quota lock patterns | Lock policy mutations and launch resolution in one documented order; no check-then-write, silent cascade clamp, cache race, or best-effort audit. |
| Errors | `CMSError` typed subclasses/kinds, `shared.api.errors`, `ApiErrorSerializer`, `shared.errors` | Reuse the hierarchy and authored stable codes. Map validation/authorization/conflict without returning Pydantic, SQL, group, or raw exception detail. |
| Audit/logging | `shared.audit` (`AuditEntityType.CONFIG`, `AuditAction.UPDATE`), request attribution, `shared.log_sanitize`, existing range extension/expiry audit | Strict-audit settings changes with safe before/after scalar policy and revisions; audit launched snapshots and existing owner mutations. Logs use stable codes, numeric IDs/revisions, and request correlation, never full requests, claim sets, emails, or group rosters. |
| HTTP/client contracts | DRF explicit serializers, drf-spectacular, `openapi/v1.json`, `frontend/src/api/client.ts`, generated `schema.d.ts`, TanStack Query invalidation/error helpers | One API schema. Reject unknown/partial command fields and non-object input. Regenerate contracts; do not hand-copy TypeScript policy types or retry mutations automatically. |
| Documentation/workflow | `docs/features/ranges.md`, `docs/technical/shifter_platform/cms.md`, documentation coverage `ranges`, ADR-011/039/046, ADR-019 tests | Update shipped user/operator and technical truth during implementation. Run ADR guard, Ruff/import-linter, migration/OpenAPI/frontend checks and relevant tests; do not claim this preflight is shipped behavior. |

## Security layers and whole-repository gates

The intended implementation crosses all of these layers:

1. **Identity binding.** OIDC/Identity Platform issuer, audience,
   authorized-party, subject, verified-email, active-user, and organizer
   provenance checks remain upstream. Policy resolution consumes the resulting
   Django user and committed policy-eligible `auth.Group` relations only; it
   never parses claims.
2. **Admin HTTP authentication.** Bearer-first authentication prevents an
   invalid/revoked token from falling through to a session. `IsStaffSession`
   rejects valid API-token principals; CMS then requires an active superuser.
   SessionAuthentication supplies CSRF enforcement. No `csrf_exempt`, browser
   token storage, or new wildcard scope is permitted.
3. **Owner HTTP authentication/authorization.** The existing Mission Control
   session/token gates, exact range-write scope, active actor, participant-only
   denial, persisted owner/source filter, and workspace `MANAGE_RANGE` check all
   run, with eligibility rechecked under the `RangeInstance` lock. `can_extend`
   and hidden buttons are never authority.
4. **Shape and semantic validation.** Explicit DRF serializers reject unknown,
   missing, null, coerced, fractional, boolean-as-integer, and out-of-range
   values. The CMS service revalidates the complete canonical Pydantic policy so
   non-HTTP callers cannot bypass cross-field and parent-bound rules. Database
   checks/uniqueness are the final persistence backstop.
5. **Configuration binding.** `RootConfig`/installer validation and
   `MISSION_CONTROL_LEASE_POLICY_JSON` runtime parsing still fail closed and
   produce the fallback. A valid runtime row supersedes it only through the
   audited CMS command; malformed deployment config never becomes permission to
   use a database default.
6. **Persistence/concurrency.** Policy rows and range assignment use atomic
   transactions, row locks, expected-revision compare-and-set, revision
   increments, uniqueness, and immutable generation ceilings. Parent changes
   cannot invalidate children silently.
   Extend still computes from persisted expiry (not `now`) and caps before save;
   expiry cleanup rechecks the locked due row.
7. **Error envelope and tenant leakage.** DRF exceptions pass through
   `shared.api.errors`; CMS outcomes map to fixed safe messages/statuses. Public
   responses never contain SQL/Pydantic text, group membership, policy rows the
   caller cannot administer, stack traces, provider payloads, or settings dumps.
8. **Secret handling.** Lease values are non-secret, but requests, cookies,
   API tokens, provider claims, VPN keys/certificates, secret references, and
   surrounding environment remain on their incumbent paths. Policy audit and
   API projections carry only four scalars, safe IDs, source, and revision.
9. **OS/process exposure.** Mutable policy is database state. It never enters
   command argv, shell interpolation, workflow output, Kubernetes Job env,
   Terraform variables/state, provider labels, events, RAES/scenario content,
   guest metadata, or VPN profile material. The fallback JSON stays one
   validated non-secret ConfigMap string and is never sourced/evaled as shell.
10. **Runtime/provider boundary.** Engine and provisioners receive only the
    already persisted deadline effects they need; they do not query policy.
    AWS/GCP parity is proved at the CMS behavior boundary plus retention of both
    existing fallback render paths. No provider branch may resolve groups or
    compensate for policy absence.
11. **Observability.** Strict audit is the durable change record; bounded logs
    provide request/revision/correlation diagnostics. Existing cleanup logging
    and health behavior remain. Do not add high-cardinality group-name/user
    metrics or log every membership roster; if a policy-resolution metric is
    needed, use source/outcome labels only.
12. **Repository controls.** CMS/model/import changes require migration drift,
    Ruff, import-linter, relevant Django/PostgreSQL tests, generated OpenAPI/client
    freshness, frontend tests/accessibility, documentation links, and the full
    ADR guard. Infrastructure validators apply only if implementation expands
    beyond this design and edits those surfaces.

## Extensibility seam

Keep resolution as an explicit CMS function over `(validated deployment
baseline, authenticated owner/group memberships, persisted tenant/group rows)`
that returns `(canonical policy, bounded provenance)`. Deadline arithmetic and
generation persistence consume only that result. A future, separately accepted
organization/workspace or owner-preference layer can add one explicit resolver
input and precedence rule without changing installer schemas, provider adapters,
range arithmetic, cleanup, or wire deadlines. Do not pre-build a generic policy
engine, selector DSL, priority registry, or nullable polymorphic scope table.

## Gotchas and anti-patterns

- Do not treat workspace role, organization membership, provider group claim,
  CTF role/team, staff flag, or cloud tenant as an RBAC policy group.
- Do not attach policy to `CTF Participant` or another self-service-synchronized
  group; committed storage is insufficient if the membership provenance is not
  administrator-controlled.
- Do not pick the first group returned by the ORM, order by group name, or add
  an undocumented priority. Multi-group resolution must use the restrictive
  meet above.
- Do not trust a group name/ID, user ID, deadline, increment, maximum, or switch
  from the launch/extend request. Admin group targets are resolved server-side;
  the owner extend request remains empty.
- Do not cache runtime policies without a versioned, cross-process invalidation
  contract. A stale process-local cache would defeat “runtime configurable.”
- Do not mutate existing generation bounds when tenant/group durations change,
  reset an already leased warm generation, or apply a current increment to an
  old generation.
- Do not make the pre-transaction policy preview authoritative. Assignment and
  snapshotting belong inside the cold/warm persistence transaction.
- Do not duplicate policy defaults/validation in model `clean()`, serializers,
  React, provider scripts, or tests. Adapters may enforce shape and DB backstops;
  the shared policy owns meaning.
- Do not use a generic settings JSON blob, `range_spec`, Engine fields, RAES
  contracts, provider state, environment, or secrets storage as policy
  persistence.
- Do not silently clamp child rows, retroactively lower ceilings, or resurrect
  a dormant out-of-bounds child after a tenant raise. Reject invalid parent
  changes explicitly.
- Do not weaken cleanup when extensions are disabled. The current deadline
  remains the automatic-destruction authority.
- Do not hand-edit OpenAPI/TypeScript generated artifacts or add direct fetches,
  client fallback defaults, optimistic authority, or automatic mutation retries.

## Non-goals and implementation boundaries

This issue is limited to runtime tenant/group policy persistence and admin
surface, deterministic CMS resolution, existing range-generation snapshots on
cold and warm paths, the existing bounded owner extension, AWS/GCP-neutral
behavior, tests, and operator/admin documentation.

It does not add workspace/organization policy, group-membership administration,
SCIM/provider-group mapping, owner-selected durations, retroactive deadline or
ceiling normalization, CTF lease changes, billing/budget/cost allocation,
capacity or warm-pool redesign, credential renewal/revocation, a generic tenant
model/settings framework, new cleanup schedulers, provider payloads, cloud/IAM/
network changes, a new API major, or a generic policy engine.

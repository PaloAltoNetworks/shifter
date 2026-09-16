# Range-to-workspace scoping administration preflight (#1944)

Status: pre-implementation guidance

Date: 2026-09-03

Requirements: PLAT-237 (implements), PLAT-241 (constrains)

This note fixes the repo-wide boundaries for range-scope administration. It
does not implement the API or SPA and is not an implementation plan.

## Decision and authority boundary

PLAT-237 administers one existing fact: the scalar `workspace_id` copied from
CMS request intent to the CMS range projection and Engine range. It does not
change the range's individual owner or make ranges shared within a workspace.

Range-scope administration needs two new closed `WorkspaceOperation` values:
one for listing scope bindings and one for rebinding a range. Both belong in the
owner/admin part of the central `ROLE_OPERATIONS` matrix. They must not reuse:

- `READ_RANGE`, which is additive to individual ownership and lets every member
  read only their own range;
- `REASSIGN_RANGE`, which authorizes an ownership handover and currently lets
  every member receive a range they will own;
- organization-admin authority, Django staff/model permissions, CTF authority,
  API-token scopes, provider groups, or cloud IAM; or
- ADR-046-R13's superuser-only user-offboarding override.

The HTTP surface is staff-session-only because it exposes cross-owner
administrative metadata inside the Administer console. Staff admission and the
workspace operation are conjunctive: staff alone grants no range-scope
authority, while a non-staff workspace owner/admin cannot call this
administration API. Platform API tokens are rejected; no new token scope is
introduced.

A list for workspace A requires the list-scope operation in A. A move from A to
B requires the rebind operation in both A and B, rechecked against live
memberships under the workspace mutexes. The unchanged range owner must also
have a live membership in B; the command never fabricates membership. This
keeps the existing owner able to pass the same per-range workspace gate after
the move. Source A may be archived so an administrator can evacuate or correct
its bindings, but target B must be active. Unknown, malformed, unauthorized, and
archived targets share bounded outcomes and do not become tenant or lifecycle
enumeration oracles.

## Service and persistence boundary

CMS owns the query and mutation because it owns request intent and the range
projection, already orchestrates Engine through `engine.services`, and is the
only domain allowed to consume both that facade and `workspaces.services`.
`workspaces` must not import CMS or Engine, and `config` does not need a new
cross-domain workflow. The CMS API calls a public `cms.services` operation; it
does not write models or compose several mutation calls in the controller or
SPA.

The list is a bounded, paginated, read-only scalar projection selected by the
authorized internal workspace ID. It may expose the request correlation UUID,
a safe owner identifier/display label, server-derived range source, lifecycle
status, and timestamps needed for administration. It must not expose internal
workspace IDs, range specs, instance/IP/access details, credentials, secret
references, provider state, membership rosters, or ORM objects. Use explicit
DRF serializers and the canonical pagination/filter conventions, not a
`ModelSerializer`, generic CRUD viewset, or unbounded materialized list.

The mutation addresses the range by its existing CMS `Request.request_id` UUID
and accepts only a target workspace public UUID. Internal range, CMS, Engine,
organization, or workspace integer IDs are never accepted from HTTP. The
selected workspace in the SPA is context, not mutation authority; the service
derives the current source from persisted range state and reauthorizes it.

One database transaction must:

1. lock the source and target workspace mutexes in deterministic ID order and
   recheck the actor plus unchanged-owner target memberships;
2. lock and uniquely resolve the CMS Request, its one range projection, and the
   correlated Engine Range;
3. verify that all three currently carry the same expected source binding; and
4. update all three bindings and write the strict audit event, or roll back all
   of them.

Projection absence, duplicate projection cardinality, or binding disagreement
is an integrity failure, not authorization to guess, update every match, or
repair drift. The Engine facade must support expected-source compare-and-set
semantics rather than an unconditional bulk update. A target equal to the
consistent current binding is an authorized idempotent no-op and emits no
mutation audit. Concurrency with another move must produce one winner and a
bounded conflict/not-found result, never last-writer-wins tenant drift.

The transaction changes only `workspace_id`. It preserves CMS/Engine user and
request ownership, `range_source`, status/deletion state, leases, participant
VPN generation, terminal/Guacamole bindings, scenario/range spec, backend and
purpose, capacity records, and the Engine range's pinned `egress_mode`.
Workspace policy is launch-time intent; moving an existing range must not
reinterpret it or trigger cloud/provisioner work.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Domain layering | ADR-001; ADR-046; `.importlinter`; `scripts/check_layer_imports/layer_imports.yaml`; `check_model_fks` | CMS orchestrates through public facades; keep scalar soft references and add no repository or cross-layer FK. |
| Scope authority | `workspaces.roles`; `authorize_workspace`; `authorize_bound_workspace`; workspace row mutex used by membership/lifecycle services | Add distinct owner/admin operations; recheck both scopes and owner membership under locks. Never compare roles in CMS or TypeScript. |
| Range truth | `cms.models.Request`; `cms.models.RangeInstance`; `engine.models.Range`; `cms.services._range_reassign`; `engine.services.rebind_range_workspace_by_request` | Build a dedicated scope-only command on the existing correlation and facade seams; do not call owner reassignment or mutate one projection. |
| Identity/browser gate | bearer-first `ApiTokenAuthentication`, `SessionAuthentication`, `IsStaffSession`; `CTFAccountBoundaryMiddleware`; `shared.spa_host` | Session + CSRF + staff + live workspace authority. Tokens and temporary CTF accounts do not enter this surface. |
| HTTP contracts | explicit DRF serializers; `config._drf_settings`; `shared.api.errors`; `ApiErrorSerializer` | Public UUIDs, standard pagination, stable typed errors, and the request-ID envelope; no writable model serializer or ad-hoc JSON. |
| API publication | `config.api_urls`; `cms.api.urls`; `api_contract`; `openapi/v1.json`; generated `frontend/src/api/schema.d.ts` | Runtime serializers are authoritative; regenerate instead of hand-copying DTOs or operation codes. |
| SPA composition | existing `range-scoping` route slot; `WorkspaceContext`; `frontend/src/api/client.ts`; TanStack Query keys/client; shared tables/dialogs/alerts | Replace the slot, use public UUID route state, never direct-fetch or treat cached capabilities as authority, and invalidate source/target/context queries after success. |
| Persistence/concurrency | `transaction.atomic`; `select_for_update`; workspace mutation mutex; request UUID correlation | Deterministic locks, exact cardinality, expected-source compare-and-set, all-three-or-none update. No signals, background convergence, or count/update loops. |
| Errors | `CMSError` hierarchy; typed workspace authorization/lifecycle errors; `shared.api.errors` | Add at most a typed/classified CMS scope outcome under the existing hierarchy; never string-match errors or disclose which authorization fact failed. |
| Audit/logging | `shared.audit`; `AuditEntityType.RANGE`; request attribution helpers; `shared.log_sanitize`; `RequestIDMiddleware` | Strict audit inside the mutation transaction with internal IDs and old/new scope; logs contain bounded codes/correlation, not names, UUID probes, rosters, SQL, or payloads. |
| Documentation/tests | ADR-022 coverage manifest; workspace user/technical docs and indexes; existing workspace/range service, API, migration, and SPA tests | Extend shipped docs and test the real facade/API/UI contracts; do not create a parallel test-only workflow. |

## Security and whole-repository layers

1. **Identity binding and account admission.** Existing OIDC/Identity Platform
   issuer, audience, authorized-party, subject, and verified-email checks bind
   the Django actor. `CTFAccountBoundaryMiddleware` continues to reject
   temporary participants. Workspace UUIDs and owner IDs never establish an
   identity.
2. **Browser/session boundary.** `shared.spa_host`, secure session cookies,
   CSRF middleware and `SessionAuthentication`, same-origin `apiFetch`, CSP,
   referrer policy, and permissions policy remain unchanged. Bearer-first
   parsing fails closed; `IsStaffSession` rejects valid platform tokens as well
   as anonymous/non-staff callers.
3. **HTTP shape.** DRF validates request/path UUIDs and the closed request body;
   unknown keys are rejected. Standard pagination bounds collection work.
   Neither the route, feature flag, selected workspace, nor a disabled button is
   authority.
4. **Tenancy policy.** `workspaces.services` resolves public UUIDs, owns the
   role matrix, checks archived target state, and reauthorizes actor membership
   in both scopes plus range-owner membership in the target under its existing
   workspace locks. CMS receives only trusted scalar IDs/proofs.
5. **Range policy.** CMS identifies the exact request/range projection and
   preserves owner, source, state, lease, access, and product semantics. The
   administrative read is metadata visibility only; it never calls interactive
   range access/lifecycle services on behalf of the administrator.
6. **Persistence.** CMS and Engine rows are in the same database transaction;
   row locks, exact cardinality, and expected-old values prevent partial or
   lost updates. Non-null scalar columns remain without defaults and no FK,
   signal, cache, or second binding table is added.
7. **Remote access and secrets.** No secret is read, rotated, returned, logged,
   audited, or passed to the client. Existing owner/READY/channel/generation,
   VPN throttle/delivery, host-key, and credential checks remain on their own
   paths and see only the committed binding afterward.
8. **Errors and observability.** Typed service failures map once to the shared
   request-ID error envelope. Range absence, wrong source scope, and inaccessible
   range remain an opaque not-found; target absence/non-membership/role/archive
   remain one opaque denial/conflict class. Raw ORM/Engine errors and tenant
   details do not cross the envelope. Successful changes are strict-audited;
   routine reads are not.
9. **Configuration and secret shapes.** PLAT-237 adds no Django setting,
   `.env`/`config/env-manifest.json` key, `.shifter.yaml` field, API-token scope,
   identity claim, Kubernetes/Helm value, Terraform variable, cloud secret, or
   provider-specific branch. AWS and GCP receive the identical control-plane
   behavior.
10. **OS/process/runtime exposure.** Workspace identity, memberships, roles,
    and the command body do not enter argv, environment, shell commands, worker
    task payloads, provisioner job specs, provider labels, range events, guest
    metadata, or static bundles. Rebinding is a database control-plane action;
    there is no external process or cloud dispatch.
11. **Repository gates.** Relevant work must pass Ruff/mypy/Django tests,
    `lint-imports`, layer/FK checks, OpenAPI drift/compatibility, frontend
    ESLint/TypeScript/Vitest/axe/build checks, documentation coverage, and the
    repository ADR guard. The existing AWS/GCP-neutral path needs no
    provider-specific test branch.

## Extensibility seam

The seam is one CMS scope-administration query/command parameterized by actor,
range request UUID, current persisted scope, and target public workspace UUID,
with one workspace-service pair authorization and one Engine
expected-source/target update. Collection filtering belongs at that same query
seam (status/source/search plus canonical pagination), so the next reasonable
addition—filtering archived/history rows or bulk-selecting candidates—does not
duplicate authorization or expose an ORM query to another layer.

A future bulk rebind must call the same per-range invariant inside an explicitly
bounded batch and report per-item outcomes; it must not introduce a bulk SQL
shortcut, wildcard target, client-composed loop, or eventual repair worker.

A binding may also be part of a stronger aggregate owned by another domain.
ADR-051 binds a CTF event immutably to a workspace and requires a range
generation to join to that same event/workspace. The CMS command must not infer
that invariant from `range_source`, import CTF models, or rewrite CTF rows. A
linked CTF range can move only when the CTF owner validates the same target
through a public service/composition seam; until that seam exists, the move
fails closed. The same guard applies to a future domain-owned immutable tenant
aggregate.

## Gotchas and anti-patterns

- Do not conflate workspace-scope rebinding with individual owner reassignment,
  offboarding transfer, workspace ownership transfer, or CTF spare handover.
- Do not grant scope administration to `member`, infer it from staff/superuser,
  or authorize only the source or only the target workspace.
- Do not move a range where its unchanged owner has no target membership, create
  that membership implicitly, or use the administrator's personal workspace as
  a fallback.
- Do not let an archived workspace receive a binding. Do allow an authorized
  administrator to list and move bindings out of an archived source.
- Do not expose internal IDs or accept a browser-provided `workspace_id`; do not
  use names, organization IDs, roles, or selected-client state as identifiers.
- Do not return `RangeInstance`, `Range`, `range_spec`, state JSON, addresses,
  connection data, or credential metadata from the administrative projection.
- Do not N+1 authorize rows, materialize an unbounded collection, or join the
  workspaces models from CMS. Authorize the selected scope once for listing.
- Do not update via model signals, three sequential HTTP calls, unconditional
  `.update()`, or best-effort compensation. A partial binding is a tenant bug.
- Do not silently repair existing projection drift during a requested move.
  Surface a bounded failure and leave evidence for an explicit reconciliation
  workflow.
- Do not recalculate egress, capacity, quota, lifecycle, access channels, or
  provider placement, and do not dispatch provision/destroy work.
- Do not independently move a range linked to an immutable CTF event workspace
  (or another domain-owned tenant aggregate), infer linkage from `range_source`,
  or cross the CMS/CTF model boundary to make the move fit.
- Do not add another DTO source, validator, role matrix, exception tree, audit
  store, fetch client, router, query cache, or confirmation-dialog pattern.
- Do not leak whether a UUID names a real workspace/range or which membership,
  role, archived-state, or projection check failed.

## Non-goals and implementation boundaries

- Sharing a range with workspace peers or letting an administrator open,
  operate, pause, destroy, extend, download from, or connect to another user's
  range.
- Changing any range/request owner, CTF participant/team/event authority,
  lifecycle state, provenance, active-range uniqueness, lease, credential, or
  access semantics.
- Workspace membership creation/removal, organization authority, user
  offboarding, range-owner transfer, or personal-workspace lifecycle changes.
- Bulk moves, automatic moves on workspace archive/delete, orphan repair, or a
  background reconciliation system.
- Moving an owning CTF event or any other domain aggregate as a side effect of
  range-scope administration.
- Re-evaluating workspace egress/quota/policy for an existing range, changing
  cloud resources, or adding AWS/GCP behavior.
- New configuration, secrets, feature flags, API-token scopes, identity claims,
  provider adapters, schemas outside the generated OpenAPI contract, or a new
  persistence abstraction.

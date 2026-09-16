# Range workspace scoping preflight

Issue: #1327, "Range ownership scoping to workspaces"

Status: pre-implementation guidance

Date: 2026-07-31

This is a requirement-free architecture preflight. The GitHub issue is the
shipping contract. This note does not implement range scoping and is not an
implementation plan.

## Boundary decision

ADR-046 remains authoritative: a range has two conjunctive ownership facts,
not one replacement owner.

- `Range.user`, `cms.Request.user`, and `cms.RangeInstance.user_id` retain the
  individual owner and product actor.
- `workspace_id` is the immutable tenancy scope carried by the CMS request
  intent, CMS range projection, and Engine range.
- An interactive caller must be that range's permitted individual owner **and**
  have a workspace role permitting the named operation. Membership never makes
  every range in the workspace shared.

Consequently, collection queries remain `user_id = actor` **and**
`workspace_id IN authorized_workspace_ids(actor, operation)`. Point operations
retain the owner/source/state checks and authorize the row's persisted binding.
Do not replace either side with a workspace-only filter.

That is the product range-access rule, not a prohibition on a separately
authorized administrative projection. ADR-046-R14 and the #1944 range-scope
administration preflight later accept one narrow, staff-session scope-only
exception. It grants no range use or lifecycle authority.

The #1325 migrations already implement the compatibility migration:
`workspaces.0002`, `cms.0038`-`0040`, and `engine.0040`-`0042` create personal
workspaces, backfill all three projections, prove ownership consistency, and
make the bindings non-null without a default. #1327 must reuse that evidence;
it must not add a second "default workspace" migration or rewrite already-bound
ranges.

## Launch scope and admission

`cms.services._range_workspace.resolve_launch_workspace` is the canonical
launch-scope seam shared by cyberscript and RAES creation. Extend that seam
rather than resolving workspaces in a view, serializer, CTF bridge, Engine, or
provisioner.

An interactive launch may supply an optional public `workspace_uuid`.
DRF validates its UUID shape. Omission resolves the actor's personal workspace,
preserving existing clients and single-user behavior. A supplied UUID goes
through `workspaces.services.authorize_workspace(..., LAUNCH_RANGE)`. HTTP must
never accept an internal workspace integer, role string, organization ID,
provider group, or workspace name as authority.

After authorization, only the trusted internal `workspace_id` crosses the CMS
to Engine boundary, beside `RequestSpec` or the RAES plan rather than inside
either scenario contract. The same value is persisted on the CMS request,
CMS range projection, and Engine range before dispatch.

Shared-workspace selection introduces a revocation race that personal
workspaces do not have. A launch must reauthorize against the membership while
holding the existing workspace row mutex used by membership mutations, and
must retain that lock through the atomic CMS request/range reservation.
Otherwise a concurrent removal can commit after the membership read but before
the range insert, leaving a newly created range scoped somewhere its owner
cannot access. Reuse the workspaces service and its workspace lock; do not add
a second advisory lock or reach into `workspaces.models` from CMS.

Engine create remains defense in depth. Both cyberscript and RAES idempotent
create paths must treat a replay carrying a different `workspace_id` as a
binding conflict, just as they already reject conflicting backend,
participant-access, and remote-access intent. Silently reusing the first range
for a differently scoped replay is a cross-tenant bug.

### Workspace quota and policy hook

The hook belongs in the one CMS launch-admission path after actor, workspace,
backend, source, purpose, and scenario inputs are validated, but before CMS
reservation, Engine persistence, or cloud dispatch. Both creation families and
all product callers must pass it.

The seam must be parameterized by the authorized `workspace_id`, individual
owner, server-derived `RangeSource`, trusted `InstantiationPurpose`, and a
stable request/draw correlation key. The initial policy may admit without an
additional workspace limit, but it must return or raise one bounded decision at
this point; callers must not reproduce quota or policy checks.

Keep two existing concepts separate:

- `cms.models.RangeInstance`'s partial unique constraint is the race-proof
  per-`(user_id, range_source)` active-range invariant. Workspace selection
  does not change it.
- `engine.models.CapacityAssessment` / `CapacityReservation` / `CapacityDraw`
  are physical provider/event-capacity accounting. They are not a workspace
  entitlement or billing quota.

If a hard workspace quota is added, reuse the existing hold/capture/release and
bounded-verdict conventions, but give the tenant quota its own durable,
idempotent reservation keyed by workspace and request. A count-then-create
query over active ranges is only a friendly pre-check and races across members;
it is not enforcement.

The zero-egress posture remains governed by the provider-neutral
`installation.range_egress.RangeEgressPolicy` and its renderer/runtime
validation chain. #1327 provides the workspace policy-resolution attachment
point; it does not create a second egress schema or implement a per-workspace
route posture. A later workspace override must resolve an effective closed
posture at launch and pin that decision on the Engine range in the create
transaction, with idempotent replay verification. It must not make the
provisioner query workspace membership or reinterpret a mutable workspace
setting during retry.

## Lifecycle enforcement coverage

The current repository already has the correct service owners. The
implementation must build on them and close gaps in place.

| Surface | Canonical incumbent | Required invariant |
| --- | --- | --- |
| Scope selection and create | `cms.services._range_workspace`, `_range_create`, `_raes_range_create`, `_reserve_active_range_slot` | Optional public UUID resolves once; lock-safe authorization, admission, and identical three-projection persistence happen before dispatch. |
| Collection/current/history/detail | `cms.services._range_queries`, `_range_lease`, `authorized_workspace_ids` | Filter owner, source, soft-delete semantics, and authorized workspace IDs together; authorize point reads without tenant enumeration. |
| Cancel/destroy/pause/resume/extend | `cms.services._range_destroy`, `_range_lifecycle`, `_range_lease` | `MANAGE_RANGE` is additive to owner and lifecycle-state checks and runs before any status write or Engine call. |
| Status and RAES sidecars | `get_range_by_request_id`, `mission_control.status_consumers`, Mission Control RAES API services | Authorize the CMS range first; never join a channel group or read request-keyed sidecars from a caller-supplied request ID alone. |
| Terminal/SSH/RDP/Guacamole | `cms.services._range_access`, `mission_control.consumers`, `_guacamole_session_builders`, Engine terminal services | CMS checks `ACCESS_RANGE` before Engine resolves READY state, declared channel, host key, or secret material. |
| OpenVPN | `cms.services._range_vpn`, `shared.credential_delivery`, `engine.services._vpn` | Workspace and owner checks precede throttle, generation/target validation, secret fetch, no-store delivery, and strict download audit. |
| CTF participant ranges | `ctf.services`, `ctf.bridges`, CMS range facades | Event/team/participant authorization remains separate; use the bound participant user for range authorization. CTF events do not become workspaces. |
| Reassignment/rehome | `cms.services._range_reassign`, `engine.services.rebind_range_workspace_by_request` | Ordinary reassignment requires target membership. Explicit cross-tenant handover moves all three bindings transactionally and strict-audits old/new scope. |
| System cleanup/callbacks | `expire_due_ranges`, reconciliation handlers, Engine result application | Trusted system correlation bypasses human role checks so revocation cannot strand cleanup; these helpers must not become public query/mutation endpoints. |

Internal helpers such as `get_range_status_by_id`,
`find_range_instance_id_by_request`, Engine lifecycle-by-request functions, and
result handlers intentionally use trusted correlation rather than an
interactive actor. "Every range query path is workspace-scoped" means every
interactive/public path. Do not add a fake system user or import workspace
policy into Engine; keep these functions behind existing CTF/event, CMS, or
callback authority.

## Cross-cutting concerns to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Layer ownership | ADR-001, ADR-046, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `check_model_fks` | Other domains consume only `workspaces.services`; scalar bindings remain cross-layer soft references. |
| Role policy | `workspaces.roles.WorkspaceOperation`, `ROLE_OPERATIONS`, `authorize_workspace`, `authorize_bound_workspace`, `authorized_workspace_ids` | Callers name operations; they never compare `owner`/`admin`/`member` strings or query memberships directly. |
| HTTP identity and scope | `IsAuthenticatedSessionOrApiToken`, `active_actor_user`, `HasMissionControlActor`, `require_scope`, CTF decorators/services | Session/token/CTF authority and workspace authority are independent gates. Exact existing range scopes remain in force. |
| Input validation and contracts | DRF command serializers, `shared.schemas`, RAES plan validators, `BackendAdmission` | Add the UUID only at the public launch command. Do not add workspace fields to scenario DSL, `RangeSpec`, RAES plans, events, token scopes, or provider tags. |
| Persistence and races | non-null workspace columns, active-range partial unique constraint, `transaction.atomic`, `select_for_update`, workspace row mutex | Persist one authorized binding, retain owner/source uniqueness, and fail conflicting replays. |
| Capacity | `shared.capacity`, Engine capacity assessment/reservation/draw services, CTF capacity bridge | Reuse policy/result and ledger conventions; do not encode tenant quota as an event or provider partition. |
| Errors | `CMSError` with bounded details, `shared.api.errors`, `ApiErrorSerializer`, `classify_user_message` | Malformed UUID is 400; unknown/non-member launch scope is one opaque 403; inaccessible existing ranges remain opaque not-found. Never string-match a new workspace error. |
| Audit and logging | `shared.audit`, request/client attribution, `shared.log_sanitize`, workspace denial logging | Strict-audit binding creation and rehome with internal IDs and request correlation. Do not log UUID probes, roster/email/role payloads, SQL, or secrets. |
| Remote-access secrets | `engine.secrets`, participant-channel bindings, `shared.credential_delivery`, Guacamole bootstrap | Workspace authorization happens before secret retrieval; no secret-bearing schema, response, log, task argument, or audit state changes. |
| API publication | `config.management.commands.api_contract`, `openapi/v1.json`, generated `frontend/src/api/schema.d.ts` | Runtime serializers are authoritative; regenerate committed artifacts if the public launch shape changes. |

Do not create a workspace DTO, validator, exception hierarchy, range
repository, role cache, lifecycle workflow, or audit store beside these
incumbents.

## Security and whole-repository layers

The intended design must pass every layer below.

1. **Identity and account gates.** `config.oidc`,
   `config.identity_platform`, provider-identity binding, active-account
   checks, CTF account middleware, session CSRF, and API-token expiry/revocation
   establish the Django actor. A workspace UUID or provider claim never does.
2. **HTTP shape and token policy.** Mission Control uses its existing
   authentication, actor permission, participant lifecycle restriction, exact
   `mission_control:range:read|write` scope, rate throttle, and explicit DRF
   serializer. CTF keeps its event/participant gates. No wildcard or
   workspace-encoded token scope is added.
3. **Workspace policy.** The workspaces service validates the public UUID,
   active membership, closed role/operation matrix, and lock-safe launch
   authorization. Missing, unknown, and unauthorized scopes remain
   indistinguishable.
4. **Range policy.** CMS retains individual owner, product `RangeSource`,
   active-range uniqueness, scenario/backend admission, lease, and lifecycle
   state checks. Workspace membership cannot bypass any of them.
5. **Persistence.** The three non-null scalar bindings agree; no default,
   cross-layer FK, workspace model copy, or partial projection update is
   permitted. Idempotent create and rehome verify the same tenant.
6. **Remote access and secrets.** CMS workspace authorization precedes Engine
   owner/READY/declared-channel/host-key/generation checks and secret fetch.
   Credential delivery remains throttled, audited, and non-cacheable. Error
   responses never include connection data or secret references.
7. **Config and environment shapes.** #1327 needs no new Django setting,
   `config/env-manifest.json` entry, `shifter.yaml` key, Helm value, Kubernetes
   env/Secret entry, Terraform variable, identity-provider claim, or secret.
   The existing installation `RangeEgressPolicy` remains the only public egress
   shape.
8. **OS/process/runtime exposure.** Workspace IDs, UUIDs, organizations,
   membership roles, and policy documents do not belong in provisioner argv,
   environment, job specs, shell commands, provider labels, events, or guest
   metadata. Existing launch-intent validation and Kubernetes provisioner-job
   admission continue to allow only canonical command/env shapes. The
   provisioner receives the existing range/request correlation and reads any
   future pinned effective policy from the range binding.
9. **Errors and observability.** Public failures use the standard DRF envelope
   and request ID. Logs use bounded reasons and sanitized/internal correlation;
   strict audit uses the shared store. Raw database errors, workspace probes,
   provider responses, and membership lists never cross those envelopes.

Membership removal revokes subsequent queries, lifecycle requests, downloads,
and new remote sessions. It does not by itself terminate an already accepted
WebSocket/Guacamole session or revoke an already downloaded VPN credential;
those are generation/session-revocation problems. Do not claim continuous
data-plane revocation in #1327. Existing expiry and system cleanup remain the
backstop.

## Extensibility seam

The required parameter is the optional public `workspace_uuid` at the product
launch boundary, resolving to one immutable internal binding. The required
extension point is the single workspace launch-admission call parameterized by
scope, owner, source, purpose, and stable correlation.

That shape admits the next reasonable changes without re-editing every create
path:

- a durable per-workspace active-range quota;
- a workspace policy profile that resolves to the existing zero-egress
  vocabulary;
- another role whose range operations differ in the central matrix; or
- a future explicit workspace rehome command.

Those changes extend the policy behind the seam or the pinned binding. They do
not add workspace arguments to provisioner commands, copy workspace state into
scenario contracts, or branch separately in cyberscript and RAES.

## Gotchas and anti-patterns

- Do not interpret "workspace owns ranges" as shared access to other members'
  ranges. Owner/admin/member currently permit operations only on resources the
  actor already owns.
- Do not change the active-range uniqueness key from `(user_id, range_source)`
  to workspace. A shared workspace must hold many members' ranges, while one
  user still has at most one active range per product source.
- Do not authorize only in a DRF view, SPA route, template, or WebSocket
  consumer. Service entrypoints are the enforcement boundary.
- Do not run membership authorization once and then reserve after releasing
  the workspace mutex. Concurrent removal is a real TOCTOU path.
- Do not trust an internal workspace ID from HTTP or silently fall back to a
  personal workspace when a supplied UUID is invalid or unauthorized.
- Do not expose internal workspace IDs in API responses. If a response needs
  scope identity, project the public UUID through `workspaces.services`.
- Do not N+1-authorize collection rows. Resolve permitted IDs once, then combine
  them with owner/source/status filters.
- Do not forget soft-deleted history, request-ID variants, leases, status
  WebSockets, RAES sidecars, or both remote-access transports when proving
  query coverage.
- Do not make trusted callback and cleanup helpers public merely because they
  lack a human workspace check.
- Do not let a CTF organizer's workspace role replace event ownership or a
  participant's workspace/individual ownership. Spare handover remains the
  explicit audited rehome path.
- Do not reuse CTF events, Django groups, API-token scopes, provider groups,
  Terraform workspaces, cloud projects/accounts, or the SPA "workspace" label
  as tenancy.
- Do not encode workspace quotas in `CapacityDeclaration.event_ref`, treat
  portal saturation metrics as quota, or enforce a hard limit with an
  unlocked count.
- Do not duplicate `RangeEgressPolicy` in Django JSON, a workspace role, a
  Terraform variable family, or a provisioner parser. The hook selects a future
  effective policy; it is not the policy schema.
- Do not place workspace identity or membership in `RequestSpec`, RangeSpec,
  RAES plans, task argv/env, range events, OpenVPN profiles, Guacamole payloads,
  or guest configuration.
- Do not translate all `IntegrityError`s into quota or active-range conflicts.
  Match named constraints and propagate unrelated persistence failures.
- Do not vary point-read error bodies by "range absent", "wrong owner",
  "workspace absent", "membership revoked", or "role denied".

## Non-goals and implementation boundaries

- Sharing one member's range with other workspace members.
- Organization-level membership, roles, quotas, or range visibility.
- Workspace discovery/creation/selection UX beyond an additive launch UUID
  field; that needs its own product contract if required.
- Changing CTF event/team/participant ownership or binding an event itself to a
  workspace.
- A hard workspace quota, billing, cost allocation, provider placement, or
  autoscaling policy.
- Implementing per-workspace zero egress or changing the deployment-global
  `settings.range_egress` contract.
- Mid-session terminal/Guacamole revocation or already-downloaded VPN
  credential revocation.
- A public range rehome API or implicit rehome on membership removal, except
  the separately authorized scope-only command accepted by ADR-046-R14.
- Moving workspace authorization into Engine, workers, the provisioner, cloud
  adapters, Terraform, or guest operating systems.
- A new range schema, status vocabulary, request ID, exception family, audit
  model, or background workflow.

## Validation expectations

Cross-workspace tests must exercise real rows and effects, not only helper-call
mocks. For each interactive lifecycle family, prove:

- the owner with a permitting membership succeeds;
- the same owner after membership removal is denied;
- an owner/member of another workspace is denied;
- another member of the same workspace still cannot use the owner's range; and
- denial occurs before status mutation, Engine dispatch, channel-group join, or
  secret retrieval.

Cover both request-ID and integer-ID variants, current/history/detail reads,
cyberscript and RAES creation/replay, terminal/SSH/RDP/Guacamole, VPN, leases,
CTF participant access, explicit spare rehome, and trusted cleanup.

Repository gates for the implementation include targeted Django/DRF/Channels
tests, migration drift, OpenAPI/frontend type drift when the launch command
changes, layer-import and model-FK checks, and:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
```

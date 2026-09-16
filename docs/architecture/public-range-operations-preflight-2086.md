# Retry-safe public range operations: architecture preflight #2086

Issue #2086 is the contract; no Ground Control requirement is attached. This is
design guidance, not an implementation plan or evidence of implemented behavior.
Inspection baseline: `ba536832543c01491b61618d71c649e780dbcc40`.

## Decision context and scope

Adopt the public-operation portion of the [review's proposed ADR-057](https://github.com/Brad-Edwards/shifter/blob/10f40285d26b20f31018c77a274bb62773073eb3/docs/adr/proposals/057-operable-lifecycle-release.md)
through ADR-040 and ADR-043. **The current accepted ADR-057 is a different
decision about GCP east-west isolation and deferred service mesh.** Do not
overwrite or renumber it, or adopt the proposal's entire release program here.
The registry links this preflight as guidance; implementation must reconcile
public-contract, retention and compatibility rules with its actual mechanisms
and behavioral evidence before advertising support.

The #2081 dependency is represented by accepted ADR-054 and
[dedicated-customer deployment authority](dedicated-customer-deployment-authority.md).
One deployment serves one customer. Deployment identity, organization,
workspace, event authority, participant identity and cloud IAM remain separate.
Use the live service checks and ADR-051's migration activation conditions;
neither a workspace role nor a retry key grants event or participant authority.

## Findings that constrain the design

- `mission_control/api/ranges.py::LaunchRangeView` has no caller retry identity.
  CMS creates a fresh request UUID and performs active-range/quota admission,
  warm-pool claim or cold dispatch. Returning an existing range after those
  effects would be too late to make launch retry-safe.
- `engine/services/_raes_range.py::create_raes_range` reuses a request after
  checking backend, workspace, egress and participant-access bindings. It does
  not compare the complete compiled plan, actor, delivery and artifact intent;
  its initial existence read is outside the creation transaction.
- `engine/launch_intents.py::enqueue_provisioner_launch` reuses an operation
  before recomposing its input. Its internal command/generation hash is not a
  public intent fingerprint. `OperationInput` is immutable per generation,
  but immutability alone does not prove replay equivalence.
- A RAES receipt currently uses the request UUID as its `operation_id`, whereas
  `ProvisionerLaunchIntent.operation_id` is an independently minted execution
  generation. Existing sidecar APIs are request-scoped history. None of these
  names can be treated as interchangeable public operation identity.
- `raes_range_ops.run_raes_range_destroy` loads current configuration and calls
  `raes_plan.parse_plan`, which accepts the current exact producer pin.
  `raes_gcp_destroy` reconstructs resource names from that plan/configuration.
  Stored placement already has a reuse seam; other old-generation identity
  must be equally durable. Current parsing is not an upgrade-safe teardown
  strategy.
- [#1919](https://github.com/Brad-Edwards/shifter/issues/1919) concerns nested
  participant hosts/VPN gateways, dependency ordering, premature assignment
  removal and misleading cleanup success. `gcp_range_cell_destroy` now calls
  gateway/instance deletion before network deletion, but
  `ctf/services/range/lifecycle.py::_destroy_single_range` still releases
  capacity and clears `range_instance_id` after asynchronous dispatch. A
  helper-order assertion cannot establish end-to-end recovery or closure.
- `shared.raes.operations.prune_expired_raes_operation_records` prunes by
  retention time, without consulting residual obligations. Sidecars alone
  cannot anchor durable recovery. Launch/result workers and failure paths
  likewise need outcome evidence beyond heartbeat, dispatch and FAILED status.

Paths below are relative to `shifter/shifter_platform/` unless prefixed with
`shifter/`, `platform/`, `scripts/`, `docs/`, or a repository dotfile.

## Identity, admission and persistence guardrails

The public retry identity is `(deployment, active actor, action, caller key)`.
Resolve actor through `shared.api.principals.active_actor_user`: session and
user-owned token calls represent the same actor, while each credential still
passes its own live checks. Deployment scope is server-owned; the dedicated
deployment's database is the existing isolation boundary. A hostname,
`ENVIRONMENT` label, workspace UUID or model-access catalog deployment ID is
not a substitute for a documented stable deployment namespace. Restore and
clone behavior must preserve recovery in the original deployment and prevent
dispatch against another deployment's resources. No client selects this scope.

Bind the key to an existing server-owned request/operation and retain its exact
generation association across subsequent pause/resume/destroy operations.
Extend owning request/operation persistence as necessary; no second execution
ledger, generic idempotency service or client-selected generation. The HTTP
request correlation ID, CMS/Engine request UUID, range UUID, caller key,
launch-intent ID, worker generation, provider task reference, result identity
and RAES receipt ID each keep their existing meaning. A retry of an old action
must never resolve to the range's newest generation or start another action.

Canonical intent binds the validated action and target, actor and workspace
scope, source/purpose/backend admission, effective egress and relevant lease
policy, package/lock digests and producer/contract versions, complete compiled
plan, selected image/artifact/configuration references, and all delivery and
participant-access bindings. Include caller selections only if they affect the
admitted operation; reject unsupported selections rather than accepting fields
that silently do nothing. Trusted ownership stays beside the RAES plan, never
inside a second Shifter-authored plan schema.

Compose `RangeBindings`, `RaesInputBindings`, `operation_input_payload` and
their existing validators. Reuse `shared.operation_envelope.canonical_payload_digest`
after validation. Specify a version for the **intent projection**, distinct
from HTTP major, RAES producer and worker-envelope versions. Normalize defaults
once; reject ambiguous duplicate JSON members, non-finite numbers and invalid
shapes before hashing. Object order is irrelevant; sort only collections whose
existing contract declares them unordered and reject duplicate identities.
Do not globally sort plan arrays. Exclude transient timestamps, generated IDs,
dispatch attempts, provider observations and secret values from equivalence;
retain admitted absolute deadlines separately so replay cannot extend a lease.

Retain the normalized caller intent and the admitted immutable binding together.
An unchanged caller replay recovers the original binding even after package,
registry or default-configuration changes; it must not recompile against today's
inputs. Explicit changed selections, or an internal replay supplying different
compiled/bound intent, conflict before reservation or effects. Reauthorization
checks current authority, not current catalog availability for a new launch.
New launches still pass all current admission checks. If policy now forbids
continuing an admitted operation, expose that restriction through its lifecycle;
never silently substitute new intent or treat a matching hash as authorization.

PostgreSQL uniqueness and transactions must arbitrate concurrent first use,
including when no row exists to lock. A cache lookup or `select_for_update` on
an absent row is insufficient. Reuse CMS's user/workspace reservation locks,
`reauthorize_launch_workspace_locked`, quota correlation, and Engine's generation
locks with a consistent lock order. Same-key contenders converge on one binding;
different-intent contenders receive a bounded conflict. An insertion race must
be handled outside the failed savepoint before reading the winner.

The accepted retry binding, immutable input, generation, durable launch intent,
admission reservations and necessary audit intent need an atomic admission or
an explicitly recoverable state in the existing owning records. Do not leave
an accepted row whose only dispatch obligation lived in an `on_commit` callback.
Keep provider/acquisition work outside long database locks; pin validated
inputs before effects and make staging cleanup accountable. Prove recovery at
each existing CMS/Engine commit gap. Replays must bypass *new* active-range,
quota and warm-claim effects without bypassing authorization or abuse limits.

Document caller-key syntax, byte limit, case/whitespace semantics, missing versus
empty behavior, retention and expiry. A replay retains operation identity;
status is a fresh authorized projection, not a permanently cached launch body.
Never expire an unresolved operation into an apparently unused key. Bounded
retention must preserve a binding/tombstone for the advertised retry window and
all outstanding recovery obligations; later key reuse must be explicit.

## Truthful results, cancellation and teardown

| Fact | Authoritative incumbent and public interpretation |
| --- | --- |
| Admitted | Existing request, immutable input and durable launch intent. Admission is not observed readiness. |
| Dispatch/execution | `ProvisionerLaunchStatus.SUCCEEDED` means dispatched. Provider task state, result progress and observation timestamps determine what is known about execution. |
| Applied result | `OperationResultInbox`, `ResultStep`, Engine applier and `shared.raes.status` own validated generation-specific truth. CMS, sidecars and events are projections. |
| Cancel intent | `request_provision_interrupt`, `InterruptState` and `launch_interrupt` own durable cancellation convergence. Requesting stop, observing task absence and enqueueing destroy are distinct. |
| Cleanup pending/unknown | Incomplete cleanup, unavailable provider/secret/DB evidence, interrupt exhaustion and missing terminal results retain obligations. Timeout, DLQ, FAILED or a missing Job is not proof of absence. |
| Verified terminal cleanup | Successful owning lifecycle plus independent inventory/readback of owned resources, with scope and observation time. A later discovered residual remains actionable and corrects the cleanup projection without rewriting historical results. |

Publish bounded status/results, cancel support and reason codes through the
existing service projections and explicit DRF serializers. Keep execution,
resource status, cancel disposition and cleanup evidence as distinct facts;
do not add cleanup/unknown values to `ResourceStatus` or RAES enums merely to
fit a public response. Extend the owning native contract where necessary,
without inventing another state machine or a raw-provider result DTO. Expose
only authorized residual categories/counts, reasons, freshness and permitted
next actions; resource/credential locators and diagnostics remain protected.

Cancel targets the admitted generation. It does not cancel a newer generation,
guarantee provider abort or give the caller cleanup authority beyond existing
policy. Stale results cannot mutate a newer range; cancelled provision results
cannot restore READY or participant access. Retain late evidence needed to
discover residuals without bypassing fencing or overwriting terminal history.
Once cleanup is owed, actor revocation must not orphan it: the existing trusted
system lifecycle continues within persisted ownership while public access is
reauthorized. Honor archived-workspace and CTF operation-specific policy.

The recovery seam belongs to Engine's immutable operation inputs and the
existing provider realization/destroy adapters. Pin enough non-secret identity
to recover the original provider/project, zone/region, network ownership,
resource names/identifiers, dynamic-secret namespace and credential references,
egress posture, plan/contract and relevant configuration/artifact versions.
Generated names alone, current registry entries and current environment values
are insufficient ownership evidence. Reuse persisted placement and binding
helpers; never reconstruct against a different configuration silently.

New provisioning keeps the exact RAES pin. Old teardown needs a narrowly
versioned, validated recovery projection/read path with an explicit supported
window; no arbitrary old-producer acceptance or new legacy provisioning path.
ADR-024/032/034 hard-cutover/drain rules and ADR-043-R7 retention must be
reconciled in the implementation's ADR evidence. Block incompatible rollout or
retain supported recovery until old obligations are discharged. Never relabel
stored plan bytes, delete evidence to make a drain pass, or require a retired
pack or enabled image mapping merely to destroy an existing range.

Revalidate #1919 through the CTF cancellation entry point, including nested host
and VPN dependencies, already-absent resources and partial cleanup. Keep range,
participant, generation and reservation linkage until terminal cleanup or an
equally durable owned recovery link exists. Distinguish logical admission quota
from physical/event capacity; do not release reusable resource slots while
unresolved resources can still own them. Inventory instances, retained disks,
addresses/forwarding rules, routes, routers/NAT, firewalls, subnets/networks,
dynamic secrets and applicable state/content/access obligations. Shared VPCs,
identity pools and shared credentials are not range-owned deletion targets.
An unavailable or incomplete inventory produces unknown, never an empty success.

## Cross-cutting boundaries to reuse

| Layer and canonical incumbents | Required passage through the boundary |
| --- | --- |
| HTTP/auth: `config/_drf_settings.py`, `config.middleware.CTFAccountBoundaryMiddleware`, `shared.api_tokens.authentication`, `.scopes`, `.permissions`, `shared.api.principals`, Mission Control permissions | Bearer-first failure, live token/owner checks, exact range read/write scopes, session CSRF and participant restrictions apply on first call, replay, lookup and cancel. Never use `request.user` alone for a token actor. |
| Object policy: `cms.services`, `cms/services/_range_workspace.py`, `workspaces.services`, `ctf.services.authorization` | Check current resource owner and bound workspace; original actor identity is not sufficient after rebind, membership removal, archive or revocation. CTF adds event/participant authority. Authorize before disclosing operation existence or conflict details; inaccessible and unknown lookup share opaque not-found behavior. Lists are filtered server-side. |
| Request validation: `mission_control/api/serializers.py`, existing bounded JSON/ref patterns in `shared.schemas` | Explicit fields and action choices; no writable model serializer, caller authority, compiled-plan input, env map, provider selector or execution generation. DRF serializers alone do not reject unknown fields and default JSON parsing loses duplicate members. Supply one bounded parsing/shape rule at ingress, using existing patterns, without importing another domain's schema or duplicating business admission. |
| Admission: `_range_launch_common`, `_range_workspace`, `_range_backend_admission`, `shared.range_instantiation_policy`, `shared.range_lifecycle_capability`, workspace quota and warm-pool services | Preserve launchability, live-fire purpose, backend capability, lease, active-range and quota rules. `RangeLaunchRateThrottle` charges authenticated POSTs before serializers; document replay 429/503 and `Retry-After`, retain read recovery, and prevent a caller-key bypass of fleet limits. Warm claims and cold starts share retry identity; internal `activate` is not a public action. |
| Pack/plan/artifact: `cms.scenarios.pack_validation`, `shared.raes.package_loader`, `.object_source`, `.runtime_target`, `.artifact_binding`, `.content_delivery`, `.participant_access`, `.image_policy`, `cms.raes.dispatch` | Reuse archive/path/size/digest checks, released RAES serialization, realizability and byte-free binding validation. Recheck immutable content before use; no arbitrary fetch paths/URLs, raw pack/credential bytes or duplicate plan schema. Retained cleanup must survive registry retirement. |
| Database/transport: `engine.launch_intents`, `engine.operation_inputs`, `engine/models/_operation_io.py`, `shared.operation_envelope`, `shared.raes.operation_input`, `shared.operation_results`, `shared.operation_result_payloads`, `engine/services/_operation_apply*` | Engine alone applies ownership/generation/version/digest/step-validated results with strict audit and outbox in one transaction. Extend exact-key parsers and rolling compatibility deliberately. Provisioner grants remain immutable-input read, result append and reviewed subnet coordination only; no domain-table or outbox grants. |
| Sidecars/history: `shared.schemas.raes_operation`, `shared.schemas._raes_validation`, `shared.raes.operations`, `shared.raes.projections`, `mission_control/api/raes.py` | Reuse bounded, redacted, authorized history. Sidecar secret-key rejection includes `secret`/`credential`; do not stuff cleanup credential references into sidecars or relax their allowlists. Use the existing protected operation-input/reference boundary. Pruning cannot delete the sole retry or residual evidence. |
| Config/env: `.shifter.yaml`, `shifter/installation/{schema,loader,settings_gcp,render}.py`, `config/_runtime_env.py`, `config/_env_manifest.py`, `config/env-manifest.json`, `engine/ecs/_env.py`, `shifter/engine/provisioner/config/`, `scripts/gcp/render_runtime_env.py` | Keep configuration server-owned and typed. Public retry keys require no env forwarding. Any justified new setting must pass root/runtime validation, generated inventories and renderer/consumer parity; a handwritten environment variable is insufficient. Snapshot only operation-relevant non-secret settings/references, not an entire env map. |
| Host/runtime: `shared.cloud.sensitive_env`, `shared/cloud/kubernetes/_job_manifest.py`, task runners, `shifter/engine/provisioner/main.py`, chart/raw provisioner admission policies | Keep canonical resource/action and request/generation UUID argv. No key, intent JSON, credential, signed URL or env map in process arguments; no shell invocation or command override. Preserve pinned images, dedicated launcher RBAC, restricted pod context, mounts, literal/Secret env allowlists, TLS and network policy. The inspected chart admission grammar does not admit `activate` although Engine does: qualify rendered warm-path admission instead of assuming Python support proves deployability. |
| Secrets/provider: shared cloud adapters, Engine secret services, `shifter/engine/provisioner/gcp_dynamic_secrets.py`, credential helpers, provider config and GCP IAM modules | Retain references/ownership, not expired credential values. Resolve through workload identity and the original permitted namespace; fail closed on unavailable credentials without substitution or broader IAM. No secrets in Helm values, ConfigMaps, public results or evidence artifacts. |
| Errors/audit/observability: `shared.exceptions`, `cms.exceptions`, `shared.api.errors`, `shared.errors`, `shared.log_sanitize`, `shifter/engine/provisioner/log_redact.py`, `shared.audit`, `_operation_apply_effects` | Reuse classified boundary errors and authored sanitized envelopes; no parallel exception hierarchy or `str(exc)`/intent diff/provider payload response. Strict state-changing audit rolls back with application. Correlate bounded deployment/request/operation IDs; omit raw caller keys and bodies from logs, audit and metric labels. Extend existing worker health/metrics with lag, stale/conflict/version rejection, missing terminal results and aged residuals; heartbeat alone is insufficient. |
| Delivery/publication: launch outbox worker, `apply_operation_results`, `RangeEventOutbox`, CMS reconciliation, `config/api_urls.py`, `shared.api.{schema,contract}`, `openapi/v1.json`, `frontend/src/api/{client.ts,schema.d.ts,types.ts}` | Keep launch retry, result apply, notification delivery and reconciliation separate. Events/WebSockets prompt DB-authoritative refresh. Reuse runtime-generated contracts and frontend CSRF/error client; no handwritten DTO copies or browser/cloud orchestration. ADR-040 permits independent operations/compatible optional additions; changed required inputs, status codes, auth, error semantics or closed response unions require its versioning process. |

The next action or configuration/producer revision belongs in the existing
operation-specific projection and declared action/version dispatch seams, with
shared canonicalization, authorization and response mapping. It must not require
another ledger, per-endpoint digest implementation, provider-specific public
schema or amendments to unrelated plan contracts. Worker inputs remain
dependency-light: no Django/RAES producer imports in the standalone provisioner.

## Evidence required of implementation

Use the existing test owners rather than adding a new workflow lane:

- API/service cases: lost response, concurrent identical replay, changed intent
  in every bound component, normalized equivalent inputs, key isolation and
  expiry, invalid bearer with valid session, revoked token/actor, changed
  workspace/defaults, inaccessible/retained operations, cancellation and warm
  claim. Assert one request/generation/quota reservation and no duplicate effect,
  plus sanitized errors and no unauthorized result disclosure.
- Reuse `tests/engine/test_launch_intents.py`, `test_launch_interrupt.py`,
  `tests/engine/services/test_operation_apply*.py`, `test_raes_range.py`,
  `tests/shared/test_operation*`, RAES parser/provisioner parity and retention
  tests. Inject duplicate, conflicting and out-of-order steps, late terminal
  results, superseded generations, cancelled READY and applier/audit rollback.
- Real contention follows `tests/workspaces/test_quota_concurrency_postgres.py`:
  `postgres` plus `django_db(transaction=True)`, independent connections and
  bounded barriers. Cover same-key insert races, different intent, workspace
  revocation/rebind, quota and cancel/result races with committed-state checks.
  Run `make test-platform-postgres`; `make test` excludes PostgreSQL and cannot
  prove these semantics. Preserve the PostgreSQL lane's fail-on-skip guard and
  effective provisioner privilege tests.
- Worker/provider-loss drills kill launcher, provisioner and applier at durable
  boundaries, including after provider mutation but before receipt/result append.
  Include DB/message/secret/provider outages, expired worker leases, partial
  destroy and #1919's real CTF journey. Exercise old plans after producer/config
  changes, image retirement and pack removal. Use existing GCP smoke/provider
  adapters and external inventory; mock-only deletion calls are insufficient.
  Record exact deployed commits/digests, environment, commands, observations,
  residual owner and recovery outcome. No live infrastructure drill is performed
  by this documentation preflight.

Repository enforcement in scope: `AGENTS.md`, `.ground-control.yaml`,
`.gc/plan-rules.md`, ADR-001/019/024/025/029/032/034/039/040/043/046/051/054,
`docs/adr/{index,exceptions}.yaml`, `.importlinter`,
`scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/`, root
`Makefile`, `.pre-commit-config.yaml`, `.github/quality-path-filters.yaml` and
`.github/workflows/_quality.yml`. Preserve ownership routing, real-boundary
testing, API drift/breaking checks, secret hygiene and documentation gates.
Run ADR guard for architecture edits; implementation additionally runs import,
platform/provisioner and published-contract checks, plus stack-native Helm/K8s,
Terraform or actionlint checks whenever those artifacts change. No guard bypass
or scope expansion is justified by adding the public endpoint.

## Explicit non-goals

No generic workflow engine, second ledger, distributed transaction framework,
additional provider, new authorization system or shared-customer control plane.
No RAES producer fork, alternate authored schema, arbitrary historical plan
execution, new service mesh/sensor/model broker, or wholesale release/restore
qualification program. Preserve existing AWS/GCP and CTF behavior where touched;
do not claim unsupported cancellation or warm execution capabilities. Public
operation recovery, truthful retained cleanup and the issue's specified failure
evidence remain in scope; a launch-only endpoint is not sufficient delivery.

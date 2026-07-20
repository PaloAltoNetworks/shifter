# Engine God-Module Decomposition Preflight (#685)

Status: pre-implementation guidance

Date: 2026-07-15

Issue: GitHub #685, "Refactor Django engine service and range model god
modules."

This is a requirement-free maintenance change. The GitHub issue is the shipping
contract. This note is intentionally not an implementation plan.

## Current Baseline And Scope Boundary

The migrated issue describes an older tree. The public `engine.services`
surface is already a package with a stable facade and concern-specific private
modules: `_range`, `_lifecycle`, `_terminal`, `_ngfw`, `_queries`, and ACES
adapters. `create_range` and terminal/NGFW connection lookup are already below
their former monolithic sizes. Preserve that progress; do not recombine the
package or make callers import private modules.

The remaining concentration is primarily:

- `engine.models.Range`: ORM fields plus query helpers, subnet allocation,
  lifecycle predicates, and raw `provisioned_instances` traversal;
- `engine.ecs`: local process launch, provider/config projection, GCP launch
  intent enqueueing, task-runner dispatch, command construction/validation, and
  task-status projection in one provider-named module;
- `engine.handlers`: transport routing, payload interpretation, Engine state
  mutation, audit, and notification-only handling.

This issue may rearrange those responsibilities without changing lifecycle,
wire, persistence, authorization, provider, or user-facing behavior. It must
not absorb the separate CMS/Engine schema work (#268), request-identity work
(#302), provisioner/Django persistence decoupling (#478), or provider substrate
design (ADR-039). ECS/task-runner work must use the existing `shared.cloud`
port; #498 must be recorded as already satisfied by, coordinated with, or
explicitly superseded by the implementation rather than recreated here.

## Architecture Decisions And Guardrails

- Keep `engine.services` as the only cross-layer Engine service facade.
  `cms`, `mission_control`, `config`, and other domains must continue importing
  public names from that package, never `engine.models`, private service
  modules, or a new repository object. Existing public names, call signatures,
  return shapes, exception behavior, and supported patch-at-source seams remain
  compatibility contracts during migration.
- Keep mutation orchestration in Engine services. A service owns validation,
  row selection/locking, status transition, dispatch, rollback/revert behavior,
  task-reference persistence, and idempotency. Pure helpers may classify a
  status or project already-loaded data, but they must not grow hidden ORM,
  settings, secret-store, network, logging, or audit side effects.
- Keep the model persistence-focused. Field declarations, relationships,
  database constraints, `__str__`, and genuinely ORM-adjacent query behavior
  may remain. `allocate_subnet_index` is persistence/concurrency behavior, not a
  pure domain policy: whether retained as an ORM helper or moved behind an
  Engine persistence helper, its PostgreSQL transaction and table-lock
  semantics must remain intact. Pure lifecycle/status classification must use
  `shared.enums.ResourceStatus` and its canonical groupings rather than a
  second state vocabulary. Raw `provisioned_instances` traversal belongs with
  the existing query/connection projection helpers, not with a new model-owned
  schema.
- Treat `range_config` and `provisioned_instances` as different concepts.
  `range_config` is a versioned persisted RangeSpec artifact and must continue
  through `shared.schemas.persistence` and `shared.range_cells` validation.
  `provisioned_instances` is provisioner-owned realized state consumed through
  `engine.services._common`, `_queries`, and `_terminal`. Do not pretend it is a
  RangeSpec, revalidate it with the DSL schema, or introduce another public
  instance/topology DTO. Defensive projection must continue to tolerate the
  currently supported AWS/GCP/GDC legacy keys while returning only the bounded
  values each caller needs.
- Keep connection lookup separate from lifecycle mutation. Resolution must be
  user-scoped and ready-state-gated before any secret fetch. Range lookup must
  preserve the portable iteration used by `resolve_active_for_instance` rather
  than adding provider-specific JSON containment queries. NGFW lookup must keep
  request ownership and `role=NGFW` checks. Secret resolution stays in
  `engine.secrets` over `shared.cloud.get_secrets_store`; SSH transport stays in
  `engine.ssh`; Guacamole URL/token construction stays in `mission_control`.
- Rename internals by responsibility, not by current provider. The stable
  service dispatch seam represents provisioner task delivery, while
  `shared.cloud.types.TaskRunner` and `get_task_runner()` own AWS ECS versus GCP
  Job selection. Do not add an `ECSRunner`, another task protocol, or provider
  branches to lifecycle services. Compatibility wrappers in `engine.ecs` may
  remain while callers and tests migrate.
- Separate event envelope parsing/routing, runtime payload validation, state
  application, and audit without changing acknowledgement semantics.
  `shared.messages.envelope.parse_sns_message` remains envelope-only;
  `shared.messages.events` supplies constants; `shared.messages.payloads`
  supplies static types; `ResourceStatus` supplies runtime status vocabulary.
  A `TypedDict` or `cast()` is not validation. Permanent malformed,
  unauthorized, unknown, or stale messages may log and return deliberately;
  transient DB/audit/broker failures must raise so ADR-025 retry/DLQ behavior
  engages.
- Preserve transaction boundaries, not merely final values. Do not hold a row
  lock across a cloud call. Pause/resume must keep `select_for_update()`, commit
  the in-progress state, dispatch outside the transaction, and preserve current
  revert behavior. Creation must keep interpretation and Range/Subnet linking
  atomic, request-id idempotency intact, and dispatch failure visible. Destroy,
  cancel, reassignment, launch generations, outbox records, and task ARN fields
  must retain their existing operation-specific semantics.
- This is a structural refactor, not a public API redesign. Return existing
  shared schemas (`RequestSpec`, `RangeSpec`, `RangeRef`,
  `LinkedRangeContext`) where they already apply. Existing internal dict
  projections remain internal compatibility shapes until a separately scoped
  contract change replaces them end to end.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Cross-domain entrypoint | `engine.services.__init__`, `engine.__init__`, ADR-001, `.importlinter` | Preserve facade imports and Engine ownership; no private-module or model imports across domains. |
| Lifecycle vocabulary/policy | `shared.enums.ResourceStatus`, `ACTIVE_STATUSES`, `TERMINAL_STATUSES`, `CANCELLABLE_STATUSES`; `engine.services._lifecycle`; `engine.launch_intents` | Do not create model-local enums, string sets, or a second transition engine. Keep generation authorization and idempotency. |
| Request/range contracts | `shared.schemas.RequestSpec`, `RangeSpec`, `RangeRef`, `RangeContext`, `LinkedRangeContext` | Reuse at existing boundaries; no duplicate DTO family. |
| Persisted scenario validation | `shared.schemas.persistence`, `shared.range_cells.build_scenario_artifact` / `validate_scenario_artifact` | Preserve discriminator, version, normalization, and digest rules for `range_config`. |
| Realized-state projection | `engine.services._common`, `_queries`, `_terminal` | Centralize supported provider/legacy key fallback here; return bounded projections, not raw state to upper layers. |
| Task delivery | `shared.cloud.types.TaskRunner`, `shared.cloud.get_task_runner`, AWS/GCP task-runner adapters, `PROVISIONER_CONTAINER_NAME` | Keep provider selection and SDK/Kubernetes behavior behind the existing port. |
| Command trust boundary | `engine.launch_intents.validate_provisioner_command`, `command_from_payload`, generation authorization; `engine.ecs` public compatibility functions | Commands stay closed, structured, request/generation scoped, and secret-free. |
| Runtime configuration | `config._runtime_env.resolve_cloud_provider`, `config._cloud`, `config.env-manifest.json`, `installation.runtime_inventory`, backend bundle registry | Do not add handler-local defaults or unregistered env names. Keep forwarded-key inventories in parity. |
| Sensitive task env | `shared.cloud.sensitive_env`, GCP task-runner Secret projection, provisioner Job admission policies | Secret material must use `secretKeyRef`; pointer IDs may remain non-secret. Never serialize credentials into Job specs or argv. |
| Secrets/terminal security | `engine.secrets`, `shared.cloud.get_secrets_store`, `engine.ssh`, `mission_control.guacamole`, terminal executor/admission gate | Keep ownership/readiness before fetch, bounded cache behavior, secret-store abstraction, and bounded blocking execution. |
| Durable events | ADR-025, `RangeEventOutbox`, `drain_range_event_outbox`, `reconcile_range_events`, `shared.management.commands.run_worker` | Preserve DB authority, retry/DLQ, idempotency, and raise-on-transient-failure behavior. |
| Event contracts | `shared.messages.envelope`, `shared.messages.events`, `shared.messages.payloads` | Do not duplicate parsing, constants, or message schemas; add shared runtime validation only if equivalent consumers need it. |
| Audit | `shared.audit` facade backed by `risk_register.services.audit_log_system_event` | Keep state changes and system-event audit coupled at the application boundary; no new audit model or direct Risk Register persistence. |
| Errors | `EngineError`, `shared.cloud.exceptions.CloudTaskError`, `engine.secrets.SecretsError`, CMS `CMSError`, `shared.api.errors`, `shared.errors.classify_user_message` | Preserve responsibility-specific exception translation. Do not add a parallel hierarchy or expose raw exception text. |
| Logging | module loggers, `shared.log_sanitize.safe_log_*`, configured ECS formatter | Keep stable correlation fields and sanitize user/provider identifiers, payload-derived text, hosts, and secret references. Never log credentials or raw payloads. |
| Tests/complexity | ADR-019, ADR-012, existing `tests/engine/services/**`, `tests/engine/ecs/**`, handler and integration suites | Drive real ORM/services; mock only provider/transport boundaries. No new `C901` exemption or oversized catch-all test module. |

## Cross-Cutting Layers The Design Must Pass

### Security And Validation

- **HTTP/auth entry:** Mission Control terminal and Guacamole endpoints retain
  `login_required`/authenticated request handling and pass the authenticated
  Django user into the Engine facade. CMS lifecycle services retain caller
  validation, ownership masking/checks, source-specific active-range admission,
  and audit attribution. Engine service extraction must not make a public
  function callable by identifier alone where it currently relies on a user or
  an already-authorized CMS call.
- **Object authorization:** range connections resolve only rows owned by the
  supplied user; NGFW connections additionally require the NGFW role and owning
  request. Reassignment must continue changing CMS RangeInstance/Request and
  Engine Range/Request ownership transactionally so old access is revoked and
  new access is granted consistently.
- **Schema/shape gates:** hydrated intent enters as validated shared
  `RequestSpec`/`RangeSpec`; persisted `range_config` stays wrapped/versioned
  and digest-bound where required; inbound events pass envelope parsing,
  event-type routing, explicit required-field/type/status validation, ownership,
  and stale-generation/state policy before mutation. `provisioned_instances`
  remains defensively projected as untrusted persisted realization data.
- **Secret handling:** service lookup must authorize and require READY before
  `engine.secrets` fetches an SSH key or RDP password. Secret values must never
  enter RangeSpec, event payloads, task intents, task references, audit state,
  logs, API errors, or websocket payloads. Preserve TTL/max-entry cache bounds
  and provider secret-store errors; do not cache credentials in new DTOs.
- **Configuration gates:** `CLOUD_PROVIDER` remains composition-root validated
  against the installation backend registry and required capabilities.
  `ENGINE_TASK_*`, local-provisioner settings, and all forwarded provisioner
  variables remain declared through `config._cloud`, the generated env manifest,
  installation runtime inventory, and deployment surfaces. Extraction alone
  needs no new configuration.
- **OS/runtime exposure:** provisioner commands remain argument arrays whose
  closed shapes are validated by `engine.launch_intents`; no shell strings,
  `shell=True`, config blobs, event bodies, or credentials in process argv.
  Local execution keeps a fixed first-party `main.py` and explicit `cwd`.
  GCP Jobs must continue satisfying the image, command, env-name, security
  context, and secret projection enforced by the checked-in and Helm
  `ValidatingAdmissionPolicy` resources.
- **Error envelopes:** internal `CloudTaskError`, `SecretsError`, database
  exceptions, provider responses, and payload-derived `error_message` values
  stay in bounded/sanitized operator logs. Mission Control/DRF continue using
  authored error labels through `classify_user_message`, `shared.errors`, and
  `shared.api.errors`; do not return `str(exc)` or provisioner error text.

### Persistence, Reliability, And Observability

- PostgreSQL remains authoritative. Keep request-id correlation, the legacy
  Range table name, JSON-field compatibility, operation-specific task refs,
  generation fields, timestamp update behavior, and existing migrations. A
  module split does not justify schema churn or a data migration.
- Preserve concurrency controls: atomic interpretation/linking, subnet
  allocation serialization, `select_for_update()` for lifecycle/generation
  decisions, database uniqueness constraints, idempotent request lookup, and
  rollback/revert on rejected dispatch. Do not replace these with in-process
  locks or check-then-write helpers.
- Preserve ADR-025 event behavior: provisioner state and outbox intent commit
  atomically; handler transient failures propagate; notification-only events
  do not become state authorities; the reconciler continues through the public
  Engine status seam.
- Retain stable logger namespaces or explicitly account for changed names in
  dashboards/queries. Log operation, safe correlation ID, old/new status, and
  task reference only where currently safe. Use `safe_log_value` or a
  fingerprint for payload/user-controlled values and internal hosts; audit
  security-relevant lifecycle changes through the existing audit port.

## Extensibility Seam

The required seam is an Engine-owned **provisioner operation descriptor** whose
variation is limited to existing facts: resource/command, correlation identity
(prefer request UUID; legacy range/user IDs remain compatibility-only), optional
operation generation/task identity, and the selected local-versus-remote
delivery path. It must compile to the existing closed, secret-free command
array and then use the existing `TaskRunner` port.

The next reasonable variation is another operation resource (such as the
existing ACES range) or another registered backend. Adding it should extend the
closed command validator/operation mapping and backend bundle, not copy a new
`start_*_ecs_task` pipeline or add provider conditionals to lifecycle services.
Keep substrate success distinct from task submission: a task reference proves
delivery acceptance, not that provisioning reached its postcondition.

For model/query decomposition, the extension seam is the existing bounded
projection over persisted realized instance state. A future provider may add
provider metadata behind `_common`'s normalization; it must not require new
provider fields on `Range`, new connection logic in views, or a public raw-state
DTO.

## Whole-Repo Surfaces In Scope

The implementation may need to touch the Engine modules and their tests, but
these surrounding artifacts constrain the design:

- `shifter/shifter_platform/engine/{models.py,ecs.py,handlers.py,launch_intents.py,secrets.py,ssh.py}`
- `shifter/shifter_platform/engine/services/**` and the public
  `engine/{services,__init__}.py` facades
- `shifter/shifter_platform/shared/{enums.py,schemas/**,messages/**,cloud/**,audit/**,errors.py,api/errors.py,log_sanitize.py}`
- `shifter/shifter_platform/cms/services/**`, CMS handlers/reconciler, and CTF
  bridges as behavior-preservation callers
- `shifter/shifter_platform/mission_control/views/_guacamole_builders.py`,
  terminal consumers/executor, and Guacamole helpers as connection callers
- `shifter/shifter_platform/config/{_runtime_env.py,_cloud.py,env-manifest.json}`
  and `shifter/installation/{registry.py,runtime_inventory.py}` if task config
  moves (it should not change for a structural split)
- GCP Job admission policies and Helm equivalents if the task command/env shape
  changes; AWS task definitions if the container/override contract changes
- `.importlinter`, `shifter/shifter_platform/pyproject.toml`, ADR-001, ADR-012,
  ADR-019, ADR-025, ADR-039, and `scripts/adr_guard/adr_guard.py`
- behavior suites under `tests/engine/{services,ecs}`, engine handler/model and
  launch-intent tests, CMS lifecycle/reconciliation tests, Mission Control
  terminal/Guacamole tests, and integration Engine lifecycle/consumer tests

## Gotchas And Anti-Patterns

- Do not measure success only by file length. A new `RangeService` or
  `EngineManager` class containing the same mixed responsibilities is the same
  god object with a different filename.
- Do not make every extracted helper a public abstraction. Keep cohesive
  implementation helpers private; preserve the small facade.
- Do not add generic repository/unit-of-work/controller layers around Django
  ORM. Existing services plus explicit atomic/query helpers are the repository
  convention here.
- Do not duplicate status sets, state machines, Range/Request/Instance schemas,
  event types, envelope parsers, provider metadata schemas, validation helpers,
  exception hierarchies, audit writers, or log sanitizers.
- Do not conflate CMS `RangeInstance`, Engine `Range`, `RangeSpec`, `RangeRef`,
  RangeContext projections, realized `provisioned_instances`, and ADR-039
  substrate results. They have different owners and trust/persistence roles.
- Do not use `engine.models.Range.Status` as a new cross-domain vocabulary;
  shared `ResourceStatus` remains canonical. Conversely, do not force
  provider-realized connection data into the scenario DSL.
- Do not move ORM access into pure policy/projection helpers, or settings/secret
  reads into DTO constructors. Dependency direction must stay visible.
- Do not introduce a task runner for each operation/provider, call boto3 or the
  Kubernetes client from Engine services, or treat `task_arn` as ECS-only; GCP
  returns a provider-neutral task reference through the same fields.
- Do not bypass `validate_provisioner_command`, generation authorization, or
  GCP launch intents when extracting dispatch. Do not silently fall through
  from configured GCP queueing to synchronous launch.
- Do not log joined command arrays if future arguments can contain sensitive or
  unbounded values. The current closed command is identifier-only; preserve
  that invariant and prefer structured operation/ID fields.
- Do not fetch secrets before ownership/readiness checks, return secret-bearing
  connection DTOs beyond the existing Mission Control handoff, or add secrets
  to events/audit/task env literals.
- Do not replace runtime event validation with casts. In particular, reject an
  unknown `new_status` before assigning it to the model; Django `choices` are
  not enforced by `save()`.
- Do not swallow transient handler/audit/DB failures. A normal return causes the
  worker to acknowledge the message.
- Do not hold database locks during cloud calls, lose `updated_at` in partial
  saves, collapse provision and teardown task references, or weaken
  revert-on-dispatch-failure behavior.
- Do not change historical mock targets without a compatibility window. New
  tests should patch the external provider/transport boundary, not entrench new
  first-party topology patches.
- Do not add a C901 exemption, broad Ruff/mypy ignore, ADR exception, or CI
  weakening to complete the split.

## Non-Goals

- No implementation in this preflight note.
- No new public API, UI, auth mechanism, permission model, broker, worker,
  workflow engine, event-sourced architecture, ORM repository framework, or
  global exception hierarchy.
- No Range/CMS model merger, schema migration, status vocabulary change,
  identifier migration, or removal of legacy persisted fields in this issue.
- No redesign of scenario hydration, ACES semantics, provisioner database
  ownership, range substrate adapters, cloud backend selection, networking,
  terminal streaming, Guacamole token construction, or credential rotation.
- No provider-specific feature work and no new environment variables. Any
  unavoidable command/config contract change is cross-cutting installation and
  deployment work, not a local `engine.ecs` edit.
- No deletion of compatibility entrypoints until all first-party callers and
  tests have migrated and the deprecation is separately approved.

## Validation Expectations

The eventual implementation must run focused Engine service/model/ECS/handler
tests and affected CMS/Mission Control integration tests. Because it changes
`shifter_platform` architecture, it must also run:

```bash
(cd shifter/shifter_platform && uv run ruff check .)
(cd shifter/shifter_platform && uv run ruff format --check .)
(cd shifter/shifter_platform && uv run mypy .)
(cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter)
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Run commands from repository root unless the command itself changes directory.
If the implementation changes Kubernetes manifests, Terraform, or workflows,
the corresponding repo-required `kube-linter`/`kubeconform`, `tflint`, or
`actionlint` checks also apply.

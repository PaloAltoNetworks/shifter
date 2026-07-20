# Core Runtime Decomposition Preflight (#561)

**Status:** architecture guidance
**Date:** 2026-07-19
**Contract:** GitHub issue #561 (requirement-free maintenance)

## Purpose and current baseline

This note constrains the remaining implementation of issue #561. It is not an
implementation plan.

The original evidence no longer describes the tree literally:

- `cms/services.py` is now the `cms.services` facade plus private service
  modules.
- `ctf/views.py` is now the `ctf.views` facade plus HTML and legacy JSON view
  modules.
- `provisioner/main.py` is a small CLI entry point.
- `AWSExecutor` delegates groups of operations to private mixins.

Those splits are useful, but file count alone does not satisfy the issue. Broad
exception conversion remains distributed across the extracted modules, some
modules are kept just below the repository's size limit, and the provisioner
still conflates guest command execution with AWS control-plane actions. The
remaining work must improve responsibility and type boundaries without changing
public behavior accidentally.

This note supplements, and does not replace, the Engine-specific guidance in
`engine-god-module-decomposition-preflight-685.md` and the repository-wide
assessment in `rev1/quality-and-testing.md`.

## Architecture decisions and guardrails

1. **Keep stable public facades.** Cross-domain callers continue to import
   `cms.services`, `ctf.services`, `engine.services`, or the documented public
   presentation surface. Private `_*.py` modules are implementation details and
   must not become new cross-layer imports. `.importlinter`,
   `scripts/check_layer_imports/layer_imports.yaml`, ADR-001, and ADR-019 remain
   authoritative.
2. **Split by responsibility and change axis, not by line count.** Presentation,
   boundary parsing, application orchestration, domain validation, persistence,
   provider I/O, and rendering belong at their existing layers. A mixin or
   private module that still shares all mutable state and dispatch knowledge is
   not a meaningful boundary.
3. **Use the existing quantitative guardrails.** Sonar `python:S104` supplies the
   500-line production-module ceiling and ADR-012 supplies the Ruff C901
   complexity ceiling. Issue #561 must not add another numeric policy. Passing
   at 499 lines is not evidence that a module has one responsibility.
4. **Preserve contracts while moving ownership.** URL names, HTTP status and
   payload shapes, CLI argument grammar, task payloads, state transitions,
   transaction boundaries, audit events, logger names, and retry/idempotency
   behavior remain stable unless a separately reviewed behavior change says
   otherwise.
5. **Translate errors once, at a deliberate boundary.** Internal helpers should
   allow unexpected defects to propagate. A boundary may translate named,
   expected failures into its existing domain or transport contract. It must not
   turn programming errors into normal-looking failure values.
6. **Do not introduce parallel infrastructure.** Existing schemas, serializers,
   exception families, service facades, cloud protocols, audit ports, and
   transaction patterns remain canonical. This refactor does not justify a
   repository/unit-of-work layer, a generic workflow engine, or a new global
   error hierarchy.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Constraint on the refactor |
| --- | --- | --- |
| Cross-layer access | Public `cms.services`, `ctf.services`, and `engine.services` facades; `.importlinter`; layer-import manifest | Keep private split modules private; place genuinely shared contracts under `shared`. |
| CMS request and range contracts | `shared.schemas` (`RequestSpec`, `RangeSpec`, `RangeContext`, credential and persistence shapes) | Move existing contracts; do not clone them as service-local DTOs. |
| CMS boundary and domain validation | DRF serializers and permissions; `cms.scenarios.schema`; asset validators; range-create and backend-admission validators; model constraints | Boundary shape, domain policy, and database integrity remain separate checks. Do not repeat them in every extracted function. |
| CMS persistence | Django ORM, `transaction.atomic()`, `select_for_update()`, constraints, and service-owned state transitions | Preserve atomicity and locking; do not hide ORM semantics behind a generic repository. |
| CTF domain failures | `ctf.exceptions` | Reuse the domain hierarchy. A presentation adapter is not a second domain hierarchy. |
| CTF HTTP boundaries | Forms and `ctf.views` for existing HTML/legacy JSON routes; `ctf.api` DRF serializers, permissions, and shared API errors for the canonical API | Preserve existing legacy envelopes, but do not create a third presentation stack or move business rules into views. |
| Provisioner command trust boundary | `engine.launch_intents`, `shared.cloud.types.TaskRunner`, and the AWS/GCP/local task-runner adapters | Keep commands closed, versioned, validated, and secret-free. Authorization and durable intent state stay in Engine. |
| Provisioner configuration | `config._runtime_env`, `config._env_manifest`, installation registry/runtime inventory, and provisioner `config.resolve_cloud_provider()` | Continue to fail closed. A structural split must not create alternate environment binding or provider selection. |
| Provisioner persistence | `provisioner_db*`, explicit status transitions, and `events.py` transactional outbox | Preserve database/outbox atomicity, request correlation, generations, and idempotency. Do not swallow enqueue failure. |
| Cloud capabilities and failures | Provisioner `cloud.types`, `cloud.exceptions`, and platform `shared.cloud.types`/`shared.cloud.exceptions` | Reuse an existing capability and exception family where it already models the operation; do not create an AWS-only duplicate contract. |
| Execution outcomes | `executors.base.CommandResult` and executor exceptions | `CommandResult` is an internal execution outcome, not an HTTP envelope and not a sink for arbitrary exceptions. |
| Audit and logging | `shared.audit`, `config.logging.ECSFormatter`, platform `shared.log_sanitize`, and dependency-light provisioner `log_redact` | Keep request IDs and stable logger identities; sanitize at the established boundary; never duplicate audit degradation handling in callers. |
| Tests | ADR-019 boundary-mock policy, import-contract tests, service/ORM tests, provisioner CLI/executor/orchestrator tests | Test behavior and real first-party collaboration; only external systems are mock boundaries. The boundary-mock baseline may shrink, not grow. |

`cms.exceptions.CMSError` is a compatibility import of the existing shared error;
it is not permission to grow a second CMS exception hierarchy. Likewise, new
non-DSL shared contracts belong natively under `shared` rather than extending
the legacy `cyberscript` dependency.

## Responsibility boundaries

### CMS

The `cms.services` facade is the application boundary. Extracted service modules
may coordinate domain validation, ORM state changes, Engine service calls, and
audit emission for one use case. They must not absorb DRF serialization,
response construction, cloud SDK calls, or presentation-specific error text.

Validation remains layered:

1. serializers/forms parse and shape untrusted input;
2. service/domain validators enforce business and admission policy;
3. model constraints, locks, and transactions protect durable invariants; and
4. provider adapters validate and translate external responses.

These checks are complementary. Extraction must call the incumbent layer, not
copy its rules into a new helper.

### CTF

`ctf.views` is a compatibility facade for HTML and existing legacy JSON routes;
`ctf.api` is the canonical DRF API surface; `ctf.services` owns reusable use
cases. A refactor must reduce, rather than deepen, canonical API imports from
private legacy view helpers. Shared business behavior moves behind a service
boundary, while route-specific parsing and response adaptation stay in their
presentation boundary.

Authorization always includes both:

- the coarse session/API-token role and exact scope check; and
- the object-level event ownership or event-scoped active-participant check.

Moving a view must not bypass either gate. Serializer or form success does not
imply authorization or domain validity.

### Provisioner and AWS operations

The CLI entry point remains composition and dispatch, not a re-export or patch
hub. Durable authorization, replay protection, and operation-generation checks
remain in `engine.launch_intents`; the provisioner consumes only the validated,
identifier-only command.

The existing `executors.base.Executor` models guest command execution.
`AWSExecutor.run_command(service, method, **kwargs)` models a different concept:
AWS control-plane actions. The implementation must not pretend those protocols
are interchangeable. The narrow seam needed by `OpsOrchestrator` is an
`execute_action(action, context) -> CommandResult` structural contract, with an
explicit implementation selected through the existing provider/configuration
composition. Remove capability guessing such as `Any` plus `hasattr()` fallbacks;
do not turn the seam into a new workflow framework or inheritance tree.

Where `cloud.types` already models an AWS capability, reuse it. Where the
existing action plans are the contract, preserve their action names and context
keys while making the consumer type explicit. A future provider should be able
to implement the narrow action contract without editing the orchestrator's
business flow.

## Exception and recovery policy

| Boundary | Permitted handling | Required result |
| --- | --- | --- |
| Pure/domain/validation helper | Catch only a named exception that adds domain meaning | Raise the existing typed domain error; unexpected failures propagate. |
| ORM or persistence service | Catch expected constraint/lookup/driver failures when the service owns the recovery policy | Preserve transaction rollback and translate once; never report a partial state as success. |
| Cloud/provider adapter | Catch the named SDK/transport failures it can classify, including `ClientError`, `BotoCoreError`, or `WaiterError` where applicable | Return the established bounded outcome or raise the existing cloud/executor error with a safe message. Programming errors propagate. |
| Orchestrator | Catch only to perform a documented retry, compensation, or terminal-state transition | Preserve the primary exception, idempotency key, and outbox/state consistency. Do not catch merely to log and rethrow. |
| Process/worker/HTTP boundary | A broad catch is allowed only as the final containment point | Log sanitized server detail with correlation, expose a fixed safe envelope, and retain non-zero exit/retry semantics. |
| Best-effort cleanup/telemetry | Broad catch only when failure must not replace an already-active primary failure | State the best-effort policy, sanitize the log, and keep the primary failure. `shared.audit` already owns audit degradation behavior. |

Raw `str(exc)`, provider response bodies, tracebacks, SQL text, request bodies,
or credentials must not enter `CommandResult.stderr`, HTTP payloads, persisted
status/error fields, audit details, or routine logs. `CommandResult` failures
need bounded, authored text suitable for their actual consumers. Full diagnostic
context belongs in sanitized server-side logs. Avoid double logging across a
helper, service, and boundary.

## Cross-cutting security and runtime gates

The intended design crosses all of the following layers:

1. **Authentication and authorization.** CMS uses the existing session/API-token
   actor resolution, exact API scopes, and authoring policy. CTF uses the
   existing session/token roles and scopes plus event ownership or active,
   event-scoped participant eligibility. Extraction preserves decorator and DRF
   permission ordering and cannot move policy behind a mutation.
2. **Untrusted-input shape.** DRF serializers, Django forms, legacy CTF JSON/UUID
   parsers, shared/Pydantic schemas, service validators, and model constraints
   retain their present roles. No internal function accepts a less-validated
   shape merely because it moved modules.
3. **Import and contract validation.** `.importlinter`, the layer-import checker,
   ADR-001, and ADR guard require public facade access and neutral shared
   contracts. Private-module imports must not leak across domains.
4. **Configuration shape.** Runtime environment resolution and cloud-provider
   selection continue through `config._runtime_env`, `config._env_manifest`, the
   installation registry/runtime inventory, and provisioner configuration. No
   new environment variable is required for decomposition. If a later behavior
   change adds one, every manifest, Terraform/Kubernetes projection, task
   definition, and validator must change together.
5. **Secret handling.** Encrypted credential fields and
   `FIELD_ENCRYPTION_KEY`, the existing `SecretsStore` boundary,
   `shared.cloud.sensitive_env`, AWS Secrets Manager injection, and Kubernetes
   `secretKeyRef` remain authoritative. Secrets, signed URLs, credentials, and
   provider payloads do not cross DTO, argv, log, audit, or error surfaces.
6. **OS and task exposure.** `engine.launch_intents` continues to accept only a
   closed `list[str]` grammar containing opaque identifiers. TaskRunner adapters
   use argv arrays, not shell strings. Container non-root identity, root-owned
   application code, GCP read-only-root/drop-capability settings, and bounded
   writable workspaces remain unchanged. Command logging is safe only while the
   grammar stays secret-free.
7. **Error envelopes.** Canonical DRF routes use
   `shared.api.errors.api_exception_handler`; legacy CTF routes retain their
   existing flat compatibility envelope. Both expose fixed safe messages and
   correlation IDs where supported. Internal executor outcomes never become a
   third public envelope.
8. **Persistence and side effects.** Django transactions/locks/constraints,
   durable launch intents and generations, provisioner database transitions,
   transactional outbox writes, and audit policy remain on their current side of
   the boundary. A refactor cannot move external I/O inside or outside a
   transaction without explicit review of failure and retry behavior.
9. **Observability.** ECS formatting, request/operation IDs, stable logger names,
   established sanitizers, and `shared.audit` remain the one observability path.
   Logs and audit details identify the operation and safe resource identifiers,
   not user/provider payloads.

## Extensibility seams

The next reasonable variation is a new provisioner action or provider. Resource
and operation names are currently represented both in the Engine launch-intent
grammar and CLI dispatch, and the accepted sets can drift. The seam is one
closed, dependency-light resource/operation descriptor consumed by validation,
parser construction, and dispatch. Authorization, persistence, and generation
checks remain in `engine.launch_intents`; only the pure grammar may be shared.
A new operation should be registered once rather than copied into several maps.

In particular, the current `aces-range` operation set in launch-intent
validation is not identical to the CLI's dispatch set. The refactor must not
silently bless or remove an operation while consolidating the grammar; existing
behavior needs a contract test and any behavior change needs separate review.

For CMS and CTF, the extensibility seam is the existing service facade plus an
existing serializer/schema and domain validator. A new transport should call the
same use case rather than duplicate workflow logic. A new cloud implementation
should satisfy an existing cloud capability or the narrow ops-action protocol,
not add provider checks throughout plans and orchestrators.

## Gotchas and anti-patterns

- Treating a package of mutually stateful mixins as decomposition while one
  facade still owns every responsibility.
- Moving code until every file is 499 lines without reducing coupling or
  complexity.
- Adding `Any`, dynamic attribute checks, service/method strings, or generic
  dictionaries where a small existing protocol/schema already exists.
- Conflating guest execution, cloud control-plane operations, task launch, and
  HTTP error envelopes under one `Executor` or `CommandResult` concept.
- Conflating CMS request/range specifications, ORM range instances, Engine
  runtime state, and provider realization state.
- Conflating CTF's legacy JSON compatibility surface with the canonical DRF API,
  or creating a third response/permission stack.
- Catching `Exception` in every extracted module, returning raw exception text,
  logging and rethrowing at several layers, or turning defects into successful
  process exits and retry suppression.
- Duplicating serializers, Pydantic models, validation rules, exception classes,
  state enums, audit degradation, retry loops, or provider dispatch tables.
- Adding a repository/unit-of-work abstraction over the Django ORM or raw
  provisioner persistence solely to make files smaller.
- Patching private first-party module topology in new tests. Preserve behavior
  through the public facade and mock only process, cloud, network, and other
  external boundaries.
- Changing transaction/lock scope, outbox atomicity, logger identity, API/CLI
  shapes, or secret placement as an incidental consequence of moving code.

## Non-goals and implementation boundaries

- No new user-facing API, CLI operation, provider feature, state transition, IAM
  permission, database schema, or environment variable.
- No wire-format migration of legacy CTF routes and no repository-wide rewrite
  of all views or services.
- No replacement of Django ORM, raw provisioner persistence, TaskRunner,
  transactional outbox, or the current audit/logging infrastructure.
- No generic dependency-injection container, workflow engine, base-service
  hierarchy, global result type, or universal exception hierarchy.
- No unbounded cleanup of every large runtime file under issue #561. Work stays
  with the originally named surfaces and directly coupled responsibility or
  exception boundaries; other modules require their own scoped contract.
- No new size or complexity threshold. Existing Sonar, Ruff, import, and ADR
  enforcement is the guardrail.

The refactor is complete only when the public behavior and cross-cutting gates
above remain covered, responsibility ownership is clearer, broad catches remain
only at documented containment/recovery boundaries, and unexpected defects are
no longer converted into routine success-shaped outcomes.

# Orchestrator / Plan / Executor Boundary Preflight (#308)

Status: pre-implementation guidance

Date: 2026-09-03

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/308>

This is a requirement-free run. The GitHub issue title and body are the
shipping contract.

## Decision

Do not create a universal executor or a heterogeneous step language. The two
current paths have different semantics and must expose different, structural
ports:

- guest setup is command execution. Its port owns `run_command`, readiness,
  reboot, a target, a shell/document family, command streams, and transport
  failures;
- provider operations are allowlisted actions. Their port owns
  `execute_action(action, context)` and rejects unknown actions or missing
  parameters before provider mutation.

`SetupOrchestrator` must depend on the command-execution port and
`OpsOrchestrator` must depend on the action-execution port. `executor: Any`,
`hasattr` dispatch, and the action-shaped `run_command(target, action, params)`
fallback must disappear. `AWSExecutor.run_command(service, method, **kwargs)`
is a third, incompatible API-call surface and must not be presented as an
implementation of the guest command port.

Composition belongs at the provisioner workflow/composition root. A flow that
needs AWS mutation followed by SSH/SSM guest setup receives the two typed
collaborators and invokes the appropriate orchestrator for each phase. A plan
does not select a concrete executor class, provider, credential source, or
transport. Do not route by class name, `hasattr`, arbitrary import path, or a
request-supplied executor/action name.

This is deliberately narrower than ADR-039. Range-wide provision, destroy,
pause, and resume are substrate-adapter operations with convergence,
idempotency, ownership, and conformance obligations. They must not be remodeled
as a generic sequence of AWS/SSH steps. The legacy AWS operation plans may be
narrowed while they remain, but new provider lifecycle behavior belongs behind
the ADR-039 range-substrate seam.

## Contract Ownership

The implementation must converge the current local contracts rather than add
parallel ones:

- `executors.base.Executor` is the existing guest command protocol. Give it a
  command-specific name and update the provisioner call sites atomically; do
  not leave the ambiguous name as the advertised cross-executor contract.
- The action port must match the existing allowlisted
  `AWSExecutor.execute_action(action, context)` surface. The allowlist and its
  required parameter set have one owner. The repeated `params` lists on every
  operation step are currently unused by `OpsOrchestrator` and duplicate the
  executor's validation; remove the duplicate source rather than trying to
  synchronize both.
- There must be one orchestrator `StepResult`. The definitions in
  `orchestrators.base` and `orchestrators._setup_types` currently have the same
  fields but are different Python types. Preserve one and import/re-export it
  from the compatibility surface needed by existing callers.
- `CommandResult` remains the command transport result used by setup execution.
  Do not turn `stdout`, `stderr`, and `exit_code` into the public or persisted
  schema for cloud lifecycle. Provider responses are internal adapter data;
  durable lifecycle results continue through `shared.operation_results`.
- `SetupStep` / `SetupPlan` remain the script-template contract. Operation
  actions must not gain script, document, reboot, PAN-OS polling, or stdin
  fields. Conversely, setup steps must not acquire provider action names.
- The broad `orchestrators.base.Orchestrator` protocol (`Any` plan/result and
  `**kwargs`) does not prove substitutability. Do not use it to hide the two
  contracts; specialize it meaningfully or remove it if no production consumer
  needs it.

The current `OpsStep` protocol says `params: dict`, while all concrete operation
steps declare `list[str]`. That mismatch must not survive. The unused
`NGFWReconcilePlan` and `UserNGFWStackSweepPlan` also name
`describe_instances`, which is not in the `execute_action` allowlist and is
tested by bypassing the orchestrator with `getattr`. Delete or explicitly bring
such surfaces under the declared action contract; do not preserve them as
evidence that dynamic method dispatch is supported.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Guest transport selection | `executors.factory.GuestExecutionContext` and `build_guest_execution_context` | Keep target, document family, transport lifecycle, and provider-routed SSH/SSM construction here. Do not add executor selection to plans. |
| Guest command execution | `SSMExecutor`, `SSHExecutor`, `GuestSSHExecutor`, `RangePodSSHExecutor`, and `NGFWExecutor` | Conform to the one command port; preserve readiness/reboot behavior and strict host-key / workload-identity boundaries. |
| Setup orchestration | `SetupOrchestrator`, `SetupPlan`, and `SetupStep` | Preserve rendering, retry, verification, reboot, and PAN-OS behavior. This issue does not create a second setup engine. |
| Provider action dispatch | `AWSExecutor.execute_action` and its closed action map | Reuse the allowlist and validate required context before calling a provider method. No `getattr` on plan or request data. |
| Range lifecycle boundary | ADR-039, `shared.range_lifecycle_capability`, and the persisted `Range.range_backend` selection | New provider lifecycle variants are registered substrate adapters/capabilities, not new operation-step executor kinds. |
| Provider/config selection | `config.resolve_cloud_provider`, the installation backend registry, and `resolve_ngfw_attachment_config` | Selection is validated configuration or persisted ownership, never inferred by an orchestrator or supplied by a plan. |
| Internal failures | `ExecutorError` and its connection/timeout/command subclasses for guest commands; `cloud.exceptions.CloudError` for cloud adapters | Do not create another generic exception tree. Map at the boundary without parsing human-readable strings. |
| Durable results | `OperationRef`, `append_operation_step_result`, `shared.operation_envelope`, `shared.operation_results`, and `ResultStep` | Persist only closed, versioned, bounded lifecycle outcomes. Executor results and raw provider payloads never become inbox schemas. |
| Logging/redaction | provisioner `log_redact`; `_SetupOrchestratorLoggingMixin`; executor-specific fingerprinting | Keep commands, stdin, contexts, credentials, and raw provider payloads out of logs. Preserve setup output value-masking. |
| Tests and static typing | provisioner mypy/pytest/Ruff plus ADR-019's boundary-mock policy | Prove real first-party orchestration with small typed fakes at external execution ports; do not grow internal `patch()` topology debt. |

## Cross-Cutting Gates

### Security and authorization

This refactor adds no user-facing auth surface. The upstream Engine launch
boundary remains authoritative: `engine.launch_intents` validates the closed
resource/operation command, UUIDs, current operation generation, target
ownership, and legal lifecycle state before dispatch. Executor/action selection
must remain internal and must not become an HTTP field, operation-input field,
CLI flag, environment override, or persisted plan value.

Provider actions continue under the provisioner's least-privilege workload
identity. A declared protocol does not grant a capability and must not bypass
ADR-039 ownership/capability checks, `range_pause_resume_capability`, or the
provider SDK's IAM boundary. Unknown actions, missing parameters, unsupported
providers, and unsupported asset mixes fail before mutation.

### Shape and validation

- Setup inputs keep plan-owned `get_context()` validation and
  `SetupOrchestrator._render_script` placeholder validation. The implementation
  must not add a second context DTO or loosen the repository's static plan
  template lint contract.
- Action validation remains closed and allowlisted in the action adapter. Pass
  only the parameters declared for that action, not the full context, into the
  provider method. Extra context may carry unrelated or sensitive values and
  must not become accidental provider kwargs.
- Backend identity continues through `config.resolve_cloud_provider` and the
  installation registry. No new env key or config schema is required.
- Outbound operation results must still pass
  `shared.operation_results.parse_result_payload`, including exact keys,
  closed reason codes, diagnostic length bounds, operation ordering, and
  generation identity before persistence/application.

Structural `Protocol` conformance is a compile-time design aid, not runtime
signature validation: `@runtime_checkable` checks attribute presence only.
Production annotations must pass the provisioner's enforced mypy scope, and
tests must include negative construction/call cases so a wrong signature cannot
hide behind `MagicMock`.

### Secrets and OS/process exposure

No new secret path is needed. `build_guest_execution_context` continues to
resolve provider secret references, keep private keys in process memory or
owner-only temporary files, and close transports. Existing SSH executors keep
structured argv, strict host-key checking, and script/runtime data on stdin;
they must not interpolate an action context into a shell command. SSM continues
to receive the setup script through its API parameter rather than a local
process argv.

Do not log or serialize whole contexts. `_SetupOrchestratorLoggingMixin` remains
the sink for masking known secret values in command output, and provisioner
`log_redact.safe_log_value` / `safe_log_fingerprint` remain the local
log-injection and identifier controls. `safe_log_value` is not secret
redaction. `OpsOrchestrator` must not log raw `stderr` previews or provider
payloads; log stable action/step names, result classification, attempt/timing,
and fingerprinted identifiers only.

Process argv remains the ADR-043 canonical resource/operation plus identifiers
and optional operation-generation UUID. Executor kinds, action contexts,
scripts, provider payloads, secret references, and secret values do not enter
argv, environment projections, Terraform/Helm values, or generated runtime
files as part of this issue.

### Error envelopes, observability, and persistence

Guest transport failures retain `ExecutorConnectionError`,
`ExecutorTimeoutError`, `ExecutorCommandError`, and the existing
`SetupError` retry/raise behavior. Provider action failure must be classified at
its adapter boundary; callers must not inspect `stderr` text to decide retry or
authorization behavior.

Raw `CommandResult` streams and SDK/Terraform JSON are internal diagnostics.
They must not flow into `error_message`, the operation-result inbox, range
events, audit context, metrics labels, WebSocket messages, or `shared.api.errors`.
Range/NGFW lifecycle publication continues to use an authored `ResultStep`, a
closed reason code such as `cloud_operation_failed`, and a bounded sanitized
diagnostic. The Engine applier remains the only owner of domain persistence,
audit, and events under ADR-043.

No executor, orchestrator, plan, or result registry is persisted for this
issue. Do not add a repository, model, migration, event type, status enum, or
public DTO.

## Extensibility Seam

The next command transport implements the command port and is selected by
`GuestExecutionContext`; the next provider lifecycle implementation registers
behind the persisted ADR-039 substrate-adapter/capability seam. Neither requires
editing a universal executor switch.

For the remaining legacy operation orchestrator, the only extension parameter
is an injected action port with a closed action registry. Adding an action means
adding one adapter-owned allowlist entry and behavior tests; adding a provider
does not mean adding provider branches to `OpsOrchestrator` or action names to a
request schema. If one workflow needs both action and command capabilities, its
composition root receives both ports explicitly.

## Whole-Repository Surfaces In Scope

- `shifter/engine/provisioner/executors/base.py`, `factory.py`, command executor
  implementations, and AWS executor/mixins
- `shifter/engine/provisioner/orchestrators/base.py`,
  `setup_orchestrator.py`, `_setup_types.py`, `_setup_logging.py`,
  `_setup_panos.py`, and `ops_orchestrator.py`
- `shifter/engine/provisioner/plans/base.py` and the operation plan modules
- setup call sites in `instance_setup.py`, `instance_orchestrator.py`,
  `instance_password_setup.py`, `dc_setup.py`, `polaris_bootstrap.py`,
  `raes_*`, `ngfw_runtime.py`, and `ngfw_terraform.py`
- operation call sites in `range_ops/` and `ngfw_runtime_ops.py`
- `shifter/shifter_platform/engine/launch_intents.py` and the provisioner
  `main.py` command boundary (verification only; their contract does not change)
- `shared.operation_envelope`, `shared.operation_results`, and
  `provisioner_db_appends.py` (verification only; no new persistence shape)
- provisioner tests for executors, orchestrators, plans, factories, range ops,
  NGFW runtime ops, logging/redaction, and module coupling
- provisioner `pyproject.toml` mypy/Ruff/pytest gates and repository ADR guard

Infrastructure, Helm/Kubernetes manifests, runtime env inventories, IAM, and
admission policy are not implementation targets because this design introduces
no config, credential, workload, or argv change. If implementation adds any of
those despite this boundary, the corresponding installation schema/runtime
inventory, Terraform/Helm validation, admission parity, and security checks
become mandatory.

## Gotchas and Anti-Patterns

- Do not make all concrete classes implement `execute(*args, **kwargs)`; that
  moves the ambiguity behind a less descriptive method name.
- Do not define `run_command` with overloads/unions for guest scripts, AWS
  service methods, and named actions.
- Do not use `Any`, `hasattr`, `getattr`, `callable`, exception-driven fallback,
  or `TypeError` probing as capability negotiation.
- Do not put an executor/provider discriminator on every plan step or create a
  service-locator/composite-executor dictionary. That couples plans to runtime
  wiring and allows partially satisfiable plans.
- Do not duplicate action parameter declarations across plans, protocols, and
  the adapter allowlist. One closed registry owns dispatch validation.
- Do not mistake identical `StepResult` fields for identical types, or keep two
  classes with conversion glue.
- Do not treat AWS SDK JSON as command stdout or persist it for later routing.
- Do not revive the removed GWLB pattern where a plan string names an arbitrary
  executor method.
- Do not broaden this issue into PAN-OS validator extraction, retry-policy
  redesign, the full ADR-039 substrate implementation, or the ADR-043
  persistence cutover.
- Do not add compatibility fallbacks that keep the invalid action-shaped
  `run_command` contract alive. Update this repository's callers and tests in
  one change.
- Do not rely on unconstrained `MagicMock`: it makes `hasattr` true and masks
  interface errors. Use spec-constrained fakes or concrete port fakes.

## Non-Goals

- A single plan that freely interleaves provider API calls and guest scripts.
- A public/plugin executor registry or user-authored action language.
- New backend, provider, runtime config, environment variables, secrets, IAM,
  network policy, or deployment workflow.
- New database/API/event/audit/status schemas or direct provisioner domain-table
  writes.
- Changing setup rendering, reboot, verification, PAN-OS polling, or retry
  semantics beyond the typing/import changes needed to preserve them.
- Implementing ADR-039's full provider-neutral range substrate or completing
  ADR-043's persistence migration.

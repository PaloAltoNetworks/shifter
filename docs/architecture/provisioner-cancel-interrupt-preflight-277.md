# Provisioner Cancel/Interrupt Preflight (#277)

Status: pre-implementation guidance

Date: 2026-07-29

Issue: GitHub #277, "Provisioner: Add cancel/interrupt capability"

This is a requirement-free architecture run. The issue is the shipping
contract. This note fixes the cancellation boundary and safety invariants; it
is not an implementation plan.

## Decision Boundary

The public cancel workflow already exists:

```text
Mission Control cancel
        |
        v
CMS transition + CANCEL audit
        |
        v
Engine Range -> DESTROYING
        |
        v
durable interrupt of the current provision task
        |
        v
terminal task absence observed
        |
        v
existing canonical range destroy operation
```

Issue #277 fills only the missing middle. Cancellation is workflow policy;
interrupt is task-delivery control; destroy is resource convergence. They are
not three spellings of one operation.

- Keep the existing Mission Control endpoint, lifecycle serializer,
  permissions, CMS ownership/state checks, Engine range identity, and
  `AuditAction.CANCEL`. API success means Engine durably accepted the
  cancellation, not that provider resources are already absent.
- Keep ADR-039's four substrate operations. Do not add `cancel` to the
  provisioner CLI or provider-neutral range substrate. Cleanup is the existing
  idempotent `destroy` operation.
- Extend the existing `ProvisionerLaunchIntent` delivery boundary with a
  durable, explicitly separate interrupt request and disposition. The same
  privileged launch worker owns dispatch, interruption, retry, and recovery.
  Do not create a second control queue, worker, event family, or repository.
- Under the Engine range/launch row lock, bind cancellation to the current
  `provision` generation and fence that generation from authoritative writes.
  A pending launch is suppressed. A running provider task is interrupted.
  Repeated requests converge on the same control state.
- Never begin destroy concurrently with a task that may still be provisioning.
  The worker must observe terminal task absence first, then submit the existing
  canonical `destroy` operation, which mints its own operation generation.
  Failure or ambiguity leaves the range in `DESTROYING` and retryable; it must
  not be reported `DESTROYED`.
- Provider task references locate work but do not prove ownership. Interruption
  must verify the provider object against the trusted launch intent and expected
  task identity before mutation.

Do not overload `ProvisionerLaunchStatus.SUCCEEDED`: it means launch dispatch
succeeded, not that the provider task or range operation succeeded. Likewise,
do not use `DLQ` as a synonym for user cancellation. Interrupt delivery needs
its own bounded retry/deadline/disposition while retaining the existing launch
status meanings.

## Correctness And Race Invariants

The cancellation state must be durable before the API reports success. The
worker then handles every point in the launch race:

| Observed state | Required behavior |
| --- | --- |
| Launch is still pending | Atomically suppress dispatch, then enqueue canonical destroy. Do not turn intentional suppression into a launch retry or DLQ. |
| Provider dispatch is in progress and the task reference is not yet stored | Persist the interrupt request; the dispatcher must notice it after dispatch, record the reference, and interrupt before declaring control complete. |
| Provider task is running | Verify task ownership, request interruption once idempotently, observe terminal absence, then enqueue destroy. |
| Task is already terminal or provably absent | Treat interruption as converged and enqueue destroy idempotently. |
| Task identity does not match | Fail closed, retain recovery evidence, alert, and do not stop the foreign task or start cleanup concurrently. |
| Provider outcome is unknown | Reconcile by trusted identity before retry. Do not submit a second provision task or assume absence. |
| Cancellation is repeated | Return the existing idempotent lifecycle response; do not duplicate audit, stop calls, destroy generations, or events. |
| A late provision result arrives | Reject it as stale by `operation_id`; it cannot move the range out of `DESTROYING` or write provisioned state. |

The current RAES result path already generation-fences
`OperationResultInbox`. Remaining compatibility paths in
`provisioner_db.py`, `terraform_ops.py`, and related state writers still update
Engine tables directly. Cancellation is unsafe unless every provision-side
write that can outlive interruption is conditional on the same current
`operation_id`, failing closed when the row is no longer current, or is moved
to the authoritative result-applier path. This issue need not finish the whole
ADR-043 cutover, but no canceled generation may later write
`PROVISIONING`, `READY`, `FAILED`, instances, subnets, access bindings, or
backend evidence.

**Scope note (implementation).** This issue wires cancellation for the
**RAES/GCP** path only; `cancel_range`/`cancel_range_by_request` record an
interrupt exclusively for `raes-range` provision generations, and the RAES
provisioner writes its authoritative lifecycle solely through the generation-
fenced `OperationResultInbox` append path (`raes_range_ops.py` →
`append_operation_step_result`; it never calls the `provisioner_db.py` direct
writers). The direct writers named above (`update_range_status`,
`write_provisioned_state`, `terraform_ops.py`) are reached only by the legacy
AWS `range` path, which is **not** cancellable in this scope, so no canceled
generation reaches them here and the inbox fence is sufficient for RAES/GCP.
Extending cancellation to the AWS `range` path — and applying the same
`operation_id` fence to those direct writers — is tracked in #1894.

Stopping the workload is not cleanup. Terraform or a provider SDK may have
mutated resources before interruption, and a killed process cannot be trusted
to run compensation. Cleanup must reuse the persisted backend ownership,
Terraform state, state locks, subnet allocation release, remote-access cleanup,
NGFW attachment cleanup, and RAES destroy paths already used by normal
teardown. Retain ownership and state until absence is observed. Never
force-unlock or delete Terraform state merely to make cancellation complete.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #277 |
| --- | --- | --- |
| Public API and validation | `mission_control.api.ranges.CancelRangeView`, `RangeLifecycleSerializer`, `shared.api.errors` | Keep the optional `request_id`/positive `range_id` shape and existing error envelope. No second endpoint or cancellation DTO. |
| Authentication and authorization | `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, exact `mission_control:range:write` scope, participant lifecycle policy, CMS ownership checks | Task identity is not user authority. Cancellation enters only through the existing authorized lifecycle service. |
| Domain transition and audit | `cms.services._range_destroy`, `engine.services._range_by_request`, `shared.enums.ResourceStatus`, `shared.audit.AuditAction.CANCEL` | Preserve `DESTROYING`, rollback-on-Engine-rejection, and one user cancel audit. Do not add a public `CANCELLING` state or duplicate audit action. |
| Generation and command persistence | `engine.launch_intents`, `ProvisionerLaunchIntent`, `Range.provisioner_operation_id`, `OperationInput` | Bind interruption to the current provision generation under `transaction.atomic` and `select_for_update`; never key control by `request_id` or task reference alone. |
| Dispatch and recovery | `drain_provisioner_launch_outbox`, `engine.ecs`, existing lease/retry/DLQ and heartbeat conventions | Extend this worker and retry policy; do not add a best-effort API-to-provider stop call or an independent consumer. |
| Provider task control | `shared.cloud.types.TaskRunner`, `AWSTaskRunner`, `GCPTaskRunner`, `shared.cloud.exceptions.CloudTaskError` | Add one provider-neutral interruption seam and map failures into the existing cloud exception surface. Do not add provider-specific exception trees. |
| Result fencing | `OperationResultInbox`, Engine operation-result applier, `shared.operation_results` | Stale canceled generations are evidence only and cannot mutate domain state, audit, or events. |
| Cleanup convergence | `terraform_ops`, `range_terraform_runner.destroy_range`, `_post_destroy_cleanup`, backend ownership/state, subnet allocation release, OpenVPN and NGFW cleanup, RAES destroy | Reuse normal teardown. Do not build a partial "cancel cleanup" implementation per provider. |
| Events and projections | ADR-025 `RangeEventOutbox`, Engine/CMS handlers, range-event reconciler | Emit existing lifecycle notification only when the authoritative transition is applied. An interrupt request is not a domain event. |
| Logging | `shared.log_sanitize`, provisioner `log_redact`, existing ECS structured logging | Log safe operation/request identifiers, stage, attempt, and fixed disposition only. Never log provider payloads, task manifests, secrets, or raw exception text. |
| Tests | existing cancel service/API tests, launch-intent/outbox tests, TaskRunner contract tests, PostgreSQL concurrency lane | Exercise first-party services for real; mock only provider/process boundaries. Preserve auth, generation, ordering, and idempotency evidence. |

Keep identifiers distinct:

- `request_id` is range correlation and ownership;
- `operation_id` is the lifecycle generation and result fence;
- launch-intent/task identity is provider-workload identity and idempotency;
- `task_ref` is only the provider locator;
- range status, launch delivery status, provider task status, interrupt
  disposition, and result disposition are separate state machines.

## Cross-Cutting Security And Runtime Layers

The intended design must pass every layer below.

1. **External auth and policy.** Django session authentication keeps CSRF
   enforcement; API tokens keep the exact range-write scope; actor and
   participant policy gates stay active; CMS rechecks ownership and current
   cancellability. No unauthenticated callback, stop endpoint, or caller-chosen
   task reference is introduced.
2. **Request shape and domain validation.** `RangeLifecycleSerializer` remains
   the only public shape validator. CMS and Engine retain their existing
   lifecycle checks. Engine resolves the server-owned range and current launch
   row, validates that the generation is a cancellable `provision`, and locks
   both before recording control state. A UUID parser, JSON field, or provider
   lookup is not authorization.
3. **Operation contract and persistence.** `engine.launch_intents` and
   `OperationInput` keep their closed resource/operation/UUID validation.
   `OperationResultInbox` and its Engine applier reject wrong ownership,
   contract version, operation kind, replay digest, or stale generation before
   domain mutation. Compatibility direct writes must gain the same fence.
4. **Provider workload identity.** The task runner must read and verify the
   target before stopping it. For GCP, validate the deterministic Job identity,
   task-identity annotation, image, command, service account, secret binding,
   and namespace as the current launcher already does. For AWS, make the trusted
   launch identity observable on the ECS task (for example, the bounded
   `startedBy` field) and validate cluster, identity, task definition,
   container, and command before `StopTask`. A syntactically valid ARN or Job
   name is insufficient.
5. **IAM, RBAC, admission, and network policy.** AWS already grants scoped
   `ecs:StopTask` with the configured cluster condition; do not broaden it.
   The GCP launcher role already has Job deletion and Secret lifecycle rights
   in the provisioner namespace, and its NetworkPolicy already permits the
   Kubernetes API. Preserve those least-privilege scopes. The provisioner Job
   admission policy continues validating `CREATE`; task deletion is controller
   control and must not require an admitted `cancel` CLI command.
6. **Secrets.** No new secret, token, cancellation reason, or end-user value is
   required. Continue using `shared.cloud.sensitive_env` and the GCP
   per-Job Secret/owner-reference flow. Delete the verified Job with foreground
   propagation and let owner-reference garbage collection handle its Secret;
   never derive and delete a Secret from an untrusted task reference. AWS stop
   reasons, logs, rows, events, and results contain fixed authored text only.
7. **Configuration and env shape.** Use `config/_cloud.py`,
   `config/env-manifest.json`, installation runtime inventory, AWS task
   definitions, Helm `values.schema.json`/runtime ConfigMap, GCP base manifests,
   and admission env allowlists as the canonical binding surfaces. The base
   design needs no new env. If a deadline becomes configurable, add one bounded
   typed setting through every renderer and validator; do not read a new
   module-local `os.environ`.
8. **OS/process exposure.** No secret or cancellation document belongs in
   process argv. Existing resource/operation/request/operation UUID argv remains
   the maximum exposure. Do not parse local task references into PIDs and call
   `kill`: PID reuse and absent durable ownership make that unsafe. Provider
   task termination controls the whole workload boundary; it is not an HTTP or
   Unix-signal surface exposed to users.
9. **Error envelopes and persistence leakage.** Task-control failures map once
   to `CloudTaskError` and fixed, bounded internal reason/disposition codes.
   Existing `shared.api.errors` and authored user messages remain the public
   envelope. Raw ECS/Kubernetes/Terraform responses, resource inventories,
   SQL details, tracebacks, task manifests, secret names, and exception strings
   must not enter `Range.error_message`, audit context, events, API JSON, or
   websocket payloads.
10. **Observability and recovery.** Reuse worker heartbeats, structured logs,
    launch retry/lease conventions, and provider alarm parity. Operators need
    safe signals for interrupt requested, pre-dispatch suppression, provider
    stop accepted, terminal absence observed, destroy enqueued, retry age,
    identity mismatch, and exhausted recovery. Metrics use bounded status and
    provider labels, never task references, request IDs, user IDs, exception
    text, or secret identifiers as dimensions.

For ECS, terminal means `STOPPED` or a reconciled absence for the verified task.
For Kubernetes, deletion must use foreground propagation or separately prove
that Job pods are gone; a Job `404` after background deletion is not sufficient
to start Terraform destroy.

## Extensibility Seam

The durable seam is one provider-neutral `TaskRunner` interruption operation,
parameterized by:

- provider task reference;
- trusted expected launch/task identity and immutable launch description; and
- a bounded grace/deadline or equivalent cancellation budget.

It returns an idempotent control disposition that distinguishes accepted,
already terminal, and identity mismatch/unknown outcome; it does not return
range lifecycle success. The launch intent persists that control progress so a
worker restart can resume it.

This seam can later interrupt another provisioner operation or resource family
without changing the public range-cancel schema, adding a fifth substrate
operation, or creating another worker. Issue #277 enables only cancellation of
range provisioning. The deadline seam should have a safe internal default;
make it deployment configuration only when operators need to tune it.

## Whole-Repo Boundary

Implementation must account for these surfaces even when a given file needs no
edit:

- API/domain: `mission_control/api/ranges.py`,
  `mission_control/api/serializers.py`, Mission Control permissions,
  `cms/services/_range_destroy.py`, `engine/services/_range.py`,
  `engine/services/_range_by_request.py`, shared lifecycle enums, API errors,
  and audit;
- operation persistence: `engine/launch_intents.py`,
  `engine/models/_launch.py`, range operation-generation fields,
  `OperationInput`, `OperationResultInbox`, result-applier workers, and
  migrations;
- delivery/providers: `engine/ecs/`, launch-outbox worker,
  `shared/cloud/types.py`, AWS/GCP TaskRunner implementations, cloud
  exceptions, sensitive-env handling, and provider contract tests;
- provisioner convergence: `main.py`, `terraform_ops.py`,
  `range_terraform_runner.py`, `provisioner_db*.py`, state helpers, backend
  ownership evidence, RAES operations, Terraform workspaces/state/locks,
  subnet, remote-access, OpenVPN, and NGFW cleanup;
- projections/recovery: Engine range handlers, ADR-025 range-event outbox and
  drainer, CMS reconciler, Mission Control fanout, and system audit;
- deployment/security: AWS engine-provisioner ECS task/IAM definitions,
  `config/_cloud.py`, `config/env-manifest.json`, Helm
  `values.yaml`/`values.schema.json`/runtime ConfigMap, base and Helm launcher
  deployment, service account/RBAC, NetworkPolicy, provisioner Job admission
  policy, and render/security tests;
- enforcement: `.importlinter`, ADR-019 boundary-mock policy, ADR guard,
  provider TaskRunner tests, PostgreSQL transaction/concurrency tests, launch
  retry tests, API auth/CSRF/scope tests, and AWS/GCP manifest parity tests.

## Gotchas And Anti-Patterns

- `subprocess.run` around Terraform is blocking. SIGTERM grace cannot guarantee
  state flush, lock release, provider compensation, or Python `finally`
  execution. Reconcile and destroy from persisted state after workload
  termination; do not trust in-process cleanup.
- The task may be dispatched before `task_ref` is persisted. A synchronous API
  lookup-and-stop loses this race; durable control state on the launch record
  closes it.
- A canceled pending launch is intentional convergence, not a retryable
  validation failure. Without an explicit suppression outcome the current
  launcher can retry it into DLQ.
- Do not start destroy merely because ECS accepted `StopTask` or Kubernetes
  accepted Job deletion. Observe terminal absence first.
- Do not use provider names, ARNs, Job names, request IDs, or cached range task
  ARN fields as ownership proof. Resolve through the current operation
  generation and launch intent.
- Do not add polling from the provisioner process back into Engine. The
  privileged external controller interrupts the provider task; the task is not
  a second workflow coordinator.
- Do not duplicate `ResourceStatus`, lifecycle DTOs, validation, exception
  hierarchies, cleanup branches, retry loops, audit actions, event schemas, or
  repositories.
- Do not conflate a user cancel audit with system cleanup evidence, or a launch
  delivery result with a range operation result.
- Do not allow a late direct SQL write or legacy handler event from the canceled
  generation to regress `DESTROYING`.
- Do not store raw provider stop errors or caller text as a cancellation reason.
  Persist bounded authored codes and sanitize operator diagnostics.
- Do not kill a local development process by parsing `local-<pid>`. Either put
  local mode behind the same owned controller seam for tests or fail explicitly
  without claiming production-grade cancellation.

## Non-Goals And Implementation Boundaries

- No implementation is part of this preflight.
- No new public endpoint, request field, token scope, audit action, lifecycle
  status, websocket message, or event family.
- No fifth substrate operation and no `range cancel` provisioner CLI command.
- No cancellation of `READY`, `PAUSED`, `FAILED`, NGFW, CTF organizer, or other
  resource workflows; their existing destroy/cleanup semantics remain.
- No synchronous API wait for task termination or resource cleanup. Accepted
  cancellation is durable and convergent, not instantaneous.
- No process-supervisor replacement, new queue, new worker, new persistence
  repository, or general orchestration framework.
- No wholesale ADR-043 migration or backend redesign. Compatibility writes
  that can violate cancellation fencing are in scope for correctness; unrelated
  persistence cutover remains separate.
- No destructive Terraform state deletion, blind force-unlock, or weakening of
  IAM, RBAC, admission, network, validation, logging, or error-envelope
  controls.
- No new ADR is required unless implementation changes ADR-039's lifecycle
  substrate, ADR-043's persistence ownership, or the established task-delivery
  trust boundary beyond the seam above.

## Validation

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation must additionally run focused API/CMS/Engine, launch-intent,
TaskRunner, provisioner, PostgreSQL race/fencing, and AWS/GCP deployment render
tests. Any architecture, workflow, platform, or guardrail changes also require
the stack-native checks specified by `AGENTS.md`.

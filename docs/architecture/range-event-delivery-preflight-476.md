# Range Event Delivery Preflight (#476)

Status: pre-implementation guidance

Date: 2026-06-29

Issue: GitHub #476, "Range and experiment state flow treats event delivery as
best-effort despite correctness dependencies."

Superseded note: ADR-027 / issue #1195 removed the legacy experiment event
bridge and run reconciler. ADR-025 now applies this durable-delivery model to
range events only.

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as a consistency and recovery problem across the provisioner,
message fabric, domain workers, CMS range state, Mission Control websocket
state, and experiment orchestration. Do not solve it by making one handler look
locally robust while the repo still has an unowned lost-event path.

The existing architecture already keeps durable range infrastructure state in
PostgreSQL. Keep that source-of-truth boundary: events are propagation signals
that make domains react to authoritative state, not a replacement state store.
The shipping implementation must make those signals recoverable. A range status
transition or experiment continuation cannot depend on a publish call that may
log and disappear.

## Consistency Model

- PostgreSQL remains authoritative for range, request, instance, app, and
  experiment-run state. Provisioner DB writes and Django domain models are the
  source to reconcile from.
- Range and experiment events are correctness-critical propagation signals. They
  may be notification shaped, but they are not best-effort. If an event is
  needed to advance CMS, Mission Control, CTF, or experiment orchestration, a
  publish or delivery failure must be visible and recoverable.
- Every correctness dependency needs one of two recovery paths:
  1. durable publish retry/replay with DLQ and alerting; or
  2. explicit reconciliation that re-reads authoritative state and resumes the
     same domain transition idempotently.
- The near-term design should prefer database-authoritative reconciliation over
  reclassifying the event stream as the state authority. A true event-sourced
  model would require a larger redesign of provisioner writes, consumers,
  replay ordering, idempotency, and audit contracts.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #476 |
| --- | --- | --- |
| Provisioner event publishing | `shifter/engine/provisioner/events.py`, `cloud.types.EventBus`, `cloud.aws.event_bus.AWSEventBus`, `cloud.gcp.event_bus.GCPEventBus`, `cloud.exceptions.CloudEventBusError` | Build on the provider-neutral EventBus seam. Do not call boto3, Pub/Sub, SNS, or SQS directly from range lifecycle code. |
| Provisioner DB authority | `shifter/engine/provisioner/provisioner_db.py`, `provisioner_db_ngfw.py`, `state_helpers.py` | Treat these writes as authoritative state changes. Do not duplicate state in event payloads just to avoid DB reconciliation. |
| Event contracts | `shared.messages.events`, `shared.messages.envelope.parse_sns_message`, `shared.enums.ResourceStatus`, `shared.schemas.RangeRef` | Reuse shared constants, parser, enum validation, and schemas. Do not create app-local event constants or ad hoc status strings. |
| Worker acknowledgement | `shared/management/commands/run_worker.py`, `shared.cloud.types.QueueConsumer`, `shared.cloud.{aws,gcp}.queue` | Preserve delete/ack-after-handler semantics. Handler failures that should retry must propagate to the worker instead of being swallowed. |
| Queue configuration | `config/_cloud.py` `QUEUE_CONFIG` / `SQS_QUEUE_CONFIG`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py` | Extend the existing queue env shape if needed. Dynamic `QUEUE_*` lookups are not enough by themselves; new queue/retry/reconcile env keys need explicit inventory or manifest coverage. Do not add parallel queue settings, magic env names, or provider-specific settings in handlers. |
| AWS messaging infrastructure | `platform/terraform/modules/portal/messaging/` | Reuse the existing encrypted SNS/SQS topic, per-consumer queues, DLQ knobs, and CloudWatch alarm knobs. Do not create a second messaging module. |
| GCP messaging infrastructure | `platform/terraform/gcp/modules/portal/messaging/`, `platform/k8s/gcp/base/worker-*-deployment.yaml`, `platform/charts/shifter/templates/worker-*-deployment.yaml` | Keep Pub/Sub topic/subscription behavior aligned with the shared queue contract. If #476 adds dead-letter, retry, or alerting posture, add it at the module/subscription boundary rather than per handler; the current GCP module does not yet mirror AWS DLQ alarms. |
| Provisioner task launch and OS exposure | `engine.ecs._start_range_ecs_task`, `shared.cloud.types.TaskRunner`, `shared.cloud.gcp.task_runner.GCPTaskRunner`, `shared.cloud.sensitive_env`, GCP provisioner `ValidatingAdmissionPolicy` | Keep runtime arguments to bounded operation/request identifiers. Do not put event payloads, retry blobs, secrets, or credentials in process argv or literal Kubernetes Job env; sensitive env stays behind the existing Secret/secretKeyRef classifier. |
| CMS range projection | `cms.handlers.__init__`, `cms.handlers.range_events`, `cms.handlers.ctf_bridge`, `cms.handlers.experiment_bridge`, `cms.models.RangeInstance` | Keep package-level worker dispatch stable and keep CTF/experiment notifications behind the existing bridge seams. |
| Experiment orchestration | `cms.experiments.events`, `cms.experiments.handlers`, `ExperimentOrchestrator`, `cms.experiments.schemas.RunStatus` / `ExperimentStatus` | Reuse state-machine transitions, `select_for_update()` orchestration locking, and existing publish error behavior. Today `cms.experiments.events` publishes lifecycle events to the CMS event stream; do not target a separate experiments worker unless the producer routing, queue config, and worker deployments are made consistent in the same change. |
| Engine projection and audit | `engine.handlers`, `engine.models.Range`, `risk_register.services.audit_log_system_event` | Keep Engine model updates and audit logging in the existing handler/audit seam. Do not make CMS write Engine models directly. |
| Mission Control fanout | `mission_control.handlers`, `shared.channels.groups`, `config/asgi.py` | Websocket updates remain a projection of state, not the authoritative recovery path. |
| Logging hygiene | `log_redact.safe_log_*`, `shared.log_sanitize.safe_log_*`, `logging_config.ECSFormatter`, `config._logging_config` | Use sanitized IDs or fingerprints for request/range/message identifiers and bounded exception text. Do not dump event bodies or env. |
| User-facing API errors | `shared.api.errors.api_exception_handler`, `shared.api.errors.api_error_response`, `shared.errors.safe_user_message` | Recovery failures belong in worker/provisioner/operator surfaces. If any status endpoint reports degraded recovery state, it must use the existing error envelope and authored safe messages, not raw provider exceptions. |
| Import boundaries | `.importlinter`, `shared/` cyberscript shims | Cross-domain coupling still goes through shared contracts, service boundaries, signals, or event bridges. Do not import CTF from CMS or CMS from Engine. |
| Test shape | `tests/cms/test_handlers.py`, `tests/engine/test_handlers.py`, `tests/mission_control/test_handlers.py`, `tests/cms/experiments/test_range_bridge.py`, ADR-019 `boundary-mock-policy` | Preserve behavior tests that drive real ORM rows, real channel-layer behavior where practical, and cloud boundaries mocked at `boto3` / provider adapters. Do not add first-party internal patching to simulate the state flow. |

## Cross-Cutting Layers

- Auth surface: user-facing requests still enter through existing Django views,
  services, and websocket consumers guarded by `config/asgi.py`,
  `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and domain
  authorization. The retry/reconciliation machinery is internal worker or
  provisioner behavior and must not add unauthenticated HTTP endpoints.
- Secret-handling surface: queue URLs, topic IDs, and subscription IDs are
  deploy configuration. Cloud credentials stay with task roles, workload
  identity, IAM auth, existing secret hydration, and the GCP task runner's
  `shared.cloud.sensitive_env` Secret projection. Do not place credentials,
  signed URLs, DB tokens, or full secret payloads in event bodies, DLQs, retry
  tables, logs, Docker argv, Kubernetes Job specs, Terraform outputs, or
  workflow logs.
- Env-binding shape: `RANGE_EVENTS_TOPIC_ID` / `SNS_RANGE_EVENTS_ARN` and
  `QUEUE_{NAME}_{CONSUMER_ID,PUBLISHER_ID}` / `SQS_*_URL` are the canonical
  event and queue bindings. Any new retry/reconcile knob belongs beside these
  settings and in `config/env-manifest.json` plus the runtime inventory, not as
  handler-local `os.environ` reads. Because the current queue env names are read
  through dynamic f-strings in `config/_cloud.py`, implementers must verify that
  the inventory/generator surface actually lists any new key instead of assuming
  manifest discovery will find it automatically. The current AWS environments
  provision `cms`, `engine`, and `mc` consumers; the GCP runtime inventory also
  has `QUEUE_EXPERIMENTS_*` keys, but the checked-in Kubernetes and Helm
  manifests do not launch a `--queue experiments` worker. Do not rely on that
  queue until the runtime surface and deployment surface agree.
- Config validators: provisioner EventBus selection comes from
  `CLOUD_PROVIDER`; platform queue selection comes from Django settings. Invalid
  required publish configuration should fail closed at the operation or worker
  boundary instead of silently disabling event propagation.
- Message shape validators: inbound workers must continue through
  `parse_sns_message`, shared event constants, and `ResourceStatus` validation.
  If typed event validation is expanded, put it in `shared.messages` or shared
  schemas so all consumers use one contract. Invalid, unauthorized, or stale
  payloads may be deliberately logged and acknowledged; transient database,
  broker, or provider failures that should be retried must not be converted into
  normal handler returns unless an explicit reconciler owns recovery.
- OS/process exposure: provisioner CLI arguments currently carry operation and
  request IDs, and the GCP provisioner Job admission policy pins the allowed
  command family and blocks entrypoint/envFrom drift. Do not add message
  payloads, secret IDs with clear values, replay blobs, or queue credentials to
  process arguments. Runtime identifiers may be logged only through the
  sanitizer/fingerprint helpers.
- Error-envelope surface: this is background processing. Failures should appear
  as provisioner failure, worker retry/DLQ, audit/log records, alerts, or
  bounded operator diagnostics. Do not expose raw event failure details through
  browser JSON, websocket payloads, DRF error envelopes, or template messages.
- Persistence surface: if a durable retry/outbox table is introduced, it must
  be a first-class model/migration with ownership, retention, idempotency, and
  replay semantics. Do not hide persistent retry state in JSON columns, cache,
  Redis channels, local files, or task memory.
- Observability surface: reuse the existing encrypted messaging module alarms,
  worker heartbeat files, ECS/portal logging, and audit service. Lost-event
  recovery needs an operator-visible signal: publish failure, retry exhaustion,
  DLQ depth, reconciliation lag, or stuck experiment/range age.

## Extensibility Seam

The durable seam is a provider-neutral range-event reliability policy with
three parameters:

- publish mode: fail operation, durable retry/outbox, or reconciler-backed
  advisory publish;
- recovery target: per event type and consumer domain, because `range.ready`
  affects CMS, CTF, Mission Control, and experiments differently;
- retry/reconciliation horizon: retention, max attempts, backoff, and alerting
  thresholds per environment.

Keep that seam at the EventBus/worker/reconciler boundary. The next reasonable
variation is adding another consumer or provider-specific dead-letter behavior;
that should be configuration and shared contract work, not a rewrite of every
handler.

## Whole-Repo Scope

Likely in scope for the implementation:

- `shifter/engine/provisioner/events.py` and tests under
  `shifter/engine/provisioner/tests/`
- `shifter/engine/provisioner/cloud/**` only if provider-neutral publish
  behavior or exceptions need to change
- `shifter/engine/provisioner/provisioner_db*.py` only if an outbox or
  reconciliation marker is persisted by the provisioner
- `shifter/shifter_platform/shared/messages/**`,
  `shared/management/commands/run_worker.py`, and `shared/cloud/**`
- `shifter/shifter_platform/cms/handlers/**`,
  `cms/experiments/{events.py,handlers.py,orchestrator/**,models.py,schemas.py}`
- `shifter/shifter_platform/engine/handlers.py` and
  `mission_control/handlers.py`
- `shifter/shifter_platform/config/_cloud.py` and `config/env-manifest.json`
  for config surface changes
- `platform/terraform/modules/portal/messaging/**`,
  `platform/terraform/gcp/modules/portal/messaging/**`, and worker deployments
  if DLQ, retry, alerting, or subscription posture changes
- targeted tests in `tests/cms/test_handlers*.py`,
  `tests/cms/experiments/**`, `tests/engine/test_handlers.py`,
  `tests/mission_control/test_handlers.py`, and provisioner event tests

Usually out of scope:

- replacing SNS/SQS or Pub/Sub with another broker;
- turning the platform into a fully event-sourced architecture;
- moving Mission Control websocket delivery into the correctness path;
- redesigning range provisioning, scenario hydration, CTF lifecycle, identity,
  upload, Guacamole, or terminal services.

## Gotchas And Anti-Patterns

- Do not preserve `_publish_event()` swallowing publish failures for events that
  drive correctness unless the same change adds durable retry or explicit
  reconciliation for the affected flow.
- Do not make consumers "retry" by catching all exceptions and returning
  normally. `run_worker.py` only retries when the handler raises and the message
  is not acknowledged.
- Do not treat DLQs as recovery by themselves. A DLQ without replay procedure,
  alert, payload safety, and ownership is delayed data loss.
- Do not confuse `range.provisioned` and `range.status.updated`. The current
  provisioned event is notification-only; status transition drives CMS,
  Engine, Mission Control, and experiment bridges.
- Do not confuse the configured `experiments` queue name with the current
  experiment lifecycle path. The deployed worker path is CMS-owned today:
  `cms.handlers.process_event` routes `experiment.*` messages into
  `cms.experiments.handlers`, and the range-ready bridge publishes to the CMS
  publisher identifier.
- Do not put full provisioned instance state into every event as a workaround
  for missing reads. The provisioner already writes state to DB; recovery should
  query authoritative rows.
- Do not duplicate `ResourceStatus`, experiment run statuses, event constants,
  message envelope parsing, or cloud adapter exceptions in each domain.
- Do not let a reconciliation job bypass domain invariants. It must call the
  same service/orchestrator/bridge logic or a shared idempotent helper, not
  manually update unrelated model columns.
- Do not conflate UI freshness with correctness. Mission Control websocket
  fanout can lag; experiment continuation and CMS/Engine state convergence
  cannot silently depend on a one-shot best-effort event.
- Do not broaden import dependencies to make reconciliation convenient. Respect
  `.importlinter` and keep shared contracts in `shared`.
- Do not log raw event payloads, exception reprs carrying provider responses,
  queue URLs with credentials, DB tokens, secret IDs, or user-controlled error
  messages without the existing sanitizers.

## Non-Goals

- No implementation in this preflight note.
- No new broker, event-sourcing platform, workflow engine, global exception
  hierarchy, duplicate schema package, or public recovery API.
- No change to user-facing auth, websocket authorization, CTF participation
  rules, scenario DSL contracts, upload validation, terminal streaming, or
  Guacamole behavior.
- No weakening of ADR guard, import boundaries, provider abstraction, queue
  encryption, secret-handling, or logging hygiene to make retries easier.

## Validation Expectations

Run the repo-required architecture check before completion:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

If implementation touches Django Python under `shifter/shifter_platform`, also
run:

```bash
cd shifter/shifter_platform && uv run ruff check .
cd shifter/shifter_platform && uv run ruff format --check .
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
```

If implementation touches AWS Terraform messaging:

```bash
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

If implementation touches GCP Kubernetes manifests:

```bash
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

If implementation touches workflows, run:

```bash
actionlint
```

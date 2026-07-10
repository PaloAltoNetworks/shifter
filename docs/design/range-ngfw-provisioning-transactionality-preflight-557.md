# Range And NGFW Provisioning Transactionality Preflight - Issue 557

Status: pre-implementation guidance

Tracking issue: GitHub #557, "Architecture review: make range and NGFW provisioning transactionally safe across CMS, engine, and provisioner"

This note records the repository-wide architecture guardrails for making range
and NGFW provisioning transactionally safe. It is intentionally not an
implementation plan.

## Scope

The change must make provisioning, retry, reconciliation, cancellation, and
failure handling durable and idempotent across CMS, engine, and the provisioner.
The existing `request_id` remains the cross-boundary correlation key.

The system must continue to treat CMS as the user-facing intent and ownership
layer, engine as the durable orchestration/materialization layer, and the
provisioner as the cloud/PAN-OS mutation layer.

## Architecture Decisions

- Use the existing `Request` and `request_id` vocabulary across CMS, engine,
  task dispatch, events, audit, and provisioner CLI boundaries. Do not add a
  parallel "workflow", "job", or "operation id" concept unless it is strictly
  an internal operation-attempt record correlated to `request_id`.
- Keep public user-visible state on the existing `ResourceStatus` vocabulary.
  If finer progress is needed, model it as operation phase/progress metadata,
  not as a competing public status enum.
- Treat database state as authoritative. Cloud events are replayable
  notifications and must not be the only durable record of a phase transition.
- Persist state transitions before dispatching external work, then compensate
  or resume by `request_id`. Do not rely on best-effort cleanup as the
  correctness boundary.
- Keep provider-specific compensation below the existing provisioner/cloud
  seams. CMS must not learn AWS, GCP, Terraform, GDC, or PAN-OS cleanup details.
- Do not hold database row locks while making cloud, ECS/Kubernetes, Terraform,
  PAN-OS, or event-bus calls. Follow the existing engine lifecycle pattern:
  atomic transition under lock, release, dispatch, then revert or record failure
  when dispatch fails.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Request identity | CMS `Request`, engine `Request`, `RequestSpec.request_id`, `RangeInstance.request`, provisioner `--request-id` | `request_id` is the only cross-boundary correlation key. `range_id` stays a legacy lookup/input compatibility path only. |
| Status vocabulary | `shared.enums.ResourceStatus`, engine `Range.Status`, CMS `EntityBase` terminal soft-delete behavior | Reuse existing statuses. Add operation phase/progress separately if necessary. |
| Service boundaries | `cms.services` and `engine.services` facades, `scripts/check_layer_imports/layer_imports.yaml`, ADR-001 | Cross-layer calls must go through public service facades. Do not import private service modules across layers. |
| Request/spec schemas | `shared.schemas.request.RequestSpec`, `shared.schemas.range.RangeSpec`, `shared.schemas.app.NGFWAppSpec`, `shared.schemas.persistence` | Do not duplicate DTOs or validators. Persist specs through the established wrapper where specs are stored. |
| CMS validation and auth | CMS `_common` validators, Mission Control DRF serializers/permissions, `block_ctf_participant_only`, API token scope helpers | New API or retry/reconcile surfaces must use the existing serializer, permission, ownership, and participant-blocking conventions. |
| Engine persistence | `engine.interpreter.interpret`, `engine.services._range._persist_range_atomically`, `engine.services._lifecycle`, engine task ARN fields | Build durable transitions on the existing engine materialization and lifecycle patterns. |
| Provisioner DB state | `provisioner_db.py`, `provisioner_db_ngfw.py`, `state_helpers.py`, NGFW attachment records | Store resumable state through the existing engine tables/state payloads and provider-neutral state helpers. |
| Cloud task dispatch | `shared.cloud.TaskRunner`, `engine/ecs.py`, `shared.cloud.sensitive_env` | Keep dispatch provider-neutral and pass only request identifiers in argv. Add sensitive env names to the central policy if new env is introduced. |
| Cloud mutation runners | `terraform_base.py`, `range_terraform_runner.py`, `terraform_ops.py`, `ngfw_terraform.py`, `ngfw_terraform_cleanup.py`, GDC runner modules | Add compensation/resume behavior to the existing runners instead of creating a second provisioning stack. |
| Events | `provisioner/events.py`, `shared.messages`, engine/CMS event handlers | Events must remain sanitized, replayable notifications. Handlers must be idempotent by `request_id`. |
| Audit, errors, logging | `risk_register.services`, `shared.errors`, `shared.api.errors`, `shared.log_sanitize`, `log_redact.py` | Audit state changes without secrets, classify user-facing errors, and log identifiers/fingerprints rather than payloads. |
| Tests | Existing service tests plus the boundary mock policy in ADR docs | Patch process/cloud/framework boundaries, not first-party internal callables, for new tests. |

## Security Layers The Design Must Pass

- Auth and ownership: Mission Control browser and API entrypoints must keep
  using login/session or API-token permissions, range write scopes, actor-user
  resolution, CMS ownership checks, and participant-only lifecycle blocking.
  A reconciliation or retry endpoint must not bypass CMS ownership semantics.
- Input shape checks: API inputs must pass DRF serializers; CMS service inputs
  must pass `_validate_caller_user`, UUID/string/id validators, and existing
  scenario/credential checks; engine inputs must pass `RequestSpec`,
  `RangeSpec`, and `NGFWAppSpec` validation; provisioner inputs must continue
  to accept validated `--request-id` values only.
- Config and environment: new runtime configuration must use the existing
  Django settings/config binding conventions and any repository env manifest
  checks. New sensitive environment variables must be classified through
  `shared.cloud.sensitive_env` and reflected in provider task-runner tests.
- Secret handling: hydrated NGFW specs contain `authcode`, `scm_pin_value`, and
  `otp_value`; credential values, Terraform tfvars, cloud secret references,
  SSM parameter names, bootstrap objects, and PAN-OS setup material must never
  be logged, audited, emitted in events, stored in argv, or returned through
  user-facing error envelopes. Continue using encrypted CMS fields, secrets
  store references, Terraform workspace file modes, tfvars purge, and log
  redaction helpers.
- OS/runtime exposure: task argv and subprocess argv must contain operation
  names and request identifiers only. Continue using argv-list subprocess calls,
  not shell strings. Per-request Terraform workspaces must stay path-safe,
  private, and cleaned after sensitive files are purged.
- Error envelopes: user-facing API/browser errors must pass through the existing
  `classify_user_message`, DRF `api_error_response`, and request-id envelope
  paths. Do not expose raw cloud, Terraform, PAN-OS, database, or stack trace
  messages.
- Policy gates: changes to architecture, workflows, platform code, or guardrail
  files must continue to pass ADR guard, import-linter, and the stack-native
  checkers named in the repository instructions when their subsystems are
  touched.

## Extensibility Seam

The extensibility seam belongs at a request-scoped operation contract:

- key: `request_id`
- resource kind: range or NGFW
- operation: provision, destroy/deprovision, cancel, pause/resume, start/stop
- durable phase/progress: generic orchestration progress, separate from public
  `ResourceStatus`
- compensation/resume handler: implemented below the existing engine and
  provisioner provider seams

That shape leaves room for a future reconciliation worker, provider-specific
cleanup strategies, and additional resource kinds without reworking CMS
controllers or duplicating provider logic. Backoff, lease/lock ownership, and
maximum attempts belong on the durable operation/reconciliation mechanism, not
inside ad hoc view or event-handler branches.

## Gotchas And Anti-Patterns

- Do not create duplicate request, workflow, state-machine, schema, validation,
  or exception hierarchies.
- Do not store lifecycle progress inside raw `RangeSpec` or `NGFWAppSpec`
  payloads. Specs describe desired resources; operation state describes what
  happened.
- Do not log full Terraform outputs, hydrated NGFW specs, provisioner payloads,
  cloud API responses, or exception strings that may contain secrets. Range
  Terraform output logging is already a risk; do not copy it and tighten it if
  touched.
- Do not put secrets or full specs in process argv, cloud event payloads, audit
  records, GitHub text, temporary filenames, or provider job names.
- Do not make CMS responsible for provider-specific cleanup or retry policy.
- Do not treat event delivery as transactional or sufficient for recovery.
- Do not mark cancellation as locally destroyed before cleanup has an explicit,
  durable, idempotent compensation path.
- Do not hold database locks across network calls.
- Do not add reconciliation behavior that bypasses CTF bridges or Mission
  Control/CMS service boundaries.
- Do not weaken import, ADR, secret, lint, or cloud policy guardrails to make
  orchestration code easier to land.

## Non-Goals And Boundaries

- This note does not implement issue #557 and does not define an implementation
  task list.
- Do not introduce a distributed transaction or two-phase commit across Django,
  cloud APIs, Terraform state, PAN-OS, and event buses. The repository should
  solve this with durable state, idempotent resume, and compensating actions.
- Do not replace Terraform, provider task runners, the event bus, CMS ownership
  models, or the public `ResourceStatus` contract as part of this issue unless
  a later design change explicitly documents that broader migration.
- Do not expand API-token scopes, participant permissions, or user-visible
  lifecycle actions unless the implementation requires a new public surface and
  updates the canonical auth/scope definitions.
- Do not move shared contracts into CMS, engine, or provisioner-private modules.
  Shared request/spec/status contracts stay in `shared`.

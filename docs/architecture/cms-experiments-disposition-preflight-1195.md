# CMS Experiments Disposition Preflight (#1195)

Status: pre-implementation architecture guidance

Date: 2026-07-01

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1195>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note records repository-wide design
guardrails; it is not an implementation plan.

## Selected Disposition

Issue #1195 selected the removal path on 2026-07-01. ADR-027 records the
accepted decision: the legacy `cms.experiments` feature is removed instead of
completed or redesigned in place, because it is superseded by the pending ACES
migration. The "keep and finish" and "redesign while frozen" guidance below is
retained only as historical preflight context and is superseded for the legacy
runtime path.

## Decision Boundary

The current `cms/experiments` feature is not a working alpha. It has authoring,
run scheduling, execution-plan construction, event bridging, and task launch
code, but no executor that consumes `EXPERIMENT_PAYLOAD` and no `experiment`
CLI subcommand in the provisioner image. It also validates/renders command
payloads through AWS-only assumptions.

Three dispositions are acceptable:

- Remove experiments: delete or archive the feature deliberately, including
  routes, navigation, services, events, workers, tests, docs, and data-retention
  handling. Do not leave callable dead paths.
- Keep and finish the legacy feature: build an end-to-end executor, artifact
  collector, provider-aware execution context, tests, deployment wiring, and
  operational documentation before enabling it.
- Redesign around ACES experiment-core: keep the current feature frozen behind
  `EXPERIMENTS_ENABLED` while the ACES sidecar/profile path proves parity in
  its own issues.

Until one disposition is completed, `EXPERIMENTS_ENABLED` stays default false,
routes stay unregistered when disabled, nav stays hidden, and
`start_experiment_task` must continue refusing to launch executor tasks while
disabled. No other product work should depend on experiments.

## Architecture Decisions

- The missing executor belongs behind the existing provisioner/runtime seams,
  not in CMS. If the executor is built in the provisioner image, add a first
  class `experiment` subcommand in `shifter/engine/provisioner/main.py` and keep
  production modules importing the real owner module, not `main`.
- Provider selection for guest command execution must use
  `executors.factory.build_guest_execution_context()`. That seam already
  returns SSM for AWS and in-range-pod SSH for GCP/GDC. Do not add a separate
  experiment-local `if aws else ssh` executor switch.
- `cyberscript.script_context.ScriptExecutionContext` is the current
  command-rendering security boundary, reached from CMS only through
  `shared.script_context`. Dropping `_enforce_aws_only_provider` is valid only
  after the context becomes provider-aware for target IDs, object download
  behavior, document/shell family, and remote command rendering.
- Task launch stays behind `shared.cloud.get_task_runner()`. Reuse
  `engine.ecs` conventions for `ENGINE_TASK_*` config, structured argv, GCP env
  forwarding, task ids, and `CloudTaskError` handling. Do not call ECS,
  Kubernetes, boto3, or google clients from the orchestrator.
- Script/object access must use cloud adapters. Django-side authoring and
  downloads use `shared.cloud.get_object_storage()` through
  `cms.experiments.s3`; provisioner/executor code uses provisioner
  `cloud.get_object_storage()` or `config.generate_presigned_url()`. Do not
  render `aws s3 cp` or `gcloud storage cp` directly as the primary abstraction.
- Experiment services remain the ownership, authorization, state, upload, and
  audit boundary. Views are HTTP adapters, handlers are event routers, and the
  orchestrator coordinates run lifecycle only.
- If the long-term direction is ACES experiment-core, do not extend
  `ExperimentRun.metadata` into the new archive schema. Follow
  `docs/architecture/aces-experiment-core-preflight-1235.md` and keep legacy
  experiments as compatibility/live-state records until cutover.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Feature exposure | `EXPERIMENTS_ENABLED`, `config.urls`, `shared.context_processors.feature_flags`, `cms.experiments.ecs.start_experiment_task` | Keep the feature off by default until it is end-to-end. |
| CMS auth | `shared.auth.threat_research_required`, `validate_cms_authoring_user`, `can_edit_cms_authoring` | UI hiding is not authorization; every service entrypoint still validates the actor. |
| Experiment lifecycle state | `cms.experiments.schemas`, `Experiment.transition_to`, `ExperimentRun.transition_to` | Do not duplicate status strings, transition maps, or terminal-state logic. |
| Service facade | `cms.experiments.services` | Views and callers use the public facade, not private service submodules or direct model writes. |
| Range provisioning | `cms.scenarios.hydrator`, `shared.schemas.RequestSpec`, `cms.models.Request`, `engine.services.create_range`, `RangeInstance` | Preserve the hydrate -> request -> engine handoff and request_id correlation. |
| Range event bridge | `cms.handlers.experiment_bridge`, `cms.experiments.events`, `shared.messages.envelope.parse_sns_message` | Keep event envelopes and redelivery behavior centralized. |
| Execution planning | `cms.experiments.orchestrator.execution_plan`, `RunExecutionPlan`, `ScriptCommand` | Extend the existing plan boundary; do not create parallel command DTOs. |
| Script/prompt validation | `shared.script_context.ScriptExecutionContext`, `shared.template_vars.build_instance_data`, `docs/architecture/ai-experiment-execution-boundary.md` | All prompt, S3 key, instance data, and AI policy handling passes this boundary. |
| Guest execution | `shifter/engine/provisioner/executors/factory.py`, `SSMExecutor`, `GuestSSHExecutor`, `RangePodSSHExecutor` | Executor implementation uses provider-routed contexts and shared executor exceptions/results. |
| Task runtime | `engine.ecs`, `shared.cloud.TaskRunner`, `shared.cloud.gcp.task_runner`, `shared.cloud.sensitive_env` | Use structured argv, task-runner adapters, and sensitive-env routing. |
| Storage | `cms.experiments.s3`, `shared.cloud.ObjectStorage`, provisioner `cloud.ObjectStorage`, `config.generate_presigned_url` | Use provider adapters and key validators; no direct SDK calls in domain code. |
| Upload safety | `ScriptUploadInput`, signed upload tokens, exact-size verification, `shared.uploads.inspection.validate_text_header` | Preserve script upload validation and full-body text inspection. |
| Exceptions | `cms.experiments.exceptions`, `shared.cloud.exceptions`, provisioner `executors.base` exceptions | Translate at boundaries; do not add another exception hierarchy. |
| Logging | `shared.log_sanitize`, provisioner `log_redact` | Log ids/status/task refs only; sanitize user-controlled values and fingerprint/mask sensitive identifiers. |
| Audit | `risk_register.services.audit_log`, `audit_log_system_event`, `AuditLog` | Reuse existing audit events; do not invent experiment telemetry tables. |
| Import policy | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, ADR-001 | CMS imports `shared` and service facades; only `shared` imports `cyberscript` directly. |
| Test policy | ADR-019, `scripts/adr_guard/boundary_mock_baseline.json` | Prefer real model/service behavior and cloud/process boundary mocks; do not grow first-party patch coupling. |

## Cross-Cutting Layers

- Auth surface: browser flows stay behind `threat_research_required`; service
  entrypoints call `validate_cms_authoring_user`; experiment rows, script
  assets, artifacts, and bundles remain scoped to `Experiment.user` /
  `ScriptAsset.user`. Worker events are not a new user-auth boundary and must
  be correlated through persisted `request_id` / `ExperimentRun`.
- Scenario and input validation: experiment creation uses
  `ExperimentCreateInput`, `ScriptAssignmentInput`, scenario registry access
  checks, `hydrate_scenario`, model `full_clean()`, and service ownership
  checks. Executor work must not trust form JSON, event JSON, or
  `provisioned_instances` until it has passed the existing schema/context gates.
- Script/prompt validation: `ScriptExecutionContext` validates script type,
  display names, target ids, private IPs, S3 keys, prompt text, template
  substitutions, and AI policy payloads. Provider-aware expansion must add a
  target abstraction here instead of weakening validators.
- Secret-handling surface: uploaded script content, prompt bodies, Claude
  transcripts, private keys, upload tokens, presigned URLs, cloud credentials,
  DB settings, field-encryption keys, and GDC access secrets must not appear in
  process argv, task env literals, event payloads, audit JSON, logs, docs
  examples, or user-visible errors. If `EXPERIMENT_PAYLOAD` ever carries
  secret material, replace plain env transport with the existing
  sensitive-env/Secret or object-reference pattern before enabling it.
- Env/config shape: Django-side task launch uses `config/_cloud.py` and
  `ENGINE_TASK_*` / optional `EXPERIMENT_TASK_*` settings. GCP provisioner Jobs
  need `_get_gcp_provisioner_env_overrides()` parity for any executor env they
  require. New settings require env-manifest/runtime-inventory/deployment docs
  updates when they become production contract.
- OS-level exposure: container argv may carry only bounded operation names and
  ids such as `experiment execute --experiment-id ... --run-id ... --request-id
  ...`. Raw commands, prompts, scripts, presigned URLs, and credentials must not
  move into argv. Remote shell text must be fixed wrappers over encoded data or
  structured executor input, not user-controlled shell concatenation.
- Error-envelope surface: HTTP responses and notifications use curated typed
  messages or generic unexpected-error text. Worker/run errors may persist
  sanitized operational summaries in `ExperimentRun.error_message`, but must
  not echo raw Pydantic `input_value`, prompt bodies, rendered commands,
  provider responses, SSH stderr containing secrets, or presigned URLs.
- Persistence surface: keep `transaction.atomic()`, `select_for_update()`,
  max-parallel accounting, `dispatch_task_arn` / `collect_task_arn`
  idempotency, model transition methods, and request_id correlation. Do not use
  `ExperimentRun.metadata` as an unvalidated provider dump or future archive
  schema.
- Observability surface: keep orchestrator logs under
  `cms.experiments.orchestrator`, provisioner logs through its logging config,
  and experiment completion/failure audit through `risk_register`. Evidence
  artifacts need refs/digests/types; presigned URLs are bearer credentials and
  are not observability data.
- Runtime/platform validators: import-linter, ADR guard, Ruff, provisioner
  pytest, task-runner tests, Kubernetes validation, Terraform lint, and
  actionlint remain hard gates for touched surfaces. Do not weaken them to make
  a partial executor pass.

## Extensibility View

The required seam is a provider-aware execution target passed through
`ScriptExecutionContext` and `build_guest_execution_context()`.

It should parameterize only facts that already vary:

- provider (`aws`, `gcp`)
- target identifier and transport (`instance_id` for SSM, private IP plus GDC
  namespace/network/secret refs for range-pod SSH)
- guest OS shell family (`AWS-RunShellScript` vs `AWS-RunPowerShellScript`)
- object download mode (cloud-adapter presigned URL or storage reference)
- artifact collection mode and artifact class
- timeout/retry policy per command phase

Do not parameterize policy by ad hoc script type, UI flow, scenario id,
hardcoded cloud CLI, or test fixture. The next reasonable variation is another
provider or artifact class; it should add an execution-target/storage/profile
branch, not copy the executor workflow.

## Whole-Repo Scope

Any future implementation must evaluate changes against:

- `shifter/shifter_platform/cms/experiments/**`
- `shifter/shifter_platform/cms/handlers/experiment_bridge.py`
- `shifter/shifter_platform/cms/management/commands/reconcile_range_events.py`
- `shifter/shifter_platform/cms/scenarios/**`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/engine/**`
- `shifter/shifter_platform/shared/**`
- `shifter/cyberscript/script_context.py`
- `shifter/engine/provisioner/main.py`
- `shifter/engine/provisioner/executors/**`
- `shifter/engine/provisioner/cloud/**`
- `shifter/engine/provisioner/config.py`
- task/deploy surfaces under `platform/terraform/**`, `platform/k8s/**`,
  `.github/workflows/**`, and installation/runtime env renderers if executor
  runtime configuration changes
- `docs/architecture/ai-experiment-execution-boundary.md`
- `docs/architecture/script-context-sanitization-preflight-700.md`
- `docs/architecture/aces-experiment-core-preflight-1235.md` if redesigning
  rather than finishing the legacy feature
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, `docs/adr/index.yaml`, and `docs/adr/exceptions.yaml`
  if guardrails or exceptions change

## Gotchas And Anti-Patterns

- Do not enable `EXPERIMENTS_ENABLED` by default, register routes, or make other
  features depend on experiments before executor and artifact flows work
  end-to-end.
- Do not remove `_enforce_aws_only_provider` without first making the execution
  context and executor provider-aware.
- Do not let CMS import `cyberscript` directly. Use `shared.script_context`.
- Do not render `aws s3 cp` / `gcloud storage cp` as feature logic. Use storage
  adapters and pass bounded references or signed URLs through a classified
  transport.
- Do not add an experiment-specific SSM/SSH abstraction when
  `build_guest_execution_context()` already owns that provider split.
- Do not put `EXPERIMENT_PAYLOAD`, rendered commands, prompt bodies, upload
  tokens, presigned URLs, or private keys into logs, audit records, argv, DLQ
  messages, or persisted metadata.
- Do not create duplicate statuses, DTOs, event envelopes, queue publishers,
  storage helpers, exception hierarchies, or workflow schedulers.
- Do not catch broad executor/provider exceptions and surface raw `str(exc)` to
  users or notifications.
- Do not add first-party internal mocks to prove the executor path. Mock cloud,
  process, Kubernetes, SSH, or SDK boundaries and drive real service/model code.
- Do not treat "staff only" as a safety boundary for command rendering or AI
  execution.
- Do not hand-edit `CHANGELOG.md`; use `changelog.d/1195.<type>.md` if the
  implementation is user-visible.

## Non-Goals

- This note does not choose product disposition; it constrains each possible
  disposition.
- Do not implement the executor, artifact collector, provider-aware script
  context, UI changes, migrations, ACES sidecars, or route exposure as part of
  architecture preflight.
- Do not redesign scenario authoring, CTF scoring, Mission Control terminals,
  range provisioning, task runners, cloud adapters, or secret hydration beyond
  what the selected experiments disposition requires.
- Do not add new Ground Control requirement UIDs for this requirement-free run.
- Do not weaken ADR guard, import-linter, Ruff, provisioner tests, actionlint,
  Terraform, Kubernetes, or secret-scanning gates.

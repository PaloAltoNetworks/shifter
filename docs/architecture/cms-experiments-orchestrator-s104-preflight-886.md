# CMS Experiments Orchestrator S104 Preflight (#886)

Status: pre-implementation guidance

Date: 2026-06-22

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/886>

Superseded note: ADR-027 / issue #1195 removed the legacy `cms.experiments`
orchestrator. This preflight is historical and no longer describes active
implementation guidance.

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Scope Boundary

Issue #886 is a maintainability refactor for SonarCloud `python:S104`: split
`cms/experiments/orchestrator.py` without changing experiment lifecycle
behavior, task dispatch, range provisioning, event routing, status transitions,
or user-visible error semantics.

The public import path is still `cms.experiments.orchestrator`. Existing
`from cms.experiments.orchestrator import ExperimentOrchestrator`,
`ScriptCommand`, `RunExecutionPlan`, `EVENT_TYPE_EXPERIMENT`, and
`EVENT_TYPE_RUN` imports must keep working after the file becomes a package.

## Architecture Decisions

- Treat the split package's `__init__.py` as the public facade. Private
  `_*.py` modules are implementation details, not new cross-layer contracts.
- Preserve facade-level patch compatibility for legacy tests that target
  `cms.experiments.orchestrator.Experiment`, `ExperimentRun`,
  `ExperimentScript`, `engine_create_range`, `start_experiment_task`,
  `build_instance_data`, and `audit_log_system_event`. Split helpers must
  either late-resolve those names through the facade or the tests must be
  deliberately rewritten to behavior/boundary assertions that shrink the
  ADR-019 baseline.
- Keep cohesive responsibilities together. Valid split boundaries are existing
  responsibilities such as public types, run scheduling/state handling,
  execution-plan construction, range provisioning, task dispatch/artifact
  collection, and completion/audit handling. Do not split by arbitrary line
  ranges or introduce a generic workflow framework.
- Keep logging on the stable public logger name
  `cms.experiments.orchestrator`, mirroring the
  `engine/provisioner/orchestrators/setup_orchestrator.py` split pattern.
- Reuse existing state, schema, dispatch, audit, and validation contracts.
  This refactor should not add tables, DTOs, repositories, exception
  hierarchies, settings, task-runner protocols, or alternate command renderers.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #886 |
| --- | --- | --- |
| Package facade and patchable names | `cms/services/__init__.py`, `cms/experiments/services/__init__.py` | Re-export every public name and keep package-level patched names effective across private modules. |
| Class-style S104 split | `engine/provisioner/orchestrators/setup_orchestrator.py` plus `_setup_types.py`, `_setup_logging.py`, `_setup_panos.py` | Prefer small private helper modules/mixins and stable public logger/import names over a new abstraction. |
| Experiment statuses and validation | `cms.experiments.schemas`, `Experiment.transition_to`, `ExperimentRun.transition_to` | Use existing enums and transition methods. Do not duplicate status strings or bypass model transition validation. |
| Experiment domain errors | `cms.experiments.exceptions.ExecutionPlanError`, `ExperimentError`, `shared.exceptions.CMSError` | Keep plan failures in the existing exception hierarchy. Do not add local one-off exception classes. |
| AI/script command validation | `shared.script_context.ScriptExecutionContext`, `build_ai_execution_policy_payload`; `shared.template_vars.build_instance_data` | All user-controlled script/prompt/runtime values must pass the shared shims. Do not import `cyberscript` directly from `cms`. |
| Range provisioning | `cms.scenarios.hydrator.hydrate_scenario`, `shared.schemas.RequestSpec`, `engine.services.create_range`, `cms.models.Request`, `cms.models.RangeInstance` | Preserve the hydrate -> request record -> request spec -> engine facade -> range tracking flow. |
| Task dispatch | `cms.experiments.ecs.start_experiment_task`, `shared.cloud.get_task_runner` | Keep experiment task launch behind the existing ECS/GKE task runner adapter. Do not call provider SDKs from the orchestrator split. |
| Message envelope and event routing | `shared.messages.envelope.parse_sns_message`, `cms.experiments.handlers` | Do not move SQS/SNS parsing or notification broadcast concerns into the orchestrator package. |
| Audit and observability | `risk_register.services.audit_log_system_event`, `risk_register.services.StateChange`, `risk_register.models.AuditLog` | Preserve system audit events and non-secret structured logging. Do not invent a parallel telemetry schema. |
| Layer enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | `cms` may use `shared` and `engine.services`; only `shared` may import `cyberscript` directly. |
| Test policy | ADR-019, `scripts/adr_guard/boundary_mock_baseline.json`, `tests/test_test_suite_structure.py` | New first-party internal patch targets are not acceptable. Touched tests should move toward behavior tests or real cloud boundary patches. |

## Cross-Cutting Layers The Design Must Pass

- Auth and authorization surface: the orchestrator is reached from experiment
  worker events, not from a new user-facing endpoint. It must keep using the
  persisted `Experiment.user`, scenario access/hydration flow, agent soft-delete
  checks, and existing service/view authorization upstream. No new public caller
  should bypass `cms.experiments.services` or view-level staff/Threat Research
  checks.
- Validation surface: `ScriptExecutionContext` remains the policy gate for
  EC2 instance IDs, S3 keys, private IPs, prompt text, template substitution
  values, and AI policy payloads. `cms.experiments.schemas` remains the source
  for `ExperimentStatus`, `RunStatus`, `ScriptType`, and terminal status sets.
  The provider gate in `_enforce_aws_only_provider` must stay explicit until a
  provider-aware execution target exists.
- Secret-handling surface: this refactor must not introduce secrets. Do not log
  command payloads, rendered prompts, raw task environment, Django settings,
  database credentials, cloud credentials, upload tokens, or rejected Pydantic
  `input_value` data. If a future change makes `EXPERIMENT_PAYLOAD` carry
  secret material, that is outside this issue and must first update the shared
  task-runner secret policy instead of relying on plain env overrides.
- Env/config shape: task configuration belongs in
  `cms.experiments.ecs._get_task_config` and `shared.cloud` adapters. Do not add
  new settings or read task runner env in private orchestrator modules.
- OS-level exposure: `start_experiment_task` passes structured command arrays
  whose argv values are only operation name plus experiment/run/request IDs.
  Script/prompt command bodies stay in the existing JSON payload path and are
  rendered only by `ScriptExecutionContext` fixed wrappers with base64 data and
  structured subprocess argv. Do not build shell strings by joining argv or
  interpolating raw prompts/S3 keys into shell syntax.
- Error-envelope surface: worker failures may set `ExperimentRun.error_message`
  and log full operational detail, but validation messages must keep the
  current redaction behavior (`ValidationError.errors(include_input=False)`).
  Do not route raw exception strings into HTTP responses or user notifications.
- Persistence and transaction surface: `schedule_runs` must preserve
  `transaction.atomic()`, `select_for_update()`, max-parallel slot accounting,
  and idempotent metadata checks (`dispatch_task_arn`, `collect_task_arn`).
  Status writes should continue through model transition methods.
- Observability surface: keep log records under `cms.experiments.orchestrator`
  and audit experiment completion/failure via `audit_log_system_event`. IDs,
  statuses, request IDs, and task ARNs are acceptable operational metadata;
  prompts, commands, tokens, and secret values are not.
- Import enforcement surface: private split modules must obey the same layer
  rules as the current file. In particular, import `shared.script_context` and
  `shared.template_vars`, not `cyberscript.*`.
- CI/workflow surface: SonarCloud sees the split files under
  `sonar.sources`; Ruff, mypy, import-linter, ADR guard, and pytest see the
  Python package path. Do not weaken any guardrail to make the split easier.

## Extensibility View

The next likely changes are a new script type or a provider-aware execution
target. The extension point for script types belongs at the existing
`ScriptType`/`ScriptExecutionContext` command-builder boundary, not in copied
status logic or local string dispatch. The extension point for non-AWS
execution belongs in the execution-target validation and task-dispatch adapter,
not by weakening the current AWS-only gate.

Keep any private helper interface parameterized by facts that already vary:
run, script assignment, provisioned instances, command list, task command
(`execute` or `collect`), and metadata key. Do not parameterize policy concepts
that do not vary yet, such as auth, audit schema, provider support, or status
vocabulary.

## Whole-Repo Scope

Likely implementation files are limited to:

- `shifter/shifter_platform/cms/experiments/orchestrator.py`, replaced by
  `shifter/shifter_platform/cms/experiments/orchestrator/__init__.py` and
  private `orchestrator/_*.py` modules
- `shifter/shifter_platform/cms/experiments/handlers.py` only if imports need
  to follow the stable public package path
- `shifter/shifter_platform/tests/cms/experiments/test_orchestrator*.py`
- `shifter/shifter_platform/tests/cms/experiments/test_handlers.py` only for
  routing tests affected by the public facade
- `scripts/adr_guard/boundary_mock_baseline.json` only if touched tests shrink
  legacy first-party patch counts

Canonical configs and checks that will see the artifact:

- `.importlinter`
- `scripts/check_layer_imports/layer_imports.yaml`
- `scripts/adr_guard/adr_guard.py`
- `shifter/shifter_platform/pyproject.toml`
- `sonar-project.properties`
- `.github/workflows/_quality.yml`

## Gotchas And Anti-Patterns

- Do not leave both `orchestrator.py` and an `orchestrator/` package. The
  module path must resolve unambiguously.
- Do not move callers to private paths such as
  `cms.experiments.orchestrator._planning` or expose private modules in
  `__all__`.
- Do not break facade-level monkeypatch behavior accidentally by binding
  dependencies once in a private module when legacy tests patch the facade.
- Do not introduce direct `cyberscript` imports in `cms`; use shared shims.
- Do not duplicate experiment status enums, transition maps, Pydantic schemas,
  request specs, task-runner config parsing, audit helpers, or error classes.
- Do not change logger names to private module names unless every caplog/log
  routing assumption is updated deliberately.
- Do not add first-party internal patch targets. If tests are touched, prefer
  real model/service behavior and cloud/process boundary mocks.
- Do not broaden provider support, change AI command policy, move payloads into
  process argv, or put secret material in `EXPERIMENT_PAYLOAD` under this issue.
- Do not weaken Ruff, mypy, import-linter, ADR guard, or Sonar settings.

## Non-Goals

- Changing experiment lifecycle semantics, event names, state transitions, or
  run scheduling behavior.
- Adding new providers, script types, AI permissions, network egress, task
  runtime hardening, or secret-delivery mechanisms.
- Reworking experiment views, services, models, migrations, notifications,
  SQS envelope parsing, scenario hydration, or engine range provisioning.
- Rewriting all orchestrator tests to ADR-019 ideal form unless doing so is
  necessary to preserve behavior through the split.
- Adding a new ADR or architecture rule. Existing ADR-001, ADR-012, and
  ADR-019 guardrails already cover this refactor.

## Validation Expectations

Run the issue-requested checks after implementation:

```bash
cd shifter/shifter_platform
uv run ruff check .
uv run mypy .
uv run pytest tests/cms/experiments -k orchestrator
cd ../..
python3 scripts/adr_guard/adr_guard.py --changed --level fast
```

If private imports, facade behavior, or cross-layer imports change, also run:

```bash
cd shifter/shifter_platform
uv run lint-imports --config ../../.importlinter
```

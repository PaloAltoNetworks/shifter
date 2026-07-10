# CMS Experiments View-Flow Preflight (#698)

Status: pre-implementation guidance

Date: 2026-06-22

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/698>

Superseded note: ADR-027 / issue #1195 removed the legacy `cms.experiments`
view surface. This preflight is historical and no longer describes active
implementation guidance.

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Scope Boundary

Issue #698 is a maintainability refactor of
`shifter/shifter_platform/cms/experiments/views.py` by request/response flow.
It must not change URL names, URL patterns, templates, messages, user-visible
routing, permissions, experiment lifecycle behavior, direct-to-S3 upload
semantics, artifact download behavior, or orchestration outcomes.

The public import path `cms.experiments.views.<view_name>` must remain stable
for `cms/experiments/urls.py` and any tests or callers that import view symbols.
The preferred local pattern is the scenario-editor split: keep
`cms.experiments.views` as a small public re-export module and put real view
functions in flow-focused sibling modules such as list/create/detail/scripts.

## Architecture Decisions

- Views remain HTTP adapters: authorize, parse request shape, call the public
  `cms.experiments.services` facade, render/redirect/return JSON.
- Domain validation and orchestration-adjacent branching belong behind the
  experiments service surface. In particular, scenario access, demo-vs-CTF
  rejection, instance-name resolution, script assignment validation, ownership
  checks, state transitions, event publishing, upload-token verification, S3
  object inspection, and presigned download URL generation must not move into
  view modules.
- Use flow modules plus a public facade rather than introducing a new generic
  controller framework. A class-based view is acceptable only if it follows
  existing Django conventions and keeps the same service-boundary rules; do not
  create a Shifter-specific view abstraction for this issue.
- Preserve the patchable `cms.experiments.services` facade. Existing service
  submodules intentionally late-resolve patchable names through that package;
  view modules should import and call the facade, not private service modules.
- Reuse existing schemas, exceptions, logging, upload, audit, scenario registry,
  and test conventions. Do not create duplicate DTOs, exception hierarchies,
  validation tables, workflow state machines, or repository layers.
- No new ADR is needed. Existing ADR-001 service-boundary rules and ADR-019 test
  boundary rules already cover the refactor.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #698 |
| --- | --- | --- |
| Per-flow view split | `cms.scenario_editor.views` re-exporting `views_list_detail`, `views_form`, `views_actions`, `views_yaml`; `mission_control.views` package facade | Keep stable public view names while moving implementation into flow-focused modules. |
| Service facade | `cms.experiments.services.__init__` | Views call `services.<name>` only; do not import private service submodules or models for domain work. |
| Request/domain schemas | `cms.experiments.schemas.ExperimentCreateInput`, `ScriptUploadInput`, `ScriptAssignmentInput`, `ScriptType`, `ExperimentStatus`, `RunStatus` | Extend or reuse these if parsing gaps exist; do not duplicate validation in views. |
| Domain exceptions | `cms.experiments.exceptions` subclasses of `shared.exceptions.CMSError` | Catch existing typed exceptions; do not add view-local error classes. |
| Auth policy | `shared.auth.threat_research_required`, `validate_cms_authoring_user`, `can_edit_cms_authoring` | Keep every view decorated and every service entrypoint revalidating the user. |
| Scenario access | `cms.scenarios.registry.check_scenario_access`, `load_demo_scenario_template`, `list_all_scenarios(user=...)` | Access filtering and demo-scenario resolution must be service-side or behind a narrow experiments service helper. |
| Upload security | `cms.experiments.s3`, `cms.experiments.services.initiate_script_upload`, `complete_script_upload`, `shared.uploads.inspection.validate_text_header` | Preserve signed-token, exact-size, full-body text inspection, and provider-adapter boundaries. |
| Error envelopes | `shared.errors.classify_user_message`; Django messages for HTML flows | JSON responses must use authored/classified messages; unexpected HTML errors stay generic. |
| Log hygiene | `shared.log_sanitize.safe_log_value`, existing inline CR/LF stripping where CodeQL needs it | Sanitize user-controlled IDs/paths. Never log tokens, presigned URLs, raw prompts, uploaded bodies, or full POST payloads. |
| Audit/persistence | `risk_register.services.audit_log`, `AuditEvent`, `Experiment.transition_to`, `ExperimentRun.transition_to`, `transaction.atomic` | Services own writes, state transitions, and audit records. |
| Tests | `tests/cms/experiments/test_views.py`, `test_view_flows.py`, ADR-019 baseline | Prefer Django client behavior tests with cloud boundary mocks over first-party internal patches. |
| Changelog | `changelog.d/README.md`, `towncrier.toml` | For issue-requested changelog coverage, add `changelog.d/698.changed.md`; do not hand-edit `CHANGELOG.md`. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: each exported view must keep `@threat_research_required`;
  POST-only mutation endpoints must keep `@require_POST`, and GET/POST mixed
  flows should prefer `@require_http_methods(["GET", "POST"])` over manual 405
  branching when that does not change behavior. Service entrypoints must still
  call `_validate_user` / `validate_cms_authoring_user`.
- Scenario access surface: non-staff Threat Research users may see only
  scenarios allowed by `list_all_scenarios(user=...)` / `check_scenario_access`.
  Hidden, disabled, staff-only, missing, or CTF scenarios must fail through the
  existing experiments validation path without creating experiments or revealing
  extra scenario detail.
- Schema and model validation surface: form data should become
  `ExperimentCreateInput`; script upload initiation should become
  `ScriptUploadInput`; model writes must keep `full_clean()` in services.
  Template variables in Claude prompts must continue to validate through
  `shared.template_vars.TemplateString` with scenario instance context.
- Ownership and persistence surface: experiment, script, bundle, and artifact
  lookups remain scoped by `user` inside services. Views must not perform
  direct ORM ownership checks or bypass the service layer for convenience.
- Upload token and S3 surface: script upload completion must continue verifying
  the signed token, user id, exact object size, object existence, and full-body
  text inspection before creating `ScriptAsset`. Presigned URLs and upload
  tokens are bearer credentials and must not be logged, audited, persisted in new
  fields, or returned in HTML messages.
- Orchestration/event surface: starting an experiment remains
  `services.start_experiment`, which owns run creation, state transition,
  best-effort event publication, and audit. View modules must not import
  `cms.experiments.orchestrator`, `events`, ECS/task helpers, or status maps to
  branch locally.
- Error-envelope surface: JSON endpoints return a stable `{"error": ...}` shape
  with `classify_user_message` for typed validation/upload failures. HTML flows
  may show curated typed-exception messages already used today, but unexpected
  exceptions must log server-side and show the generic message.
- Logging/observability surface: flow modules may use `logging.getLogger(__name__)`
  or a small shared view-support helper, but user-controlled values must be
  sanitized. Log only operational metadata such as user id, experiment id,
  artifact id, status, and scenario id; do not log prompts, script contents,
  POST bodies, presigned URLs, upload tokens, S3 response payloads, or secrets.
- Config/env surface: this refactor should not add settings. Existing upload
  limits and storage provider configuration stay in `config.settings`,
  `cms.experiments.s3`, and `shared.cloud`.
- OS/runtime exposure: the refactor should not introduce subprocesses, shell
  commands, process argv, temp files, or new environment variables. Script and
  Claude execution remains behind the orchestrator and
  `shared.script_context.ScriptExecutionContext`.
- Import-enforcement surface: the code remains inside `cms` and may depend on
  `shared` and `cms.scenarios` service/registry surfaces. Do not introduce
  direct `mission_control`, `ctf`, `engine`, or `cyberscript` imports from the
  new view modules.
- Test-boundary surface: new tests must not grow first-party internal patch
  counts under ADR-019. Mock external cloud/framework transport boundaries
  only, such as `boto3.client` for storage/event publication.

## Extensibility View

The next likely variations are another experiment request flow, another script
assignment type, or another upload/storage backend. The seam should be a small
service-facing parser/helper that accepts the varying HTTP form/query facts
(`user`, `post_data`, `scenario_id`, `upload_token`, object ids) and returns
existing schemas or service results. Script-type branching belongs in
`ScriptType` / `ExperimentCreateInput` / execution-context validation, not in
views. Provider variation belongs in `cms.experiments.s3` and `shared.cloud`,
not in view modules.

## Whole-Repo Scope

Likely implementation files are limited to:

- `shifter/shifter_platform/cms/experiments/views.py`
- New `shifter/shifter_platform/cms/experiments/views_*.py` flow modules
- `shifter/shifter_platform/cms/experiments/services/*.py` and
  `services/__init__.py` only for narrow service-surface helpers that remove
  domain branching from views
- `shifter/shifter_platform/cms/experiments/urls.py` only if imports need to
  continue pointing at the public facade
- `shifter/shifter_platform/tests/cms/experiments/test_views.py`
- `shifter/shifter_platform/tests/cms/experiments/test_view_flows.py`
- `changelog.d/698.changed.md` if satisfying the issue's changelog criterion via
  a towncrier fragment

Canonical configs and checks that will see the artifact:

- `.importlinter`
- `scripts/adr_guard/adr_guard.py`
- `scripts/adr_guard/boundary_mock_baseline.json`
- `shifter/shifter_platform/pyproject.toml`
- `.gc/plan-rules.md`
- `towncrier.toml`
- `changelog.d/README.md`

## Gotchas And Anti-Patterns

- Do not leave both `views.py` and a `views/` package for the same import path.
  If a package split is chosen, remove the module ambiguity deliberately; the
  simpler local precedent is sibling `views_*.py` modules plus a facade file.
- Do not make URL route names, templates, redirects, context keys
  (`active_nav`, `experiments`, `scripts`, `experiment`, `scenarios`), or JSON
  keys drift during the split.
- Do not move `_validate_experiment_create_input` unchanged into another view
  module if it still loads scenarios and computes instance names there; that is
  the domain branch this issue is trying to push behind services.
- Do not duplicate `ExperimentCreateInput`, `ScriptUploadInput`, upload-token
  parsing, status constants, scenario access checks, model validators, or S3
  helper behavior in the view layer.
- Do not catch broad exceptions and return raw `str(exc)` in JSON. Log full
  details server-side and return fixed/classified user-facing text.
- Do not add first-party internal mocks to view tests to make the refactor easy.
  If tests need to drive failure paths, prefer real service behavior or existing
  cloud/framework boundary patches.
- Do not hand-edit `CHANGELOG.md`; use a fragment when changelog coverage is
  required.

## Non-Goals

- Changing experiment creation/start/cancel semantics, state transitions,
  orchestration scheduling, event names, queue publication, or audit schema.
- Redesigning script upload, artifact download, storage provider adapters, S3 key
  normalization, or upload inspection.
- Introducing new permissions, groups, middleware, settings, template structure,
  URL shape, frontend behavior, API response shape, providers, script types, or
  database migrations.
- Refactoring `cms.experiments.orchestrator`, handlers, consumers,
  notifications, models, migrations, scenario registry, or shared auth/error
  utilities except for a narrow service helper needed to keep views HTTP-only.

## Validation Expectations

After implementation, run at least:

```bash
cd shifter/shifter_platform
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/cms/experiments/test_views.py tests/cms/experiments/test_view_flows.py
cd ../..
python3 scripts/adr_guard/adr_guard.py --files shifter/shifter_platform/cms/experiments --level fast
```

If imports move across modules, also run:

```bash
cd shifter/shifter_platform
uv run lint-imports --config ../../.importlinter
```

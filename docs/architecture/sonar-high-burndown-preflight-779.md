# SonarCloud HIGH Burn-Down Preflight (#779)

Status: pre-implementation guidance

Date: 2026-06-22

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/779>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Scope Boundary

Issue #779 burns down SonarCloud HIGH-impact findings from the dev-to-main
analysis surface. It is a maintainability and static-analysis cleanup, not a
product behavior change.

Keep the scope to the reported HIGH rules:

- `python:FunctionComplexity`
- `python:S8554`
- `python:S134`
- `css:S4664`

Do not change runtime authorization, provisioning semantics, persistence
schemas, user-visible error envelopes, deployment workflows, or lower-severity
Sonar findings as part of this issue unless a local refactor cannot remain
correct without a narrow supporting edit.

## Architecture Decisions

- Treat complexity findings as structural maintainability defects. Extract
  cohesive helpers, small private modules, or outcome/result types only where
  they preserve the existing behavior and local domain boundary.
- Keep public service and package facades stable. Split private implementation
  behind existing exports such as `cms.services`, `ctf.services`,
  `engine.services`, and `orchestrators.setup_orchestrator`; do not create new
  cross-layer APIs to make one function smaller.
- For provisioner setup orchestration, follow the existing
  `_AttemptOutcome` / `_StepAttemptContext` precedent. Keep retry exhaustion
  semantics distinct: transport/PAN-OS hard failures raise `SetupError`, while
  soft command failures return a failed `StepResult` where that is the current
  contract.
- For Python logging findings, fix interpolation at the call site by passing
  values as logger arguments. Do not remove existing sanitizers or fingerprints
  to make the code look simpler.
- For CSS selector-order findings, preserve the cascade deliberately. Reorder
  or narrow selectors after comparing the properties they write; do not make
  broad visual restyles or enable/disable stylelint rules under this issue.
- Do not add new Sonar, Ruff, or lint suppressions. No new `# noqa: C901`,
  blanket `# noqa`, `sonar.issue.ignore.multicriteria`, or false-positive /
  wontfix disposition belongs in the implementation without explicit PR
  authorization.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #779 |
| --- | --- | --- |
| Complexity gate | ADR-012, `docs/adr/complexity-backlog.md`, `scripts/adr_guard/adr_guard.py`, package `pyproject.toml` files | Keep the no-new-suppressions invariant. If a documented offender is removed, update the backlog note in the same PR; do not add new backlog rows by default. |
| Python lint surface | `.pre-commit-config.yaml`, package-local Ruff configs, `_quality.yml` Python lint/test jobs | Validate the touched package's native Ruff/pytest surface instead of adding a new quality path. |
| Sonar source inventory | `sonar-project.properties` | HIGH count is measured on Sonar's configured source set. Do not change source/exclusion rules to hide findings. |
| Layer boundaries | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Keep cross-layer imports on facades (`cms.services`, `engine.services`, `shared`). Private split modules remain same-layer details. |
| Shared schemas | `shared.schemas.*`, `shared.schemas.persistence`, `shared.schemas.registry` | Non-`shared` platform layers must not import `cyberscript` directly. Reuse shared shims and existing Pydantic validation. |
| CMS service validation | `cms.services._common` validators, `shared.auth.validate_cms_authoring_user` | Reuse caller/user/range/string/int validators. Do not duplicate user-shape or ownership validation. |
| CTF domain errors and bridges | `ctf.exceptions`, `ctf.bridges`, `ctf.services.*` | Keep CTF-to-CMS calls behind `ctf.bridges`; preserve authored `CTF*Error` types and `details` payloads. |
| Provisioner orchestration | `SetupPlan`, `SetupStep`, `Executor`, `CommandResult`, `SetupError`, `_setup_logging`, `_setup_panos`, `_setup_types` | Preserve command execution, rendering, masking, and retry contracts when splitting high-complexity provisioner code. |
| Logging sanitization | `shared.log_sanitize`, `shifter/engine/provisioner/log_redact`, `_SetupOrchestratorLoggingMixin._mask_sensitive_output` | Lazy formatting and sanitization both apply. Sanitized/fingerprinted values should still be passed as `%s` arguments. |
| Error envelopes | `shared.errors`, `ctf.views._access._json_error`, `cms.exceptions.CMSError`, `engine.services._common.EngineError`, provisioner `SetupError` | Do not surface raw exception strings, cloud payloads, stack traces, or ownership details to users. |
| Persistence | Django models/managers, `SoftDeleteMixin`, model transition methods, existing `transaction.atomic()` and `select_for_update()` sites | Refactors may move code, but must not split existing atomicity or add duplicate repositories/tables/DTOs. |
| Observability and audit | `config.logging.ECSFormatter`, `risk_register.services.audit_log*`, existing logger names on split packages | Keep stable logger names and audit/event schemas. IDs/statuses are acceptable; secret material and rendered commands are not. |
| CSS quality | `shifter/shifter_platform/static/css/*.css`, `.stylelintrc.json`, Sonar `css:S4664` | Fix selector ordering in the owning stylesheet. Do not broaden stylelint policy in this issue. |

## Cross-Cutting Layers The Design Must Pass

- Auth and authorization: no new endpoint or service bypass is needed. CMS
  changes must continue through CMS service validators and ownership checks;
  CTF changes must keep organizer/participant access in views/services and use
  `ctf.bridges` for CMS calls; Mission Control changes must keep
  `shared.auth` decorators/predicates intact.
- Validation and schema shape: persisted range/app/request data still flows
  through `shared.schemas` and `shared.schemas.persistence`; CMS and CTF service
  inputs keep their existing validators; provisioner plans keep `SetupPlan` /
  `SetupStep` / `get_context()` contracts. Do not introduce parallel schemas
  just to lower a function's branch count.
- Secret handling: user-controlled log values use `safe_log_value`; sensitive
  identifiers use `safe_log_id` or `safe_log_fingerprint` when the existing
  call site does so; setup stdout/stderr continues through
  `_mask_sensitive_output`; Kubernetes/GCP task env splitting remains governed
  by `shared.cloud.sensitive_env`. No token, password, secret ARN payload,
  rendered command body, or provider credential should move into logs, HTTP
  responses, process argv, CSS, docs, or tests.
- Env/config binding: this cleanup should not add runtime settings, env vars,
  Terraform variables, Kubernetes env, or workflow inputs. Quality enforcement
  remains in package `pyproject.toml`, `.pre-commit-config.yaml`,
  `.github/workflows/_quality.yml`, `.stylelintrc.json`, and
  `sonar-project.properties`.
- OS/process exposure: bootstrap/provisioner command code must keep existing
  fixed-argv subprocess patterns and no-shell assumptions. Do not join
  untrusted values into shell strings or move secrets into command-line args.
- Error envelopes: Django/JSON responses keep authored messages and existing
  status mappings; worker/provisioner internals keep operational detail in logs
  only after sanitization. Refactors must not leak private module names,
  provider errors, stack traces, or ownership mismatches.
- Persistence and transactions: keep current atomic sections, row locks,
  status transitions, soft-delete behavior, and audit writes coupled exactly as
  they are today unless the touched function already has a tested helper for
  that concern.
- Import and workflow enforcement: changes under guardrail paths must satisfy
  ADR guard, import-linter, actionlint, Terraform/Kubernetes validators where
  relevant, and package-local Ruff/pytest. Do not weaken gates to make the
  burn-down pass.

## Extensibility View

The only extension seams needed are private and local:

- helper functions that parameterize operation facts already varying inside a
  module, such as operation name, target status, audit action, retry policy, or
  parser result;
- small result/outcome dataclasses where they replace nested control flow and
  preserve a public contract;
- facade re-exports that keep existing import and patch targets stable after a
  file split.

Do not introduce a generic workflow engine, repository layer, DTO family,
schema registry, validation framework, logging wrapper, CSS architecture, or
Sonar abstraction for this cleanup.

## Whole-Repo Scope

The implementation may touch Python under Sonar's configured source set:

- `shifter/shifter_platform`
- `shifter/engine/provisioner`
- `shifter/packer`
- `shifter/installation`
- `scripts/bootstrap`
- `scripts/check_layer_imports`

It may also touch `scripts/adr_guard` because ADR-012 and architecture checks
apply outside Sonar's Python source set, and `shifter/shifter_platform/static/css`
for `css:S4664`.

Guardrail files are in scope only when the implementation intentionally changes
enforcement or documentation. If touched, run the repo-required architecture
checks and update ADR docs in the same change.

## Gotchas And Anti-Patterns

- Do not confuse lazy logger formatting with sanitization. The correct shape is
  `logger.info("x=%s", safe_log_value(x))`, not `logger.info(f"x={x}")` and not
  `logger.info("x=%s", x)` for values that were previously sanitized.
- Do not replace existing domain exceptions with generic `ValueError` /
  `RuntimeError`, or add a new exception class when `CTFError`, `CMSError`,
  `EngineError`, `ExecutorError`, or `SetupError` already owns the failure.
- Do not move private service helpers to `shared` unless the concern is truly
  cross-layer. Most Sonar helper extraction should stay beside the caller.
- Do not import `cyberscript` from CMS, CTF, Mission Control, or engine code.
  Use `shared` shims.
- Do not collapse CMS user-facing lifecycle state with engine/provisioner
  infrastructure state. Similar status strings are not the same abstraction.
- Do not use regex-only rewrites for complexity findings. The findings call for
  semantic extraction with behavior-preserving tests.
- Do not use a broad formatter, generated rewrite, or selector sort on CSS
  without checking the affected cascade and responsive states.
- Do not add lower-severity Sonar cleanups, dependency upgrades, workflow
  changes, or policy ratchets unless they are a direct prerequisite for the
  HIGH burn-down.

## Non-Goals

- No product behavior changes.
- No new Ground Control requirement or traceability contract.
- No Sonar/Ruff/stylelint policy change unless explicitly justified by a
  supporting guardrail edit.
- No new public APIs, database schema, persistent workflow state, repository
  layer, DTO layer, or validation framework.
- No false-positive or wontfix dispositions without recorded authorization in
  the resolving PR.

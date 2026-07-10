# CMS Scenario Clone Definition Preflight (#996)

Status: pre-implementation guidance

Date: 2026-07-01

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/996>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Issue #996 fixes a latent data-loss bug in `clone_scenario`: cloning must carry
forward the source scenario's persisted structural definition fields by default,
including fields added to the scenario schema later. The change must preserve the
existing scenario-editor workflow: authoring auth, scenario lookup, validation,
persistence, audit, logging, and view error handling.

This is not a schema redesign, YAML-editor redesign, ACES migration slice, API
expansion, or scenario metadata cloning change.

## Architecture Decisions

- Treat `Scenario.definition` as the persisted structural payload and
  `cms.scenarios.schema` as the validation authority. Do not maintain a
  clone-specific allowlist of structural keys.
- Clone should use a deep copy of the structural definition payload. New
  schema-backed definition fields should survive clone without editing
  `clone_scenario`.
- If a field must be reset during clone, model that as an explicit exclusion or
  reset policy beside the structural-definition projection. Do not return to an
  inclusion list of fields to preserve.
- Do not persist the flattened registry detail dict. `get_scenario_detail()`
  includes identity, display, metadata, and derived fields such as `id`, `name`,
  `description`, `enabled`, `staff_only`, `is_default`, and
  `agent_requirements`; those are not all `Scenario.definition`.
- Reuse the scenario-editor service facade and helper split. The fix belongs in
  the existing scenario-editor/domain boundary, not in views, templates, API
  serializers, or model save hooks.
- No new ADR is needed unless the implementation changes enforceable import
  boundaries, schema ownership, workflow policy, or validation rules.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #996 |
| --- | --- | --- |
| Public service surface | `cms.scenario_editor.services` | Keep callers on the facade; do not expose private helper modules as a new public API. |
| Clone/create workflow | `cms.scenario_editor._crud.clone_scenario` and `create_scenario` | Clone still delegates persistence through create, so duplicate-id checks, validation, audit, and logging stay centralized. |
| Scenario source lookup | `cms.scenarios.registry.get_scenario_detail`, `load_scenario_template`; `cms.models.Scenario.to_template` | Reuse registry/template/model conversion; do not query YAML paths or DB JSON directly from views. |
| Structural schema | `cms.scenarios.schema.ScenarioTemplate`, `CTFScenarioTemplate`, `AnyScenarioTemplate` | The schema owns allowed structural fields. Do not fork it in clone tests or serializers. |
| Editor validation | `cms.scenario_editor._validation.validate_scenario_payload`, `validate_definition`, `validate_scenario_id`, `validate_yaml` | Validate the cloned payload through the same service path as create/update. |
| Persistence | `cms.scenario_editor._persistence.create_custom_scenario`, `Scenario.save()`, `transaction.atomic`, `unique_active_scenario_id`, `SoftDeleteManager` | Preserve duplicate detection, soft-delete behavior, and model validation. |
| Auth | `shared.auth.validate_cms_authoring_user`, `can_edit_cms_authoring`, `threat_research_required` | Service authorization remains mandatory even if a caller bypasses the HTML view. |
| Error handling | `ScenarioEditorError`, `view_support.render_*`, shared DRF API errors for API routes | Do not introduce a clone-specific exception hierarchy or leak internal validation traces. |
| Logging/audit | `shared.log_sanitize.safe_log_value`, `risk_register.services.audit_log` via `audit_scenario_change` | Log sanitized IDs and operational facts only; audit successful mutations once through services. |
| Import enforcement | `.importlinter`, `scripts/adr_guard/adr_guard.py` | Stay inside CMS/shared boundaries; no Mission Control, CTF, Engine, or direct non-shared CyberScript dependency. |
| Tests | `tests/scenario_editor/test_services.py`, `test_views.py`, `test_registry.py`, `tests/cms/test_scenario_schema.py` | Add behavior coverage at the service boundary; keep view tests focused on HTTP flow. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: HTML clone remains behind `threat_research_required`, and the
  service still calls `validate_cms_authoring_user` through `validate_user`.
  Active staff and active Threat Research users may clone; unrelated, inactive,
  unsaved, or non-user callers must fail before lookup or persistence.
- Scenario lookup surface: source resolution must preserve the current registry
  semantics: DB custom scenarios take precedence, YAML defaults remain
  code-managed, soft-deleted custom scenarios are excluded, and metadata overlays
  apply only to presentation/access fields.
- Schema validation surface: the cloned structural payload must pass
  `validate_scenario_payload`, then `Scenario.save()` / `Scenario.to_template()`
  validation. Do not bypass Pydantic with raw JSON writes.
- Persistence surface: clone still creates a new custom `Scenario` through
  `create_custom_scenario` inside `transaction.atomic`, preserving
  `unique_active_scenario_id`, created/updated actor fields, and soft-delete
  uniqueness semantics.
- Error-envelope surface: service failures remain `ScenarioEditorError` with
  `public_message`; HTML views render existing scenario-editor error templates.
  Any future API exposure must use `shared.api.errors`, not HTML redirects.
- Logging and observability surface: keep module loggers and `safe_log_value` for
  user-controlled scenario IDs. Do not log full scenario definitions, YAML
  bodies, future secret-like scenario fields, stack traces to clients, or raw POST
  payloads.
- Secret-handling surface: current demo definitions are not secret-bearing, but
  future scenario fields may carry package refs, credentials placeholders, CTF
  content, or provisioning hints. The clone design must not emit definitions to
  logs, audit JSON beyond existing minimal state, OpenAPI examples, shell traces,
  process argv, temp files, or CI output.
- Config/env/OS surface: this fix should not add settings, environment
  variables, subprocesses, shell commands, temp-file handoffs, or provider calls.
  It is in-process Django/Pydantic/ORM work only.
- Import-boundary surface: CMS may depend on `shared` and CMS scenario modules.
  Do not import Mission Control, CTF, Engine, or `cyberscript` directly from the
  scenario editor.

## Extensibility View

The next reasonable change is adding a new schema-backed field to
`ScenarioTemplate` or `CTFScenarioTemplate`. The seam should be a single
structural-definition projection/reset policy that can accept a source template
or scenario detail and return the persistable `Scenario.definition` payload. The
varying parameter is the explicit reset/exclusion set, defaulting to empty.

That seam should distinguish persisted structure from registry presentation
metadata. It should not require editing clone whenever the canonical scenario
schema gains a field.

## Whole-Repo Scope

Likely implementation surfaces are limited to:

- `shifter/shifter_platform/cms/scenario_editor/_crud.py`
- A nearby scenario-editor helper module only if a small projection helper avoids
  duplicating structural-definition logic
- `shifter/shifter_platform/tests/scenario_editor/test_services.py`
- `shifter/shifter_platform/tests/scenario_editor/test_views.py` only if HTTP
  behavior changes, which this issue should not require

Canonical configs and checks that will see the artifact:

- `.importlinter`
- `scripts/adr_guard/adr_guard.py`
- `shifter/shifter_platform/pyproject.toml`
- `docs/adr/index.yaml` and `docs/adr/exceptions.yaml` only if an enforceable
  guardrail or exception changes, which is not expected

## Gotchas And Anti-Patterns

- Do not deep-copy `get_scenario_detail()` wholesale into `Scenario.definition`;
  it includes non-definition and derived fields.
- Do not preserve `enabled` or `staff_only` from the source as cloned
  `ScenarioMetadata` unless a separate issue explicitly changes clone semantics.
- Do not infer definition fields from the current three-key shape
  `instances/subnets/ngfw`; that is the bug.
- Do not use a shallow copy of nested lists/dicts; clone mutations must not share
  nested Python objects with the source during the request.
- Do not duplicate `ScenarioTemplate` fields in a second DTO, serializer, or test
  helper that must be manually synchronized.
- Do not weaken model/schema validation to make a future field pass through.
- Do not broaden clone to edit YAML defaults, bypass default-scenario
  immutability, or clone soft-deleted custom scenarios.
- Do not log definitions or raw YAML while debugging the data-loss path.
- Do not fix this by adding migration-time data cleanup; the issue is clone-time
  behavior.

## Non-Goals

- Changing the scenario schema, adding fields, or changing Pydantic extra-field
  semantics.
- Changing create/update/YAML editor projection behavior beyond what is required
  to share a narrow structural-definition helper.
- Cloning scenario metadata overlays, permissions, launch history, experiments,
  ranges, requests, assets, credentials, audit records, or soft-delete state.
- Adding API routes, DRF serializers, new settings, migrations, providers,
  async jobs, subprocesses, or storage access.
- Refactoring the scenario registry, hydrator, loader, ACES catalog path,
  experiment services, or CTF bridge.

## Validation Expectations

After implementation, run at least:

```bash
cd shifter/shifter_platform
uv run pytest tests/scenario_editor/test_services.py tests/scenario_editor/test_views.py
cd ../..
python3 scripts/adr_guard/adr_guard.py --files shifter/shifter_platform/cms/scenario_editor --level fast
```

If the implementation adds or moves imports across app boundaries, also run:

```bash
cd shifter/shifter_platform
uv run lint-imports --config ../../.importlinter
```

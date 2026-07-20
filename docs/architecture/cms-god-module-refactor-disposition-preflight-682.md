# CMS God-Module Refactor Disposition Preflight (#682)

Status: current-tree architecture disposition

Date: 2026-07-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/682>

This is a requirement-free run. The issue is the original contract. This note
records how later accepted work changed that contract's implementation surface;
it is architecture guidance, not an implementation plan.

## Current-Tree Disposition

Do not start a new broad refactor from the issue's 2026-05-03 line counts. Every
named hotspot has since been decomposed or deliberately removed:

- Legacy experiments were first decomposed behind compatibility facades by
  #886 and related work, then removed by #1195. ADR-027 prohibits reviving
  `cms.experiments`, `EXPERIMENTS_ENABLED`, `EXPERIMENT_PAYLOAD`, its models,
  routes, queue/websocket wiring, or runtime assumptions as a shortcut.
- Scenario-editor services were split by #699 into `_validation`,
  `_persistence`, `_metadata`, `_crud`, `_yaml`, and request-adapter helpers.
  `cms.scenario_editor.services` is an implementation-free compatibility
  facade. Views were split by #700 into per-flow modules, with
  `cms.scenario_editor.views` retained as the URL-facing export facade.
- CMS models were split by #1067 into bounded-context modules under
  `cms.models`; `cms.models` remains the public import path. Compatibility and
  zero-migration-drift tests protect the split.
- CMS event handling was split by #1068 into range, NGFW, and CTF bridge
  modules behind `cms.handlers.process_event`. The shared SNS/SQS envelope
  parser is `shared.messages.envelope.parse_sns_message`.

The issue's acceptance surfaces are therefore represented in the current tree,
and its experiment-specific decomposition criterion is superseded by the
stronger accepted removal decision. The issue should be reconciled against
that evidence before any implementation is authorized. Any newly discovered
behavioral defect or still-large function needs a narrow issue with current
evidence; it must not reopen this obsolete aggregate scope.

No new ADR is needed. ADR-001, ADR-012, ADR-019, ADR-027, ADR-031, and ADR-040
already govern the relevant boundaries.

## Architecture Decisions and Guardrails

1. Public facades are compatibility boundaries, not new homes for logic.
   Existing callers continue to import `cms.models`,
   `cms.scenario_editor.services`, `cms.scenario_editor.views`, and
   `cms.handlers`. Private split modules are internal to CMS.
2. Presentation owns HTTP parsing, Django messages, redirects, templates, and
   response selection. Scenario services own authorization, orchestration,
   validation coordination, persistence coordination, audit emission, and
   typed domain failures. Models own row invariants, not request behavior.
3. There is one scenario definition schema and validation pipeline. YAML uses
   `yaml.safe_load`; scenario meaning is validated by the existing Pydantic
   scenario contracts. DRF serializers validate the transport shape but must
   not reproduce the Pydantic domain schema.
4. Persistence keeps Django's existing model identities, app label, table
   names, fields, constraints, managers, soft-delete behavior, and migration
   state. Moving a class or helper is not permission to generate a migration.
5. Behavior tests drive public entry points and real ORM state. ADR-019 forbids
   making private split modules into a mock-patching API.
6. Legacy experiments stay absent. A future experiment product starts from an
   accepted ACES-backed product/security contract and is not an extension of
   this refactor.

## Canonical Incumbents to Reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Layer ownership | ADR-001, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml` | CMS may use shared contracts and allowed public services; other layers do not reach CMS private modules or models. |
| Scenario public API | `cms.scenario_editor.services`, `cms.scenario_editor.views` | Preserve their exports; keep implementation in focused internal modules. |
| Catalog/source projection | `cms.scenarios.registry`, `cms.scenarios.loader` | Preserve one catalog, collision policy, access overlay, slug/path containment, and safe YAML loading. |
| Scenario schema | `cms.scenarios.schema.ScenarioTemplate` and `AnyScenarioTemplate` | Remain the domain validators; serializers/forms are adapters, not competing schemas. |
| Authoring authorization | `shared.auth.can_edit_cms_authoring`, `validate_cms_authoring_user`, `threat_research_required` | Apply both HTTP-boundary and service-boundary checks. UI visibility is never authorization. |
| DRF authorization | `cms.api.permissions.CMS_READ_PERMISSIONS` / `CMS_WRITE_PERMISSIONS`, `shared.api_tokens.scopes` | Require authenticated session or token, the CMS authoring actor policy, and exact read/write scopes. |
| Persistence | `cms.models`, `shared.db` soft-delete primitives, Django transactions and database constraints | Preserve default/all-object manager semantics, atomic writes, collision handling, and row invariants. |
| Audit | `shared.audit.AuditEvent` and `shared.audit.audit_log` | Emit through the neutral audit port; do not import its risk-register persistence adapter. |
| Errors | `ScenarioEditorError` -> `shared.exceptions.CMSError`, `shared.api.errors`, scenario `view_support` | Translate at the HTTP boundary and keep unexpected exception details out of responses. |
| Logs | `shared.log_sanitize.safe_log_value` and normal module loggers | Log bounded identifiers, states, counts, and request/event IDs; sanitize caller-controlled values. |
| Event workflow | `shared.messages.envelope`, typed payloads in `shared.messages.payloads`, `ResourceStatus`, `cms.handlers` | Reuse the envelope, status validation, ownership checks, idempotency, transactions, and existing CTF bridge. |
| API contract | Runtime DRF serializers/views plus `shifter/shifter_platform/openapi/v1.json` under ADR-040 | Preserve v1 behavior or treat an incompatible change as a versioned API change, not refactor fallout. |
| Complexity/tests | ADR-012 Ruff C901 and ADR-019 boundary-mock policy | Split by responsibility when needed; do not add blanket exemptions or private-module mocks. |

## Cross-Cutting Layer Walk

Any narrowly re-scoped implementation on this surface must pass every
applicable layer below.

| Layer | Required behavior |
| --- | --- |
| Browser/session and CSRF | Classic HTML views retain `threat_research_required` and their existing `require_GET`, `require_POST`, or explicit method decorators. Unsafe session requests remain protected by Django CSRF middleware. Preserve the SPA-safe-method routing and legacy unsafe-method fallback in `cms.scenario_editor.urls`. |
| API authentication and scope | DRF routes retain `IsAuthenticatedSessionOrApiToken`, `HasCMSAuthoringActor`, and the exact CMS read/write scope permissions. Session auth keeps CSRF on unsafe requests; token auth does not create a second role model. |
| Service authorization | Every mutating or sensitive scenario service entry point calls `validate_cms_authoring_user`; direct service callers cannot bypass the HTTP gate. Preserve active/saved-user and staff-or-Threat-Research checks. |
| Request and identifier shape | Forms/JSON/YAML are normalized by existing request adapters and serializers. Scenario IDs keep the canonical lowercase slug rule and collision checks across built-ins, custom rows, and registered packages. Do not pass raw `request`, `QueryDict`, or response objects into persistence/model helpers. |
| YAML and domain shape | Use `yaml.safe_load`, require a mapping, and validate through the existing Pydantic scenario contract. Model `save()` validation remains defense in depth. Never add a second YAML loader, JSON schema, dataclass DTO, or partial validator with divergent rules. |
| Persistence and concurrency | Use existing `Scenario`/`ScenarioMetadata` models, soft-delete managers, database uniqueness, and `transaction.atomic()` where the current workflow requires it. Preserve the `IntegrityError` race translation and update fields. Model movement must produce no migration diff. |
| Audit | Mutations continue to emit canonical `AuditEvent` records through `shared.audit`; do not substitute informational logs for audit evidence or create a CMS-specific audit store. |
| Error envelope | Domain failures remain `ScenarioEditorError`/`CMSError`. DRF uses `api_error_response`; HTML uses the scenario view-support renderers and authored messages. Unexpected database, parser, framework, and internal exception text stays in server diagnostics and never enters HTML/JSON responses. |
| Logging/observability | Preserve module loggers, request/event identifiers, lifecycle transitions, and `safe_log_value` for attacker-controlled strings. Do not log YAML bodies, definitions, credentials, tokens, presigned URLs, provider payloads, or exception-derived client messages. |
| Event input and ownership | Handler work continues through `parse_sns_message`, canonical event constants/typed payloads, `ResourceStatus`, request/range lookup, and user ownership comparison. Range status plus CTF bridge effects retain atomic retry behavior; unknown/malformed events fail without mutation. |
| Secret/config/env surface | This refactor requires no new secret, setting, environment key, feature flag, queue, or storage credential. Adding one is scope expansion and must pass `shifter/shifter_platform/config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, settings validation, deployment renderers, and config tests in a separately justified change. |
| OS/process exposure | This refactor requires no subprocess, shell, cloud command, or generated argv. YAML, scenario fields, identifiers, credentials, and tokens must never become shell fragments or process arguments. Any future runtime execution belongs behind the existing engine/provider boundaries, not CMS authoring code. |
| Cross-layer/import enforcement | Keep consumers on public facades and shared contracts. Only `shared` may import CyberScript directly; ACES tooling is confined to `shared.aces` by ADR-031. Run the import and ADR guards for structural changes. |

## Extensibility Seams

The next reasonable scenario-authoring variation is another catalog source or
an additive scenario field. Its seam is the existing
`cms.scenarios.registry` projection plus the canonical Pydantic scenario
contract, consumed through the existing scenario service facade. Source kind
or schema field is the parameter; views and persistence must not grow
source-specific validation branches.

The next CMS model belongs in the bounded-context module that owns its state
and is re-exported from `cms.models` when public. The bounded context is the
placement parameter; a generic repository, base-model taxonomy, or model
registry is not needed.

The next CMS event type belongs in a focused handler selected by the canonical
event type and consumes a shared typed payload. Event type is the dispatch
parameter; do not add a second envelope, status enum, retry loop, or exception
hierarchy.

These are narrow seams, not invitations to introduce collaborator protocols
for code with only one implementation. Future experiments are explicitly not
an extensibility seam here.

## Gotchas and Anti-Patterns

- Do not recreate any `cms.experiments` import path for compatibility. Its
  intentional absence is covered by `tests/cms/test_experiments_removed.py`.
- Do not judge current scope from deleted-file line counts or split a facade
  merely to reduce LOC. Measure present responsibility and complexity.
- Do not move orchestration into models, forms/serializers into services, or
  request/message/rendering concerns into persistence helpers.
- Do not duplicate `ScenarioTemplate` in DRF serializers, form dataclasses,
  YAML helpers, or a new schema package. Transport validation and domain
  validation are different layers, not competing sources of truth.
- Do not catch broad exceptions and convert `str(exc)` into a response. Do not
  add CMS-, scenario-, handler-, or repository-wide exception taxonomies when
  the existing domain error and shared envelope cover the failure.
- Do not bypass soft-delete managers, catalog collision checks, model `save()`
  validation, database constraints, atomic status/bridge behavior, or service
  authorization during extraction.
- Do not expose private split modules cross-layer or add first-party internal
  patch targets to tests. Facade export coverage plus behavior/ORM assertions
  are the compatibility evidence.
- Do not change Django model `Meta`, app labels, field deconstruction paths,
  constraints, managers, or table identity as a side effect. A generated
  migration is a regression for a structural-only refactor.
- Do not break SPA/classic coexistence: safe GET routing, legacy form POSTs,
  action URLs, route names, decorators, status codes, messages, templates, and
  the DRF v1 contract are behavior.
- Do not weaken Ruff, Sonar, CodeQL, import-linter, ADR guard, secret scanning,
  or OpenAPI compatibility checks to land a decomposition.

## Non-Goals and Implementation Boundaries

- No implementation change is authorized by this preflight.
- No legacy experiment restoration or ACES experiment-core design.
- No database schema/data migration, table rename, model semantic change, or
  new repository/unit-of-work layer.
- No new scenario DSL, validator, serialization format, catalog, error
  envelope, status taxonomy, event bus, logging pipeline, or audit store.
- No authorization, API scope, CSRF, secret/config, queue, worker, cloud,
  provider, shell, or deployment behavior change.
- No redesign of the scenario-editor SPA/classic rollout or `/api/v1/`.
- No expansion into the separate `cms.services` backlog, scenario hydration,
  range lifecycle, engine/provisioner, CTF scoring, or ACES migration work.

## Existing Evidence to Preserve

- `tests/scenario_editor/test_services.py`, `test_views.py`,
  `test_view_error_flows.py`, and registry/model tests.
- `tests/cms/test_scenario_editor_api.py` and
  `test_drf_api_token_access.py`.
- `tests/cms/test_models_package.py`, `test_models_no_migration_drift.py`, and
  focused model lifecycle/soft-delete tests.
- `tests/cms/test_handlers.py`, `test_handlers_ngfw.py`, and
  `test_reconcile_range_events.py`.
- `tests/cms/test_experiments_removed.py`.
- Shared auth, audit, API-error, log-sanitization, import-boundary, OpenAPI,
  and ADR-guard checks when their surfaces are touched.

# Maintainability Cleanup Preflight (#949)

Status: pre-implementation guidance

Date: 2026-06-21

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/949>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Scope Boundary

Issue #949 is a cleanup pass across four related maintenance findings:

- remove the CMS pause/resume service duplication;
- tighten the ADR-001 layer gate so private split-service submodules are not
  cross-layer seams;
- avoid growing mock-coupled tests while touched suites are cleaned up under
  ADR-019; and
- remove stray or dead test artifacts.

Do not change the public product workflow for range pause/resume, range
ownership, audit logging, engine dispatch, CTF integration, cloud provisioning,
or user-facing error semantics.

## Architecture Decisions

- The cross-layer service seam is the public facade, not the package internals.
  Runtime callers in other layers may import `cms.services` / `engine.services`
  and exported names from those facades. They must not import private
  implementation modules such as `cms.services._range_pause`,
  `cms.services._range_resume`, `engine.services._lifecycle`, or the equivalent
  `from cms.services import _range_pause` shape.
- The pause/resume deduplication belongs inside the CMS service implementation,
  behind `cms.services.pause_range`, `pause_range_by_request_id`,
  `resume_range`, and `resume_range_by_request_id`. Do not move the helper to
  `shared`, expose it as a cross-layer API, or make range lifecycle look like a
  generic workflow engine.
- The engine already owns infrastructure lifecycle state and ECS dispatch via
  `engine.services._lifecycle`. CMS owns user authorization, CMS
  `RangeInstance` status transitions, audit events, and conversion of engine
  rejection into `CMSError`. Keep those responsibilities separate.
- ADR-019 is the testing policy for this cleanup. Tests should drive public
  service/view behavior, real ORM state, and real framework clients where
  practical. Patching real cloud/process/network/framework boundaries remains
  acceptable; new first-party internal patch targets are not.
- Dead-artifact cleanup should be literal and evidence-based. Remove only
  tracked files or baseline rows proven unused by current tests/enforcement.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #949 |
| --- | --- | --- |
| CMS public service seam | `shifter/shifter_platform/cms/services/__init__.py` | Keep all cross-layer callers on exported facade names. Private `_*.py` service files remain same-layer implementation details. |
| Engine lifecycle precedent | `shifter/shifter_platform/engine/services/_lifecycle.py` | Reuse the parameterized operation shape: operation name, idempotent/required/target/revert statuses, dispatch callback, and revert-on-failure behavior. |
| CMS caller validation | `cms.services._common._validate_caller_user`, `shared.constants.USER_CANNOT_BE_NONE` | Do not add a second user validator or weaken the current `None`, type, unsaved-user, and range-id checks. |
| Status vocabulary | `shared.enums.ResourceStatus` | Reuse existing `READY`, `PAUSED`, `PAUSING`, and `RESUMING` values. Do not introduce duplicate lifecycle enums or string constants. |
| CMS persistence | `cms.models.RangeInstance` | Keep CMS status updates on the existing model. No new repository, DTO, table, or durable workflow record is needed for this cleanup. |
| Engine dispatch seam | `cms.services.engine_pause_range`, `cms.services.engine_resume_range`; `engine.services.pause_range`, `engine.services.resume_range` | Keep CMS delegating through the existing facade aliases so callers and legacy tests do not reach into engine internals. |
| Audit logging | `risk_register.services.audit_log`, `risk_register.services.AuditEvent`, `risk_register.models.AuditLog` | Preserve `PAUSE` and `RESUME` audit events with non-secret entity/user/request metadata. Do not add a duplicate audit helper. |
| Exceptions | `cms.exceptions.CMSError` | Preserve current domain errors and "not found" ownership masking. Do not add a parallel exception hierarchy. |
| Layer gate | `scripts/check_layer_imports/check_layer_imports.py`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py`, ADR-001 | Tighten the public-facade rule in both checker entrypoints and cover dotted private imports plus `from layer.services import _private` aliases. |
| Package contracts | `.importlinter` | Treat import-linter as the broad package-boundary backstop. The private service-submodule rule belongs in the repo-native ADR checker. |
| Test policy | ADR-019, `scripts/adr_guard/boundary_mock_baseline.json`, `scripts/adr_guard/tests/test_adr_guard.py` | Baseline counts may shrink, not grow. Touched suites should prefer behavior tests over topology assertions. |
| Test structure | `shifter/shifter_platform/tests/test_test_suite_structure.py` | Keep new or edited tests behavior-scoped and below the module/class size gates. |

## Cross-Cutting Layers The Design Must Pass

- Auth and authorization surface: CMS pause/resume entrypoints must continue to
  validate the caller, require ownership via `RangeInstance.user_id`, and mask
  non-owned ranges as not found. No layer-gate or dedup change may bypass view
  auth, CTF bridge authorization, or CMS service authorization.
- Validation surface: keep `_validate_caller_user`, explicit `range_id` type
  and non-negative checks, non-empty request-id checks, and the engine status
  gate. The layer checker must validate both AST import module paths and
  imported alias names so private service modules cannot slip through via
  `from cms.services import _range_pause`.
- Secret-handling surface: this cleanup should not introduce secrets. Logs,
  audit events, JSON errors, and test artifacts should continue to contain only
  range IDs, request IDs, user IDs, statuses, and task ARNs already emitted by
  existing code; do not log provider credentials, SSH/RDP material, or raw
  secret references.
- Env/config/OS exposure surface: no new runtime env vars, shell commands,
  process argv, Terraform variables, Kubernetes env, or settings parsers are
  needed. If the implementation finds itself adding one, it has left the scope
  of #949.
- Error-envelope surface: preserve existing `CMSError`, `TypeError`, and
  `ValueError` behavior. Do not leak ownership mismatches, engine internals,
  stack traces, private module names, or cloud exception payloads into user
  responses.
- Persistence and transaction surface: CMS should keep updating
  `RangeInstance.status` and reverting on engine rejection exactly once.
  Engine `_lifecycle` keeps its own transaction and ECS dispatch semantics.
  Do not combine CMS and engine state into one transaction or add a workflow
  table.
- Observability surface: preserve current structured logging intent and
  risk-register audit events. A helper may accept the operation name and audit
  action as parameters, but it should not invent a new telemetry schema.
- Import enforcement surface: `scripts/check_layer_imports` and
  `scripts/adr_guard` both enforce ADR-001. Tightening one without the other
  creates a local/CI mismatch. Import-linter remains complementary and should
  not be weakened.
- Test enforcement surface: ADR-019 boundary-mock policy and the test-suite
  structure checks apply to any touched tests. Boundary mocks such as
  `boto3.client` are acceptable; first-party service-function patches should
  not be introduced.

## Extensibility Seam

The only extension seam needed is a private CMS lifecycle helper that
parameterizes operation-specific facts:

- operation name for logging and engine dispatch;
- engine facade callback;
- desired CMS target status and revert status;
- audit action;
- user/range lookup mode (`range_id` or `request_id`); and
- user-facing failure message.

That leaves one future same-shape lifecycle variation possible without
re-copying pause/resume logic, while keeping the public API and cross-layer
seams unchanged. The layer-checker extensibility seam is a single predicate for
"public service facade import" used consistently by the standalone checker and
ADR guard tests.

## Whole-Repo Scope

Likely in scope for the future implementation:

- `shifter/shifter_platform/cms/services/_range_pause.py`
- `shifter/shifter_platform/cms/services/_range_resume.py`
- `shifter/shifter_platform/cms/services/__init__.py` only if exports move
  within the facade
- `shifter/shifter_platform/tests/cms/test_services_range_pause_resume.py`
- `scripts/check_layer_imports/check_layer_imports.py`
- `scripts/check_layer_imports/tests/test_check_layer_imports.py`
- `scripts/check_layer_imports/layer_imports.yaml` only if comments need to
  match the tightened rule
- `scripts/adr_guard/adr_guard.py`
- `scripts/adr_guard/tests/test_adr_guard.py`
- `scripts/adr_guard/boundary_mock_baseline.json` only when touched test
  rewrites reduce legacy first-party patch counts
- `docs/adr/index.yaml` for the ADR-001 wording now updated by this preflight

Out of scope unless direct evidence proves otherwise: engine provisioner plans,
ECS task definitions, Terraform, Kubernetes, CTF event lifecycle, risk-register
schema, Django view routing, frontend behavior, changelog generation, and new
Ground Control requirements.

## Gotchas And Anti-Patterns

- Do not make the dedup helper public or cross-layer importable. A private CMS
  helper is enough.
- Do not collapse CMS and engine lifecycle concepts. CMS `RangeInstance`
  status is user/domain-facing; engine `Range` status and ECS dispatch are
  infrastructure-facing.
- Do not change ownership masking. "Not owned" must keep behaving like "not
  found" where it does today.
- Do not rewrite pause/resume into a generic command framework, state machine,
  repository, schema, or exception hierarchy.
- Do not rely on the current regex prefix match to secure private submodules.
  It misses some alias-import shapes and currently treats every
  `cms.services.*` prefix as allowed.
- Do not update only `scripts/check_layer_imports` and forget the mirrored
  `adr_guard` implementation. CI and local guardrails must agree.
- Do not increase `boundary_mock_baseline.json` or add new `patch()` targets
  against first-party services, views, model helpers, logging aliases, or
  transaction aliases.
- Do not delete files based on names alone. Dead artifacts must be shown unused
  by import/search/test discovery.
- Do not weaken `.importlinter`, ADR-001, ADR-019, or test structure checks to
  make cleanup easier.

## Validation Expectations

Run the repo-required architecture gate for touched architecture/enforcement
surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

If the implementation touches Django package imports, also run:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
```

Targeted tests should include the CMS pause/resume behavior suite, the
standalone layer checker tests, and ADR guard tests for the layer-import and
boundary-mock policy surfaces.

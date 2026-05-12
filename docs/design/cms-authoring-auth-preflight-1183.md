# CMS Authoring Authorization Preflight - Issue 1183

## Scope

Issue 1183 is a security consistency fix for the experiment and scenario editor
authoring surfaces. The intended policy is: active staff users and active
members of the `Threat Research` group may access and invoke these CMS
authoring operations; unrelated authenticated users may not.

The implementation must align the view decorators, service-layer gates,
template/navigation visibility, and tests to that one policy. This is not a new
roles system, a scenario visibility redesign, or a permission matrix rewrite.

## Architectural Decisions

- The canonical policy belongs in `shifter/shifter_platform/shared/auth.py`.
  Reuse the existing `THREAT_RESEARCH_GROUP`, `threat_research_required`, and
  staff-or-Threat-Research predicate shape instead of adding app-local
  group-name checks.
- Service methods remain an authorization boundary. They must reject callers
  that fail the same canonical policy even when called directly, outside a
  decorated Django view.
- Scenario availability is a separate domain policy. Preserve
  `cms.scenarios.registry.check_scenario_access`, `list_all_scenarios(user=...)`,
  `enabled`, and `staff_only` semantics; do not treat editor authorization as
  permission to use disabled or staff-only scenarios in non-staff workflows.
- Ownership checks remain per-object. Experiment and script queries must stay
  scoped to `user`, and scenario editor writes must continue to respect default
  scenario immutability and soft-delete/update rules.
- User-facing text and navigation must describe exactly the same audience as the
  service gate: staff or Threat Research, not staff-only unless the policy is
  intentionally changed in the canonical helper.

## Cross-Cutting Concerns To Reuse

- Auth surface: `shared.auth.THREAT_RESEARCH_GROUP`,
  `_is_staff_or_threat_researcher`, `threat_research_required`, and
  `shared.context_processors.user_permissions`.
- Scenario access policy: `cms.scenarios.registry.check_scenario_access`,
  `list_all_scenarios(user=...)`, `get_scenario_detail`, `enabled`, and
  `staff_only`.
- Validation layers: `cms.experiments.schemas.ExperimentCreateInput`,
  `ScriptUploadInput`, `cms.scenarios.schema.ScenarioTemplate`,
  `validate_definition`, `validate_yaml`, model `full_clean()`, and existing
  form JSON parsing.
- Exception handling: existing `ExperimentError` subclasses,
  `ScenarioEditorError`, `CMSError`, and Django `PermissionDenied`; do not add a
  parallel authorization exception hierarchy.
- Persistence and integrity: transaction blocks, soft deletes, per-user
  experiment/script ownership filters, default scenario checks, and
  `ScenarioMetadata` overlays.
- Observability: module-level loggers, ID-only authorization logs, `safe_log`
  for scenario IDs/S3 keys where already used, and `risk_register.services.audit_log`
  for successful mutating operations.
- Workflow gates: `scripts/adr_guard/adr_guard.py`, `.importlinter`, and the
  existing pytest suites under `shifter/shifter_platform/tests/cms/experiments`,
  `tests/scenario_editor`, and `tests/shared`.

## Security Layers

- Django authn: views remain protected by `threat_research_required`, which
  redirects unauthenticated users to `LOGIN_URL` and unauthorized authenticated
  users to Mission Control with a permission message.
- Service authz: every experiment and scenario editor service entrypoint that
  currently calls a local `_validate_user` must use the same canonical predicate
  as the decorator after validating that the user is present, active, valid, and
  saved.
- Domain authorization: experiments must still call
  `check_scenario_access(scenario_id, user)` before loading/using a scenario,
  and object access must remain constrained by ownership or scenario edit rules.
- Input shape validation: keep Pydantic schemas, YAML parsing, scenario template
  validation, slug validation, and Django model validation as the source of
  structural truth.
- Error envelope: view responses should keep generic permission or validation
  messages and avoid leaking hidden scenario details, S3 keys, script content,
  raw YAML bodies, or internal exception traces.
- Secret handling and OS exposure: this change must not introduce environment
  variables, shell commands, process arguments, tokens, or config-bound secrets.

## Extensibility Seam

If the private staff-or-Threat-Research predicate needs to be used from service
code, expose that existing predicate as a named shared policy helper rather than
copying the group query into each service. The likely next variation is another
CMS authoring role or a policy split between read-only authoring access and
mutating authoring access; that variation should be added as an explicit
parameter or separate helper in `shared.auth`, not as app-local branches in
experiments or scenario editor services.

## Non-Goals And Anti-Patterns

- Do not implement object-level collaboration or shared experiments.
- Do not give Threat Research users Django admin or unrelated staff-only Risk
  Register/API access.
- Do not weaken scenario `enabled` or `staff_only` filtering to make a service
  authorization test pass.
- Do not authorize by navigation visibility, template context, or view decorator
  alone.
- Do not duplicate `Threat Research` string literals, local predicates, DTOs,
  validators, or exception classes in each app.
- Do not log raw uploaded scripts, YAML bodies, presigned URLs, upload tokens,
  or hidden scenario details.

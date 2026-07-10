# ACES Legacy Stability Guardrails Preflight

Issue: GitHub #1239, "10 - ACES migration: stability guardrails for legacy
Shifter during transition."

Status: accepted guardrail governance for the ACES transition. This note is the
durable guardrail artifact for #1239: it names the legacy surfaces that stay
authoritative, the regression evidence expected for each, and the legacy-only
change categories. It does not itself add tests, change CI or the PR template,
add a new executable gate, launch ranges, mutate production behavior, or cut
over any ACES path; concrete test/check gaps are filed as follow-up issues (see
"Follow-Up Implementation Issues").

## Boundary

ADR-024 remains the controlling migration decision:
`docs/architecture/aces-migration-adr.md` keeps current Shifter behavior
authoritative until a parallel ACES path passes parity through the normal
portal, CMS, engine, provisioner, CTF, Mission Control, artifact, status, and
validation surfaces. ADR-027 remains the explicit exception for the already
removed legacy experiments path.

Issue #1239 is the stability governance layer for that transition:

- name the legacy workflows that stay current authority until cutover;
- define the regression evidence expected for those workflows while ACES work
  proceeds;
- classify legacy-only changes as allowed, discouraged, frozen, or migration
  support;
- bind guardrail expectations to existing local and CI checks where they
  already exist;
- require follow-up implementation issues when a missing test/check is found.

This is not a file-local implementation plan. Later implementation must design
the actual guardrail artifact against the repo-wide constraints below and must
not create a second migration doctrine beside ADR-024, the parity inventory, or
the existing ACES preflight notes.

## Architecture Decisions

- Current legacy behavior is the default safety rail. ACES work can add
  parallel entries, adapters, conformance evidence, sidecars, or read-only
  projections, but it must not weaken or replace the current launch, CTF,
  Mission Control, artifact, event/status, Polaris, or provisioner behavior
  before the cutover gates in ADR-024 and #1238 pass.
- The guardrail list should be row-based and evidence-based. Each guardrail
  should cite the existing surface, incumbent owner, current tests/checks, and
  any missing follow-up issue. Do not turn the guardrail list into a runtime
  schema, new validator DSL, new status taxonomy, or ACES package manifest.
- Regression coverage expectations should reuse incumbent tests and smoke
  checks first. Add new tests only where a named legacy workflow lacks coverage;
  do not build a parallel "ACES stability" test harness that reimplements
  existing CMS, engine, CTF, Mission Control, upload, or Polaris checks.
- Legacy-only changes are acceptable only when they protect current users,
  repair production behavior, close a security/control gap, preserve parity
  evidence, or enable ACES migration without expanding old semantics.
- New scenario meaning, participant-runtime semantics, backend contract
  semantics, evaluation/scoring semantics, and experiment semantics belong in
  ACES contracts/profiles or later accepted ADRs. They must not be slipped into
  CyberScript, legacy YAML, provisioner plan names, CTF metadata, Mission
  Control templates, or ad hoc JSON fields as compatibility work.
- Missing test/check follow-ups should be filed or cited by the implementation
  before #1239 is declared complete. A gap is actionable when an acceptance
  surface has no existing unit, integration, smoke, static, or live-readback
  check that would catch a regression in that surface during ACES migration.

## Legacy Guardrail Surfaces

| Surface | Current workflow that must stay stable | Regression evidence expectation | Legacy-only change rule |
| --- | --- | --- | --- |
| Range provisioning and lifecycle | Mission Control or CMS launches through `cms.services.create_range`, `cms.scenarios.hydrator`, `engine.services`, `engine.interpreter`, `engine.ecs`, and the provisioner CLI keyed by `request_id`. Pause, resume, destroy, and cancel stay request-id based. | Reuse `tests/cms/test_services_range*.py`, `tests/engine/services/test_create_range.py`, `test_pause_range.py`, `test_resume_range.py`, `test_destroy_range.py`, `tests/engine/ecs/test_start_range_operation.py`, integration range lifecycle tests, and any path-specific smoke. | Allowed for production fixes and migration adapter support that preserves the service facade. Frozen for direct Terraform/cloud/shell calls from CMS, CTF, or Mission Control. |
| Scenario catalog and authoring | Legacy YAML defaults and DB custom scenarios flow through `cms.scenarios.loader`, `cms.scenarios.registry`, `ScenarioMetadata`, and scenario editor services. | Reuse scenario loader/schema/editor/service tests. Preserve slug validation, path containment, `yaml.safe_load`, Pydantic validation, collision handling, enabled/staff-only overlays, and soft-delete behavior. | Allowed for current-stack correctness. Discouraged for new legacy fields. Frozen for ACES-by-YAML-shape detection or a second catalog/editor workflow. |
| Scenario hydration and persisted specs | Legacy demo and CTF templates hydrate into `RangeSpec` / `CTFRangeSpec`; runtime specs persist through `wrap_persisted_spec` and engine interpreter creation. | Reuse `tests/cms/test_scenario_hydrator.py`, `test_ctf_hydrator.py`, shared schema tests, engine interpreter/service tests, and import-linter. | Allowed for compatibility and bug fixes. Frozen for raw ACES blobs or unwrapped specs in CMS/engine rows. |
| CTF event and participant flows | Events, challenge release/visibility, scoring, hints, flags, participant lifecycle, range spin-up, and notifications remain CTF service responsibilities. | Reuse `tests/ctf/test_events.py`, `test_event_lifecycle.py`, `test_challenge_services.py`, `test_scoring*.py`, `test_submit_flag_rate_limit_api.py`, `test_services/test_range.py`, organizer/participant access tests, and CTFd Polaris readback tooling where applicable. | Allowed for current CTF correctness, abuse controls, and ACES evidence readback. Frozen for new private ACES scoring/evaluator semantics in CTF models. |
| Mission Control access | Range pages, APIs, terminal access, Guacamole RDP/SSH, NGFW SSH, owner-scoped status, and lifecycle buttons remain Mission Control and engine-service projections. | Reuse `tests/mission_control/**`, Mission Control integration view tests, terminal/Guacamole tests, API-token access tests, and status consumer tests. | Allowed for current access reliability/security. Frozen for treating Mission Control access channels as ACES participant-runtime capability before ACES contracts and conformance exist. |
| Event and status delivery | Durable status delivery uses `RangeEventOutbox`, `drain_range_event_outbox`, `cms.handlers.range_events.apply_range_status`, CTF bridges, and `reconcile_range_events`; websocket fanout remains advisory. | Reuse engine outbox tests, CMS handler/reconciler tests, range status service tests, and any worker retry/ack checks touched by implementation. | Allowed for idempotency, retry, or projection fixes. Frozen for an ACES-only event bus, websocket topic, lifecycle enum, or status pipeline. |
| Artifact and upload handling | Agent uploads, CTF attachments, object storage, script/artifact references, inspection, and S3/GCS adapters remain Shifter-owned storage/security concerns. | Reuse CMS upload tests, CTF attachment/upload tests, shared upload inspection tests, object storage tests, and secret-scanning/ADR generated-artifact checks. | Allowed for security fixes and migration evidence references. Frozen for copying raw artifacts, flags, scripts, prompts, presigned URLs, or provider dumps into ACES docs, logs, events, or sidecars. |
| Polaris current path | The live `polaris` template, standalone Polaris AWS tooling, content packages, image realization, CTFd sync/readback, and smoke harnesses remain parity evidence until cutover. | Reuse `scenario-dev/polaris/tests/run-all-smoketests.sh`, `scenario_smoketest`, isolation checks, `scripts/ctfd-workshop/test_sync_polaris_ctfd.py`, and #1237 evidence requirements. | Allowed for current Polaris reliability and parity evidence. Frozen for shadowing the `polaris` id, making Polaris the adapter type system, or deleting evidence before cutover. |
| CyberScript and shared shims | CyberScript contracts stay behind `shared` shims while legacy templates and CTF hydration still depend on them. | Reuse shared schema tests, CyberScript tests when touched, `.importlinter`, and `scripts/check_layer_imports/layer_imports.yaml`. | Allowed for compatibility, bug fixes, docs, and archive support. Frozen for new canonical scenario semantics unless a later ADR explicitly widens scope. |
| Legacy experiments | The removed `cms.experiments` path must stay removed per ADR-027; future experiment capability starts from a new ACES-backed design. | Reuse `tests/cms/test_experiments_removed.py`, ADR-027 checks, route/scope/nav absence tests, and migration drift tests. | Frozen for reintroduction. Any future experiment work needs accepted ACES-backed design and product/security review. |
| CI and local enforcement | ADR guard, import-linter, Ruff, actionlint, Terraform, Kubernetes, secret/generated-artifact, and docs coverage checks remain enforcement, not advisory text. | Reuse `.gc/plan-rules.md`, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py`, `.github/workflows/_quality.yml`, `.tflint.hcl`, `.kube-linter.yaml`, and config/env tests. | Allowed only to strengthen or precisely route checks. Frozen for silent skips, broad soft-fail, weakening import rules, or path filter changes that hide ACES/legacy regressions. |

## Legacy-Only Change Acceptance

Use these categories when triaging ACES-era changes that touch old models,
templates, workflows, or docs:

| Category | Accept when | Review bar |
| --- | --- | --- |
| allow | The change fixes a current production bug, closes a security/control gap, restores parity evidence, repairs flaky/current tests, updates docs/runbooks, or adds missing regression coverage for a legacy workflow. | Must cite the guarded legacy workflow and existing or new regression evidence. |
| migration-support | The change adds an adapter, selector, read-only projection, sidecar reference, or validation hook that helps ACES migration while preserving the legacy default. | Must pass through existing service/auth/persistence/error/logging boundaries and keep rollback to legacy simple. |
| discourage | The change adds new legacy YAML fields, CyberScript shape, CTF metadata, Mission Control template logic, or provisioner behavior that is not required for current correctness or ACES migration. | Should be redirected to ACES SDL/profile/backend manifest or a later ADR unless the issue states a concrete current-stack need. |
| freeze | The change reintroduces removed experiments, makes CyberScript a future canonical contract, shadows live scenario ids before cutover, creates duplicate schemas/statuses/events/exceptions, weakens CI/local checks, or deletes parity evidence before replacement. | Reject unless a new accepted ADR changes the boundary. |

Follow-up implementation issues should be filed for missing tests/checks, not
for broad migration anxiety. The issue body should name the surface, the
specific regression that would currently slip through, the incumbent test or
checker to extend, and the acceptance evidence expected after the gap closes.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024 | Keep current Shifter behavior authoritative until parity and cutover gates pass. |
| Parity ledger | `docs/architecture/aces-migration-parity-inventory.yaml` | Cite row ids for guarded surfaces and follow-up scope; do not turn rows into runtime schema. |
| Prior ACES boundaries | #1231 through #1238 preflight docs under `docs/architecture/aces-*-preflight-*.md` | Reuse the established catalog/profile, backend-manifest, operation/status, participant-runtime, Polaris, and cutover boundaries. |
| Scenario loading | `cms.scenarios.loader` | Preserve slug validation, path containment, `yaml.safe_load`, and Pydantic `TypeAdapter(AnyScenarioTemplate)`. |
| Scenario catalog | `cms.scenarios.registry`, `ScenarioMetadata` | Keep one projection with enablement/staff-only overlays and collision handling. |
| Scenario authoring | `cms.scenario_editor.services` and supporting `_validation`, `_persistence`, `_metadata`, `_yaml`, `_crud` modules | Do not add a second YAML/parser/editor workflow for guardrails. |
| Hydration | `cms.scenarios.hydrator` | ACES or legacy compatibility changes adapt into Shifter range specs here or at the already defined adjacent adapter seam. |
| CMS launch | `cms.services.create_range`, `get_range_by_request_id`, lifecycle service facades | Preserve user validation, active-range checks, request state, audit, failure status, and engine dispatch. |
| Engine/provisioner | `engine.services`, `engine.interpreter`, `engine.ecs`, provisioner `main.py`, provider task runners | Use request-id keyed structured dispatch; no cloud/Terraform/Docker/shell calls from request-path app layers. |
| Status/event durability | `RangeEventOutbox`, `drain_range_event_outbox`, `apply_range_status`, `reconcile_range_events`, `shared.messages.events` | Correctness-critical projection stays outbox/reconciler backed. |
| CTF integration | `ctf.bridges`, `ctf.services.*`, CTFd sync/readback scripts | CTF crosses into CMS through bridge/service seams and owns event/scoring/access behavior. |
| Mission Control access | `mission_control.api`, `mission_control.views`, terminal services, Guacamole bootstrap/views, engine terminal services | Reuse existing owner, token, scope, capacity, and access-channel controls. |
| Artifact/upload security | `cms.assets`, `cms.services._uploads`, `ctf.services.attachment`, `shared.uploads.inspection`, `shared.cloud` storage adapters | Keep upload tokens, size checks, inspection, key normalization, and object-storage facades. |
| Auth and API scopes | `shared.auth`, `cms.api.permissions`, `mission_control.api.permissions`, `shared.api.permissions`, `shared.api_tokens.scopes` | Service-layer authorization and exact scopes remain mandatory; UI hiding is not authorization. |
| Errors | `shared.api.errors`, `shared.errors`, `shared.exceptions.CMSError`, existing CTF exceptions | Translate at domain boundaries; do not add guardrail-specific or ACES-only error envelopes. |
| Logging and audit | `shared.log_sanitize`, provisioner `log_redact`, `risk_register.services.audit_log` | Log sanitized ids/status/counts/digests only; use audit rows for real Shifter auditable actions. |
| Runtime config | `config/settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, deploy renderers, config tests | New selectors, retention, evidence paths, or check toggles need typed settings and manifest/inventory coverage. |
| Import and workflow enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py`, `.gc/plan-rules.md` | Do not bypass cross-layer contracts or weaken local/CI enforcement for migration convenience. |

## Cross-Cutting Layers

- Auth surface: CMS authoring/catalog work stays behind
  `validate_cms_authoring_user`, `threat_research_required`,
  `HasCMSAuthoringActor`, `CMS_READ_PERMISSIONS`, and
  `CMS_WRITE_PERMISSIONS`. Mission Control uses
  `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, exact
  `mission_control:*` scopes, owner checks, and participant blockers. CTF uses
  organizer/participant ownership helpers and service checks. A guardrail
  artifact must not rely on hidden UI controls as authorization.
- Scenario and ACES shape: legacy YAML stays behind slug/path containment,
  `yaml.safe_load`, and Pydantic scenario adapters. ACES packages stay behind
  explicit contract/profile, backend manifest, lock/digest, and conformance
  gates. Do not infer ACES from filenames, branch names, YAML keys, or the
  Polaris id.
- Persistence shape: live Shifter state remains in CMS, engine, CTF, and
  Mission Control models. Runtime specs stay wrapped with
  `wrap_persisted_spec` and interpreted through engine transactions. ACES
  receipts, snapshots, participant records, or evidence records use
  version/profile-keyed sidecars only when their implementation issue lands.
- Status/event shape: Shifter `ResourceStatus`, `engine.Range.Status`,
  `RangeEventOutbox`, event handlers, CTF bridges, and reconcilers remain the
  current status authority. Any ACES status is an adapter view with explicit
  mapping and tests, not a replacement enum.
- Secret-handling surface: docs, evidence bundles, logs, API responses, audit
  JSON, events, DLQs, workflow summaries, argv, and env literals must exclude
  credential values, bearer tokens, private keys, upload tokens, presigned
  URLs, CTF flags, CTFd admin tokens, Guacamole URLs, terminal streams, prompt
  bodies, scripts, provider dumps, raw package bodies, and rendered runtime
  config.
- Artifact surface: uploaded files, challenge attachments, experiment/script
  inputs, runtime reports, and parity evidence are references plus digests and
  redaction state. Guardrails may name artifact classes and checks; they must
  not copy raw artifact contents into architecture docs or issue bodies.
- OS/process exposure: range and NGFW dispatch continue through structured
  argv keyed by `request_id` and operation names. CTFd and cloud credentials
  must come from established secret/config surfaces, not command-line
  arguments. Request-time code must not execute arbitrary ACES/package commands
  or assemble shell fragments from YAML, ACES, CTFd, or issue content.
- Env-binding/config validators: new cutover selectors, launchability toggles,
  conformance paths, evidence output paths, retention policies, cleanup
  cadences, or CI guard toggles need explicit settings, env-manifest/runtime
  inventory coverage, and tests. Do not add opportunistic `ACES_*` or
  guardrail env reads inside views, handlers, migrations, or workers.
- Error-envelope surface: DRF APIs use `shared.api.errors`; HTML/JSON views
  use existing typed errors and `classify_user_message` / `safe_user_message`;
  terminal and Guacamole paths keep their existing bounded failure messages.
  Raw ACES parser, CTFd, cloud, Terraform, SSM, SSH, Docker, storage, or
  provider exceptions stay in sanitized diagnostics.
- Observability surface: log request ids, range ids, scenario ids, guardrail
  row ids, parity inventory row ids, profile ids, counts, durations, status
  classes, report refs, digests, and fingerprints. Do not log full package
  bodies, Terraform outputs, provider dictionaries, terminal streams,
  generated commands, prompts, scripts, credential values, or flags.
- Import-boundary surface: CMS, CTF, Mission Control, engine, and management
  keep using `shared` contracts and published service facades. Only `shared`
  may import CyberScript directly today. ACES imports need the same discipline
  unless a later ADR changes import policy.
- Workflow validators: architecture/workflow/platform changes must pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci` and the
  path-specific checks in `.gc/plan-rules.md`. Workflow, Terraform,
  Kubernetes, Python import, config, and secret/generated-artifact checks stay
  blocking where they are blocking today.

## Extensibility Seam

The guardrail artifact should reuse the existing parity inventory row ids and
surface names as its extension seam. If the implementation needs a structured
checklist, each entry should carry only:

- the guarded legacy surface;
- the related parity inventory row id when one exists;
- the incumbent owner/service/test/check;
- the minimum evidence class, such as unit test, integration test, smoke test,
  static checker, live readback, or docs-only review;
- the legacy-only change category from this note.

Future variations should add rows or evidence classes behind that seam: a new
ACES profile, another provider, another smoke universe, or another cutover
phase. They should not require edits in CTF event code, Mission Control
templates, engine models, provisioner internals, or workflow path filters just
to describe a new guardrail.

The runtime migration seam remains the explicit catalog/profile/backend
manifest/hydrator selector from #1232, #1233, #1237, and #1238. #1239 should
not introduce a second selector or a parallel launchability model.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `docs/architecture/aces-scenario-cyberscript-rescope-preflight-1231.md`
- `docs/architecture/aces-catalog-package-boundary-preflight-1232.md`
- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/aces-experiment-core-preflight-1235.md`
- `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md`
- `docs/architecture/aces-polaris-acceptance-parity-gate-preflight-1237.md`
- `docs/architecture/aces-cutover-archive-plan-preflight-1238.md`
- `docs/architecture/aces-cyberscript-issue-triage.md`
- `docs/architecture/experiments-removal-adr.md`
- `docs/adr/index.yaml` and `docs/adr/exceptions.yaml` if enforceable
  guardrails or exceptions change
- `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`, and
  `scripts/check_layer_imports/layer_imports.yaml` if workflow, import, or
  planning policy changes
- `.github/workflows/**` and `.github/pull_request_template.md` only if CI or
  review gates are intentionally changed
- `shifter/shifter_platform/cms/scenarios/**`
- `shifter/shifter_platform/cms/scenario_editor/**`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/cms/api/**`
- `shifter/shifter_platform/cms/assets/**`
- `shifter/shifter_platform/shared/**`
- `shifter/shifter_platform/engine/**`
- `shifter/shifter_platform/ctf/**` through bridge/service seams
- `shifter/shifter_platform/mission_control/**`
- `shifter/shifter_platform/config/**`, `config/env-manifest.json`, and
  `shifter/installation/runtime_inventory.py` for new runtime settings
- `shifter/engine/provisioner/**`
- `scenario-dev/polaris/**`
- `scripts/polaris-aws-range/**`
- `scripts/ctfd-workshop/**`
- `scripts/adr_guard/**` and related checker suites if policy changes

## Gotchas And Anti-Patterns

- Do not treat #1239 as permission to delete old behavior. It defines the
  rails that keep old behavior stable until cutover.
- Do not create duplicate scenario schemas, ACES package schemas, status enums,
  event buses, error envelopes, exception hierarchies, CTFd clients, smoke
  schemas, artifact stores, upload-token formats, or workflow DSLs.
- Do not make Polaris the public adapter contract. Polaris is the parity
  proving case; the reusable seam is the ACES Shifter profile and backend
  manifest.
- Do not shadow live ids such as `polaris` before cutover and rollback posture
  are explicit.
- Do not encode missing ACES vocabulary as private legacy YAML fields,
  CyberScript fields, Terraform variables, provisioner plan names, CTF metadata,
  Mission Control templates, or audit JSON.
- Do not satisfy regression coverage by checking only a standalone demo,
  local Docker path, or `scripts/polaris-aws-range` path. Cutover-relevant
  evidence must include the Shifter path operators actually use.
- Do not use websocket fanout, UI rendering, or issue labels as the only
  evidence for status, access, or workflow correctness.
- Do not weaken `EXPERIMENTS_ENABLED` removal checks, API-token exact scopes,
  terminal/Guacamole controls, import-linter, ADR guard, actionlint, Terraform
  and Kubernetes validators, secret scanning, generated-artifact blocks, or
  live-cloud fail-loud behavior to make migration progress easier.
- Do not leave missing coverage as prose-only TODOs. File or cite concrete
  implementation issues when the guardrail implementation discovers a real
  test/check gap.

## Follow-Up Implementation Issues

The guardrail review of the acceptance surfaces found two concrete test/check
gaps where a current ACES-era regression would slip through existing coverage.
Each is filed as its own issue naming the surface, the regression that slips
through today, the incumbent to extend, and the acceptance evidence expected.
They are filed for visibility and worked on their own merit; neither is a
prerequisite of the other or of ACES cutover.

- **#1313, add a parity-inventory path-integrity check to adr_guard.** Nothing
  currently references `docs/architecture/aces-migration-parity-inventory.yaml`,
  so ACES file moves/renames silently rot the inventory's `legacy_source` and
  `validation_evidence` paths. Extend `scripts/adr_guard/adr_guard.py` to fail
  when a row's path-valued evidence no longer resolves, classifying path vs
  shell command vs glob vs prose so command/prose rows are not false-flagged.
- **#1314, add a Shifter-path regression test for the Polaris portal template.**
  `cms/scenarios/templates/polaris.yaml` has no test exercising it through the
  loader/registry/hydrator/engine path; the `polaris.portal-template` parity row
  cites only the standalone `scripts/polaris-aws-range` script. Extend
  `tests/cms/test_scenario_hydrator.py` and the scenario loader/registry tests
  to hydrate the `polaris` template through the Shifter path and assert a valid
  persisted `RangeSpec`, with no live cloud dependency.

The other acceptance surfaces (scenario catalog, CTF flows, Mission Control
access, event/status delivery, artifact/upload handling, and the legacy launch
path through `cms.services.create_range`) already carry the incumbent unit and
integration coverage cited in the guardrail table above, so no follow-up issue
is filed for them.

## Non-Goals

- No ACES parser, runtime selector, backend manifest, conformance CLI, sidecar
  model, migration, API, UI, workflow, or provisioning implementation in this
  preflight.
- No CI route or PR-template change, and no new executable gate, in this change.
  Follow-up test/check issues (#1313, #1314) are filed for visibility but are
  not implemented here.
- No cutover from legacy scenario paths to ACES-backed paths.
- No removal or archival of CyberScript, current CMS scenario templates,
  Polaris runtime material, CTF behavior, Mission Control behavior,
  provisioner paths, artifacts, status models, or validation gates.
- No reintroduction of removed legacy experiments.
- No new Ground Control requirement UID for this requirement-free run.
- No live AWS, GCP, CTFd, Guacamole, SSM, Terraform, Kubernetes, AMI bake, or
  range mutation.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future implementation must also run the stack-native checks required by
`AGENTS.md` and `.gc/plan-rules.md` for any touched Python, workflow,
Terraform, Kubernetes, platform, import, or guardrail path.

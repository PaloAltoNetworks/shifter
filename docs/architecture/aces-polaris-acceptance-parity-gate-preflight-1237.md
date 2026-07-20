# ACES Polaris Acceptance And Parity Gate Preflight

Issue: GitHub #1237, "08 - ACES migration: Polaris acceptance and parity gate."

Status: pre-implementation architecture guidance. This note does not implement
the ACES path, add schemas, add tests, launch ranges, or cut over runtime
behavior.

Issue #1293 was re-scoped on 2026-07-15. Per-scenario verification adapters and
answer-key material are now out-of-tree installed plugins; Shifter core owns
only the provider/pack-neutral discovery, runner, prerequisite, result, and
redaction framework. The issue-specific seam guidance in
`aces-polaris-scenario-smoketest-coverage-preflight-1293.md` supersedes this
note's original in-core adapter-expansion wording.

## Boundary

ADR-024 remains the controlling decision:
`docs/architecture/aces-migration-adr.md` keeps current Shifter behavior
authoritative until a parallel ACES path passes parity through the normal
portal, CMS, engine, provisioner, CTF, experiment, Mission Control, artifact,
status, and validation surfaces.

Issue #1237 defines the acceptance path for that cutover. Polaris is the
primary proving case because it contains the current expressiveness pressure:
multi-zone topology, adjacent Windows AD, dynamic splice behavior, content
packages, image realization, CTF challenge/metric dependencies, Modbus/PLC
state, Kali access, and runtime bootstrap behavior that previously required
standalone provisioner support or operator end-runs.

The first ACES backend claim is still the #1233 `provisioning-only` claim.
Passing the Polaris acceptance gate does not by itself mean Shifter implements
ACES `orchestrator`, `evaluator`, or `participant_runtime`. CTF scoring,
experiment execution, Mission Control access, terminal/Guacamole behavior, and
artifact storage remain Shifter-owned projections unless later ACES contracts,
profiles, and conformance gates explicitly cover them.

The current Polaris/Shifter path must remain available and default until this
gate passes. During the parallel phase, an ACES-backed Polaris catalog entry
must use a distinct id such as `polaris-aces` or an explicit migration link.
It must not shadow the live `polaris` id until cutover and rollback posture are
reviewed.

## Acceptance Decision

Polaris parity means an ACES-authored Polaris package can be selected through
Shifter's scenario catalog and launched through the existing CMS, engine, and
provisioner path, then produce a live range that satisfies the same Shifter
operator and participant readiness evidence as the current Polaris path.

Cutover is blocked unless all of these gates are green:

| Gate | Blocking acceptance condition |
| --- | --- |
| ACES authoring and conformance | The full Polaris SDL/package validates through ACES contract/profile tooling and the Shifter backend manifest. Missing vocabulary is filed as an ACES schema/profile gap, not encoded as Shifter-only scenario semantics. |
| Catalog and launch selection | The ACES entry uses an explicit contract/profile discriminator in `cms.scenarios.registry` / `cms.scenarios.hydrator`; no YAML-shape detection, no Polaris-specific branch in core services, and no legacy `polaris` id shadowing before rollback is ready. |
| Normal Shifter backend path | Launch goes through `cms.services.create_range`, `engine.services.create_range`, `engine.interpreter`, task-runner dispatch, and the provisioner CLI keyed by `request_id`. A standalone APTL/demo script or `scripts/polaris-aws-range` success is useful evidence but cannot satisfy this gate alone. |
| Runtime parity | The launched ACES-backed range satisfies the asset, network, pivot, service, content, DNS, AD, Kali, and isolation expectations currently validated by the Polaris smoke harnesses and Shifter range state projections. |
| Product projection parity | `engine.Range`, `cms.RangeInstance`, `RangeEventOutbox`, CTF range status, Mission Control range/API views, and experiment bridge behavior continue to project Shifter status through existing services and envelopes. |
| Evidence and rollback | The run produces a redacted evidence bundle with ACES conformance, Shifter launch/status, smoke-test, CTFd readback, and rollback-selector evidence; the legacy path is still launchable or explicitly restorable. |

Cutover is also blocked if any inventory row needed by Polaris acceptance is
unreconciled, including `polaris.full-sdl`, `polaris.demo-sdl`,
`polaris.image-realization`, `polaris.content-packages`,
`polaris.portal-template`, `polaris.smoketests`, `ctf.ctfd-sync`,
`provisioner.persisted-specs`, `provisioner.range-services`,
`provisioner.polaris-aws-path`, `status.engine-range`,
`aces.operation-status-projection`, `mission-control.range-ui`,
`aces.operation-api-projection`, and `validation.aces-manifest-conformance`.

## Parity And Evidence

Required evidence artifacts for the later implementation:

| Evidence | Canonical incumbent | Required artifact |
| --- | --- | --- |
| ACES package/profile validation | ACES parser, profile, backend manifest, and conformance tooling from #1233 | Machine-readable conformance report naming profile, package ref, lock/digest, manifest version, and pass/fail summary. |
| Catalog projection | `cms.scenarios.registry`, `ScenarioMetadata`, package-source boundary from #1232 | Test or report showing legacy `polaris` and ACES `polaris-aces` entries are distinct, access-filtered, and launchability-filtered through the same registry projection. |
| Hydration/runtime spec | `cms.scenarios.hydrator`, `shared.schemas.RangeSpec`, `shared.schemas.persistence.wrap_persisted_spec` | Sanitized mapping report or tests proving ACES RuntimeModel maps into the Shifter spec envelope without raw ACES blobs in runtime tables. |
| Backend launch | `cms.services.create_range`, `engine.services.create_range`, `engine.ecs`, provisioner `main.py range provision --request-id` | Launch receipt with request id, range id after projection, task id fingerprint, profile id, and final Shifter status. |
| Status projection | `RangeEventOutbox`, `cms.handlers.range_events.apply_range_status`, `reconcile_range_events`, Mission Control status consumers | Status readback showing READY/FAILED/DESTROYED semantics recover through outbox/reconciler paths, not websocket-only fanout. |
| Polaris infrastructure smoke | `scenario-dev/polaris/tests/run-all-smoketests.sh` and `isolation-smoketest.sh` | Redacted transcript or JSON summary with every asset sweep and isolation check passing. |
| Polaris scenario-content smoke | Core scenario-verification framework plus an explicitly installed out-of-tree adapter plugin | Versioned, redacted report output. A cutover-grade run must have zero failed, blocked, errored, or missing checks for the declared acceptance universe. Core CI proves only the framework contract; adapter coverage evidence comes from the installed plugin and must not be copied back into core. |
| CTFd board parity | `scripts/ctfd-workshop/common.py`, `sync_polaris_ctfd.py`, `sync_polaris_ctfd_onboarding.py`, and explicit read-only operator tooling | Read-only CTFd flag-row/challenge readback with token-safe diagnostics. It stays outside the plugin ABI, may report drift, and must not mutate CTFd as part of acceptance. |
| Mission Control/CTF access projection | `mission_control.api`, `mission_control.views`, `ctf.services.range`, `ctf.bridges` | API/view tests or live readback showing owner-scoped range status and access projections still use existing auth, serializers, and error envelopes. |
| Rollback | Catalog/profile selector, `ScenarioMetadata`, legacy `polaris` template, range destroy lifecycle | Evidence that disabling the ACES entry or selector leaves the legacy Polaris path available, and that failed ACES validation tears down through existing range lifecycle controls. |

Evidence bundles must contain ids, digests, status classes, report paths, and
sanitized diagnostics only. They must not contain raw flags, credential values,
private keys, bearer tokens, presigned URLs, prompt bodies, generated scripts,
Terraform outputs, provider payloads, raw package bodies, CTFd admin tokens, or
Guacamole/terminal access URLs.

## Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024 | Keep ACES parallel and parity-gated; do not replace current behavior by declaration. |
| Parity ledger | `docs/architecture/aces-migration-parity-inventory.yaml` | Use row ids as the acceptance ledger; do not turn inventory rows into runtime schema. |
| Scenario catalog | `cms.scenarios.registry`, `ScenarioMetadata` | One catalog projection for legacy and ACES entries, with existing enablement/staff-only overlays. |
| Scenario loading | `cms.scenarios.loader` for legacy YAML and the #1232 package-source adapter for ACES | Preserve slug/path/YAML/Pydantic gates for legacy; validate ACES through explicit package/profile contracts. |
| Hydration | `cms.scenarios.hydrator` | ACES adapts into Shifter `RangeSpec` / `CTFRangeSpec` semantics here or at an adjacent adapter seam. |
| CMS launch | `cms.services.create_range` | Preserve user validation, agent/scenario checks, active-range checks, CMS request state, audit logging, failure status, and engine dispatch. |
| Persisted specs | `shared.schemas.persistence.wrap_persisted_spec`, `engine.interpreter` | Persist ACES-derived Shifter runtime specs through the existing envelope; no raw ACES JSON blobs in range rows. |
| Engine/provisioner | `engine.services`, `engine.ecs`, provisioner `main.py`, `range_terraform_runner`, provider factories | ACES must not call Terraform, SSM, SSH, Docker, AWS, or GCP directly from CMS, CTF, or Mission Control request paths. |
| Status durability | `RangeEventOutbox`, `cms.handlers.range_events`, `reconcile_range_events` | Projection correctness remains outbox/reconciler backed; no ACES-only lifecycle pipeline. |
| CTF integration | `ctf.bridges`, `ctf.services.range`, CTFd sync/readback scripts | Shifter owns CTF event/range/status/scoring behavior unless ACES later publishes matching contracts. |
| Experiment execution | `cms.experiments.orchestrator.execution_plan`, `shared.script_context.ScriptExecutionContext` | Commands, prompts, S3 keys, instance ids, and artifacts stay behind current execution and redaction gates. |
| Mission Control | `mission_control.api`, `mission_control.views`, terminal and Guacamole services | ACES-backed fields are read-only projections through existing auth, serializers, token lifecycle, and capacity controls. |
| Polaris smoke | `scenario-dev/polaris/tests/run-all-smoketests.sh`, `shared.scenario_verification`, an explicitly selected installed adapter plugin, walkthroughs, and CTFd JSON | Keep topology-aware execution and redacted reporting. Core ships no scenario adapters or answer-key schema; the plugin owns the realization-specific glue and must not become a second challenge schema. |
| Logging/audit | `shared.log_sanitize`, provisioner `log_redact`, `risk_register.services.audit_log` | Logs and audit carry sanitized ids/status/classes, not package bodies, secrets, flags, commands, or provider dumps. |
| Errors/API | `shared.api.errors`, `shared.errors`, `cms.exceptions.CMSError`, CTF/experiment exceptions | Translate at domain boundaries; do not add an ACES-only API envelope or exception hierarchy. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | ACES imports stay behind `shared` and service seams unless a later ADR changes the rule. |

## Cross-Cutting Layers

- Auth surface: catalog, manifest, conformance, and launch work stays behind
  CMS authoring gates (`shared.auth.validate_cms_authoring_user`,
  `threat_research_required`, `HasCMSAuthoringActor`) or the existing
  session/API-token DRF model with exact scopes. Mission Control projections
  use `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, exact
  `mission_control:*` scopes, and owner/participant blockers. UI hiding is not
  authorization.
- Scenario input shape: legacy YAML keeps scenario id slug validation, template
  path containment, `yaml.safe_load`, and `TypeAdapter(AnyScenarioTemplate)`.
  ACES packages use explicit package/profile validation and conformance. Do not
  infer ACES from YAML keys, file paths, branch names, or the Polaris id.
- ACES contract shape: Polaris topology mutations, content/provenance,
  CTF metrics/prerequisites, AD/domain/service-feature vocabulary, and image
  realization must be represented by ACES SDL/profile/backend-manifest
  contracts. Missing coverage is an ACES gap and a cutover blocker, not a
  private Shifter extension.
- Persistence shape: live Shifter runtime state remains in CMS/engine models;
  ACES receipts/status/snapshots/evidence use version/profile-keyed sidecars
  when those issues land. Do not overload `RangeInstance.range_spec`,
  `Range.provisioned_instances`, `ExperimentRun.metadata`, event payloads, or
  `AuditLog` JSON as canonical ACES stores.
- Status/event shape: Shifter `ResourceStatus`, `engine.Range.Status`,
  `RangeEventOutbox`, `apply_range_status`, bridge hooks, and
  `reconcile_range_events` remain authoritative for product projection. ACES
  status is an adapter view with explicit mapping and tests.
- Secret-handling surface: scenario-intent credentials in Polaris are challenge
  content, but operational secrets, generated access URLs, token values,
  private keys, CTFd admin tokens, flags, prompts, scripts, provider outputs,
  and raw artifacts must not appear in logs, issue bodies, docs examples,
  evidence bundles, API responses, DLQs, argv, env literals, or workflow
  summaries.
- OS/process exposure: launch and validation use structured argv keyed by ids
  such as `request_id`, not shell fragments assembled from ACES/CTFd/YAML
  content. CTFd admin tokens come from environment or restrictive token files,
  never command-line arguments. ACES conformance tooling must not run arbitrary
  package commands in request paths.
- Config/env validators: new selectors, retention knobs, conformance toggles,
  evidence paths, or launchability flags need explicit settings, env-manifest
  coverage, runtime inventory/render tests, and docs. Do not add handler-local
  `ACES_*` reads.
- Error-envelope surface: browser and CLI diagnostics should classify errors
  by gate, row id, request id, report id, or sanitized reason. DRF responses use
  `shared.api.errors`. Raw ACES parser, CTFd, Terraform, SSM, SSH, Docker,
  cloud, or provider exceptions stay in sanitized logs.
- Observability surface: log profile ids, row ids, counts, durations, status
  classes, request ids, digests, and fingerprints. Do not log full package
  bodies, Terraform output dictionaries, terminal streams, command strings,
  prompt bodies, scripts, or credential values.
- Architecture validators: any implementation touching architecture,
  workflows, hooks, or `shifter/shifter_platform` must pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci` plus the
  path-specific import-linter, Ruff, actionlint, Terraform, Kubernetes, and
  smoke checks required by `AGENTS.md` and `.gc/plan-rules.md`.

## Extensibility Seam

The required seam is an explicit contract/profile discriminator at the
catalog, package-source, backend manifest, and hydrator/adapter boundary. The
first acceptance target is the Shifter ACES Polaris profile over the
`provisioning-only` backend claim. Later profiles may add orchestration,
evaluation, participant runtime, or provider variants only behind that seam.

The scenario-verification plugin seam is orthogonal to this ACES selection
seam. It produces redacted evidence about a realized run; it neither selects a
backend nor changes manifest, admission, hydration, or launchability decisions.

Acceptance tooling should also keep selection parameters explicit:
scenario id/profile, package ref/digest, backend manifest ref, provider,
environment, evidence output path, CTFd base URL, smoke challenge universe, and
timeouts. Future scenarios or providers should add profile/source/smoke
parameters, not edit CTF event code, Mission Control templates, engine models,
or provisioner internals per scenario.

## Follow-Up Issues Filed Or Confirmed

Concrete follow-up work identified by this gate is tracked as:

- #1253: registry/profile validation and launchability for ACES package-backed
  catalog entries, including a distinct Polaris ACES selector.
- #1261, #1262, #1263, and #1264: backend manifest, RuntimeTarget adapter,
  conformance gate, and live Shifter backend validation.
- #1293: define the provider-agnostic scenario-verification plugin seam, keep
  the framework in core with zero adapters, and move cutover-universe coverage
  to a separately installed plugin.
- #1294: generate the redacted Polaris parity evidence bundle that collects
  conformance, launch, status, smoke, CTFd readback, and rollback artifacts.
- #1238: define the cutover/archive/rollback plan before the live `polaris`
  selector is reclaimed.
- #1239: define legacy-path stability guardrails that keep current Shifter
  behavior passing during ACES migration.

Any Polaris SDL feature that cannot be represented by ACES contracts remains an
ACES schema/profile gap, not a Shifter-only semantic extension. Expected gap
areas include topology mutations, content/provenance, AD/domain semantics, CTF
metrics/prerequisites, image/content realization, Modbus/PLC state,
participant access, and evidence vocabulary.

## Gotchas And Anti-Patterns

- Do not satisfy parity with an APTL demo, local Docker run, or standalone
  `scripts/polaris-aws-range` success. The gate requires the Shifter backend
  path operators actually use.
- Do not make Polaris the adapter type system. Polaris is the proving case; the
  seam is the ACES Shifter profile.
- Do not encode ACES-owned gaps as fields in `cms.scenarios.schema`,
  `Scenario.definition`, provisioner plan names, Terraform variables, or
  Shifter-only YAML just to make Polaris pass.
- Do not create duplicate scenario schemas, validation helpers, status enums,
  event buses, exception hierarchies, API envelopes, CTFd clients, smoke
  schemas, artifact stores, or workflow DSLs.
- Do not shadow the live `polaris` catalog id before rollback is explicit.
- Do not bypass `cms.scenarios.hydrator`, `cms.services.create_range`,
  `engine.services`, `engine.interpreter`, provisioner CLI boundaries,
  `RangeEventOutbox`, Mission Control permissions, CTF bridges, or
  `ScriptExecutionContext`.
- Do not treat generated content, CTFd flags, prompt bodies, access URLs,
  provider payloads, or terminal transcripts as acceptable evidence-bundle
  contents.
- Do not weaken `EXPERIMENTS_ENABLED`, API-token exact scopes, terminal/Guacamole
  controls, import-linter, ADR guard, actionlint, Terraform/Kubernetes
  validators, secret scanning, or live-cloud fail-loud behavior to make the
  ACES path pass.

## Non-Goals

- No implementation of ACES parsers, sidecars, adapters, migrations, APIs,
  workflows, smoke runners, or runtime selectors in this preflight.
- No cutover from current Polaris to ACES-backed Polaris.
- No removal or archival of CyberScript, legacy scenario templates, current
  Polaris runtime material, CTF behavior, experiments, Mission Control,
  provisioner paths, artifacts, status models, or validation gates.
- No new Ground Control requirement UID for this requirement-free run.
- No live AWS/GCP/CTFd operation, range mutation, AMI bake, or GitHub issue
  closure from this preflight.

## Validation Expectations

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation must also run the stack-native checks required
by `AGENTS.md` and `.gc/plan-rules.md` for the paths it touches.

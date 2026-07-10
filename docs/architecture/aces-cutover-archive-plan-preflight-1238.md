# ACES Cutover And Archive Plan Preflight

Issue: GitHub #1238, "09 - ACES migration: cutover and archive plan."

Status: pre-implementation architecture guidance. This note does not implement
the ACES path, change defaults, create issues, remove code, archive files, run
live ranges, or mutate production behavior.

## Boundary

ADR-024 remains the controlling migration decision: current Shifter behavior is
authoritative until a parallel ACES path passes parity through the normal
portal, CMS, engine, provisioner, CTF, Mission Control, artifact, status, and
validation surfaces. ADR-027 is the explicit exception for the already-removed
legacy experiments path.

The #1238 boundary is cutover governance:

- Define the phase sequence from parallel operation to first ACES slice,
  parity validation, default cutover, and archive cleanup.
- Define the readiness gates before any public or default behavior changes.
- Define what remains reversible before final cutover.
- Define how CyberScript, legacy scenario templates, docs, issues, and tests
  stop being current authority without creating long-term dual authority.

This is not a file-local implementation plan. Later implementation issues must
design their code changes against the repo-wide constraints below.

## Cutover Sequence

| Phase | Allowed posture | Blocking gate before moving on |
| --- | --- | --- |
| Parallel current-default | Legacy Shifter scenario/runtime paths remain default. ACES entries may be visible only through explicit profile/package selectors such as a distinct `polaris-aces` catalog id. | Legacy launch, CTF, Mission Control, status, and provisioner behavior still pass. No ACES row shadows an active legacy id. |
| First ACES vertical slice | ACES proves `provisioning-only` through the Shifter catalog, hydrator, CMS service, engine service, task-runner, and provisioner path. | ACES package/profile validation, backend manifest/conformance, wrapped persisted spec creation, `request_id` operation correlation, and sanitized status/snapshot projection all pass. |
| Parity validation | Polaris and the inventory rows needed for the acceptance universe are proven through the normal Shifter operator path. | `docs/architecture/aces-migration-parity-inventory.yaml` rows are reconciled; #1237 evidence gates pass; Shifter smoke, CTFd readback, Mission Control/CTF projections, and ADR guard are green. |
| Controlled default cutover | The default selector can point at the ACES-backed path only with an explicit rollback selector and preserved legacy reference path. | One reviewed cutover record names the selector, legacy restore path, evidence bundle, known rollback window, and stale docs/issues/tests to retire. |
| Archive cleanup | CyberScript and legacy templates become reference material or are removed only after imports, loaders, docs, tests, and rollback posture no longer treat them as runtime authority. | Archive/delete inventory rows are satisfied by code, docs, tests, import boundaries, and release notes. No long-term dual-authority remains. |

## Cutover Decisions

- The default behavior must not change by implication. The cutover selector
  must be explicit at the catalog/profile/backend-manifest boundary, not hidden
  in YAML shape detection, path names, branch names, or Polaris-specific code.
- A legacy id such as `polaris` must not be reclaimed until the ACES path has
  parity evidence and a reversible selector. Before that, ACES uses a distinct
  id or a read-only migration link.
- CyberScript compatibility is freeze/maintain/archive work during the
  migration. It must not receive new scenario semantics that compete with ACES.
- Legacy scenario templates remain runtime authority until the selected ACES
  path launches through the same CMS, engine, provisioner, CTF, status, and
  Mission Control surfaces and the rollback window is defined.
- Archive means "no longer runtime authority." Reference retention is allowed
  when it is clearly labeled, disconnected from loaders/imports, and excluded
  from live validation except for historical/reference tests.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024 | Do not create a second cutover doctrine or issue-local source of truth. |
| Parity ledger | `docs/architecture/aces-migration-parity-inventory.yaml` | Use row ids for gate/cleanup scope; do not turn rows into a runtime schema. |
| Catalog/profile selector | `cms.scenarios.registry`, `ScenarioMetadata`, #1232 package-source boundary | One catalog projection, existing enablement/staff-only overlay, no ACES-only catalog or access model. |
| Legacy YAML loading | `cms.scenarios.loader` | Preserve slug validation, path containment, `yaml.safe_load`, and Pydantic validation until archive/delete gates pass. |
| Hydration | `cms.scenarios.hydrator` | ACES adapts into Shifter `RangeSpec` / `CTFRangeSpec` semantics here or at an adjacent adapter seam. |
| Launch handoff | `cms.services.create_range`, `engine.services`, `engine.interpreter` | Keep user/agent validation, active-range checks, request state, transactions, wrapped specs, and engine dispatch. |
| Operation/status | `request_id`, `RangeEventOutbox`, `apply_range_status`, `reconcile_range_events` | Use current outbox/reconciler-backed projection; no ACES-only lifecycle pipeline. |
| Runtime dispatch | `engine.ecs`, `shared.cloud` task runners, provisioner `main.py` | Structured argv keyed by ids only; no Terraform/cloud/shell calls from CMS, CTF, or Mission Control request paths. |
| Auth and scopes | `shared.auth`, `cms.api.permissions`, `mission_control.api.permissions`, `shared.api_tokens.scopes` | Service-layer authorization and exact scopes remain mandatory. UI hiding is not authorization. |
| Errors and logging | `shared.api.errors`, `shared.errors`, `shared.exceptions.CMSError`, `shared.log_sanitize`, provisioner `log_redact` | No duplicate ACES exception hierarchy, API envelope, or raw exception leakage. |
| Secrets/env | `shared.cloud`, `shared.cloud.sensitive_env`, `config/env-manifest.json`, runtime inventory | New selectors/retention/toggle knobs need explicit config and secret routing, not handler-local env reads. |
| CTF and Mission Control | `ctf.bridges`, `ctf.services.*`, `mission_control.api`, terminal and Guacamole services | Product semantics, access, scoring, status, token lifecycle, and capacity controls stay Shifter-owned. |
| Validation | ACES conformance tooling, `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard` | Cutover must pass ACES gates and repo gates without weakening either. |

## Cross-Cutting Layers

- Auth surface: catalog, package, conformance, and selector changes stay behind
  CMS authoring gates (`validate_cms_authoring_user`,
  `threat_research_required`, `HasCMSAuthoringActor`,
  `CMS_READ_PERMISSIONS`, `CMS_WRITE_PERMISSIONS`). Mission Control
  projections use `IsAuthenticatedSessionOrApiToken`,
  `HasMissionControlActor`, exact `mission_control:*` scopes, and participant
  lifecycle blockers. CTF flows keep organizer/participant ownership checks.
- Scenario and ACES shape: legacy YAML keeps loader/editor validation until it
  is no longer runtime input. ACES packages use explicit contract/profile,
  lock/digest, backend manifest, and conformance validation. Prose, filenames,
  or shape probes are not validation gates.
- Persistence shape: live Shifter state remains in CMS/engine/CTF/Mission
  Control models. ACES operation, status, snapshot, participant, evidence, or
  archive records must be version/profile-keyed sidecars. Hydrated runtime
  specs stay behind `wrap_persisted_spec` and `engine.interpreter`.
- Status/event shape: Shifter `ResourceStatus`, `engine.Range.Status`,
  `RangeEventOutbox`, bridge hooks, and reconcilers stay authoritative for
  product projection. ACES status is an adapter view with explicit mapping and
  tests.
- Secret-handling surface: evidence bundles, docs, logs, API responses, event
  payloads, audit JSON, workflow summaries, argv, and env literals must not
  contain private keys, bearer tokens, presigned URLs, CTF flags, CTFd admin
  tokens, Guacamole URLs, prompt bodies, scripts, provider payloads, raw
  package bodies, rendered runtime config, or credential values.
- OS/process exposure: launch, conformance, smoke, CTFd readback, and cleanup
  tooling use structured argv with ids, refs, digests, paths, or profile names.
  Request-time code must not execute arbitrary package commands or assemble
  shell fragments from ACES/YAML/CTFd content.
- Config/env validators: any cutover selector, launchability toggle,
  conformance path, evidence output path, retention policy, or cleanup cadence
  must be a typed setting with env-manifest/runtime-inventory coverage and
  tests when runtime configurable. Do not add opportunistic `ACES_*` reads in
  views, handlers, workers, or migrations.
- Error-envelope surface: DRF APIs use `shared.api.errors`; HTML views use
  existing typed/user-safe errors. Raw ACES parser, conformance, CTFd, cloud,
  Terraform, SSM, SSH, Docker, storage, or provider exceptions stay in
  sanitized diagnostics.
- Observability surface: log row ids, profile ids, counts, durations, request
  ids, status classes, report refs, digests, and fingerprints. Do not log
  terminal streams, generated commands, package bodies, credential values, or
  provider output dictionaries.
- Import-boundary surface: future ACES imports need the same discipline as
  current CyberScript imports. Keep ACES/CyberScript implementation packages
  behind `shared` and existing service facades unless a later ADR changes the
  import contract.
- Workflow validators: any architecture/workflow/platform change must pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`; runtime Python
  under `shifter/shifter_platform` also needs Ruff and import-linter; workflow,
  Terraform, and Kubernetes changes inherit `.gc/plan-rules.md`.

## Extensibility Seam

The required seam is one explicit cutover/profile selector at the catalog,
package-source, backend manifest, and hydrator/adapter boundary. It should
carry the active contract/profile and package/source identity for a scenario,
plus launchability/readiness state. Rollback changes that selector back to the
legacy path or disables the ACES entry; it must not require edits in CTF event
code, Mission Control templates, engine models, or provisioner internals.

Future variation should add profile/source/capability branches behind that
seam: another ACES profile, another provider, another package source, or a new
participant/evidence profile. It should not add new Shifter-only scenario
semantics, duplicate status enums, duplicate validators, or per-scenario
branches in core services.

## Cleanup Buckets

Cleanup must be issue-scoped after cutover evidence exists:

- CyberScript shared re-exports and schema shims:
  `cyberscript.shared-reexports` is an archive/delete row and can be retired
  only after import-linter/layer checks and tests prove no runtime dependency.
  `cyberscript.schema-shims` is an ACES schema/profile-gap row, not a delete:
  its ACES-owned semantics must first be mapped into ACES contract/profile
  coverage, and only the Shifter-only compatibility wrappers then become
  archive candidates once no runtime path treats them as authority.
- Legacy YAML templates and live Polaris template:
  `scenario.yaml-defaults` and `polaris.portal-template` can move to reference
  archive or removal only after the active catalog selector no longer loads
  them as current authority and rollback posture no longer depends on them.
- Polaris standalone and content evidence:
  `scenario-dev/polaris/**`, `scripts/polaris-aws-range/**`, content packages,
  image realization, and smoke harnesses remain evidence until the ACES path
  has equivalent coverage. Archive generated/runtime material separately from
  authored ACES SDL and provenance.
- Experiment remnants:
  ADR-027 already removed `cms.experiments`; stale references such as removed
  experiment template comments in locale files and older preflight notes should
  be updated or explicitly marked historical, not resurrected.
- Stale issue posture:
  Use `docs/architecture/aces-cyberscript-issue-triage.md` as the backlog
  disposition surface. Maintain/migrate issues such as legacy CyberScript docs,
  current production correctness bugs, and future ACES profile gaps should be
  re-reviewed after cutover; do not close or delete them from this preflight.
- Tests:
  Keep legacy behavior tests while legacy remains default. After cutover,
  convert them to archive/reference tests or remove them only when ACES parity
  tests, import-boundary tests, scenario registry tests, CTF range tests,
  Mission Control projection tests, and provisioner smoke evidence replace the
  same safety properties.

## Follow-Up Cleanup Issues

The cutover-execution and cleanup work above is tracked as GitHub issues so the
follow-on lives in the backlog, not only in this note. Each is gated on the
cutover evidence described here and carries a checklist against the parity
inventory rows:

- **#1310, execute controlled default cutover and rollback selector.** The
  Cutover Sequence "Controlled default cutover" phase: flip the explicit
  selector, reclaim the `polaris` id, and post the reviewed cutover record with
  a reversible rollback selector and preserved legacy reference path.
- **#1311, archive legacy scenario, CyberScript, and Polaris surfaces after
  cutover.** The archive/delete cleanup buckets: `cyberscript.shared-reexports`,
  the `cyberscript.schema-shims` compatibility wrappers, `scenario.yaml-defaults`
  / `polaris.portal-template`, and the Polaris standalone/content evidence under
  `scenario-dev/polaris/**` and `scripts/polaris-aws-range/**`.
- **#1312, retire stale migration docs and legacy scenario/runtime tests after
  cutover.** The experiment remnants, the CyberScript-triage re-review, and the
  legacy-test conversion/removal once ACES-path tests replace the same safety
  properties.

These issues are filed now for visibility but must not be worked before their
gating cutover evidence exists.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `docs/architecture/aces-catalog-package-boundary-preflight-1232.md`
- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/aces-experiment-core-preflight-1235.md`
- `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md`
- `docs/architecture/aces-polaris-acceptance-parity-gate-preflight-1237.md`
- `docs/architecture/aces-cyberscript-issue-triage.md`
- `docs/architecture/experiments-removal-adr.md`
- `shifter/shifter_platform/cms/scenarios/**`
- `shifter/shifter_platform/cms/scenario_editor/**`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/cms/api/**`
- `shifter/shifter_platform/shared/**`
- `shifter/shifter_platform/engine/**`
- `shifter/shifter_platform/ctf/**` through bridge/service seams
- `shifter/shifter_platform/mission_control/**`
- `shifter/engine/provisioner/**`
- `scenario-dev/polaris/**`
- `scripts/polaris-aws-range/**` and CTFd readback tooling
- `config/env-manifest.json`, runtime inventory, and deploy renderers for new
  runtime settings
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, `docs/adr/index.yaml`, and `docs/adr/exceptions.yaml`
  if guardrails or exceptions change

## Gotchas And Anti-Patterns

- Do not make legacy scenario semantics and ACES semantics co-equal long-term
  authorities. Parallel operation is temporary and gate-bound.
- Do not reclaim `polaris` or any other live id before the rollback selector is
  explicit and proven.
- Do not encode missing ACES vocabulary as Shifter-only YAML fields, Terraform
  variables, provisioner plan names, CTF challenge metadata, or Mission Control
  template logic.
- Do not turn parity inventories, evidence bundles, docs, issue bodies, audit
  JSON, snapshots, or event payloads into runtime schemas.
- Do not create duplicate schemas, validators, exception hierarchies, status
  taxonomies, event buses, API envelopes, artifact stores, upload-token
  formats, CTFd clients, or workflow DSLs for ACES.
- Do not bypass `cms.scenarios.registry`, `cms.scenarios.hydrator`,
  `cms.services`, `engine.services`, `engine.interpreter`, task-runner
  factories, `RangeEventOutbox`, CTF bridges, Mission Control permissions, or
  shared error/logging helpers.
- Do not archive or delete legacy paths while imports, loaders, docs, tests,
  rollback runbooks, or operator workflows still treat them as current.
- Do not weaken ADR guard, import-linter, API-token exact scopes, terminal and
  Guacamole controls, secret scanning, actionlint, Terraform, Kubernetes,
  conformance, or smoke gates to make cutover appear ready.

## Non-Goals

- No implementation of ACES parsers, package-source rows, sidecars, adapters,
  runtime selectors, conformance runners, UI/API projections, migrations, or
  cleanup jobs.
- No public/default behavior change and no cutover from legacy Shifter paths to
  ACES.
- No removal or archival of CyberScript, legacy scenario templates, current
  Polaris runtime material, CTF behavior, Mission Control, provisioner paths,
  artifacts, status models, or validation gates.
- No implementation, closure, or merge of the follow-up cleanup issues from
  this plan. The cutover-execution and cleanup issues (#1310, #1311, #1312) are
  filed for backlog visibility (see "Follow-Up Cleanup Issues") but are gated on
  the cutover evidence and are not worked here.
- No new Ground Control requirement UID for this requirement-free run.
- No live AWS/GCP/CTFd operation, range mutation, AMI bake, or evidence-bundle
  generation in this preflight.

## Validation Expectations

For this architecture note, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation must also run the stack-native checks required
by `AGENTS.md` and `.gc/plan-rules.md` for the paths it touches.

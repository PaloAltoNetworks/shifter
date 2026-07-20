# ACES Experiment-Core Preflight

Issue: GitHub #1235, "06 - ACES migration: redesign experiments around
ACES experiment-core."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, APIs, UI, event handlers, or a cutover.

Superseded note: ADR-027 / issue #1195 removed the legacy `cms.experiments`
runtime path. Future experiment-core work should start from a new ACES-backed
design rather than using the removed legacy models, routes, or feature flag as
compatibility records.

## Boundary

ADR-024 remains the controlling migration decision: current Shifter behavior is
authoritative until a parallel ACES path passes the parity inventory,
manifest/conformance, portal/engine/provisioner, CTF, experiment, Mission
Control, artifact, status, and validation gates.

Issue #1195 is the current local decision point for the half-built experiments
feature: experiments remain disabled by default through `EXPERIMENTS_ENABLED`,
routes are not registered while disabled, and `start_experiment_task` refuses
to launch executor tasks when disabled. #1235 does not remove that safety
posture and does not force a production cutover.

The experiment-core boundary for #1235 is:

- ACES owns experiment-core contract meaning: task, apparatus context, study,
  run, capture spec, evidence record, derived measure, contract versions,
  profiles, and conformance vocabulary.
- Shifter owns the current product behavior: feature exposure, CMS experiment
  authoring surfaces, service authorization, range provisioning, script and AI
  command execution, artifact storage, audit, logs, Mission Control projection,
  and operator recovery.
- Current `Experiment`, `ExperimentRun`, `ExperimentScript`, `RunArtifact`,
  `ExperimentArtifact`, and `ScriptAsset` rows are migration-only
  compatibility records during the parallel phase. They are not the future
  canonical ACES experiment-core store.
- No production behavior, table, route, artifact, event path, or feature flag
  is removed by this design. Archive/delete happens only in a later cutover
  issue after parity and rollback gates are explicit.

## Architecture Decisions

- Replace the bespoke experiment semantics by mapping to ACES-aligned records,
  not by extending the current `Experiment` / `ExperimentRun` model with more
  polymorphic JSON fields.
- Keep existing experiments code as a compatibility and migration reference
  until a separate implementation issue proves the ACES path. It may be
  retained temporarily, frozen to bug/security fixes, or hidden behind the
  existing feature flag. It must not become the long-term schema.
- Persist future canonical ACES experiment-core records in an ACES-owned
  sidecar surface keyed by explicit contract/profile/version identifiers. Do
  not store canonical ACES study/run/evidence/measure records in
  `ExperimentRun.metadata`, `RangeInstance.range_spec`,
  `engine.Range.provisioned_instances`, `AuditLog.new_state`, event payloads,
  or task-runner environment variables.
- Preserve live state versus archive state. `ExperimentStatus`, `RunStatus`,
  `engine.Range.status`, `ResourceStatus`, task ARNs, and `RangeInstance`
  projections are live operational state. ACES study/run/evidence/measure
  records are archival contract records and should be append/read oriented
  except for deliberate repair workflows.
- Use both experiment-run identity and operation identity where they differ:
  `ExperimentRun.uuid` or a future ACES run id identifies the archival
  experiment run; `request_id` correlates the provisioning operation and range
  projection. Do not make `range_id` the ACES experiment-run id.
- Keep command execution behind `cms.experiments.orchestrator.execution_plan`
  and `shared.script_context.ScriptExecutionContext`. ACES capture specs may
  reference capture intent, artifact classes, profiles, and evidence targets;
  they must not copy rendered commands, raw prompts, script bodies, private
  keys, tokens, or provider payloads into ACES records.
- Evidence records reference sanitized artifact metadata, immutable storage
  refs, digests, provenance, capture profile, and redaction status. They do
  not contain presigned URLs, upload tokens, raw transcripts, raw script output,
  CTF flags, or generated content unless a later ACES contract and redaction
  policy explicitly allows that payload class.
- Derived measures are a separate ACES contract layer over evidence. Do not
  conflate them with Shifter run status, CTF score, artifact count, duration,
  provider task state, or UI labels unless the ACES profile defines that
  measurement and tests the mapping.

## Concept Mapping

| Shifter concept | ACES experiment-core mapping | Guardrail |
| --- | --- | --- |
| `Experiment.scenario_id` | ACES task reference or task-backed catalog entry | Reference the scenario/package/profile identity; do not copy raw SDL/YAML into experiment rows. |
| `Experiment` | Migration-only study/run-batch compatibility record | Future ACES Study is explicit and contract-versioned, not `Experiment.status` with new meanings. |
| `ExperimentScript` and script assignments | Capture/execution input references | Capture spec records may reference intent and artifact classes; rendered commands stay behind `ScriptExecutionContext`. |
| `ExperimentRun.uuid` | ACES run identity candidate | Pair with `request_id` for operation correlation; do not use mutable range state as archival run identity. |
| `ExperimentRun.request_id` | ACES operation correlation key | Align with #1234 operation/status/snapshot sidecars; `range_id` stays Shifter projection/backfill state. |
| `ExperimentRun.status` | Shifter live run state | Map deliberately to ACES run lifecycle only after the profile exists; never infer by lowercase string names. |
| `ExperimentRun.metadata.provisioned_instances` | Apparatus context reference material | Replace with references to sanitized operation/runtime context; do not store full provider dumps. |
| `RangeInstance`, `engine.Range`, provisioned instances | Apparatus context and live runtime realization | Shifter remains authoritative for mutable runtime state; ACES stores archival context refs/snapshots. |
| `RunArtifact`, `ExperimentArtifact`, Claude transcript artifacts | ACES evidence records | Store refs, digests, type/profile, provenance, redaction state, and ownership; no presigned URLs or raw secrets. |
| Future metrics over artifacts | ACES derived measures | Define formulas/contracts separately from status and scoring workflows. |

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024 | Keep ACES parallel and parity-gated; do not replace current behavior by declaration. |
| Operation/status boundary | `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md` | Reuse `request_id`, operation sidecars, status projection, and runtime snapshot separation. |
| Backend manifest/profile | `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md` | Do not claim ACES evaluator/orchestrator/participant-runtime capability until conformance exists. |
| AI execution policy | `docs/architecture/ai-experiment-execution-boundary.md`, `shared.script_context` | Preserve prompt/command boundaries and policy payloads. |
| Current experiment schemas | `cms.experiments.schemas`, transition maps, `Experiment.transition_to`, `ExperimentRun.transition_to` | Treat as compatibility live state; do not duplicate or silently reinterpret statuses. |
| Experiment services | `cms.experiments.services` public facade | Existing ownership, validation, audit, upload, and lifecycle behavior stay service-owned. |
| Execution planning | `cms.experiments.orchestrator.execution_plan`, `ScriptCommand`, `RunExecutionPlan` | All prompt/script/runtime rendering remains behind `ScriptExecutionContext`. |
| Range provisioning | `cms.scenarios.hydrator`, `RequestSpec`, `cms.models.Request`, `engine.services.create_range`, `RangeInstance` | Keep the hydrate -> request -> engine handoff for Shifter runtime. |
| Artifact/upload security | `cms.experiments.s3`, `cms.assets`, `shared.uploads.inspection`, `shared.cloud` | Reuse signed upload tokens, exact-size checks, full-body script inspection, storage adapters, and key normalization. |
| API auth/errors | `cms.api.permissions`, `shared.api_tokens.scopes`, `shared.api.errors`, `shared.errors` | Future API projections use existing session/API-token gates, exact scopes, serializers, and safe envelopes. |
| HTML auth | `shared.auth.threat_research_required`, `validate_cms_authoring_user`, `can_edit_cms_authoring` | UI hiding and feature flags are not authorization; services still validate actors. |
| Logging and audit | `shared.log_sanitize`, `risk_register.services.audit_log`, `audit_log_system_event`, provisioner `log_redact` | Logs and audit carry sanitized ids/status/classes, not raw ACES payloads or experiment contents. |
| Runtime config | `config/settings.py`, `config/env-manifest.json`, `config/_cloud.py`, `shifter/installation/runtime_inventory.py` | New knobs require explicit settings, inventory, rendering, and tests; no handler-local env reads. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | ACES imports remain behind `shared` and service seams. |

## Cross-Cutting Layers

- Feature exposure surface: `EXPERIMENTS_ENABLED`, `config.urls`, the shared
  context processor, and `start_experiment_task` continue to gate the unfinished
  feature. Future ACES experiment-core APIs or UI must preserve this boundary
  until a separate graduation issue changes it deliberately.
- Auth surface: HTML experiment flows stay behind `threat_research_required`
  and service `_validate_user` / CMS authoring validation. DRF work uses
  `IsAuthenticatedSessionOrApiToken`, `HasCMSAuthoringActor`,
  `CMS_READ_PERMISSIONS` / `CMS_WRITE_PERMISSIONS`, and exact
  `cms:authoring:*` scopes. Scope checks do not replace ownership checks.
- Scenario/task shape: task references enter through the catalog/registry and
  ACES package/profile boundaries from #1232. Legacy YAML still uses scenario
  slug validation, path containment, `yaml.safe_load`, and Pydantic validation.
  Do not infer ACES task/profile from YAML shape, scenario id, or Polaris file
  paths.
- ACES contract shape: Study, Run, ApparatusContext, CaptureSpec,
  EvidenceRecord, and DerivedMeasure payloads validate through ACES
  contract/profile/conformance gates. Shifter may add shared-native sidecar
  metadata schemas, but not app-local duplicate ACES schemas.
- Persistence shape: live Shifter runtime state remains in existing tables and
  persisted specs remain wrapped through `shared.schemas.persistence` and
  `engine.interpreter`. ACES experiment-core sidecars need unique keys,
  idempotency, ownership, retention, redaction, and migration semantics in
  first-class fields rather than hidden JSON subfields.
- Script/prompt/OS exposure: `ScriptExecutionContext` remains the prompt,
  S3-key, instance-id, private-IP, command-rendering, and AI-policy gate.
  Structured task argv may carry only bounded ids and operation names. Raw
  prompts, commands, scripts, credentials, ACES records, and provider
  diagnostics must not move into argv, shell strings, local subprocess calls,
  workflow logs, or Kubernetes Job env literals.
- Task-runner/env surface: `EXPERIMENT_PAYLOAD` is plain environment payload
  today and must not carry secret material. If a future executor needs
  secret-bearing payloads, use the shared task-runner sensitive-env/Secret
  path and update the AI execution boundary before enabling it.
- Artifact and secret-handling surface: upload tokens, presigned URLs, bearer
  tokens, private keys, script bodies, transcript bodies, prompt bodies, CTF
  flags, rendered runtime config, cloud credentials, provider outputs, and raw
  package bodies stay out of logs, audit JSON, docs snippets, OpenAPI examples,
  API responses, event payloads, DLQs, and test fixtures.
- Error-envelope surface: HTML views use curated Django messages for typed
  experiment errors and generic messages for unexpected exceptions. DRF/API
  projections use `shared.api.errors` and `classify_user_message` /
  `safe_user_message`. Raw ACES parser, storage, SSM, SSH, Docker, cloud, or
  provider exceptions stay in sanitized logs.
- Event/projection surface: correctness-critical range projection remains with
  `RangeEventOutbox`, `cms.handlers.range_events`, `experiment_bridge`,
  Mission Control handlers, and `reconcile_range_events`. Do not add an
  ACES-only event bus, websocket topic, lifecycle enum, or reconciler.
- Import-boundary surface: CMS experiments may use `shared`, CMS services, and
  engine service facades already allowed by the repo. They must not import
  ACES implementation packages, CyberScript internals, Mission Control, CTF, or
  engine models directly to reach sidecar data.

## Extensibility Seam

The required seam is an explicit `experiment_core_profile` or equivalent
contract/profile discriminator on the ACES sidecar and adapter boundary. The
first value should represent the Shifter ACES experiment-core profile that can
map current experiment compatibility records without claiming evaluator,
orchestrator, or participant-runtime capability beyond #1233.

The next likely variation is not another status string; it is another capture,
evidence, or derived-measure profile. Add those as profile/capability branches
behind the shared sidecar and adapter boundary. Do not edit CMS views, CTF
flows, Mission Control templates, engine models, and task-runner payloads for
each variation.

Storage variation also belongs behind data references: repository ref, object
storage ref, digest, artifact type/profile, retention class, and redaction
state. Do not bake an S3-only or transcript-only assumption into ACES records.

## Follow-Up Issues To File Or Confirm

- Storage: add ACES experiment-core sidecar records for study, task refs,
  apparatus-context refs, run records, capture specs, evidence records, and
  derived measures with version/profile discriminators, idempotency keys,
  retention, redaction, and ownership. Candidate title: "ACES migration:
  implement experiment-core storage sidecars."
- Evidence and capture mapping: map `ScriptAsset`, `ExperimentScript`,
  `RunArtifact`, `ExperimentArtifact`, and Claude transcript artifacts to ACES
  capture/evidence records without copying rendered commands, prompt bodies, or
  raw artifact contents. Candidate title: "ACES migration: map experiment
  capture specs and evidence records."
- API projection: expose read-only experiment-core projections through the
  existing CMS API auth, exact scopes, serializers, feature flag, and shared
  error envelope. Do not create an ACES-only API surface. Candidate title:
  "ACES migration: expose read-only experiment-core API projections."
- UI projection: show ACES-backed experiment/run/evidence status in existing
  experiment or Mission Control surfaces as read-only migration evidence until
  a separate launch/cutover issue graduates it. Candidate title: "ACES
  migration: surface experiment-core projections in the UI."
- Migration and cutover gate: decide when current experiment creation,
  orchestration, and artifact flows become frozen, archived, removed, or
  replaced. That issue must include parity evidence and rollback posture.
  Candidate title: "ACES migration: define experiment cutover and legacy
  archive gate."
- Derived measures: define the first Shifter-supported measure profile and
  formulas over evidence records. Keep it separate from run status, CTF score,
  and UI display labels. Candidate title: "ACES migration: define first
  experiment derived-measure profile."

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/ai-experiment-execution-boundary.md`
- `shifter/shifter_platform/cms/experiments/**`
- `shifter/shifter_platform/cms/scenarios/**`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/cms/api/**`
- `shifter/shifter_platform/shared/**`
- `shifter/shifter_platform/engine/**`
- `shifter/shifter_platform/mission_control/**`
- `shifter/shifter_platform/ctf/**` only through existing bridge/service seams
- `shifter/engine/provisioner/**` when executor/provisioner realization changes
- `shifter/shifter_platform/config/settings.py`,
  `config/env-manifest.json`, `config/_cloud.py`, and
  `shifter/installation/runtime_inventory.py` for new config keys
- provider/task-runner surfaces under `platform/terraform/**`,
  `platform/k8s/**`, and `platform/charts/**` only if runtime deployment
  contracts change
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, `docs/adr/index.yaml`, and
  `docs/adr/exceptions.yaml` if guardrails or exceptions change

## Gotchas And Anti-Patterns

- Do not remove current experiment behavior, tables, routes, templates,
  artifacts, event handlers, feature flags, or task launch guards in #1235.
- Do not make `ExperimentRun.metadata` the ACES archive because it already
  accepts JSON.
- Do not copy command strings, prompt bodies, script contents, transcript
  bodies, provider dumps, or presigned URLs into ACES records.
- Do not add a second experiment status taxonomy, event bus, websocket topic,
  exception hierarchy, API envelope, artifact store, upload-token format, or
  task-runner abstraction.
- Do not conflate live range/runtime state with archival ACES run records.
- Do not equate Shifter experiments with ACES Evaluator, Orchestrator, or
  ParticipantRuntime capability until those protocols and conformance gates
  exist.
- Do not bypass `cms.experiments.services`, `cms.scenarios.hydrator`,
  `engine.services`, `ScriptExecutionContext`, `shared.cloud`, or shared API
  permissions to make the ACES path work quickly.
- Do not weaken `EXPERIMENTS_ENABLED`, import-linter, ADR guard, API token
  scope validation, secret scanning, upload inspection, command rendering, or
  error-envelope policy during migration.
- Do not make Polaris or a single current experiment scenario the public type
  system. It is evidence for parity, not the adapter contract.

## Non-Goals

- No implementation of ACES experiment-core models, migrations, APIs,
  serializers, UI, event handlers, workers, cleanup jobs, or data backfills in
  this preflight.
- No production behavior removal or feature graduation.
- No claim that current experiments implement ACES evaluator, orchestrator,
  participant runtime, or derived-measure protocols.
- No conversion of historical experiments into ACES archives.
- No new Ground Control requirement UID for this requirement-free run.
- No creation, merge, close, or cleanup of GitHub issues in this preflight.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation under `shifter/shifter_platform` also needs the
stack-native checks required by `AGENTS.md` and `.gc/plan-rules.md` for the
files it touches.

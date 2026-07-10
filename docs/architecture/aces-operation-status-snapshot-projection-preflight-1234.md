# ACES Operation Persistence And Range Projection Preflight

Issue: GitHub #1234, "05 - ACES migration: design operation, status,
snapshot, and range projection persistence."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, APIs, event handlers, or UI projections.

ADR-027 note: legacy experiment bridge and `cms.experiments` references in this
preflight describe the pre-removal state. Future experiment status projection
must come from a new ACES-backed design rather than the deleted app.

## Boundary

ADR-024 remains the controlling migration decision: current Shifter runtime
behavior is authoritative until the parallel ACES path passes parity,
manifest/conformance, portal/engine/provisioner, CTF, Mission Control, artifact,
status, and validation gates. Legacy experiments are the ADR-027 exception.

The #1234 boundary is persistence and projection:

- ACES operation receipts, operation status, runtime snapshots, and execution
  plans are canonical ACES contract records once validated against the ACES
  contract/profile that introduced them.
- Shifter `engine.Request` / `cms.Request` are the existing correlation
  aggregates for one launched provisioning request. The shared UUID
  `request_id` is the primary operation identity for ACES-backed ranges.
- `engine.Range` remains Shifter's authoritative mutable runtime state for
  range lifecycle and provider-owned realization.
- `cms.RangeInstance`, Mission Control status cards, websocket payloads, and CTF
  range views are compatibility projections over authoritative state. They must
  not become a second ACES record store.
- Runtime snapshots are operational observation records. They are not archival
  experiment history, not audit logs, not raw provider dumps, and not a place
  to stuff run transcripts, prompts, challenge evidence, flags, or generated
  content.

## Architecture Decisions

- Use `request_id` as the ACES operation correlation key. It already spans
  CMS `Request`, engine `Request`, engine `Range`, provisioner argv, event
  payloads, `RangeInstance`, experiment `ExperimentRun.request_id`, and
  Mission Control websocket groups. `range_id` remains a Shifter engine
  projection/backfill key for legacy handlers and UI links.
- Persist canonical ACES contract records in an ACES-owned sidecar surface
  keyed by operation id and contract version/profile. Do not overload
  `engine.Range.range_config`, `engine.Range.provisioned_instances`,
  `engine.Instantiation.state`, `cms.RangeInstance.range_spec`,
  `ExperimentRun.metadata`, or `AuditLog.new_state` as polymorphic ACES blobs.
- Keep Shifter runtime state in the existing Shifter tables. ACES receipts and
  statuses may reference Shifter `request_id`, `range_id`, task id, status, and
  sanitized diagnostic ids, but they do not replace `engine.Range.status`,
  `ResourceStatus`, `RangeEventOutbox`, or the DB-authoritative reconciler.
- Project ACES status into existing range surfaces through the current
  handler/service seams: `engine.services`, `cms.handlers.range_events`,
  `apply_range_status`, `ctf_bridge`, `experiment_bridge`, Mission Control
  handlers, and `reconcile_range_events`. Do not introduce an ACES-only range
  lifecycle, websocket topic, event bus, or status enum.
- Treat ACES runtime snapshots as bounded, redacted, latest-observation
  records plus optional short retention history. They may contain normalized
  resource identity, lifecycle/status, timestamps, capability/profile ids, and
  sanitized diagnostics. They must not contain secrets, private keys, bearer
  tokens, presigned URLs, prompt bodies, generated scripts, full Terraform or
  cloud provider payloads, CTF flags, transcript bodies, or raw package bodies.
- Execution plans must stay separated by domain. Shifter experiment execution
  plans remain behind `cms.experiments.orchestrator.execution_plan` and
  `ScriptExecutionContext`; ACES execution-plan contracts belong to the ACES
  operation sidecar only after the relevant ACES profile exists. Do not copy
  Shifter experiment command strings into runtime snapshots.
- Auditable lifecycle actions continue to use `risk_register.services.audit_log`
  and `AuditLog` enum choices. ACES receipts may be audit-relevant evidence,
  but an ACES receipt is not an `AuditLog` row and `AuditLog` JSON is not the
  canonical ACES receipt store.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024 | Keep ACES parallel and parity-gated; do not replace current behavior by declaration. |
| Backend manifest/profile | `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md` | First slice remains `provisioning-only` and declares `operation-receipt-v1`, `operation-status-v1`, and `runtime-snapshot-v1` only within that claim. |
| Parity rows | `docs/architecture/aces-migration-parity-inventory.yaml` rows `status.engine-range`, `mission-control.range-ui`, `experiment.lifecycle`, `experiment.execution-plan`, `provisioner.persisted-specs`, `provisioner.range-services`, and validation rows | Cite row ids for follow-up work; do not turn the inventory into a runtime schema. |
| Operation identity | `cms.models.Request.request_id`, `engine.models.Request.request_id`, `engine.Range.request`, `engine.ecs._start_range_ecs_task`, provisioner `main.py --request-id` | Use `request_id` as the ACES operation id/correlation id. Keep `range_id` legacy/projection-only. |
| Runtime authority | `engine.models.Range`, `Instance`, `Subnet`, `Range.Status`, `provisioner_db.write_provisioned_state`, `provisioner_db.update_range_status` | Continue writing authoritative mutable runtime state through existing engine/provisioner paths. |
| Compatibility projection | `cms.models.RangeInstance`, `cms.handlers.range_events.apply_range_status`, `cms.management.commands.reconcile_range_events` | ACES-backed ranges must still drive current `RangeInstance` status until projections are intentionally replaced. |
| Event durability | ADR-025, `RangeEventOutbox`, `drain_range_event_outbox`, `shared.messages.events`, `parse_sns_message` | Status propagation remains transactional-outbox/reconciler-backed; events carry ids/status, not snapshots or secrets. |
| Persisted specs | `shared.schemas.persistence.wrap_persisted_spec`, `engine.interpreter` | ACES-derived Shifter runtime specs still enter engine rows through the existing persisted-spec envelope. |
| Experiment plans | `cms.experiments.schemas`, `ExperimentRun`, `build_execution_plan`, `ScriptExecutionContext` | Do not duplicate experiment state machines or command validation in ACES snapshot/projection code. |
| API/auth/errors | `mission_control.api.permissions`, `cms.api.permissions`, `shared.api_tokens.scopes`, `shared.api.errors`, `shared.errors` | Any API projection uses existing session/API-token gates, exact scopes, DRF serializers, and safe error envelopes. |
| Audit/logging | `risk_register.services.audit_log`, `AuditEvent`, `AuditLog`, `shared.log_sanitize`, provisioner `log_redact` | Audit rows and logs carry sanitized ids/status/diagnostic classes only; full ACES payloads stay out of logs and audit JSON. |
| Runtime config | `config/settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, `config/_cloud.py` | New retention/reconcile knobs must be explicit settings and inventory entries, not handler-local `os.environ` reads. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | ACES imports remain behind `shared` and existing CMS/engine service seams. |

## Cross-Cutting Layers

- Auth surface: Mission Control projections use
  `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, range read/write
  scopes, and participant lifecycle blockers. CMS authoring/conformance
  surfaces use `CMS_READ_PERMISSIONS` / `CMS_WRITE_PERMISSIONS`,
  `HasCMSAuthoringActor`, and `validate_cms_authoring_user`. UI hiding is not
  authorization.
- Contract shape: canonical ACES records must validate through ACES
  `operation-receipt-v1`, `operation-status-v1`, `runtime-snapshot-v1`, and
  profile/conformance gates. Shifter may define a shared-native sidecar schema
  for persistence metadata, but not an app-local duplicate ACES schema.
- Shifter status shape: projected range state uses `shared.enums.ResourceStatus`
  and `engine.Range.Status`. Any ACES status mapping must be explicit and
  tested; do not infer by lowercase strings, provider task states, or UI labels.
- Persistence shape: Shifter runtime specs remain wrapped by
  `wrap_persisted_spec`; engine/CMS rows stay responsible for runtime state;
  ACES sidecars store ACES contract records and sanitized metadata only. Any
  new sidecar model needs ownership, unique keys, idempotency, retention, and
  migration semantics in the model, not hidden in JSON subfields.
- Event-delivery shape: correctness-critical projection changes must use
  `RangeEventOutbox`, `drain_range_event_outbox`, worker ack-after-handler
  retry, and `reconcile_range_events`. Mission Control websocket fanout remains
  advisory and must not be the only ACES projection path.
- Secret-handling surface: snapshots, receipts, status payloads, audit rows,
  event payloads, API responses, logs, Terraform outputs, DLQs, and test
  fixtures must exclude secrets, credential values, token-bearing URLs, private
  keys, prompt bodies, rendered command strings, generated scripts, flags, and
  raw provider diagnostics. Store references only when the existing
  `shared.cloud`/Secret Manager/SSM shape already treats them as references,
  and log them through fingerprints when needed.
- OS/process exposure: provisioner operations continue through structured argv
  `["range", <operation>, "--request-id", <uuid>]` and task-runner env
  contracts. Do not put ACES payloads, snapshots, execution plans, credentials,
  or provider diagnostics in argv, shell strings, Kubernetes Job env literals,
  workflow logs, or local subprocess command lines.
- Env-binding/config validators: if snapshot retention, ACES projection
  reconciliation, or cleanup cadence becomes configurable, add explicit
  settings, env-manifest coverage, runtime inventory/back-end rendering, and
  tests. Do not add dynamic `ACES_*` reads in handlers or migrations.
- Error-envelope surface: browser/DRF responses use `shared.api.errors` and
  `classify_user_message`/`safe_user_message`. Raw ACES parser, Terraform,
  cloud, SSM, SSH, Docker, and provider exceptions stay in sanitized logs or
  bounded operator diagnostics.
- Audit surface: lifecycle audit continues through `risk_register.services`.
  Add `AuditLog` enum/schema changes only for real Shifter auditable actions,
  with migration, admin/API visibility, and docs; do not use audit JSON as the
  ACES receipt table.
- Import-boundary surface: CMS, CTF, Mission Control, and experiments must not
  import ACES implementation packages or engine models directly to reach
  sidecar data. Shared contracts and service facades are the boundary.

## Extensibility Seam

The required seam is an explicit operation-contract/profile discriminator on
the ACES sidecar and adapter boundary, keyed by `request_id` and capability.
The first value should align with the #1233 `provisioning-only` backend
profile. Later values may add orchestration, evaluation, participant runtime,
or additional providers only by adding contract/profile branches behind the
adapter, not by editing `RangeInstance`, Mission Control templates, experiment
metadata, or event handlers for each variation.

Snapshot retention needs an explicit policy seam:

- current projection: the latest sanitized snapshot needed to answer status
  and range UI queries;
- short operational history: bounded rows for troubleshooting/replay, with
  retention and cleanup cadence configured per environment;
- archival experiment evidence: separate experiment/artifact/evidence records,
  never `runtime_snapshot.metadata`.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `docs/adr/index.yaml`, especially ADR-024 and ADR-025
- `shifter/shifter_platform/shared/**`
- `shifter/shifter_platform/cms/models/{provisioning,range}.py`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/cms/handlers/**`
- `shifter/shifter_platform/cms/management/commands/reconcile_range_events.py`
- `shifter/shifter_platform/cms/experiments/**`
- `shifter/shifter_platform/engine/models.py`
- `shifter/shifter_platform/engine/services/**`
- `shifter/shifter_platform/engine/ecs.py`
- `shifter/shifter_platform/engine/management/commands/drain_range_event_outbox.py`
- `shifter/engine/provisioner/{main.py,events.py,provisioner_db.py,terraform_ops.py,log_redact.py}`
- `shifter/shifter_platform/mission_control/api/**` and
  `shifter/shifter_platform/mission_control/handlers.py`
- `shifter/shifter_platform/ctf/**` only through existing bridge/service seams
- `shifter/shifter_platform/config/settings.py`,
  `config/env-manifest.json`, `config/_cloud.py`, and
  `shifter/installation/runtime_inventory.py` for new config keys
- provider messaging/task-runner surfaces under `platform/terraform/**`,
  `platform/k8s/**`, and `platform/charts/**` only when the runtime/deployment
  contract changes
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, and
  `scripts/adr_guard/**` when import or guardrail policy changes

## Follow-Up Implementation Issues

The design is split into these implementation issues:

- #1273: add ACES operation sidecar records for receipts,
  statuses, snapshots, and execution-plan references with version/profile
  discriminators, idempotency keys, redaction policy, and retention cleanup.
  Use
  `docs/architecture/aces-operation-sidecar-persistence-preflight-1273.md`
  for the issue-specific sidecar persistence guardrails.
- #1274: map ACES operation status into existing
  `RangeEventOutbox`, `ResourceStatus`, `RangeInstance`, CTF/experiment bridges,
  and reconciler behavior without adding a second lifecycle pipeline.
- #1275: expose read-only ACES operation/status/snapshot projections through the
  existing Mission Control/CMS API auth, serializer, and error-envelope
  patterns.
- #1276: show ACES-backed range state in current Mission Control/range
  surfaces while preserving existing range lifecycle UX and websocket behavior.
- #1277: implement snapshot redaction, bounded retention, cleanup,
  and audit visibility rules without turning snapshots into archival experiment
  records. Use
  `docs/architecture/aces-snapshot-retention-redaction-audit-preflight-1277.md`
  for the issue-specific retention, redaction, cleanup, and audit guardrails.

## Gotchas And Anti-Patterns

- Do not make `range_id` the ACES operation id; it is legacy/engine-local and
  absent until after dispatch in request-based flows.
- Do not store ACES receipts/status/snapshots in `RangeInstance.range_spec`,
  `Range.provisioned_instances`, `ExperimentRun.metadata`, `AuditLog.new_state`,
  or event payload JSON just because those fields already accept JSON.
- Do not add a parallel ACES status enum, event bus, websocket channel,
  exception hierarchy, API envelope, audit table, or scenario/runtime schema.
- Do not conflate ACES operation status with Shifter `ResourceStatus`, CTF
  participant status, experiment `RunStatus`, provider task status, or UI
  display labels. Map them deliberately.
- Do not turn runtime snapshots into experiment archives. Store transcripts,
  prompts, collected artifacts, scoring/evaluation evidence, and generated
  content in the experiment/artifact/evidence domains that own them.
- Do not put full provisioned instance state, provider responses, Terraform
  outputs, SSM output, SSH output, command strings, package bodies, or secrets
  in events, DLQs, audit rows, logs, API responses, or docs examples.
- Do not bypass `engine.services`, `cms.services`, `engine.interpreter`, the
  provisioner CLI, or cloud task-runner factories to make ACES operations work.
- Do not weaken ADR guard, import-linter, event delivery recovery, API token
  scope validation, or secret-scanning policy for the ACES migration path.

## Non-Goals

- No implementation of ACES models, migrations, APIs, handlers, UI, or cleanup
  jobs in this preflight.
- No replacement of `engine.Range`, `cms.RangeInstance`, `ResourceStatus`,
  `RangeEventOutbox`, Mission Control range UX, CTF range workflows, or
  experiment orchestration.
- No ACES orchestrator/evaluator/participant-runtime claim beyond the
  `provisioning-only` backend profile from #1233.
- No backfill of historical experiments into ACES snapshots.
- No new Ground Control requirement UID for this requirement-free run.
- No further GitHub issue creation beyond the reviewed, narrowly scoped
  follow-ups listed above unless a later implementation discovers a concrete
  missing work item.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation under `shifter/shifter_platform` also needs the
stack-native checks required by `AGENTS.md` and `.gc/plan-rules.md` for the
files it touches.

# ACES Participant Runtime History And Evidence Preflight

Issue: GitHub #1289, "20 - ACES migration: capture participant runtime history
and evidence."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, APIs, evidence capture, execution services, workers, UI, or
tests, and it is not an implementation plan. This is a requirement-free run; the
GitHub issue is the shipping contract.

## Boundary

The controlling decisions remain ADR-024, ADR-027, the parent #1236
participant-runtime/Mission Control preflight, and the #1288 participant-runtime
sidecar slice:

- Current Shifter runtime, CTF, Mission Control, upload, storage, audit, and
  logging behavior remains authoritative until a later ACES path passes parity
  and conformance gates.
- ADR-027 removed the legacy `cms.experiments` app. Stale experiment references
  in older docs describe a removed path; #1289 must not reintroduce those
  models, routes, workers, metadata fields, or status strings.
- `shared.models.AcesParticipantRuntimeRecord` is the incumbent participant
  sidecar, and `shared.models.AcesOperationRecord` is the incumbent operation
  receipt/status/snapshot/execution-plan-reference sidecar. #1289 should extend
  these shared seams before proposing a new persistence abstraction.
- Evidence capture is reference-oriented. It may map scripts, prompts, dispatch
  receipts, behavior-history events, transcripts, and artifacts to ACES-aligned
  references, but it must not copy raw execution inputs, terminal streams,
  credentials, token URLs, or provider payloads into ACES rows.

## Architecture Decisions

- Default to explicit reference record kinds in the existing participant-runtime
  sidecar family for behavior-history and evidence references. Add a sibling
  shared sidecar only if cardinality, retention, or indexing cannot be handled
  by `AcesParticipantRuntimeRecord`; any sibling must mirror the same shared
  validation, idempotency, digest, retention, and projection pattern.
- Keep command dispatch receipts and execution-plan references in the operation
  sidecar vocabulary (`AcesOperationRecord` / `execution_plan_ref` /
  `operation_receipt`). Participant evidence rows may reference operation ids,
  operation-record ids, receipt refs, and digests, but they must not store
  rendered commands or dispatch payloads.
- Evidence payloads must be small, allowlisted, and append/reference oriented.
  Required vocabulary belongs in shared validators and constants, not ad hoc
  per-controller JSON. The minimum profile fields are:
  `evidence_kind`, `capture_profile`, `artifact_ref`, `artifact_digest`,
  `provenance_source`, `provenance_ref`, `redaction_state`,
  `redaction_policy`, `retention_class`, `source_timestamp`, and bounded
  correlation refs such as `request_id`, `participant_ref`, `range_id`,
  `range_instance_id`, and optional `operation_id`.
- Store provenance as refs and digests, not bodies. Python scripts, Claude
  prompts, transcripts, artifacts, terminal output, and provider diagnostics are
  cited by storage ref, digest, source service, capture profile, and redaction
  state only.
- Preserve existing authorities. `ScriptExecutionContext`, future
  ACES-backed experiment services, upload inspection, object-storage adapters,
  Mission Control access services, CTF services, `AuditLog`, and logging
  helpers remain the boundaries that own raw material and policy decisions.
- Validate before persistence and redact again at response time. Shared schema
  validators reject unsafe keys/values, body-shaped fields, unbounded JSON,
  invalid profile/version pairs, digest drift, and unsupported retention or
  redaction vocabulary. Shared projections then apply response allowlists.
- Keep read surfaces product-scoped. Mission Control reads stay under
  `/api/v1/mission-control/range/<request_id>/...` with ownership checks before
  sidecar lookup. Do not add a global `/api/v1/aces/` evidence API for this
  slice.
- Do not update the backend manifest to claim ACES `participant_runtime`.
  History/evidence references are migration support until ACES
  participant-runtime lifecycle/history/evidence contracts and conformance exist.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024, `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md` | Keep ACES parallel, sidecar-backed, and parity-gated. |
| Participant sidecar | `shared.models.AcesParticipantRuntimeRecord`, `shared.aces.participant_runtime`, `shared.schemas.aces_participant_runtime`, `shared.aces.participant_runtime_projections` | Extend record-kind/profile vocabulary here first; do not add app-local evidence schemas. |
| Operation receipts | `shared.models.AcesOperationRecord`, `shared.aces.operations`, `shared.schemas.aces_operation`, `execution_plan_ref` | Reuse operation sidecars for dispatch receipts and execution-plan refs; participant evidence stores refs to them. |
| Shared validation | `shared.schemas._aces_validation` | Reuse digest, bounded ref, timestamp, JSON size, diagnostic ref, and secret rejection primitives. |
| Execution boundary | `shared.script_context.ScriptExecutionContext`, `build_ai_execution_policy_payload`, `docs/architecture/ai-experiment-execution-boundary.md` | Treat scripts/prompts as execution inputs and capture intent, not ACES evidence bodies. |
| Removed experiments | ADR-027, `cms/migrations/0034_remove_legacy_experiments.py`, `tests/cms/test_experiments_removed.py` | Do not resurrect deleted `cms.experiments` runtime code or metadata. |
| Upload inspection | `cms.services._uploads`, `cms.assets.upload_token`, `cms.assets.s3`, `shared.uploads.inspection`, `ctf.services.attachment` | Keep signed tokens, ownership, exact size, inspection, immutable copy, and storage-key normalization outside ACES rows. |
| Object storage | `shared.cloud.aws.storage`, `shared.cloud.gcp.storage`, CMS/CTF storage facades | Evidence refs cite stable storage keys/refs and digests, never presigned URLs or upload tokens. |
| Mission Control APIs | `MissionControlReadAPIView`, `_validated`, `AcesParticipantRecordQuerySerializer`, `mission_control.api.aces_participant` | Reuse auth, scopes, ownership checks, serializers, bounded limits, and canonical error handling. |
| Auth/scopes | `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `shared.api_tokens.scopes`, CTF/CMS permission helpers | Exact scopes and service-layer ownership checks remain mandatory. |
| Events/status | `RangeEventOutbox`, `drain_range_event_outbox`, `cms.handlers.range_events`, `reconcile_range_events`, CTF bridges | Evidence rows do not create a second status pipeline, event bus, or websocket topic. |
| Audit/logging | `risk_register.services.audit_log`, `AuditEvent`, `shared.log_sanitize`, provisioner `log_redact` | Audit and logs carry sanitized refs/counts/statuses only; ACES rows are not audit logs. |
| Errors | `shared.api.errors`, `shared.errors`, `shared.exceptions.CMSError`, CTF exceptions | Translate at domain boundaries; do not add an ACES-only exception hierarchy or raw provider error envelope. |
| Runtime config | `config/settings.py`, `config/_aces_settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py` | New retention/profile/capture knobs need canonical settings and inventory/render coverage. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Apps reach ACES behavior through `shared` and service facades; only `shared` may import CyberScript directly. |

## Cross-Cutting Layers The Design Must Pass

- Session/API-token authentication: any Mission Control evidence read uses
  `MissionControlReadAPIView`, `IsAuthenticatedSessionOrApiToken`,
  `HasMissionControlActor`, and exact `mission_control:range:read`. Invalid
  bearer tokens fail closed and must not fall through to session auth.
- Product authorization: authorize range/request ownership through
  `cms.services.get_range_by_request_id` or an equivalent product service before
  sidecar lookup. CTF participant reads, if added later, must resolve through
  event-scoped CTF services and `ctf.bridges`; sidecar existence is never
  authorization.
- Request and query shape: route UUIDs, participant refs, record kinds, evidence
  kinds, capture profiles, and limits use DRF serializers or shared validators.
  Do not parse enum-like strings or limits ad hoc in views or workers.
- Sidecar contract validation: shared validators enforce supported
  record-kind/contract-version/profile pairs, participant-runtime profile,
  owner, idempotency key, aware timestamp, payload digest equality, payload
  allowlists, JSON byte caps, single-line refs, diagnostic ref allowlists,
  retention class, and redaction state before a row can exist.
- Secret-handling surface: validators, API projections, docs examples, tests,
  logs, audit rows, events, DLQs, workflow logs, argv, and env literals must
  exclude presigned URLs, upload tokens, Guacamole token URLs, bearer tokens,
  SSH private keys, RDP passwords, CTF flags, raw terminal streams, rendered
  commands, prompt bodies, script bodies, transcript bodies, provider payloads,
  Terraform/SSM/SSH output, cloud credentials, and raw artifact contents.
- Upload and artifact gates: raw uploads stay behind signed upload-token
  verification, object-size equality, full/header inspection, immutable copy,
  CTF attachment validation, and storage adapter rules. ACES evidence may cite
  only the post-validation storage ref, digest, provenance source, capture
  profile, redaction state, and retention class.
- Execution and OS exposure: #1289 should not introduce shell commands,
  subprocess calls, Kubernetes Job env literals, or argv-carried ACES payloads.
  Future execution remains structured and keyed by ids; prompts, commands,
  tokens, provider diagnostics, and transcripts do not travel through process
  argv or shell strings.
- Error envelopes: canonical `/api/v1` errors use `shared.api.errors`; legacy
  Mission Control routes keep existing flat-error compatibility if touched.
  Raw ACES, storage, provider, SSH, SSM, Guacamole, DB, or parser exceptions
  become curated messages and sanitized operator logs only.
- Persistence and retention: evidence/history records are append-only,
  idempotent rows with explicit first-class discriminator fields. They are not
  hidden in `RangeInstance.range_spec`, `Range.provisioned_instances`,
  deleted experiment metadata, `AuditLog` JSON, event payloads, templates, or
  frontend state. Retention uses indexed retention fields and bounded cleanup,
  not hidden API-read side effects.
- Logging and audit: use `safe_log_value`, `safe_log_id`, or
  `safe_log_fingerprint` for log correlation. `AuditLog` records real Shifter
  lifecycle actions and may cite ACES record ids/digests; it is not the ACES
  evidence store and must not carry evidence payloads.
- Config/env binding: new capture profiles, retention classes, pruning cadence,
  batch sizes, feature flags, or storage-profile knobs must be Django settings
  with env-manifest/runtime-inventory coverage. No handler-local `os.environ`
  reads and no local secret files.
- Import boundaries: Mission Control may use `shared`, `cms.services`, and
  `engine.services`; CTF may use `shared`, `cms.services`, and
  `management.services`; CMS may use `shared`, `management.services`, and
  `engine.services`. Do not import app-private models to write/read evidence.

## Extensibility Seam

The seam belongs in the shared participant-runtime sidecar/projection boundary,
parameterized by:

- `record_kind` and contract version for behavior-history versus evidence refs;
- `participant_runtime_profile` and `contract_profile`;
- `evidence_kind` such as script input, prompt input, dispatch receipt,
  transcript ref, artifact ref, terminal-session ref, or manual evidence;
- `capture_profile` for how the ref was captured and redacted;
- `provenance_source` and `provenance_ref` for the owning Shifter boundary;
- `artifact_ref`, `artifact_digest`, `redaction_state`,
  `redaction_policy`, `retention_class`, and optional retention expiry;
- bounded Shifter correlation refs and optional `operation_id`.

The next reasonable variation is another evidence class, another capture
profile, or a future ACES participant-runtime contract version. That should add
one profile/record-kind branch behind shared validators and projections, not
edits across Mission Control views, CTF services, CMS range logic, engine
models, object storage helpers, audit services, and frontend schema files.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md`
- `docs/architecture/aces-participant-runtime-api-sidecars-preflight-1288.md`
- `docs/architecture/aces-operation-sidecar-persistence-preflight-1273.md`
- `docs/architecture/aces-operation-api-projections-preflight-1275.md`
- `docs/architecture/aces-snapshot-retention-redaction-audit-preflight-1277.md`
- `docs/architecture/ai-experiment-execution-boundary.md`
- `docs/architecture/aces-legacy-stability-guardrails-preflight-1239.md`
- `docs/architecture/aces-migration-parity-inventory.yaml` row
  `aces.participant-history-evidence`
- `docs/adr/index.yaml` entries for ADR-024, ADR-025, and ADR-027
- `shifter/shifter_platform/shared/models.py`
- `shifter/shifter_platform/shared/aces/**`
- `shifter/shifter_platform/shared/schemas/**`
- `shifter/shifter_platform/shared/script_context.py`
- `shifter/shifter_platform/cms/services/_uploads.py`, `cms/assets/**`,
  and `shared/uploads/inspection.py`
- `shifter/shifter_platform/shared/cloud/**`
- `shifter/shifter_platform/mission_control/api/**`
- `shifter/shifter_platform/mission_control/consumers.py` and
  Guacamole/terminal access services if access-channel refs are touched
- `shifter/shifter_platform/ctf/services/**` and `ctf/bridges.py` for CTF
  participant/event provenance
- `shifter/shifter_platform/cms/handlers/**`,
  `cms/management/commands/reconcile_range_events.py`, and engine outbox
  drainers if behavior events are sourced from range status
- `shifter/shifter_platform/risk_register/{models,services}.py`
- `shifter/shifter_platform/config/**`, `config/env-manifest.json`, and
  `shifter/installation/runtime_inventory.py` if settings change
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, `.gitleaks.toml`, and `.gc/plan-rules.md`

## Regression Evidence Expectations

- Shared schema tests cover supported evidence/history record kinds, required
  reference fields, digest equality, retention/redaction vocabulary, idempotency
  conflicts, diagnostic ref allowlists, bounded JSON, and unsupported profile
  rejection.
- Negative redaction tests cover every prohibited payload class named by the
  issue: presigned URLs, upload tokens, Guacamole token URLs, SSH private keys,
  RDP passwords, CTF flags, terminal streams, rendered commands, prompt bodies,
  script bodies, transcript bodies, and provider diagnostics.
- Persistence tests prove append/idempotent replay behavior and prove evidence
  records cannot be hidden in range JSON, audit JSON, events, or deleted
  experiment metadata.
- Projection/API tests prove shared response allowlists, Mission Control
  session/API-token access, missing-scope denial, malformed bearer-token
  fail-closed behavior, unknown/not-owned request-id 404 behavior, and stable
  non-ACES responses when no evidence rows exist.
- Upload/artifact tests reuse CMS upload, CTF attachment, shared inspection, and
  storage tests to prove evidence refs point only to validated storage refs and
  digests, not upload tokens or presigned URLs.
- Logging/audit tests use `caplog` or row assertions where practical to prove
  logs and `AuditLog` rows contain ids, refs, digests, status/redaction classes,
  and counts only.
- Import/config tests cover import-linter, layer-imports, ADR guard, and
  env-manifest/runtime-inventory updates when boundaries or settings change.

## Gotchas And Anti-Patterns

- Do not treat Python scripts, Claude prompts, transcripts, terminal streams,
  CTF flags, provider diagnostics, or rendered commands as ACES evidence bodies.
  They are raw material behind Shifter boundaries.
- Do not overload `participant_runtime` rows with unrelated evidence blobs.
  Use explicit evidence/history record kinds and response allowlists.
- Do not create duplicate evidence schemas, status enums, exception
  hierarchies, event buses, websocket topics, artifact stores, upload-token
  formats, audit tables, or API envelopes.
- Do not authorize by finding a sidecar row, frontend field, scenario entry, or
  visible UI element. Authorize through product service gates first.
- Do not store evidence/history records in `RangeInstance.range_spec`,
  `Range.provisioned_instances`, deleted `ExperimentRun.metadata`,
  `AuditLog` JSON, event payloads, templates, or frontend state.
- Do not put presigned URLs, token-bearing refs, prompt/script/transcript
  bodies, terminal streams, flags, private keys, passwords, provider dumps, or
  raw artifacts in sidecars, API responses, logs, audit rows, events, DLQs,
  docs, test fixtures, argv, env literals, or workflow summaries.
- Do not weaken ADR guard, import-linter, secret scanning, API-token exact-scope
  validation, DRF error handling, upload inspection, Guacamole token lifecycle,
  terminal capacity controls, or runtime env inventory for ACES evidence work.

## Non-Goals

- No implementation in this preflight note.
- No new lifecycle controls, command dispatch, artifact fetching, transcript
  capture, terminal recording, websocket behavior, Guacamole behavior, cleanup
  job, UI, or conformance publication.
- No resurrection of the removed `cms.experiments` app.
- No replacement of `ScriptExecutionContext`, upload inspection, object-storage
  facades, `AuditLog`, Mission Control access services, CTF services,
  `RangeEventOutbox`, CMS/engine range status, or shared API/error/logging
  helpers.
- No ACES `participant_runtime` backend capability claim.
- No new Ground Control requirement UID for this requirement-free run.
- No changelog fragment for this docs-only preflight note.

## Validation Expectations

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation touching `shifter/shifter_platform` should also
run the relevant shared ACES schema/persistence/projection tests, Mission
Control API tests, upload/artifact tests, CTF provenance tests, audit/log tests,
import/layer checks, config/runtime-inventory tests, and any stack-native checks
required by `AGENTS.md` and `.gc/plan-rules.md` for the files it touches.

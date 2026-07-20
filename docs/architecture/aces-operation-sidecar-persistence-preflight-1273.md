# ACES Operation Sidecar Persistence Preflight

Issue: GitHub #1273, "14 - ACES migration: implement operation
receipt/status/snapshot persistence sidecar."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, APIs, event handlers, jobs, or UI projections, and it is
not an implementation plan.

## Boundary

This issue is the storage slice for the operation persistence design in
`docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`.
The GitHub issue is the implementation contract for this requirement-free run.

The sidecar stores canonical ACES operation receipt, operation status, runtime
snapshot, and execution-plan reference records or references after they pass the
contract/profile gate that introduced them. It does not move Shifter runtime
authority out of:

- `engine.models.Request` and `engine.models.Range`;
- `cms.models.Request` and `cms.models.RangeInstance`;
- existing range event outbox/reconciler paths;
- existing CTF, Mission Control, and CMS service boundaries.

`request_id` is the Shifter operation correlation key. `range_id` is only a
projection/backfill field because it can be absent before engine dispatch and is
engine-local once present.

## Architecture Decisions

- Use first-class sidecar persistence. Do not store ACES receipts, statuses,
  snapshots, execution-plan refs, or contract metadata inside
  `RangeInstance.range_spec`, `Range.range_config`,
  `Range.provisioned_instances`, `ExperimentRun.metadata`,
  `AuditLog.new_state`, or event payload JSON.
- Give every sidecar record explicit discriminator columns for ACES contract
  kind, contract version, contract profile/backend profile, record kind,
  operation id, Shifter `request_id`, source timestamp, idempotency key, and
  sanitized diagnostic reference metadata. Do not hide these keys inside a JSON
  subfield that cannot be indexed, constrained, or reviewed.
- Default the sidecar owner to the cross-layer ACES/shared boundary. If an
  implementation proves that writes must be transactionally coupled to
  `engine.Range` state, the owner may be the engine app, but every non-engine
  read/write must go through `engine.services`. Do not put direct cross-app
  model imports or shared-model FKs to CMS/engine into the design.
- Validate ACES contract payloads with the real ACES contract/profile tooling
  and the published Shifter backend profile in `shared.aces.manifest`. Shifter
  may add shared-native metadata validators for persistence fields, but not
  duplicate ACES schemas inside CMS, Engine, Mission Control, CTF, or the
  provisioner.
- Make idempotency a database invariant, not just service-layer branching.
  Replayed writes with the same idempotency key/source event must converge to
  the same row. Replays with the same idempotency key but different sanitized
  payload digest/source timestamp must fail closed as a conflict.
- Preserve current status authority. Sidecar status records may be evidence for
  later projection work, but #1273 does not create a new range lifecycle enum,
  event bus, websocket topic, reconciler, or authoritative status path.
- Persist only sanitized diagnostics and references. Raw provider payloads,
  Terraform output, SSM/SSH output, token-bearing URLs, private keys, CTF flags,
  prompt bodies, rendered commands, generated scripts, and raw package bodies
  must be rejected at the sidecar boundary.
- Define retention in the sidecar surface from the beginning: current/latest
  projection state, bounded operational history, and cleanup hooks are distinct
  from archival experiment/evidence records.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Parent ACES operation design | `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md` | Keep its boundary: sidecar records are ACES evidence, not Shifter runtime authority. |
| ACES backend/profile claim | `shared.aces.manifest` | Use `SHIFTER_BACKEND_PROFILE` and `SHIFTER_SUPPORTED_CONTRACT_VERSIONS` as the supported-profile source, not app-local constants. |
| Request correlation | `cms.models.Request.request_id`, `engine.models.Request.request_id`, `engine.Range.request` | Key sidecar correlation by `request_id`; treat `range_id` as optional projection/backfill. |
| Runtime state | `engine.models.Range`, `engine.services`, `provisioner_db.write_provisioned_state`, `provisioner_db.update_range_status` | Do not replace Range/Instance/Subnet state writes or status transitions. |
| CMS projection | `cms.models.RangeInstance`, `cms.handlers.range_events.apply_range_status`, `cms.management.commands.reconcile_range_events` | Sidecar persistence must not bypass or duplicate projection status behavior. |
| Durable events | `RangeEventOutbox`, `drain_range_event_outbox`, `shared.messages.payloads`, `parse_sns_message` | Events stay notification-shaped; sidecar payloads do not ride in event JSON. |
| Existing sidecar validation style | `cms.models.AcesPackageSource`, `shared.schemas.aces_package_source` | Reuse the provenance-only, allowlist-first pattern for bounded refs and diagnostics. |
| Idempotent persistence | `shared.notifications._get_or_create_notification`, `RangeEventOutbox.event_id`, service tests around pause/resume/destroy idempotency | Use unique constraints plus race-safe create/update behavior. |
| Redaction/logging | `shared.log_sanitize`, provisioner `log_redact`, `config._logging_config.ECSFormatter` | Log IDs/status/classes only; use fingerprints/masks for sensitive identifiers. |
| API/auth/errors | `mission_control.api.permissions`, `cms.api.permissions`, `shared.api_tokens.scopes`, `shared.api.errors`, `shared.errors` | Any read API added later must use existing auth, scope, serializer, and safe-envelope patterns. |
| Runtime config | `config/settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py` | New retention/batch/cadence settings need canonical settings and inventory coverage. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Keep ACES access behind `shared` and service seams; only `shared` may import ACES/CyberScript contract packages directly. |

## Cross-Cutting Layers

- Auth surface: #1273 can be storage-only. If it exposes a read path, Mission
  Control uses `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`,
  exact `mission_control:*` scopes, owner checks, and participant lifecycle
  blockers. CMS authoring uses `CMS_READ_PERMISSIONS` /
  `CMS_WRITE_PERMISSIONS`, `HasCMSAuthoringActor`, and
  `validate_cms_authoring_user`. Scope checks do not replace ownership checks.
- Contract validation surface: incoming ACES records must pass the ACES
  contract/profile validator for `operation-receipt-v1`,
  `operation-status-v1`, `runtime-snapshot-v1`, or the execution-plan reference
  profile actually in scope. Unsupported profile/version values fail closed.
- Sidecar metadata validation surface: Shifter-owned metadata validators must
  enforce single-line refs, bounded diagnostic fields, source timestamps,
  known record kinds, supported profiles, idempotency-key shape, digest shape,
  and a strict allowlist for diagnostic keys.
- Persistence surface: use model columns, indexes, unique constraints, and
  migrations for operation identity, idempotency, owner/correlation fields,
  retention timestamps, and record kind. JSON fields may hold already-validated
  canonical contract payloads only when first-class discriminator/index fields
  remain outside the blob.
- Provisioner DB permission surface: if the standalone provisioner writes
  sidecar rows directly, add explicit PostgreSQL grants in migrations for the
  provisioner role. Do not rely on broad default privileges or grant access to
  unrelated ACES/CMS/engine tables.
- Event-delivery surface: the existing durable bus stays notification-shaped.
  Outbox and reconciler payloads may carry IDs/status/source event IDs, but not
  sidecar contract bodies, snapshots, provider state, or diagnostics.
- Secret-handling surface: sidecar validators must reject secrets before
  persistence. Logs, audit rows, API responses, tests, docs examples, DLQs,
  Terraform outputs, Kubernetes env, and workflow logs must never contain raw
  secret-bearing payloads.
- OS/process exposure: ACES payloads, execution-plan bodies, snapshots,
  credentials, diagnostics, and provider payloads must not be passed in process
  argv, shell strings, Kubernetes Job command arrays, workflow command lines, or
  plain env vars. Structured task invocations carry bounded IDs and operation
  names only.
- Config/env surface: retention days, pruning batch size, reconcile cadence, or
  feature exposure must flow through Django settings and the generated
  env-manifest/runtime-inventory path. No handler-local dynamic `os.environ`
  reads for new knobs.
- Error-envelope surface: DRF/browser clients receive shared safe error
  envelopes or curated messages only. Raw ACES parser, provider, DB,
  Terraform, SSH, SSM, or storage exceptions stay in sanitized operator logs.
- Audit surface: lifecycle audit remains `risk_register.services.audit_log`.
  ACES sidecar rows may be audit evidence, but `AuditLog` is not the canonical
  ACES receipt/status/snapshot store.
- Import-boundary surface: CMS, CTF, Mission Control, and the provisioner must
  not import ACES implementation packages or app-private sidecar modules
  directly. Use shared validators/contracts and service facades.

## Extensibility View

The required seam is the operation contract/profile discriminator, parameterized
by record kind and backend profile. The first profile should align with the
published Shifter `provisioning-only` backend claim. Future orchestration,
evaluation, participant-runtime, or provider-specific records should add
supported profile/record-kind branches behind the same sidecar service and
validator boundary, not edit `RangeInstance`, `Range`, event payloads, or UI
templates per variation.

Retention also needs an explicit seam: latest projection state, bounded
operational history, and archival experiment/evidence records are different
classes of data. #1273 may store latest plus bounded history; archival evidence
belongs to a later experiment/evidence design.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/aces-backend-manifest-publication-preflight-1261.md`
- `docs/architecture/aces-registry-validation-launchability-preflight-1253.md`
- `docs/architecture/aces-legacy-stability-guardrails-preflight-1239.md`
- `docs/adr/index.yaml` and `docs/adr/exceptions.yaml`
- `shifter/shifter_platform/shared/aces/**`
- `shifter/shifter_platform/shared/schemas/**`
- `shifter/shifter_platform/shared/models.py`
- `shifter/shifter_platform/engine/models.py`
- `shifter/shifter_platform/engine/services/**`
- `shifter/shifter_platform/cms/models/{provisioning,range}.py`
- `shifter/shifter_platform/cms/handlers/**`
- `shifter/shifter_platform/cms/management/commands/reconcile_range_events.py`
- `shifter/engine/provisioner/{events.py,provisioner_db.py,log_redact.py}`
- `shifter/shifter_platform/mission_control/api/**` if any read API is exposed
- `shifter/shifter_platform/config/settings.py`,
  `config/env-manifest.json`, and `shifter/installation/runtime_inventory.py`
  for new runtime knobs
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `.gc/plan-rules.md`, and `scripts/adr_guard/**`

## Gotchas And Anti-Patterns

- Do not make `range_id` the operation key.
- Do not make a generic `metadata` JSON table with unconstrained record kinds,
  profile strings, or payload contents.
- Do not create app-local ACES validators, exception hierarchies, status enums,
  API envelopes, event types, websocket topics, or audit stores.
- Do not treat `conformance_status == passed`, backend-manifest support, or a
  known profile string as sufficient payload validation.
- Do not store secret-bearing diagnostics and then rely on serializers/logging
  to hide them later. Reject them before persistence.
- Do not let a sidecar write update `engine.Range.status` or
  `RangeInstance.status` outside the existing service/event/reconciler paths.
- Do not weaken ADR guard, import-linter, gitleaks/secret scanning, queue
  recovery, API-token scopes, or runtime env validation for the ACES path.

## Non-Goals

- No implementation in this preflight note.
- No replacement of Shifter runtime authority, event delivery, CTF workflows,
  Mission Control range UX, or CMS range projection.
- No ACES-only public API, UI product, lifecycle enum, event bus, or websocket
  channel.
- No raw ACES package/source persistence, execution-plan bodies, transcripts,
  prompts, generated scripts, provider dumps, or experiment evidence archive.
- No new Ground Control requirement UID for this requirement-free run.

## Validation Expectations

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation under `shifter/shifter_platform` must also run
the stack-native checks required by `AGENTS.md` and `.gc/plan-rules.md` for the
files it touches.

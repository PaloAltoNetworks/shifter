# ACES Operation Status Range Event Projection Preflight

Issue: GitHub #1274, "15 - ACES migration: project operation status through
range event handling."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, adapters, event handlers, workers, APIs, or UI behavior.
This is a requirement-free run; the GitHub issue is the shipping contract.

## Boundary

The controlling decisions remain ADR-024, ADR-025, ADR-027, and the parent
#1234 preflight:

- Current Shifter range lifecycle behavior remains authoritative until the
  ACES path passes the parity and cutover gates.
- `request_id` is the Shifter operation correlation key for ACES-backed range
  work unless a later sidecar contract names a distinct external operation id.
- `engine.Range.status` is the authoritative mutable runtime state for range
  lifecycle.
- `cms.RangeInstance`, CTF range status, and Mission Control status are
  compatibility projections over Shifter state.
- Correctness-critical status propagation stays DB-authoritative through
  `RangeEventOutbox`, `drain_range_event_outbox`, worker retry, and
  `reconcile_range_events`.
- ADR-027 removed the legacy `cms.experiments` runtime path. Any experiment
  projection mentioned by ACES planning must come from a future accepted
  ACES-backed experiment design; #1274 must not recreate the removed app.

## Architecture Decisions

- Add an explicit ACES-operation-status-to-Shifter-status adapter at the ACES
  boundary, not in CMS, CTF, Mission Control, websocket consumers, or templates.
  The adapter output is a Shifter `ResourceStatus` / `engine.Range.Status`
  value plus operation correlation and a sanitized diagnostic reference.
- Treat the adapter as the only place that knows ACES operation-status
  vocabulary. Do not infer by lowercasing strings, matching provider task
  states, or reading UI labels.
- Validate the mapped Shifter status before creating a durable event. A status
  that cannot become `ResourceStatus(...)` must never reach
  `RangeEventOutbox.payload["new_status"]`.
- Preserve the existing durable wire contract. The ACES path should emit the
  normal `range.status.updated` event through `shared.messages.events` and
  `RangeStatusUpdatedPayload`; if an ACES diagnostic reference must be added,
  add it to the shared payload contract and tests, not as handler-local JSON.
- Use `provisioner.events.build_status_event` with
  `provisioner_db.update_range_status(..., outbox_event=...)` or the equivalent
  first-class engine-side transaction so the authoritative `engine.Range.status`
  write and outbox intent commit atomically.
- Keep `cms.handlers.range_events.apply_range_status` as the CMS projection
  seam. Its atomic save plus CTF bridge behavior is part of the recovery
  contract and must not be split into best-effort follow-up work.
- Keep `reconcile_range_events` Shifter-native. It should continue to compare
  stale `RangeInstance` rows with authoritative `engine.Range.status` through
  `engine.services.get_authoritative_range_status`; it must not parse ACES
  payloads or learn an ACES lifecycle enum.
- Stale ACES observations are not transient delivery failures. If the adapter
  can determine that an observation is older than the latest accepted operation
  status or would regress Shifter state outside the existing recovery relation,
  it should not enqueue a status event. Persist or log only sanitized operation
  ids, status names, timestamps/sequences, and diagnostic refs.
- Mission Control websocket fanout remains advisory. It may stream the same
  `range.status` channel payload after the durable event is consumed, but it is
  never the recovery path for ACES projection correctness.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`, ADR-024 | Keep ACES parallel and parity-gated; do not create issue-local lifecycle doctrine. |
| Event durability | ADR-025, `engine.models.RangeEventOutbox`, `engine.management.commands.drain_range_event_outbox` | Projection events are transactional-outbox backed with retry and DLQ behavior. |
| Operation identity | `cms.models.Request.request_id`, `engine.models.Request.request_id`, `engine.Range.request`, `shared.schemas.RangeRef` | Use `request_id` for operation correlation and websocket groups; keep `range_id` as engine projection/backcompat id. |
| Status vocabulary | `shared.enums.ResourceStatus`, `engine.models.Range.Status` | ACES status maps into existing Shifter statuses; no duplicate status enum. |
| Durable payloads | `shared.messages.events`, `shared.messages.payloads.RangeStatusUpdatedPayload`, `shared.messages.envelope.parse_sns_message` | Reuse shared event constants, typed payload shape, and SNS/Pub/Sub envelope parsing. |
| Engine/provisioner write | `provisioner.events.build_status_event`, `provisioner_db.update_range_status`, `provisioner_db.write_provisioned_state` | Commit state changes and outbox rows in one DB transaction. |
| Engine reconciliation read | `engine.services.get_authoritative_range_status` | Other layers must read engine status through the service facade, not direct model imports. |
| CMS projection | `cms.handlers.range_events.process_range_event`, `apply_range_status`, `cms.models.RangeInstance` | Keep request-id-first lookup, user ownership check, idempotency, soft-delete invariant, and bridge firing. |
| CTF bridge | `cms.handlers.ctf_bridge.notify_ctf_range_status`, `cms.signals.range_status_changed`, `ctf.signals.sync_ctf_participant_range_status` | CTF status stays fed by the current CMS signal seam. |
| Mission Control fanout | `mission_control.handlers`, `shared.channels.payloads.RangeStatusChannelEvent`, `mission_control.status_consumers.RangeStatusConsumer` | Websocket consumers receive the existing channel payload and hydrate from CMS on connect. |
| Worker acknowledgement | `shared.management.commands.run_worker`, `config._cloud.QUEUE_CONFIG`, cloud queue adapters | Preserve ack-after-handler behavior; transient DB/broker failures propagate. |
| Auth/API/errors | `shared.api.errors`, `shared.errors`, `shared.exceptions.CMSError`, `mission_control.api.permissions`, `cms.api.permissions` | Any API projection keeps existing session/API-token gates, scopes, and safe error envelopes. |
| Logging/audit | `shared.log_sanitize`, provisioner `log_redact`, `risk_register.services.audit_log` | Logs and audit rows carry sanitized ids, statuses, counts, and refs only. |
| Runtime config | `config/settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, `config._cloud`, `config._channels` | Do not add handler-local env reads; any new runtime knob needs manifest/inventory/tests. |
| Enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py`, `.gc/plan-rules.md` | Preserve layer boundaries and architecture checks. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: background range events are internal, but any read/API surface
  created around ACES status still uses `IsAuthenticatedSessionOrApiToken`,
  `HasMissionControlActor`, exact API-token scopes, CMS authoring permissions,
  and service-layer owner checks. UI hiding is not authorization.
- ACES contract shape: incoming ACES operation status must already have passed
  the relevant ACES contract/profile/conformance gate. The Shifter adapter may
  map validated ACES values, but it must not become a duplicate ACES parser or
  schema.
- Shifter status shape: mapped statuses must validate as
  `shared.enums.ResourceStatus` and fit `engine.Range.Status.choices` before
  event creation. Existing CMS and Mission Control validation stays as a second
  boundary for untrusted durable events.
- Persistence shape: `engine.Range` remains the runtime status authority;
  `RangeInstance` remains a projection; ACES operation sidecars, when present,
  store ACES contract state keyed by operation/profile/version. Do not hide
  lifecycle state in JSON fields such as `range_spec`, `range_config`,
  `provisioned_instances`, `AuditLog.new_state`, or outbox payload blobs.
- Event-delivery shape: correctness-critical status projection passes through
  `RangeEventOutbox`, the drainer, worker retry/DLQ, and
  `reconcile_range_events`. Websocket delivery and channel-layer Redis posture
  are advisory UI freshness only.
- Secret-handling surface: event payloads, DLQs, logs, audit rows, API
  responses, test fixtures, workflow summaries, argv, and env literals must
  exclude snapshots, credentials, bearer tokens, private keys, presigned URLs,
  prompt bodies, command strings, generated scripts, execution plans, provider
  dumps, Terraform output, terminal streams, and CTF flags.
- OS/process exposure: keep provisioner/task dispatch keyed by structured
  operation names and `request_id`. Do not pass ACES payloads, snapshots,
  status JSON, diagnostic bodies, credentials, or plans through shell strings,
  process argv, Kubernetes Job env literals, workflow logs, or local subprocess
  command lines.
- Env-binding/config validators: #1274 should not need new env knobs. If a
  future status-retention or adapter-selector knob is unavoidable, add it to
  settings plus `config/env-manifest.json`, runtime inventory/renderers, and
  tests.
- Error-envelope surface: user-facing API or template responses use
  `shared.api.errors`, `classify_user_message`, and `safe_user_message`. Raw
  ACES parser, provider, Terraform, SSM, SSH, Docker, storage, or broker
  exceptions stay in sanitized operator diagnostics.
- Observability surface: log operation/request ids, event ids, status names,
  diagnostic refs, counts, durations, and fingerprints. Do not log raw event
  payloads, ACES bodies, provider dictionaries, queue bodies, or exception text
  that could contain secrets.
- Import-boundary surface: ACES implementation packages should enter the
  platform through `shared` and existing CMS/engine service seams. CMS, CTF,
  Mission Control, and workers must not import ACES internals directly to make
  projection work.

## Extensibility Seam

The seam is a profile/versioned status adapter:

- input: ACES operation status contract/profile/version, operation id
  (`request_id` for the Shifter-backed operation), observed timestamp or
  monotonic sequence, and sanitized diagnostic reference;
- output: Shifter `ResourceStatus`, idempotency/staleness classification, and
  optional bounded user-safe diagnostic reference.

The next reasonable variation is another ACES status contract or backend
profile. That should add one mapping branch/table behind the adapter and one
test vector set. It should not require re-editing CMS handlers, CTF receivers,
Mission Control consumers, event constants, or the reconciler for every new
ACES status vocabulary.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/aces-legacy-stability-guardrails-preflight-1239.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `docs/adr/index.yaml` entries for ADR-024, ADR-025, and ADR-027
- `shifter/shifter_platform/shared/messages/**`
- `shifter/shifter_platform/shared/channels/**`
- `shifter/shifter_platform/shared/enums.py`
- `shifter/shifter_platform/engine/models.py`
- `shifter/shifter_platform/engine/services/**`
- `shifter/shifter_platform/engine/handlers.py`
- `shifter/shifter_platform/engine/management/commands/drain_range_event_outbox.py`
- `shifter/engine/provisioner/events.py`
- `shifter/engine/provisioner/provisioner_db.py`
- `shifter/shifter_platform/cms/models/range.py`
- `shifter/shifter_platform/cms/handlers/range_events.py`
- `shifter/shifter_platform/cms/handlers/ctf_bridge.py`
- `shifter/shifter_platform/cms/management/commands/reconcile_range_events.py`
- `shifter/shifter_platform/ctf/signals.py`
- `shifter/shifter_platform/mission_control/handlers.py`
- `shifter/shifter_platform/mission_control/status_consumers.py`
- `shifter/shifter_platform/config/_cloud.py`
- `shifter/shifter_platform/config/_channels.py`
- `shifter/shifter_platform/config/env-manifest.json`
- `shifter/installation/runtime_inventory.py`
- `platform/terraform/**` and `platform/k8s/**` only if messaging, worker, or
  runtime config contracts change
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, and `.gc/plan-rules.md`

## Regression Evidence Expectations

- Adapter tests cover every accepted ACES operation-status value for the active
  profile, plus unknown, missing, malformed, stale, duplicate, and regression
  observations.
- Outbox tests prove ACES-derived status changes enqueue the normal
  `range.status.updated` payload atomically with the `engine.Range.status`
  write and never include snapshots, provider dumps, secrets, or execution
  plans.
- CMS/reconciler tests prove stale `RangeInstance` rows converge from
  authoritative `engine.Range.status` through `apply_range_status` and CTF
  bridge behavior, including invalid event payload handling.
- Mission Control tests prove websocket/status UX for non-ACES ranges is
  unchanged and remains advisory over the hydrated CMS state.
- Non-ACES range lifecycle and event-delivery tests remain in scope when shared
  payloads, handlers, outbox, worker routing, or reconcilers are touched.

## Gotchas And Anti-Patterns

- Do not create an ACES-only event bus, websocket topic, lifecycle enum,
  reconciler, worker, exception hierarchy, API envelope, or audit table.
- Do not map ACES status inside CMS handlers, CTF receivers, Mission Control
  consumers, templates, or JavaScript.
- Do not let invalid ACES status strings flow into `engine.Range.status`; model
  choices are not a replacement for adapter validation.
- Do not equate ACES operation status with provider task state, CTF participant
  `range_status`, UI labels, experiment run status, or Terraform state.
- Do not put ACES snapshots, execution plans, provider responses, cloud
  diagnostics, credentials, prompts, scripts, terminal output, flags, or package
  bodies in `RangeEventOutbox.payload`, DLQs, logs, audit JSON, or API
  responses.
- Do not use `error_message` for raw ACES/provider exception text. Use a
  bounded user-safe phrase or a diagnostic reference.
- Do not make `range_id` the ACES operation id. It is engine-local and may be
  absent early in request-id keyed flows.
- Do not bypass `engine.services`, `cms.services`, `parse_sns_message`,
  `ResourceStatus` validation, `apply_range_status`, or CTF bridge signals to
  make ACES status appear in the UI quickly.
- Do not weaken ADR guard, import-linter, worker retry/DLQ behavior, channel
  layer fail-closed posture, API-token scopes, or secret-scanning policy for
  the ACES path.

## Non-Goals

- No implementation of ACES status models, adapters, sidecars, migrations,
  event handlers, APIs, UI, workers, or cleanup jobs in this preflight.
- No replacement of `engine.Range`, `cms.RangeInstance`, `ResourceStatus`,
  `RangeEventOutbox`, `drain_range_event_outbox`, `reconcile_range_events`,
  Mission Control range UX, or CTF range workflows.
- No resurrection of removed legacy experiments.
- No new ACES orchestrator/evaluator/participant-runtime claim.
- No new Ground Control requirement UID for this requirement-free run.
- No changelog fragment for this docs-only preflight note.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation touching `shifter/shifter_platform` should also
run the subsystem tests for engine outbox/drainer, CMS range events and
reconciliation, Mission Control status consumers/API, CTF range status sync,
and any import/config checks for changed boundaries.

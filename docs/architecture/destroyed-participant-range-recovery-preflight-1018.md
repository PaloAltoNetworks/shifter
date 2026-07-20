# Destroyed Participant Range Recovery Preflight (#1018)

> **Superseded:** the disposition/forensics-retention concept described below
> was dropped by the issue owner. The revised plan replaces it with spare-pool
> provisioning (an event-owned pool of prewarmed ranges, each held by a
> managed system user until consumed) instead of a retention/disposition
> choice on the old range. See the
> [revised plan](https://github.com/Brad-Edwards/shifter/issues/1018#issuecomment-4884742322).
> The rest of this document is kept for historical context only and does not
> describe the shipped behavior.

Status: pre-implementation guidance

Date: 2026-07-05

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1018>

This is a requirement-free run. The GitHub issue title, body, and acceptance
criteria are the contract. This note is intentionally not an implementation
plan.

## Scope Boundary

Issue #1018 adds a supported operator flow for recovering one CTF participant's
live-fire range when the existing range is beyond in-place repair. The recovery
operation may rebuild a same-event/same-scenario range or reassign a prewarmed
spare range, while preserving the participant's identity, event enrollment,
submissions, awards, team/bracket membership, and audit trail.

This belongs to Shifter's range lifecycle and CTF operator surfaces, not to
scenario content. The implementation must not require manual edits to
`cms.RangeInstance`, `engine.Range`, or `CTFParticipant` rows.

## Architecture Decisions And Guardrails

- Treat recovery as a CTF participant range lifecycle operation that crosses
  CTF, CMS, Engine, Mission Control/Guacamole, audit, and range-event
  projection boundaries. Do not solve it only in a template or admin button.
- Preserve CTF identity. The participant row is the stable scoring and access
  identity. Recovery may change `CTFParticipant.range_instance_id` and
  `range_status`; it must not create a replacement participant, user, team,
  bracket, submission, award, or invite-history row.
- Keep score authority unchanged. `CTFSubmission`, `CTFAward`, and the
  materialized score fields on `CTFParticipant`/`CTFTeam` remain authoritative
  and rebuildable through `ctf.services.scoring`. Range replacement must not
  recompute, migrate, delete, or duplicate score rows.
- Route new CTF ranges through `ctf.bridges.cms_create_range` and
  `cms.services.create_range` so scenario hydration, agent validation,
  `RangeSource.CTF`, request-id correlation, CMS persistence, Engine dispatch,
  failure status, and audit behavior remain centralized.
- Route spare assignment through a service boundary that validates the spare is
  same event/scenario/range config compatible, CTF-sourced, not tied to an
  eligible scoring participant, and not currently reachable by the target
  participant until the old range is blocked.
- Make old-range disposition explicit and server-derived. The service should
  accept a bounded disposition such as `retain_forensics`, `quarantine`, or
  `destroy`, plus a replacement strategy such as `reassign_spare` or `rebuild`.
  These are operator workflow facts, not `ResourceStatus` replacements.
- The old range must leave every participant-accessible active path before or
  atomically with the participant pointer switch. At minimum this means the old
  `engine.Range` and `cms.RangeInstance` are no longer `ready`/active for the
  participant, and terminal/Guacamole helpers cannot resolve old instance UUIDs
  for that user.
- If a range is retained for forensics, retention must not mean "left ready
  under the participant's normal owner." Use an explicit quarantined/forensic
  ownership or access posture, while keeping the normal participant access path
  closed.
- Idempotency needs a durable key for retries after partial failure. The key
  should include participant id, event id, old `RangeInstance.pk`, replacement
  strategy, and old-range disposition. If existing rows and `CTFScheduledTask`
  cannot represent the recovery phase/failure reason clearly, add one small
  first-class recovery record rather than hiding state in untyped JSON.
- Use existing async infrastructure when work is long-running. A spare
  reassignment may complete synchronously; a rebuild or teardown that waits on
  provisioning must use existing CMS/Engine async lifecycle and, if CTF needs a
  background controller, the existing scheduler/task pattern. Do not start
  gunicorn-local threads or block request workers while provisioning sleeps.
- Expose status and failure reasons as bounded operator diagnostics. Admin and
  Mission Control surfaces may show recovery phase, strategy, disposition,
  replacement range id/request id, and authored failure categories. They must
  not show raw provider exceptions or secret-bearing diagnostics.
- Audit through the existing `AuditLog` and `risk_register.services` path.
  Record the actor, participant id, event id, old range instance, replacement
  range instance/request id when known, strategy, disposition, previous status,
  and resulting status. Do not add a parallel audit table.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| CTF participant identity | `ctf.models.CTFParticipant`, `ParticipantStatus`, `eligible_participant_q()` | Preserve the existing participant row and eligibility semantics. Do not create fake spare participants that can leak into scoring/access. |
| CTF range assignment | `ctf.services.range.provision_participant_range`, `destroy_participant_range`, `_get_participant_with_range` | Extend this service family and preserve row locks, already-assigned handling, and CTF exception mapping. |
| CTF/CMS boundary | `ctf.bridges.cms_create_range`, `cms_destroy_range`, `cms_get_range_status`, `cms_find_range_instance_id` | Add bridge helpers only if needed; do not import CMS models or Engine internals from views. |
| CMS range persistence | `cms.models.RangeInstance`, `Request`, `RangeSource.CTF`, `SoftDeleteManager`, `apply_terminal_soft_delete` | Keep `RangeInstance.pk`, legacy `range_id`, and `request_id` distinct. Use `all_objects` only for terminal/history lookups that intentionally include soft-deleted rows. |
| CMS lifecycle services | `cms.services.create_range`, `_range_destroy`, `_range_lifecycle`, `_range_queries` | Reuse validation, ownership masking, request-id dispatch, status transition/revert-on-rejection, and audit behavior. |
| Engine authority | `engine.models.Range`, `engine.services.create_range`, `destroy_range_by_request`, `Range.resolve_active_for_instance` | Engine remains authority for runtime status and participant terminal access. Do not update Engine rows from CTF views. |
| Status vocabulary | `shared.enums.ResourceStatus` and `engine.Range.Status` | Do not invent duplicate lifecycle statuses for range readiness. Model recovery strategy/disposition separately. |
| Status projection | `cms.handlers.range_events.apply_range_status`, `cms.handlers.ctf_bridge`, `ctf.signals.sync_ctf_participant_range_status`, `reconcile_range_events` | Let CMS/Engine events converge range status, or call the same idempotent helper. Do not set only one side. |
| Scoreboard state | `ctf.services.scoring`, `CTFSubmission`, `CTFAward`, materialized score fields | Validate preservation by asserting rows and cached score survive replacement. |
| Operator auth/API | `ctf.views._access`, `ctf.views.api.ranges`, `MissionControlAPIView`, `IsAuthenticatedSessionOrApiToken`, API-token scopes | Reuse organizer/session/API-token gates and event ownership checks. UI hiding is not authorization. |
| Guacamole/terminal access | `mission_control.api.guacamole`, `mission_control.views._guacamole`, `engine.services._terminal` | Stale old instance UUIDs must fail because the old range is not active/ready for that user. |
| Error envelopes | `ctf.views._access._json_error`, `shared.errors.classify_user_message`, `shared.api.errors.api_error_response` | Return authored messages only; never serialize `str(exc)` from CMS, Engine, provider, or secrets code. |
| Logging hygiene | `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint`, module loggers | Log IDs, statuses, strategy, disposition, and counts. Do not log tokens, flags, credentials, provider payloads, or env dumps. |
| Audit trail | `risk_register.models.AuditLog`, `risk_register.services.audit_log`, CTF audit helper pattern | Use existing audit rows and JSON fields with sanitized identifiers. |
| Tests | `tests/ctf/test_services/test_range.py`, `test_mid_event_operations.py`, `test_api_view_flows.py`, `test_api_error_paths.py`, `tests/integration/engine/test_range_lifecycle.py`, CMS range service/handler tests | Add DB-backed service and integration tests at existing seams; avoid broad UI-only smoke coverage. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: CTF operator endpoints must keep `@login_required`,
  `@ctf_organizer_required`, and event-owner checks. Mission Control DRF
  surfaces must keep session/API-token auth, `HasMissionControlActor`,
  exact range read/write scopes, and participant lifecycle blockers. A
  participant must not be able to trigger their own recovery.
- Domain authorization surface: the target participant must belong to the
  organizer's event. Replacement or spare ranges must be same-event,
  same-scenario compatible, CTF-sourced, and not owned by another active
  participant. Cross-event and cross-organizer swaps are forbidden.
- Request validation surface: validate participant ids through route converters
  or serializers; validate strategy/disposition as fixed choices; validate
  spare ids as positive integers/UUIDs at the HTTP boundary; then validate
  state again in the service under a row lock. Do not accept scenario ids,
  user ids, range source, score fields, or arbitrary status strings from the
  request body.
- CMS/Engine validation surface: reuse `cms.services.create_range` for rebuilds
  so scenario templates, `agents_by_os`, `ngfw_enabled`, request specs,
  persisted-spec wrappers, and Engine dispatch all pass their existing checks.
  Reassignments must validate `RangeInstance.range_spec` through the persisted
  schema envelope instead of ad hoc JSON key walks.
- Secret-handling surface: recovery must not print, return, store in audit JSON,
  or log invite tokens, raw registration URLs, CSRF tokens, API tokens,
  Guacamole signed URLs, SSH private keys, RDP passwords, CTF flags, presigned
  URLs, provider responses, task env, or local environment dumps. If an invite
  resend is needed, call `ctf.services.participant.resend_invite`.
- Config/env surface: this issue should not need new env variables, shell
  commands, Terraform variables, Kubernetes env literals, or runtime inventory
  keys. If a future spare-pool policy becomes configurable, add it through typed
  settings and the existing env-manifest/runtime-inventory path.
- OS/process exposure: do not pass recovery payloads, user emails, provider
  diagnostics, secrets, or JSON blobs through process argv. Existing provisioner
  task argv should remain bounded to operation and request id.
- Error-envelope surface: CTF legacy JSON keeps controlled `{"error": "..."}`
  messages through `_json_error`; Mission Control canonical API responses use
  `shared.api.errors`. Failure reasons displayed to operators must be authored
  categories, with detailed exception text only in sanitized server logs.
- Event/reconciliation surface: status updates that affect CTF/Mission Control
  visibility must either flow through `apply_range_status` and the
  `range_status_changed` bridge or be reconciled by the existing DB-authoritative
  recovery path. A successful service return is not enough if CMS, CTF, and
  Engine projections can drift.
- Terminal/Guacamole surface: `Range.resolve_active_for_instance`,
  `get_rdp_connection_info`, `get_ssh_connection_info`, and Guacamole bootstrap
  status must reject the old range after recovery. A stale old instance UUID
  cannot keep resolving just because the engine row still belongs to the user.
- Audit/observability surface: record actor, event, participant, old range,
  replacement range, request id, strategy, disposition, phase, and outcome as
  low-cardinality structured context. Do not use audit JSON as a workflow state
  store.
- Import-boundary surface: respect `.importlinter` and ADR guardrails. CTF
  crosses to CMS through bridges/services; CMS/Engine communicate through shared
  contracts and events; Mission Control must not reach into CTF internals for
  lifecycle mutation.

## Extensibility Seam

The durable seam is a service-owned recovery intent:

- identity: `event_id`, `participant_id`, `old_range_instance_id`;
- strategy: `reassign_spare` or `rebuild`;
- old-range disposition: `retain_forensics`, `quarantine`, or `destroy`;
- replacement: optional spare `RangeInstance.pk` or created replacement
  `request_id`/`RangeInstance.pk`;
- result projection: phase, status, failure category, and retry-safe operation
  key.

Keeping strategy and disposition explicit lets the next variation add a spare
pool, provider-specific quarantine, delayed destruction, or operator retry
without re-editing scoring, participant identity, or status enums. If the
implementation adds persistence for the intent, use a first-class model with
clear ownership, unique idempotency key, retention, and audit relation rather
than opaque metadata in `CTFParticipant.range_status`, `RangeInstance.range_spec`,
or `AuditLog.new_state`.

## Whole-Repo Scope

Implementation must evaluate changes against:

- `shifter/shifter_platform/ctf/services/range/**`
- `shifter/shifter_platform/ctf/bridges.py`
- `shifter/shifter_platform/ctf/views/api/ranges.py`
- `shifter/shifter_platform/ctf/views/admin_people.py`
- `shifter/shifter_platform/templates/ctf/admin/range_list.html`
- `shifter/shifter_platform/templates/ctf/admin/participant_detail.html`
- `shifter/shifter_platform/static/js/ctf-ranges.js`
- `shifter/shifter_platform/cms/models/range.py`
- `shifter/shifter_platform/cms/services/_range_create.py`
- `shifter/shifter_platform/cms/services/_range_destroy.py`
- `shifter/shifter_platform/cms/services/_range_lifecycle.py`
- `shifter/shifter_platform/cms/services/_range_queries.py`
- `shifter/shifter_platform/cms/handlers/range_events.py`
- `shifter/shifter_platform/ctf/signals.py`
- `shifter/shifter_platform/engine/models.py`
- `shifter/shifter_platform/engine/services/_range.py`
- `shifter/shifter_platform/engine/services/_terminal.py`
- `shifter/shifter_platform/mission_control/api/ranges.py`
- `shifter/shifter_platform/mission_control/api/guacamole.py`
- `shifter/shifter_platform/mission_control/views/_guacamole.py`
- `shifter/shifter_platform/risk_register/models.py`
- `shifter/shifter_platform/risk_register/services.py`
- `shifter/shifter_platform/shared/enums.py`
- `shifter/shifter_platform/shared/errors.py`
- `shifter/shifter_platform/shared/api/errors.py`
- `shifter/shifter_platform/shared/schemas/persistence.py`
- targeted tests under `shifter/shifter_platform/tests/ctf/`,
  `tests/cms/`, `tests/engine/`, and `tests/integration/`
- `.importlinter`, `scripts/check_layer_imports/**`, and
  `scripts/adr_guard/**` if imports or architecture rules change

Usually out of scope:

- changing challenge scoring, flag validation, awards, team/bracket semantics,
  invite token shape, CTF event lifecycle, or participant registration;
- redesigning scenario templates or moving recovery into scenario content;
- replacing CMS/Engine request-id correlation, range event delivery, Guacamole
  bootstrap, or terminal access architecture;
- adding a new workflow engine, queue system, global exception hierarchy,
  duplicate range status enum, or parallel audit log;
- changing Terraform/Kubernetes/runtime config unless the implementation truly
  adds a deployed background worker, retention job, or spare-pool setting.

## Gotchas And Anti-Patterns

- Do not identify a CTF participant by email, user id, team, or scoreboard row
  when the operation is participant-scoped. Use `CTFParticipant.pk`.
- Do not move submissions or awards to a new participant row. That breaks audit,
  ranking, and historical solve identity.
- Do not represent spare ranges as eligible fake participants unless they are
  provably excluded from access control, scoreboards, event capacity, invites,
  and participant counts. A dedicated spare-pool concept is safer than polluting
  participant identity.
- Do not set `CTFParticipant.range_instance_id` to the new range while the old
  `engine.Range` remains `ready` and participant-owned.
- Do not mark a forensics-retained range as `ready` just because EC2 resources
  still exist. "Retained" is not "participant accessible."
- Do not bypass `cms.services.create_range` by cloning `RangeInstance` JSON or
  writing Engine rows directly for rebuilds.
- Do not use `RangeInstance.range_id` when callers hold `RangeInstance.pk`.
  Request-based ranges may have no legacy engine id until backfill.
- Do not key idempotency only on "participant currently has no range." Partial
  failure after creating or assigning a replacement can make that predicate lie.
- Do not overload `CTFParticipant.range_status` with workflow states like
  `queued_recovery`, `quarantined`, or raw failure strings. Keep range lifecycle
  status and recovery operation status distinct.
- Do not expose raw `CTFScheduledTask.error_message`, provider exception text,
  Terraform output, Guacamole signed URLs, secret references, or traceback text
  in admin/Mission Control surfaces.
- Do not broaden participant lifecycle permissions so participant-only users can
  destroy, reassign, or rebuild ranges.
- Do not let a reconciler or retry helper "repair" by manually updating unrelated
  CMS, Engine, and CTF rows outside the same service helpers the normal path uses.

## Non-Goals

- No implementation is performed by this preflight.
- No formal Ground Control requirement or traceability update is attached.
- No new scoring model, event model, scenario DSL field, CTF public API posture,
  or participant registration flow is required.
- No migration away from `CTFParticipant.range_instance_id` as the participant's
  CMS range pointer is required.
- No provider-specific forensic acquisition, disk snapshotting, malware
  collection, or evidence-chain tooling is required by #1018. The flow only
  needs to make the old range disposition explicit and block participant access.
- No weakening of ADR guard, import boundaries, API-token scope checks, CSRF,
  secret scanning, safe error envelopes, or logging sanitization.

## Validation Expectations

Architecture or `shifter/shifter_platform` changes on this path must pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups should also run focused DB-backed tests for:

- a simulated destroyed-range replacement that preserves participant id,
  submissions, awards, cached score, team, bracket, and registration state;
- old-range access denial through terminal/Guacamole resolution after
  replacement;
- retry after each partial phase: old range marked inactive, replacement
  created, participant pointer switched, audit written, and teardown dispatched;
- organizer authorization, event ownership, validation, and controlled API error
  envelopes;
- status projection from CMS/Engine to `CTFParticipant.range_status` and admin
  range-list failure/status displays.

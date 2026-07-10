# Hydrator Failure Status Preflight (#389)

Status: pre-implementation guidance

Date: 2026-06-28

Issue: GitHub #389, "Bug: Requests not marked as failed when hydrator throws
error"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is not an implementation plan.

## Scope Boundary

The bug is a CMS-to-engine orchestration failure: CMS has accepted user intent
and may already have materialized CMS-owned rows, but the hydrated
`RequestSpec` is not successfully accepted by engine and no provisioner event
will arrive to repair CMS state.

Keep these concepts separate:

1. `cms.models.Request` is the durable request/correlation container.
2. `RangeInstance`, `Instance`, and `App` are the user-visible CMS lifecycle
   records that carry `ResourceStatus`.
3. `engine.models.Request` and engine materialization are separate durable
   orchestration records.
4. Provisioner and engine events are replayable notifications, not the
   correctness boundary for a failure that happens before engine/provisioner
   work exists.

No new public workflow, job, request-status, or error taxonomy is needed for
this narrow bug. A broader request-operation model remains governed by
`docs/design/range-ngfw-provisioning-transactionality-preflight-557.md`.

## Architecture Decisions

- Reuse the existing public lifecycle vocabulary from
  `shared.enums.ResourceStatus`. Failed CMS-owned materialized rows should use
  `ResourceStatus.FAILED`; do not add a CMS-only "error" status or a parallel
  request-state enum for this issue.
- Preserve `request_id` as the only cross-boundary correlation key. Do not
  introduce a second operation id or infer ownership from engine ids that may
  not exist on this path.
- Keep `cms.models.Request` as a request container. It has no status column by
  design; if implementation needs durable request-level failure metadata beyond
  child statuses, that is a separate schema/design change.
- Treat `RangeInstance`, `Instance`, and `App` as the user-visible status
  carriers. When a CMS row was created before hydration or engine dispatch
  fails, transition every CMS-owned child row for that request to `failed` in
  the same compensation path.
- Preserve the existing terminal soft-delete invariant. `FAILED` auto-sets
  `deleted_at` through `cms.models.lifecycle.apply_terminal_soft_delete`; use
  `all_objects` only in tests/admin/repair paths that explicitly need to see
  terminal rows.
- Keep service boundaries intact. Mission Control and DRF views call
  `cms.services`; CMS calls engine through `engine.services`; neither layer
  should import engine private modules or provider/provisioner code for this
  bug.
- Log the full server-side exception with sanitized identifiers, but surface
  only authored/sanitized user messages through the existing legacy and DRF
  error-envelope helpers.
- Do not fabricate engine/provisioner events to drive this repair. This failure
  path occurs before those components own the work.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #389 |
| --- | --- | --- |
| Status vocabulary | `shared.enums.ResourceStatus`, `TERMINAL_STATUSES` | Use `FAILED`; do not add duplicate CMS request states. |
| Terminal behavior | `cms.models.lifecycle.apply_terminal_soft_delete`, `SoftDeleteManager`, `all_objects` | Let failed child rows soft-delete; use `all_objects` only where terminal rows are intentionally inspected. |
| CMS request/entity model | `cms.models.Request`, `RangeInstance`, `Instance`, `App` | Keep request as correlation container; child rows carry visible lifecycle state. |
| Hydration schemas | `cms.scenarios.hydrator`, `shared.schemas.RequestSpec`, `RangeSpec`, `InstanceSpec`, `NGFWAppSpec` | Reuse Pydantic schemas and hydrator validation; no duplicate DTOs or validators. |
| Persisted spec shape | `shared.schemas.persistence.wrap_persisted_spec` / `unwrap_persisted_spec` | Store specs through the existing wrapper where specs are persisted. |
| CMS services | `cms.services._range_create`, `cms.services._ngfws`, `cms.services._common` | Put compensation in the service workflow; do not push it into views or model save hooks. |
| Engine services | `engine.services.create_range`, `engine.services.create_ngfw`, engine dispatch failure handling | Mirror the existing persist-then-dispatch-then-mark-failed pattern; do not hold DB locks across dispatch. |
| HTTP views | `mission_control.views._ranges`, `_ngfw`, `mission_control.api.ranges`, `mission_control.api.resources` | Preserve legacy flat errors and canonical DRF errors through existing view/base helpers. |
| Auth and actor policy | `login_required`, `block_ctf_participant_only`, `IsAuthenticatedSessionOrApiToken`, `require_scope`, `HasMissionControlActor` | Do not change who may launch ranges/NGFWs while fixing failure reporting. |
| Error leakage controls | `shared.errors.classify_user_message`, `shared.api.errors.api_error_response`, `MissionControlAPIView.bad_request` | Never return raw `str(exc)` from hydrator, engine, cloud, database, or PAN-OS paths. |
| Logging hygiene | `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint`, module loggers | Log request id, user id, app/instance ids, scenario id, and exception class/message with sanitizer where user-controlled. |
| Audit | `risk_register.services` and `AuditLog.Action.PROVISION` / `FAILED` | Do not write successful provision audit rows when hydration/dispatch failed. If adding failure audit, use existing actions and sanitized state. |
| Secret-bearing NGFW data | `cms.credential_encryption.EncryptedInstanceDataField`, credential resolvers, `NGFWRegistration` | Hydrated `authcode`, `scm_pin_value`, and `otp_value` remain encrypted at rest and must not be logged, audited, returned, or put in argv. |

## Cross-Cutting Layers

Security layers the intended design must pass:

- Browser auth surface: legacy Mission Control launch/create endpoints remain
  `@login_required`; range lifecycle launch keeps
  `block_ctf_participant_only("launch")`. The compensation path runs only after
  those gates admit the caller.
- DRF auth and scope surface: canonical `/api/v1/mission-control/...` callers
  use `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, and the
  relevant Mission Control range/NGFW scope permission. Token scopes admit an
  endpoint; CMS service ownership checks still own domain authorization.
- Ownership surface: CMS service lookups must keep filtering credentials,
  NGFWs, and ranges by the acting user. Failed compensation must update only
  rows created for the current request/user, not arbitrary `request_id` input.
- Payload validation surface: JSON bodies pass the existing view/DRF serializer
  checks; CMS service arguments pass `_common` user/id/string validators and the
  existing scenario, agent, credential, and registration-method validators;
  hydrated specs pass `RequestSpec`, `RangeSpec`, `InstanceSpec`, and
  `NGFWAppSpec` validation.
- Persistence surface: CMS status updates use `ResourceStatus.FAILED.value`
  and model `save(update_fields=...)` so terminal soft-delete persists. Engine
  materialization, when it exists, uses existing engine service failure marking.
- Secret-handling surface: NGFW hydration may carry `authcode`,
  `scm_pin_value`, and `otp_value`. Those values may be persisted only through
  `EncryptedInstanceDataField` and wrapped engine specs; they must not appear in
  logs, audit JSON, WebSocket messages, API responses, GitHub text, shell
  command lines, process argv, environment variables, or test assertion output.
- Error-envelope surface: legacy HTML/JSON views return flat authored
  `{error: ...}` bodies; DRF views use `MissionControlAPIView.bad_request` /
  `shared.api.errors.api_error_response`. Both paths must use fixed or
  classified messages, not raw exception text.
- Event surface: existing engine/CMS/Mission Control handlers remain consumers
  of provider/provisioner events. This issue must not depend on event delivery
  for the pre-engine failure case and must not publish fake success/failure
  events to drive local state.
- Runtime/OS exposure surface: no new subprocess, shell, cloud task, or
  environment binding should be needed. If touched incidentally, existing rules
  still apply: request ids only in argv, no hydrated specs or secrets in argv,
  and new sensitive env names must go through `shared.cloud.sensitive_env`.
- Import/config validator surface: Python changes in `shifter/shifter_platform`
  must satisfy ruff and import-linter; architecture work must satisfy ADR guard.
  Terraform, Kubernetes, actionlint, and env-manifest checks apply only if those
  surfaces are touched.

Maintainability incumbents the implementation must build on:

- `cms.services._range_create.create_range` and `_ngfws.create_ngfw` for the
  orchestration path and compensation ownership.
- `cms.scenarios.hydrator` for scenario and NGFW hydration errors.
- `engine.services.create_range` and `create_ngfw` for engine acceptance and
  dispatch semantics.
- `cms.services._range_queries.get_active_range` and `get_range_by_request_id`
  for the projection/visibility contract after terminal statuses.
- Existing service tests in `tests/cms/test_services_range.py` and
  `tests/cms/test_services_ngfws.py`, plus HTTP boundary tests in
  `tests/mission_control`.

Extensibility seam:

The seam is a request-scoped failure-compensation helper owned by CMS services:

- key: `request_id`;
- resource kind: range or NGFW;
- child rows to update: `RangeInstance` for range, `Instance` and `App` for
  NGFW;
- target status: a `ResourceStatus`, initially `FAILED`;
- failure reason category: optional sanitized/log-only metadata, not a new
  user-visible enum;
- audit policy: no success audit on failure, optional sanitized failure audit
  through the existing audit facade if product requirements demand it later.

That shape lets a future reconciliation worker or request-operation table call
one service-owned compensation boundary without moving status logic into views,
events, model hooks, or provider code.

## Whole-Repo Scope

Likely implementation surfaces are:

- `shifter/shifter_platform/cms/services/_range_create.py`
- `shifter/shifter_platform/cms/services/_ngfws.py`
- `shifter/shifter_platform/cms/scenarios/hydrator.py` only if exception
  typing or logging needs a narrow adjustment
- `shifter/shifter_platform/cms/models/provisioning.py`,
  `cms/models/range.py`, and migrations only if a deliberate schema change is
  accepted
- `shifter/shifter_platform/mission_control/views/_ranges.py`,
  `_ngfw.py`, `mission_control/api/ranges.py`, and
  `mission_control/api/resources.py` if user feedback changes at the HTTP edge
- tests under `shifter/shifter_platform/tests/cms`,
  `tests/mission_control`, and `tests/engine/services`

Usually out of scope:

- Terraform, Kubernetes, provisioner, task-runner, platform env, workflow, or
  runtime secret-delivery changes.
- New public API routes, new token scopes, new roles, or changed CTF
  participant launch policy.
- Redesigning request/operation state, retry/reconciliation, audit durability,
  or provider cleanup. Those are broader transactionality concerns.

## Gotchas And Anti-Patterns

- Do not add a `status` field to `cms.models.Request` as a quick fix without a
  broader schema and projection decision. Existing contracts put lifecycle on
  child resources.
- Do not mark only `App` or only `Instance` failed for NGFW; both are
  user-visible CMS entities tied to the same request.
- Do not leave `RangeInstance` stuck in `provisioning` when engine dispatch
  raises after the CMS row exists.
- Do not write a successful provision audit row after compensation. A failed
  launch/create must not look successful in audit evidence.
- Do not catch broad exceptions in views and duplicate compensation there; the
  service owns the rows and the request id.
- Do not swallow the exception silently. The caller still needs a failed
  response when the launch/create request cannot be accepted.
- Do not expose raw hydrator, Pydantic, engine, cloud, database, or PAN-OS
  exception text to users. Classify or use authored messages.
- Do not log or audit full `RequestSpec`, `RangeSpec`, `InstanceSpec`,
  `NGFWAppSpec`, credential data, Terraform output, cloud provider response
  bodies, or encrypted-field plaintext.
- Do not use events, WebSocket broadcasts, or frontend timers as the source of
  truth for this failure path.
- Do not weaken import-linter, ADR guard, ruff, or service-boundary rules to
  land the fix.

## Non-Goals

- No implementation in this preflight note.
- No formal Ground Control requirement or traceability work.
- No new ADR unless implementation changes enforceable architecture policy,
  request schema, import boundaries, workflow rules, or global error-envelope
  behavior.
- No distributed transaction across CMS, engine, provisioner, cloud APIs,
  Terraform, PAN-OS, and event delivery.
- No retry/reconciliation worker, operation-attempt table, or public request
  status API in this issue.
- No historic database cleanup for already-stuck production rows unless a
  separate data-repair task is explicitly scoped.

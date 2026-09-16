# Provisioner Persistence Boundary — Phase 4 Preflight (#1836)

Status: pre-implementation guidance

Date: 2026-07-26

Issue: GitHub #1836, phase 4 of #478

This note narrows ADR-043 and the repository-wide
`provisioner-persistence-boundary-preflight-478.md` to the pause/resume and
NGFW write family. It records phase-specific boundaries and cutover blockers;
it is not an implementation plan.

## Authoritative Boundary

The Engine result applier becomes the only authoritative writer for every
domain transition represented by this family:

- Range pause/resume completion or failure;
- status changes for the Range's lifecycle-managed `Instance` rows;
- direct NGFW provision/deprovision/start/stop status and normalized state;
- the matching NGFW `App` status;
- inline NGFW power changes that occur as a step of NGFW provision; and
- an NGFW pause/resume cascade performed for a Range operation.

The result disposition, all affected Engine rows, strict system-audit record,
and any ADR-025 `RangeEventOutbox` notification must commit in one
`transaction.atomic()` block. Provisioner event-outbox inserts and direct
domain writes are not a second authoritative path during or after cutover.
One operation generation must use exactly one authoritative path.

Reuse `engine.services._lifecycle`, `engine.services._ngfw`,
`engine.launch_intents`, and the existing Engine handler event/audit shaping.
The applier may factor their persistence logic into an Engine-owned service,
but must not create a parallel transition matrix, status vocabulary, audit
shape, or ORM repository.

## Operation Ownership: Command Versus Cloud Step

An operation is the Engine-authorized command generation, not every physical
cloud power action performed while executing it.

- Direct NGFW `provision`, `deprovision`, `start`, and `stop` results use
  `resource="ngfw"` and the NGFW `Instance.provisioner_operation_id`.
- Range `pause` and `resume` results use `resource="range"` (or
  `aces-range` when that family is enabled) and the
  `Range.provisioner_operation_id`.
- An NGFW stop performed by Range pause, or start performed by Range resume,
  is a bounded subordinate result of that Range operation. It must be
  ownership-checked through `Range.ngfw_instance` and current attached-range
  state. It must not pretend that the Range operation id is the NGFW
  Instance's generation.
- An auto-stop performed during NGFW provision remains a step of the NGFW
  `provision` generation. It does not silently launch a second `stop`
  generation.

Do not mint an implicit child launch intent merely to persist a cascade, and
do not weaken `_resolve_operation_target` so any operation id can mutate any
NGFW. Those approaches respectively duplicate workflow identity and remove
the generation fence.

The applier must lock the owning operation target first, then affected
instances/apps in deterministic primary-key order. For a shared NGFW cascade,
it must re-check the current attachment and whether another attached Range is
`READY` or `RESUMING` before applying the NGFW projection. The existing
provisioner `should_pause_ngfw` check remains a pre-cloud compatibility check,
not authorization for the later Engine write.

## Result Shape, Identity, And Ordering

`shared.operation_envelope` remains the only transport envelope. Phase 4 needs
one closed operation-specific payload parser shared by producer and applier;
a JSONField, `TypedDict`, ORM `choices`, or digest is not that parser.

The payload composes:

- `shared.enums.ResourceStatus`;
- normalized NGFW attachment/runtime state already shaped by
  `config.resolve_ngfw_attachment_config`, `ngfw_terraform_state`, and
  `state_helpers`;
- stable UUID correlation, never Engine integer primary keys as authority;
- bounded instance outcome summaries for Range pause/resume; and
- a fixed reason code plus bounded authored diagnostic for failure.

Do not transport arbitrary `**state_updates`, table columns, caller-selected
field names, raw Terraform/provider responses, exception strings, or complete
state snapshots. If the legacy NGFW runtime state has no closed shared parser,
formalize it once in dependency-light `shared` and consume that parser on both
sides. Preserve provider-native secret references only where the existing
state contract already permits them; never include secret values.

The current identity `f"{operation_id}:{result_kind}"` is not sufficient:
one operation emits more than one `RESOURCE_STATE` result
(`pausing -> paused`, `resuming -> ready`, and multiple NGFW provisioning
observations). Result identity must therefore be parameterized by a closed,
deterministic operation-local step/target key. The same semantic step on retry
must reproduce the same identity and digest; a different payload for that
identity is a conflict. Wall-clock time, completion order from a thread pool,
and random delivery UUIDs are not valid ordering keys.

Legal step order and terminality are closed per `(resource, operation)`.
Progress arriving after an applied terminal result must not regress domain
state. A terminal result may make a delayed progress result stale; creation
time alone must not authorize it.

The current shadow append is also not authoritative-ready:

- it catches every exception and continues;
- it treats a conflicting replay as a warning;
- its conflict path reads the existing digest although migration 0036 grants
  no inbox `SELECT`; and
- it omits NGFW state updates from the shadow payload.

At cutover, result append failure must fail the operation so existing task
retry/re-drive can recover it. The append boundary must atomically distinguish
insert, identical replay, and conflicting replay without granting the
provisioner general inbox read/update access. A conflict is a fixed,
operator-visible failure, not a swallowed warning.

## Validation And Security Layers

The design passes these layers in order:

1. **User authorization.** Existing DRF/session/token permissions and CMS
   ownership masking authorize pause/resume or NGFW lifecycle intent.
   `cms.services._range_lifecycle` and the CMS NGFW services remain the public
   edge. A result is never proof of user authority.
2. **Engine lifecycle authorization.** `engine.services._lifecycle`,
   `engine.services._ngfw`, and `engine.launch_intents` authorize current
   status and mint the canonical generation. The applier resolves and locks
   that server-created generation.
3. **Command/argv validation.** `validate_provisioner_command` and
   `command_from_payload` remain authoritative. Argv contains only resource,
   operation, request UUID, and operation UUID. No payload, state, error,
   credential, capability, or environment map enters argv.
4. **Wire and payload validation.** Engine validates before materializing
   input; the provisioner validates before cloud mutation and before append;
   the applier validates again. In addition to
   `validate_operation_envelope`, the applier must compare every flattened
   inbox discriminator with the validated envelope
   (`operation_id`, `request_id`, `resource`, `operation`, and
   `contract_version`), validate `result_kind` and result identity/step shape,
   verify the canonical digest, then invoke the operation-specific payload
   parser.
5. **Ownership and transition validation.** The applier checks current
   generation, Request ownership, role=`ngfw`, Range-to-NGFW attachment,
   exact target UUID membership, legal prior status, step order, and
   terminality. Payload-supplied integer ids never select rows.
6. **Database authentication and privilege.** Continue through
   `provisioner_db.get_db_connection`, provider DB-auth adapters, TLS/IAM, and
   the portal runtime role for the applier. The provisioner receives no new
   domain-table or inbox read/update grant.
7. **Secret and environment shape.** Reuse provider secret stores,
   `shared.cloud.sensitive_env`, provisioner `config` parsing, the platform env
   manifest/renderers, and current task/job admission. This cutover needs no
   new endpoint, callback token, environment variable, or cloud-IAM role.
8. **Logging and error envelopes.** Reuse provisioner `log_redact`, platform
   `shared.log_sanitize`, structured worker logging, `shared.errors`, and
   `shared.api.errors`. Log safe operation/result correlation, version, step,
   disposition, and status only. Raw provider/SQL exceptions, payload
   fragments, secret references, tracebacks, and table names must not enter
   Range error text, audit context, notifications, websocket/public API
   envelopes, or normal info logs.
9. **Audit and notification.** Reuse `shared.audit` vocabulary and writer,
   `_status_to_action`, `StateChange`, shared message constants/payload
   validators, and `RangeEventOutbox`. The applied transition requires a
   strict audit write inside the transaction; the default best-effort
   `audit_log_system_event` behavior is insufficient for ADR-043-R3 unless its
   failure policy is explicitly made strict. Audit the domain transition, not
   inbox receipt or the raw result.

## Grants And Migration Proof

Use forward migrations only. Historical Mission Control migrations 0020/0031
and Engine migration 0012 are evidence of the old capability, not edit
targets.

Engine 0012 granted table-level `UPDATE` on all `engine_instance` and
`engine_app` rows. That grant cannot be revoked safely until every active
writer that depends on it is on the applier path, including Range
provision/destroy and NGFW attachment-state writers
(`provisioner_db_ngfw`), not merely `_update_ngfw_status`. Phase 4's migration
must be sequenced after the earlier family cutover and must fail validation if
any active provisioner SQL still updates those tables.

Mission Control 0020 granted columns that later migrations removed, while
0031 granted objects later moved or dropped. Do not assume historical SQL
still maps one-to-one onto the live schema, and do not make a forward migration
fail by naming an absent table/column unconditionally. Reconcile the live
catalog and revoke every surviving effective NGFW write capability.

PostgreSQL tests must exercise the migrated schema and the real
`provisioner_lambda` role. Prove effective table and column privileges, not
just that a migration function emitted a `REVOKE` string:

- input projection remains readable and inbox append remains allowed;
- inbox/domain-table read, update, and delete stay denied except for the
  reviewed input read;
- `engine_instance` and `engine_app` updates are denied after all dependent
  families cut over;
- surviving Mission Control NGFW column/table updates are denied; and
- normal result append, identical replay, conflict handling, and applier
  writes still work under their actual runtime principals.

## Observability And Runtime Surfaces

Reuse the existing `apply_operation_results` worker, heartbeat, batching,
`select_for_update(skip_locked=True)`, deployment/container security context,
and AWS/GCP render paths. Do not add a second worker or queue.

The authoritative path must expose safe signals for oldest pending result,
apply latency, unsupported version, invalid payload, stale generation,
ownership rejection, ordering rejection, conflicting replay, append failure,
and an operation generation lacking a terminal result. A transaction failure
leaves the row retryable; a deterministic invalid/stale/conflicting result is
dispositioned without domain mutation. Worker liveness alone is not evidence
that results are progressing.

## Gotchas And Anti-Patterns

- Do not apply both direct SQL and inbox results for one generation.
- Do not keep `publish_ngfw_event` or `update_range_status(...,
  outbox_event=...)` as a provisioner-owned side effect after cutover.
- Do not use one NGFW generation for a Range cascade, or one Range generation
  for an independently requested NGFW operation.
- Do not key authority by `engine_instance.id`, `engine_app.id`, or
  payload-supplied ownership.
- Do not bulk-update every instance for a Request without matching the closed
  target UUID set and validating the prior state under lock.
- Do not update every App beneath an Instance; only the existing NGFW App
  projection belongs to the NGFW lifecycle result.
- Do not allow a late progress result to overwrite terminal state, or clear a
  newer operation generation on an old failure.
- Do not preserve arbitrary state merging merely because
  `update_instance_state(**state_updates)` currently permits it.
- Do not reuse the result payload as an SNS/SQS/websocket event.
- Do not swallow authoritative append/audit/outbox failures.
- Do not revoke table-level grants while earlier cutover families still use
  them, and do not retain unused grants “just in case.”

## Non-Goals

- No provider orchestration, Terraform state, PAN-OS plan, retry-policy, or
  cloud power-operation redesign.
- No new public API, callback endpoint, broker, event-sourcing model, generic
  repository, workflow engine, status enum, exception hierarchy, or logging
  sanitizer.
- No GCP pause/resume enablement; the existing parity guard remains closed.
- No redesign of CMS user-intent audit, Mission Control projection, CTF
  lifecycle behavior, or participant access.
- No migration of unrelated provisioner read families in this phase. Existing
  compatibility reads may remain only where their grants are still required;
  phase 4 must not add or broaden them.

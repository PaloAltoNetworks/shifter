# CTF Durable Communication Delivery Engine Preflight

Date: 2026-09-12. Repository baseline: `613f365ac`.

Scope: issue #2049; CTF-008, CTF-010, CTF-012. This is architecture guidance,
not an implementation plan or a claim that the engine ships today.

The immediate implementation target is #2099, slice 2 of #2049. Slice 1's
delivery-command/lease engine, durable in-app availability, reference-only
WebSocket acceleration, adapter contract, worker observability, and worker runtime
are now incumbents to extend, not designs to replace. This slice owns source
normalization, admission, due-time processing, lifecycle fencing, and correctness
of the existing CTF scheduler. REST endpoints, the public API-token scope surface,
and legacy cutover remain slice 3 (CTF-012); email transport remains #1525.

This note specializes [ADR-051's communications decision](ctf-communications-raes-inject-preflight-2047.md)
for execution after #2048. Its ownership, content, RAES, workload-ingress,
retention, and API boundaries remain authoritative. Extend the existing CTF
ledger and services; no new messaging domain or general workflow framework is
needed. Email transport completion belongs to #1525 / PLAT-103.

For CTF-010 / CTF-1001, the incumbent scheduler is `CTFScheduledTask` (now in
`ctf/models/notification.py`, re-exported from `ctf.models`) and the command's
`TASK_HANDLERS`; the requirement's older monolithic paths are historical.
“Platform scheduler” does not imply a missing generic scheduler to build.
Range provisioning, event transitions, and CMS lease expiry retain their owners.

## Repository Findings That Constrain Implementation

Application paths in the findings below are relative to
`shifter/shifter_platform/`; repository-level `platform/`, `scripts/`,
`shifter/installation/`, and documentation paths are written from repository
root. These are current implementation gaps, not new alternative contracts.

| Incumbent | Finding and required consequence |
| --- | --- |
| `ctf/services/communication/release.py` | Already commits intent, recipient snapshots, receipts, delivery commands, and strict audit together. Reuse this transaction boundary. It does **not** reauthorize a live user/token/workspace, enforce due time, validate a current range generation, or populate source/correlation evidence. Its optional actor IDs are attribution inputs, not authentication. Admission must own those checks for every caller, including replay. |
| Release locking | `_assert_release_allowed()` locks only rows already matching `CANCELLED`; it does not lock live target events despite the release comment. Lock all relevant live targets before checking state, in a documented deterministic order shared with lifecycle operations. Campaign locking alone cannot serialize event cancellation or participant removal. |
| `ctf/services/communication/lifecycle.py` | Campaign cancellation has a campaign lock; participant removal and range fencing lack a shared release/claim mutex. The hooks have no production callers outside this package at this baseline. Wire them through the owning event/participant/range lifecycle services, including soft deletion, account purge, teardown, and replacement; direct hook tests do not establish lifecycle coverage. |
| `ctf/models/communication.py`, `ctf/enums_communication.py` | `DeliveryAttempt` is one durable command per `(snapshot, channel)`, not one immutable row per physical attempt. Slice 1 added claim tokens, lease expiry, attempt/observation times, retry budgets, and stale-worker settlement fencing. Reuse that engine and its current pre-I/O eligibility fence; slice 2 extends live source/workspace/event/range authorization through admission rather than adding another outbox, lease model, or competing status. |
| In-app materialization | Release now creates a receipt only when `in_app` is selected and queues one command for every selected channel. That committed snapshot/receipt remains the availability gate; the in-app command is only the reference wake-up accelerator. Preserve explicit email-only selection and this truthful separation when scheduled release enters the same path. |
| `ctf/communication_contracts.py` | Reuse its closed audience/trigger/channel/content validators and `canonical_digest`. Trigger values currently receive only non-empty-string checks; UUID lists lack maximum cardinality. Add semantic UTC/status/reference/type and size bounds here, not a separate validator per source. Markdown regex checks are not proof of the complete safe-document profile. |
| Model persistence | `CTFBaseModel.save()` runs `full_clean`; `bulk_create` and queryset updates bypass it. Only `MessageRevision` uses `ImmutableFieldsMixin`, and that does not freeze its campaign association. Campaign scope/targets, released intent fields, and snapshot identity are not made immutable by their docstrings. Enforce them through the canonical services, existing mixin where appropriate, and database constraints; audit every bulk-write path. |
| `ctf/management/commands/run_ctf_scheduler.py` | Reuse the one-shot registry, handlers, claims, heartbeat, and shutdown conventions. The stale sweep marks tasks `FAILED`, rather than requeuing as its header claims. Completion is not fenced by claim identity and can overwrite a handler's cancelled status. Communication recovery must address these paths at the scheduler owner. The default 30-second polling interval is not a precision guarantee. |
| `ctf/services/event/scheduling.py` | `_reschedule_event_tasks()` cancels **all** pending event tasks, then recreates lifecycle/reminder/challenge work; it does not recreate scheduled announcements or communication occurrences. Cancellation filters only `PENDING` and does not fence a task already claimed. Extending timing must preserve independently authored schedules and invalidate obsolete event-derived occurrences through the same admission owner. |
| Lifecycle and range-status handoff | `activate_event` / `complete_event` and their scheduler handlers mix transitions with best-effort notification calls. `cms.handlers.range_events.apply_range_status` wraps a bridge in a transaction, but `cms.handlers.ctf_bridge.notify_ctf_range_status` catches receiver exceptions; converged status skips the bridge on replay. `ctf.signals` updates the range projection, while `ctf.services.range.status.get_range_status` sends range-ready mail only when a read observes a change. None proves recoverable communication handoff. Preserve the existing CMS signal/public-service boundary and require durable occurrence evidence or reconciliation before claiming automated milestone coverage; never depend on a browser poll. |
| Server-owned cleanup | `cms.services.expire_due_ranges` and `cms/management/commands/reconcile_range_events.py` enforce persisted range leases; legacy `CLEANUP_RANGES` dispatch invokes the global bounded lease sweep. `defer_event_cleanup` / `cancel_event_cleanup` currently change scheduler rows only. Neither changes `expires_at`, so a deferred/cancelled task does not promise postponed/prevented destruction. |
| Organizer task controls | `ctf/api/organizer/lifecycle.py` admits task listing/run-now with event scopes and `LIFECYCLE` authority, and returns `task.error_message` directly. A communication task must not become an alternate path around exact communication scopes, per-target `NOTIFICATIONS` authority, due-time policy, or bounded public failure reasons. |
| `shared/email.py` | Synchronous `send_email` returns `True` after `msg.send()` without inspecting its count; `False` conflates all failures. Console output is not external delivery. Full exception logging can expose provider data. #1525 must supply truthful, bounded, redacted adapter outcomes; this engine cannot manufacture them from that boolean or `send_email_async`. |
| `ctf/services/notification/realtime.py` | Slice 1 added `publish_communication_wakeup` and the in-app adapter, using stable snapshot identity and one explicit recipient for reference-only wake-ups. Reuse that narrow path. The older event-content/broad-audience publisher is not a communication admission or delivery seam. |
| Activation and compatibility | Migrations `0051_backfill_ctfevent_workspace` and `0052_communication_models`, the CTF-to-workspaces service edge, `USE_CTF_COMMUNICATIONS`, the delivery worker, and its deployment surfaces now exist. Earlier preflight text describing them as absent is historical. Exact communication token scopes and the legacy notification/scheduler cutover are still missing. Do not infer deployed migration completion from source presence. |

## Slice 2 Activation Guardrails (#2099)

This slice has one architectural seam: each trusted source normalizes a bounded
declaration or occurrence, then calls the existing communication service's one
admission transaction. Manual, event-lifecycle, absolute-time, supported RAES
shared/script-time, and generation-bound range signals differ only in how they
prove source authority and form occurrence evidence. They do not own release,
audience resolution, idempotency, fan-out, delivery, or retry policy. Scheduler
handlers carry typed identifiers and reload authoritative rows; free-form task
metadata, caller-supplied origin/actor/token/scope, and event routing anchors are
never privilege evidence.

Admission must linearize live authority with its durable commit. Reuse the API
token row's owner/revocation/expiry checks, the event authority resolver,
`USE_CTF_COMMUNICATIONS`, and the workspace-row mutex pattern in
`authorize_launch_workspace_locked`; promote or generalize owner-owned helpers
when needed instead of importing tenancy/token models into CTF or copying their
policy. Within the CTF aggregate, lock all target events in stable primary-key
order before campaign/revision/declaration rows, and make event, participant,
account-purge, and communication lifecycle paths use the same event-first order.
The current campaign-then-event release comment is not the contract. Revalidate
actor/profile/token, workspace membership/state, every event, affected
participation, declaration fence, and range generation inside the transaction;
recheck effect-relevant fences immediately before each delivery retry.

`shared.api_tokens.scopes` has no communication scope at this baseline, while
the public scope surface is explicitly slice 3. Slice 2 must neither invent a
private scope string nor substitute `ctf:event:write`. Token-authored declarations
remain fail-closed until the canonical exact communication write scope exists;
the due-time path may be built to consume that closed policy without exposing a
new REST or scope-registration surface here. Human/session admission still needs
the live actor, active bound workspace, and `NOTIFICATIONS` authority on every
target event. A missing actor or token is never implicit system authority.

Use the existing `CommunicationIntent` as the scheduled declaration/occurrence
ledger and its `due_at`, occurrence, source/generation evidence, and
`policy_revision` as immutable authored meaning. `CTFScheduledTask.scheduled_for`
is only the mutable next execution index because retry/resume overwrite it.
Scheduling the declaration and its task must be one recoverable commit; release
materializes the audience only when due. Define one closed lateness/expiry policy
with an explicit durable no-work/expired outcome; do not call expiry `FENCED`, and
do not treat scheduler completion as release or channel delivery. Run-now either
passes the same communication authority and explicit early-release policy or is
unavailable for communication tasks.

Fix scheduler correctness at `CTFScheduledTask`/`TASK_HANDLERS`: a claim needs a
unique completion fence or an equivalent conditional transition, stale recovery
requeues eligible work rather than terminally failing it, and shutdown must not
strand unexecuted members of a preclaimed batch. A handler-cancelled or superseded
task cannot be overwritten as completed. Bound claims to executable capacity,
and keep provisioning/provider work out of the timing transaction. Repeated ticks,
restarts, clock adjustments, run-now, and stale recovery all re-enter the same
intent admission/fence path and therefore collapse or reject on full meaning.

Wire lifecycle fencing from the services that own the durable mutation, inside
the same transaction or through durable reconciliable handoff. Cover event cancel
and soft/force delete, participant removal and account purge, range teardown and
replacement, and scheduler rescheduling. Do not use model signals, browser polling,
or `on_commit` alone as workflow truth. CMS keeps lease expiry and range lifecycle
ownership; CTF consumes only a frozen scalar generation/authority projection from
the public CMS service plus `ctf.bridges`. A range-instance identifier is not a
generation fence. `shared.raes` remains the only RAES interpreter; because its
current runtime target is provisioning-only, unsupported Inject/time realization
stays closed rather than being approximated as an absolute timestamp or mirrored
in a CTF schema.

## Execution Contract

**One admission owner.** Source-specific normalizers prove their own trust
boundary, then enter `ctf.services.communication`. Human work resolves a live
active actor, the bound active workspace, and `notifications` authority on every
target event. Scheduled token-authored work additionally checks that exact stored
token row, owner, revocation/expiry, and exact communication scope at due time.
Derive origin, authority source, actor, token, and range evidence server-side;
never accept them as privileges from a request or scheduler metadata. Scenario
automation is an admitted declaration, not an ambient superuser. Recheck current
event/participant/range eligibility before consequential fan-out and retries.
Historical inbox access uses live participant authority, not the author's
continued membership or the delivery-coordinate value.

Keep trusted lifecycle/lease automation distinct from human-authored scheduled
communication. A missing actor is not sufficient proof of system authority.
Organizer revocation, communication backpressure, or mail failure must never
disable server-owned range expiry or become a prerequisite for teardown.

**One recoverable commit.** Keep accepted intent, pinned revision/policy/source
evidence, immutable audience, initial selected-channel commands, in-app
availability, and strict correlated audit in one transaction. Validate and bound
the audience and fan-out cost before reporting acceptance. Worker processing can
be batched; batch boundaries must never re-resolve a later audience. Do not relax
ADR-051 into “commit an intent, then discover recipients asynchronously.” An
over-budget request is rejected/deferred explicitly; an empty eligible audience
has an explicit no-work outcome and never claims delivery. `on_commit` or a broker
message may wake a worker but cannot be the only recoverable work. A database
poll/reconciliation path must recover lost wake-ups.

**Idempotency includes meaning.** Retain the campaign-qualified structured digest
and stable `(intent, snapshot, channel)` command identity. Normalize source class
and source occurrence/generation before deriving identity. A retry returns the
same authorized occurrence without growing recipients; the same key with
conflicting revision, source, scope, or policy is rejected, not silently treated
as equivalent. Soft-deleted rows must not hide uniqueness/replay evidence, and
retention must not allow an expired declaration to resurrect delivery. Catch
uniqueness races outside a nested savepoint before querying the winning row;
the current release `IntegrityError` handler queries inside the broken atomic
block. Model validation may also reject uniqueness before the database insert.

**Claims are leases, not observed sends.** Follow the short transaction,
`select_for_update(skip_locked=True)`, conditional update, lease comparison,
bounded retry, and terminal-state patterns in
`engine/management/commands/drain_provisioner_launch_outbox.py`, without importing
Engine code or using its tables. Each claim/reclaim needs a unique fence and
expiry; stale workers may not complete, retry, heartbeat, or resurrect a newer
claim. Persist the attempt boundary, use bounded transport timeouts, then record
only an outcome observed by that attempt. Do not hold database locks during
email/Redis/provider I/O; the launch worker's provider call inside an atomic
block is not a pattern to copy into communication delivery.

Cancellation and release/claim must share a linearization boundary. ADR-051
guarantees cancellation of **unclaimed** work; a committed claim is the boundary
after which cancellation cannot promise recall, not proof an email was sent.
Recheck a visible lifecycle/generation fence immediately before transport I/O and
suppress where still possible. Reclaimed or retry-due work must recheck fences
and cannot escape a cancellation that arrived while an older lease was active.
Crash/reclaim cycles consume bounded execution time/attempt budgets too; counting
only caught provider exceptions permits an infinite recovery loop.
Event cancellation affects only that event's snapshots in an already released
multi-event intent. Participant removal erases coordinates without retargeting;
range replacement requires a new generation-qualified occurrence. A failed
recipient/channel remains isolated from unrelated commands.

External delivery remains at-least-once. A crash after provider acceptance but
before result persistence is indeterminate and can produce duplicate mail;
stable backend message identities mitigate this only where supported. Do not
promise exactly-once external effects or cross-channel ordering. Retry policy
has one owner in the ledger worker: bounded exponential backoff with jitter,
attempt and elapsed-time ceilings, and an operator-visible terminal outcome.
Scheduler, broker, and email adapter retries must not multiply that budget.
An outcome/audit persistence failure after a send cannot roll back that send;
retain indeterminate evidence and recover through the same fenced command.

## State And Time Must Remain Distinct

| Evidence | Meaning |
| --- | --- |
| Admission accepted / intent released | The database committed recoverable work, not channel delivery. `IntentStatus` remains occurrence lifecycle. |
| Queued / claimed / attempted / retry due | Durable command and execution evidence. A worker lease alone is not an attempted external call. |
| In-app available | Selected inbox entry exists durably at commit. Its success is derived from the selected channel plus persisted snapshot/receipt availability, not from a queued accelerator command. WebSocket outage cannot hold it pending, undo it, or fail it. |
| Email backend accepted | The platform adapter observed backend acceptance. It is not delivery to a mailbox, read, acknowledgement, or a successful thread dispatch. |
| Socket written | Shared transport replay bookkeeping only; not a participant receipt. |
| Read / acknowledged | `ParticipantReceipt` state, changed only by the authorized participant interaction. Explicit acknowledgement requires the deliberate mutation; preview/list/replay never implies it. |
| Suppressed / expired / cancelled / terminal failure | Distinct bounded dispositions and reasons where applicable; never silently mapped to acceptance. Extend the existing closed enums and constraints coherently rather than adding another universal status enum. |

Campaign lifecycle is not a transport success counter. Aggregate from unique
selected commands/receipts with pending, successful, and failed/suppressed counts;
do not count retries as recipients, count WebSocket wake-ups as deliveries, or
hide partial failure behind `RELEASED`/`SENT`. Define an empty denominator and
unavailable channel explicitly. Unsupported adapters must not silently downgrade
the requested channel policy. For `in_app`, any retained `DeliveryAttempt` governs
only fenced execution/reconciliation of the accelerator work: the worker first
observes the already-committed inbox availability and may then emit a best-effort
reference wake-up. Accelerator failure is a separate bounded degradation signal,
not a reversal of durable in-app success and not a reason to duplicate the inbox
entry.

`CTFScheduledTask` owns absolute UTC due-time indexing and carries bounded
occurrence/intent references only. Event rescheduling uses
`ctf.services.event.scheduling`; stale task copies, run-now operations, restart,
and repeated ticks all enter the same admission/fence logic. A durable occurrence
survives a crash before scheduler completion. State the supported lateness and
expiry policy: polling, queue backlog, provider latency, and clock adjustments
cannot be represented as exact delivery at the requested instant. RAES
shared/script time retains its coordinate, ordering, package, and generation
identity through `shared.raes`; it is not a Unix timestamp or a new CTF clock.
The current `shared.raes.runtime_target` is provisioning-only. Do not invent an
available inject/time API; unsupported realization stays closed until its owning
adapter exists. Provider work must not block the timing scheduler.

Keep authored due time/occurrence separate from the next retry time:
`CTFScheduledTask.retry_or_fail` and `requeue_for_resume` overwrite
`scheduled_for`, so that mutable field cannot supply occurrence identity.

Scheduling accepts a **future declaration**, not a released delivery: commit its
pinned content/policy/source references and recoverable timing work together.
At the eligible occurrence, release resolves and freezes the audience in the
transaction above. A replay of an existing `SCHEDULED` intent must perform or
observe that release, not return early as though recipient work already exists.
Future content must not become inbox-visible just because scheduling succeeded.
Validate timezone-aware instants in `ctf.communication_contracts`, normalize to
UTC, and reject ambiguous naive dates. Keep absolute time, event-derived timing,
RAES coordinates, retry deadlines, and retention expiry distinct. Event pause or
reschedule must not silently reinterpret an absolute instant; run-now must use
an explicitly authorized early-release policy or remain unavailable for that
trigger. Recheck the current schedule/declaration fence at execution, including
ties, clock jumps, overdue startup, and rescheduling after claim. Changing event
times does not resend an already released occurrence; intentional new delivery
requires a separately authorized occurrence.

`CTFScheduledTask.event` is required, whereas one campaign can target multiple
events. Its event is a routing anchor, never the complete authorization or
audience scope. Any task rows indexing the same campaign-wide occurrence must
collapse to the same intent; event-derived occurrences retain their own event
identity. Cancelling/deleting the anchor must not silently orphan timing work or
authorize cross-event fan-out. This relationship belongs in the existing trigger
normalizer and lifecycle services, not in a second scheduler or an arbitrary
“first event” controller shortcut.

Keep range lease mutation at `ctf.services._event_range_lease` → `ctf.bridges` →
`cms.services.reconcile_ctf_range_leases`. The CMS owner bounds `expires_at` by
the generation's immutable `maximum_expires_at`/credential lifetime; a later
deadline can require a new generation. Communication expiry never extends that
lease. Cleanup warnings must describe the authoritative deadline, and a finished
legacy cleanup task proves only that a lease sweep ran, not that every range of
its event was destroyed. The CMS reconciler remains the backstop even when the
CTF scheduler is unavailable; pending-task cancellation is not a range control.

## Cross-Cutting Gates And Canonical Owners

| Layer the design passes through | Required reuse and satisfaction |
| --- | --- |
| HTTP identity and authorization | `config`'s CTF account middleware, canonical DRF session/API-token authentication, `shared.api.principals.active_actor_user`, CSRF, `ctf.api._base`, `ctf.services.authorization.resolve_event_authority`, and `workspaces.services.authorize_bound_workspace(..., USE_CTF_COMMUNICATIONS)`. Preserve owner/staff/platform-admin distinctions (including the existing co-organizer role); use the authority-returning resolver for strict root-override audit. Slice 3 adds exact `ctf:communication:read/write` to `shared.api_tokens.scopes` and uses its machine-readable `require_scope` permission; slice 2 does not substitute an older scope. Token authentication does not make `request.user` the actor automatically. Participant receipts remain session-bound and parent-scoped. |
| Range workload admission | ADR-051's workload boundary and `shared.raes` remain authoritative. Prove issuer/audience/expiry and exact deployment, range operation generation, participation, event, workspace, scenario/package, and allowlisted declaration/occurrence before normalizing. A status signal's range instance ID alone is not that proof. Neither a guest clock, participant session, API token, outbound webhook HMAC, nor client-supplied origin substitutes for workload authority. This slice consumes validated projections; absent realization/ingress capability stays closed. |
| Parsing, shape and content validation | Explicit serializers delegate semantic rules to `ctf.communication_contracts`; do not use writable model serializers or free-form metadata. Enforce byte/depth/list/reference bounds and reject unknown/duplicate keys before normalized dicts lose evidence. `ctf.content_bundle._reject_duplicate_pairs` is the incumbent parser pattern, not a reusable communication schema. Handle malformed field types as bounded domain rejection, not uncaught `TypeError`. Keep content/profile/digest and allowed-host checks; render through the existing safe-content/Markdown and email-wrapper boundaries, with no raw HTML, template execution, URL fetching, or CSP relaxation. |
| Persistence and lifecycle | Reuse `CTFBaseModel`, `ImmutableFieldsMixin`, the #2048 models, migrations, constraints, `transaction.atomic`, and communication services. Prove snapshot-event-campaign confinement, revision ownership, `DeliveryAttempt.intent == snapshot.intent`, and immutable policy even on bulk paths. Lock authoring revision changes against release as well as cancellation. Use default soft-delete filtering for visibility but explicit retained evidence for recovery/uniqueness. |
| Secrets and host exposure | `shared.field_encryption.EncryptedStringField` owns coordinates; decryption/key failure denies only the dependent channel effect with a bounded reason. Build a minimal, immutable adapter command per channel: the in-app adapter receives stable snapshot/event/user references and must never decrypt or receive the email coordinate; only the future email adapter may decrypt that coordinate immediately before its bounded call. `entrypoint.sh`/`entrypoint-lib.sh` hydrate existing `APP_SECRET_ID` and `EMAIL_API_KEY_SECRET_ID` references from provider stores, with `FIELD_ENCRYPTION_KEY` and email keys kept private to the process. Pass references, never secret values, in argv, ConfigMaps, Helm values, Terraform, task metadata, diagnostics, or shell interpolation. Reuse stdin/private-file secret handling and avoid shell tracing/env dumps. If a job adapter is involved, satisfy `shared.cloud.sensitive_env.split_env`; `EMAIL_API_KEY` does not match its current sensitive-name/suffix rules and must never pass as a literal job env value. No new credential is needed for the ledger worker. |
| Error envelopes, audit and logging | Reuse `CTFCommunicationError`/`CTFError`, canonical CTF-to-DRF mapping, `shared.api.errors`, and fixed authored errors. `safe_user_message` only strips/truncates; `error.details` normalization does not redact arbitrary values or field names. Never return raw provider/model/parser errors. Slice 2 adds no public HTTP error surface: its management-command stderr/logs, persisted bounded reason classes, heartbeat probe, and metrics must likewise omit bodies, coordinates, provider text, tracebacks, and database errors; health reports liveness/readiness classes rather than command detail. Extend `ctf.services.audit.audit_communication_release` and `shared.audit` with bounded source/authority/token-record/correlation evidence, strict in the admission transaction. Carry that non-secret correlation into worker outcomes. `config.logging.ECSFormatter` emits only allowlisted extra fields; arbitrary extras silently disappear. Reuse `shared.log_sanitize` for safe identifiers, but its process-local fingerprints are not durable correlation. Audit/logging defaults and `logger.exception` are not PII redaction; inspect nested exception text from model validation, scheduler, email, and middleware too. |
| WebSocket and browser | Preserve `AllowedHostsOriginValidator` → `AuthMiddlewareStack` → `CTFAccountWebSocketBoundary` → `SharedNotificationConsumer` topic authorization. Temporary accounts currently cannot use `/ws/notifications/`; admit only that exact route after live participation/password-change checks, never a `/ws/` bypass. Reuse `shared.notifications`, its payload handler, group naming, replay bounds, and existing enablement flag. Project only authorized message references; reconnect/poll fetches the durable inbox and deduplicates by stable snapshot/message ID. Revalidate participant authority on fetch/read/ack even for an already open socket. |
| Admission bounds and observability | Reuse `shared.rate_limit.consume_fixed_window` and the fail-closed 429/Retry-After versus 503 posture in `mission_control.api.rate_limit`. Enforce actor, range-generation, event, workspace, and global budgets in shared storage, plus audience size, outstanding-work, and in-flight limits. A rate counter alone does not bound durable backlog; database reservations/counts require serialization. `workspaces.services` quotas already own range/seat resources: do not misuse those resources as message budgets or duplicate their membership policy. Fair bounded worker batches must prevent one event monopolizing delivery. Reuse the provider-aware metric publication pattern of `shared.warm_pool.metrics` / `config.capacity_metrics`, without importing config from CTF. Report oldest-due age, backlog, admission denials, retries/exhaustion, lease recovery, latency, and channel degradation. Metrics use closed source/channel/reason/scope-class labels, never recipient IDs/PII or unbounded workspace/event/range IDs; bounded IDs belong in authorized audit evidence. Metrics outages cannot change delivery truth. |

## Configuration And Runtime Estate

The policy seam is a typed, bounded, server-owned configuration: per-scope
budgets, admission/batch sizes, concurrency, polling, lease duration, transport
timeout, retry ceilings, and lateness/expiry policy. Validate their relationships
(for example, transport timeout versus lease/recovery and shutdown windows), not
just each number. Keep `config/_ctf_communication_settings.py` as the CTF owner;
reuse `_runtime_env`, `_email`, `_channels`, `_cache_settings`, and `_redis` for
deployment, provider, Redis AUTH/TLS/CA, and cache posture. No silent local-memory
limiter/channel fallback in a multiple-process deployment.

Every exposed knob/process must pass the actual repository shapes:

- `config/_env_manifest.py` and generated `config/env-manifest.json` (helper-read
  bindings need explicit registration); `shifter/installation/runtime_inventory*.py`
  and `scripts/gcp/render_runtime_env.py` inventories/rendering;
- `scripts/bootstrap/{gcp_control_plane,aws_eks}.py`, Helm
  `platform/charts/shifter/{values.yaml,values.schema.json,templates/}` and chart
  tests, plus GCP base manifests, overlays, and workload identity/network policy;
- `shifter/shifter_platform/docker-compose.yml`, retained AWS EC2
  `platform/terraform/modules/portal/ec2/user_data.sh`, and
  `scripts/portal-deploy/deploy_portal.sh` startup/stop/restart lists;
- `entrypoint.sh`, database/field-key hydration, least-privilege worker service
  accounts and email/Redis/network permissions, heartbeat health probes,
  graceful shutdown, restart recovery, and `scripts/stack-smoke` coverage.

Helm's closed `values.schema.json` worker/service-account keys, restricted pod
security context, writable `/tmp` volume, NetworkPolicy, and disabled automatic
service-account token mounting must match the rendered workload. Reuse the chart
helpers and worker identity; a communication drainer needs no provisioner Job
creation permission. If provisioner inputs change elsewhere, their separate
admission-policy env/secret allowlists still apply; passing `split_env` alone is
not Kubernetes admission. Run the matching Helm/chart, kube-linter/kubeconform,
TFLint, or actionlint checks only when those artifacts change.

The scheduler currently claims an entire batch before executing it serially;
range spin-up can occupy the loop while other claimed tasks age without progress.
Shutdown leaves not-yet-executed batch members `RUNNING`. Bound claims by actual
execution capacity, retain recovery for every claimed member, and prove timing
under provisioning and communication load together. Bound stale sweeps and
housekeeping too. File heartbeat freshness is only process liveness: the loop
touches it even after poll failure, so measure successful polling and oldest-due
age separately. CLI numeric parsing currently has no positive/upper bounds;
validate flags and settings consistently. `CTF_SCHEDULER_STALE_TASK_MINUTES` is
read through `_env_int` but absent from `_EXPLICIT_BINDINGS` and the generated
manifest at this baseline; do not copy that configuration gap to new knobs.

At this baseline the `SHIFTER_CTF_COMMUNICATION_*` settings appear in the
generated settings manifest and slice 1 worker surfaces, but the policy values
have no matching first-class deployment bindings in
`platform/`, bootstrap/render scripts, or installation inventories. Settings
acceptance alone is not deployment configurability. Shared email can explicitly
select a console backend; durable external email must report that as unavailable,
not delivered or printed with real message content. Do not give a communication
worker the provisioner launcher's cloud permissions merely to copy its supervisor.
Duplicate admission must not reserve outstanding-work capacity twice. Reuse the
fixed-window primitive for abuse limits, without confusing those counters with
idempotent durable capacity reservations.

## Extensibility, Verification, And Boundaries

A new source belongs at the validated normalizer seam; a new channel implements
the same bounded command/result contract with stable identity, transport timeout,
outcome/retry classification, and optional provider receipt. Provider details stay
in `shared.email` for #1525; source-specific authorization, audience, and scheduling
do not change for a new email provider. Content profile and locale remain pinned
revision parameters. These are closed application seams, not plugin registration
or `AppConfig.ready()` workflow hooks. Existing shared notification registration
is transport wiring, not permission to add a communication extension registry.

Implementation evidence must extend `tests/ctf/test_communication_*`, scheduler
tests, worker/outbox tests, and `tests/platform/test_ctf_scheduler_startup.py`.
Use the root `Makefile` PostgreSQL/Redis lanes and the real connection/barrier
patterns in `tests/workspaces/test_quota_concurrency_postgres.py` and
`tests/ctf/test_communication_delivery_postgres.py`; the existing delivery lease
tests do not prove admission/lifecycle/scheduler races. Exercise simultaneous
release/revision/cancel/remove/teardown/claim, stale-worker writes, crashes at
commit/claim/provider-result boundaries, audit failure rollback, conflicting
replay, due-time revocation/clock races, fair bounded load, and mixed channel
outcomes. Mock external transport boundaries, not first-party services (ADR-019).
Also exercise scheduled-declaration-to-release recovery, event-reschedule versus
independent/multi-event timing, generic run-now scope bypass, lost lifecycle
handoff through the real CMS bridge, and CMS expiry while the CTF scheduler is
down. A test of the handler alone misses executor status overwrite; the current
scheduler concurrency suite's sequential backdating does not prove simultaneous
claim/recovery. Corrupt or undecryptable recipient coordinates must fail only
their dependent commands, without poisoning a whole batch or the durable inbox.
Real ASGI/Redis reconnect tests must prove stable inbox identity and live denial;
negative tests must inspect envelopes, logs, rendered env/manifests, and argv for
leaks. Schema/OpenAPI/generated-client and migration checks accompany affected
contracts. `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
`AGENTS.md`, `.ground-control.yaml`, `.pre-commit-config.yaml`, and
`.github/quality-path-filters.yaml` remain the enforcement/workflow incumbents.

Retention reuses `purge_expired_communications` and its command, with bounded
batches, worker fences, and physical content/coordinate deletion. Its current
query omits soft-deleted campaigns and collects all eligible IDs; neither is a
sufficient production purge. Keep the dependency-aware deletion order and
protect event/user deletion paths affected by `PROTECT` foreign keys. Resolve
expiry and retained replay evidence together; do not extend content retention to
solve retries. Shared WebSocket TTL and body-free audit retention stay separate.

Non-goals: implementation in this preflight; a second outbox/scheduler/Celery/RQ
stack; a generic repository or per-channel exception hierarchy; portable RAES
schema/control reimplementation; new guest credentials or an ingress API in this
engine slice; marketing/contact management; attachments or new rich-content/UI
features; arbitrary webhooks; exactly-once email or recall after an effect.
Legacy `CTFNotification` and pending `SEND_NOTIFICATION` work cut over atomically
or remain explicitly outside the new delivery claim until their owner migrates
them. No dual sending, invented historical recipient success, or success from
dispatch alone. Shipping docs/traceability must describe the actual completed
slice; do not mark the umbrella capability complete from this preflight.

Legacy credential notifications must not put passwords, tokens, or volatile
`ParticipantPasswordIssuance` into retained message revisions. Reuse
`ctf.services.participant.credentials`, the tokenless login URL convention, and
`shared.credential_delivery` for their existing secret, rate, and audit concerns;
communication admission never rotates or reissues credentials on retry.

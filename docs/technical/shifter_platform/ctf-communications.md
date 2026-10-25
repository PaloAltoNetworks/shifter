# Communication API and receipt boundaries

The `/api/v1/ctf/communications/` controllers translate closed DRF inputs into
`CampaignDraft` and the existing communication services. PostgreSQL remains the
workflow authority; no second outbox, scheduler, or transport layer is added.
See the [API and cutover preflight](../../architecture/ctf-communication-api-cutover-preflight-2100.md)
and [operator guide](../../features/ctf-communications.md).

## Authorization and serialization

Bearer authentication precedes session authentication. `require_scope` publishes
and enforces the exact communication scopes. Token requests resolve the effective
actor through `active_actor_user`, never by assuming `request.user` is that actor.
Admission locks the live user and token and verifies the original user/token pair,
activity, expiry, profile eligibility, and exact scope. The workspace owning
service enforces its membership/archive mutex, and `resolve_event_authority`
enforces notification permission on every target. Event locks follow primary-key
order, ahead of campaign/revision mutations. Revise and cancel take an explicit
actor and reload the campaign under lock. Per-target strict audit records retain
the effective actor, token principal, operation, request correlation and authority source without message content.

Organizer collection queries filter complete-target authority before pagination,
have finite limits and preload target aggregates. Continuation describes only
authorized campaigns; the organizer page can load each subsequent page.
Authorization must cover the complete persisted target set; hiding a deleted
target must not turn a multi-event campaign into a smaller authorization scope.
Body, envelope, reference-list and page limits are independent. Domain validators
reject unhashable discriminators, invalid Unicode and invalid URL parser inputs
with bounded errors. API errors use authored messages through `shared.api.errors`.

## Inbox and socket policy

`ctf.services.communication.inbox` matches event, immutable participant public
identity and user together. A committed receipt and released intent prove in-app
availability. A GET never creates or changes a receipt. Read/ack actions lock and
recheck live participation, then set the first timestamp idempotently. The pinned
acknowledgement policy governs explicit acknowledgement. Retained inbox access
is distinct from permission to compete or temporary-account lifetime.

The exact `/ws/notifications/` path is admitted for an eligible temporary account
after password change, through the existing origin/session/account stack. The
consumer rechecks topic policy on each delivery and projects retained payloads
through the current registration. CTF wake-ups contain references only; legacy
bodies become a refresh hint. The communication Markdown profile on the canonical
renderer rejects media and non-allowlisted navigation at render time.

## Public contract and verification

`CommunicationSchema` builds closed object schemas from the actual serializers
and audience/trigger alternatives from the domain vocabulary. Regenerate with
`manage.py api_contract` and `npm --prefix frontend run gen:api`; generated
artifacts are never edited manually. Participant operations advertise only
session authentication.

Behavior coverage lives in `tests/ctf/test_communication_*`, token tests, and the
real ASGI notification tests. PostgreSQL admission tests cover concurrent release,
cancel, removal and scheduler fences. Redis tests exercise fan-out/replay and a
live temporary participant's body-free replay followed by authority revocation.
ADR, import-linter, Ruff, OpenAPI drift/compatibility and frontend checks remain
mandatory. Cutover tests cover historical aggregate preservation, invalid/ambiguous
rows, restart-safe ownership transfer, and database rejection of stale writers.


## Maintenance cutover

This is a maintenance deployment, not a rolling replacement. ADR-065 records the
maintainer-approved legacy write retirement and ADR-040 exception.

1. Disable incoming writes and stop **all** old web and scheduler instances.
   Drain and terminate their process-local email threads. Inspect old workers and
   reconcile every `SENDING` notification and every `RUNNING` task against
   available external evidence. Never guess that dispatch
   succeeded or reset ambiguous work to pending for a resend.
2. Apply migrations with the new code while application workers remain stopped.
   Once a cutover marker exists the fence migration cannot be reversed. It installs conditional PostgreSQL
   triggers; the maintenance command records the permanent activation marker.
3. Run `manage.py cutover_ctf_communications --legacy-producers-stopped --batch-size 100`.
   This assertion is an operator attestation, not automatic process discovery.
   The command checks database quiescence and serializes with in-flight legacy
   writes before committing the fence. It maps at most 100 rows per transaction;
   repeat until `mapped=0`. A failed batch rolls back its campaign mappings and
   task cancellations together. Previously committed batches remain resumable.
4. Invalid content, missing/deleted authority or scope, unsupported targeting,
   missing/duplicate task ownership and orphaned pending tasks block activation.
   Reconcile those declarations explicitly during maintenance. Do not edit a
   rejected row into apparent historical success, truncate its body, drop its
   task, or invent recipients. Failure output contains only bounded codes.
5. Run the same command with `--activate`. All legacy rows must have mappings
   and no pending/running `SEND_NOTIFICATION` task may remain. Historical rows
   keep their original count/status as aggregate evidence, without new recipients
   or receipts. Draft/scheduled announcements become campaigns with their original
   author, target and email channel. Old tasks are cancelled atomically with that
   mapping. Email-unavailable mappings have no runnable release/delivery work.
6. Start only the new workers and web code. Verify old writes return 410, exact
   communication scopes work, participant inbox reads stay parent-scoped, and the
   command's `email_ready` / `channel_unavailable` counts match the deployment.

The PostgreSQL fence rejects legacy row creation and all scheduler claims from
an old binary, including lifecycle and provisioning callbacks. New claims must
declare the ledger writer version in the claim transaction and cutover must be
activated; this declaration expires at transaction end. It cannot recall an already dispatched email; this is why the
process drain precedes fencing. Rollback must be forward recovery using the new
writer and retained fence. Do not reverse migrations, delete the marker, or
restart an old sender. A database restore requires another full maintenance
reconciliation before any workers are admitted.

When the email adapter is installed, recover one mapped schedule through
`resume_migrated_schedule(legacy_id)`. It uses the original campaign, actor, due
instant and stable `legacy:<id>` occurrence. Retries return the same declaration;
a past-due declaration obeys the existing lateness policy rather than silently
changing its due time. Ordinary migrated drafts remain deliberate authoring work.

Migrated campaigns follow the ledger's retention window. The purge transaction
also physically deletes their legacy source rows and mappings, erasing duplicate
content and preventing later cutover passes from importing it again.

Participant lifecycle notices use stable server-derived campaign identities and
remain visibly staged when email is unavailable. Organizer-only alerts have no
participant audience and remain unavailable rather than creating fake recipient
rows. Password issuance stays volatile in `participant.credentials`; non-secret
login notices never retain passwords, tokens or issuance objects. The deprecated
credential-resend helper fails at the retired dispatch boundary without changing
the participant's password.

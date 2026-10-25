# Legacy communication API migration decision

Status: accepted by the maintainer on 2026-09-19. Issue: #2100.
Decision: Option A, explicitly retire legacy notification writes under ADR-065.
The maintainer instructed: "Retire legacy notification writes and record the explicit ADR exception; use the new communication routes."

## Incompatible existing and required contracts

Legacy v1 notification writes accept broad event token scopes and report `sent`
after asynchronous dispatch. The scoped communication plan requires exact
communication scopes, reports ledger acceptance separately, and fences every
legacy producer. Keeping the existing write behavior would preserve the bypass;
silently changing its semantics would violate ADR-040's compatibility rule.
The additive communication endpoints pass the existing OpenAPI compatibility
check. That does not authorize changing the legacy endpoints.

The affected legacy write operations are:

- `POST /api/v1/ctf/events/<event_id>/notifications/`
- `POST /api/v1/ctf/notifications/<notification_id>/send/`
- `POST /api/v1/ctf/notifications/<notification_id>/cancel-schedule/`
- `POST /api/v1/ctf/events/<event_id>/invitations/send/`
- `POST /api/v1/ctf/participants/<participant_id>/resend-invite/`
- Their retained non-versioned JSON and HTML notification write entry points.

## Option A: explicitly retire the legacy notification write capability

Recommended for a single ledger and one authorization contract. Record a
separately accepted ADR retirement decision for this complete legacy write
capability, add the exact API retirement metadata, and update first-party callers
to the new communication endpoints or the existing volatile credential-issuance
owner as appropriate. Old write entry points fail closed with bounded migration
responses; none creates legacy send work. Historical notification reads remain
truthful aggregate evidence and never synthesize recipient success or receipts.

The explicit retirement approval is recorded above; ADR-065 and the dated
ADR-040-R3 exception record its scope.

## Option B: parallel API major and migration window

Preserve v1's published contract while introducing the changed operations under
a parallel major, with namespace/settings/schema metadata and a verifiable
migration note. Both majors must converge on the same fenced occurrence writer;
a compatibility route must never independently send or report acceptance as
successful delivery. Define the supported migration window and treatment of old
broad-scope tokens explicitly. This is a larger API/versioning change than the
additive v1 endpoints already implemented on the branch.

## Required under either choice

The data/writer cutover must quiesce old deployment instances and claimed legacy
work before activation. Convert bounded batches with stable legacy-row mapping,
validate scope/actor/content/due time/channels, and transfer pending task ownership
atomically. Ambiguous `RUNNING`/`SENDING` records block activation until reconciled.
Restart and rollback must never revive the old sender for migrated work.

Historical send counts remain labelled legacy aggregate evidence. Passwords,
tokens and credential-issuance objects are never copied into retained content.
Email transport remains #1525: unavailable migrated email work is explicitly
readiness-gated rather than silently changed to in-app or claimed deliverable.

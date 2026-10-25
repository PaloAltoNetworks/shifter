# ADR-065: Retire legacy CTF notification writes

Status: accepted, 2026-09-19. Decision owner: @Brad-Edwards. Issue: #2100.

The maintainer explicitly chose retirement of legacy notification writes and the
new scoped communication routes. This is the separately accepted ADR-040
exception for the complete legacy write capability. Historical reads remain
available. No compatibility write may keep broad event-scope dispatch or return
`sent` for ledger acceptance. Retired HTTP operations return a bounded 410;
their exact paths/methods are recorded in `openapi/v1.retirements.json`.

Cutover requires maintenance downtime. Stop and drain all old web, scheduler,
and asynchronous email processes before recording the fence. A database lock
cannot recall external mail or prove that an old process has exited. The
maintenance command refuses unresolved `SENDING` notifications and `RUNNING`
jobs. PostgreSQL triggers enforce the durable fence against old notification
inserts/updates and every scheduler claim. New claim transactions identify the
ledger writer version and require activated cutover; old binaries cannot claim
lifecycle or provisioning tasks that could invoke legacy notification callbacks.
The version is transaction-local and cannot authorize a later connection user. Never roll
back to an old sending binary or reverse the fence migration: restore or repair
forward with the same writer ownership.

Conversion uses bounded transactions and a stable old-row mapping. Invalid
content, missing authority/scope, ambiguous task ownership, unsupported targeting,
and orphaned work block activation with bounded diagnostics. Historical counters
stay on the legacy aggregate; no successful recipients or read/ack receipts are
inferred. Pending email declarations retain their channel and due time but no
runnable delivery work while #1525 is unavailable. Explicit dependency recovery
uses the same mapped campaign and occurrence key. No silent substitution of
in-app delivery is permitted.

Non-secret participant notices use the ledger. Password issuance remains
volatile at its existing credential owner. Organizer-only legacy email alerts
are unavailable until a supported recipient/transport contract exists; the
participant ledger must not gain invented organizer participants or disclose
organizer-only material to participants.

The API compatibility checker supports exact absent write-method retirements so
retaining GET on the same URL does not exempt it from compatibility checking.
Reintroducing any retired method fails the checker. All unrelated differences
remain subject to the pinned compatibility oracle.

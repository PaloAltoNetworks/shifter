# Scoped CTF communications

The communication API lets an organizer author a message for participants in one
or more events within one workspace. The actor must have live notification
permission on **every** target event and communication access to that workspace.
Workspace membership alone does not grant event authority.

## Author and release

Use `/api/v1/ctf/communications/` with an authenticated browser session or an API
token. Tokens need the exact `ctf:communication:read` or
`ctf:communication:write` scope for the requested operation; neither scope
implies the other. Existing event/play scopes do not grant communication access.

Create a campaign with `workspace_id` (the public workspace UUID), `title`,
`target_event_ids`, `audience_spec`, `trigger_spec`, `channels`, `subject`, and
`body`. `acknowledgement_policy` defaults to `none`; `read` and `explicit` are
also supported. The generated OpenAPI contract describes closed selector and
trigger variants. Unknown fields and duplicate JSON keys are rejected.

| Operation | Route relative to `/api/v1/ctf/` |
| --- | --- |
| Create a draft | `POST communications/` |
| List campaigns | `GET communications/?workspace_id=<uuid>&limit=25&offset=0` |
| Read summary | `GET communications/<campaign_id>/` |
| Append draft content revision | `POST communications/<campaign_id>/revisions/` |
| Release or schedule | `POST communications/<campaign_id>/release/` |
| Cancel unclaimed work | `POST communications/<campaign_id>/cancel/` |

Release requires an `occurrence_key`; reuse the same key when retrying the same
request. A future absolute-time trigger creates a scheduled declaration. The
scheduler rechecks the original actor and token before releasing it. Revoking a
token or changing its owner prevents subsequent admission, including replay.

HTTP 202 means the ledger accepted the declaration. It does not mean an email
was delivered, a socket received a message, or a participant read it. The in-app
channel is available. Email delivery is deferred to #1525; attempting to release
an email campaign returns dependency-unavailable rather than creating queued
work that cannot be delivered. Cancellation cannot recall an accepted message.

Collections default to 25 campaigns and are capped at 100 per request. Campaigns
are visible only when the actor may access every target. Visibility is applied
before pagination; `next_offset` advances through authorized campaigns only.
The organizer page can load subsequent pages to inspect or cancel older work.
Bodies are limited to 65,536 UTF-8 bytes, targets to 100, and explicit audience
lists to 5,000 references. Authoring and release share admission rate budgets.

## Participant inbox

The inbox is session-only and is scoped to the parent event:
`/api/v1/ctf/me/events/<event_id>/communications/`.
GET the collection or `<message_id>/` to view content without changing a receipt.
POST an empty object to `<message_id>/read/` or `<message_id>/acknowledge/` for a
deliberate action. Browser writes require CSRF. Repeating an action preserves its
first timestamp; acknowledgement requires the message's pinned `explicit` policy.

Banned or removed participants cannot fetch messages or change receipts. A
participant eligible to view an event may interact with their own receipts even
if disqualified from competition. Temporary accounts must satisfy their live
participation and password-change requirements. Email-only declarations do not
appear in the inbox.

WebSocket notifications are hints to fetch the durable inbox. Reconnect and
polling recover committed messages; socket writes never mark them read. Retained
legacy notification bodies are not replayed through the CTF notification socket.

## Legacy migration

Legacy notification create, send, schedule-cancel, bulk invitation and individual
login-information resend operations return HTTP 410. Use communication campaigns
for non-secret notices and the existing participant password operation for
explicit password issuance. Existing broad event tokens are not upgraded.

The organizer announcement dialog now writes to the participant inbox through
the communication API. Its retry preserves the campaign and occurrence identity.
Historical notification rows remain read-only; their dispatch counts are legacy
aggregate evidence, never delivery or read receipts.

Deployment uses the [maintenance cutover procedure](../technical/shifter_platform/ctf-communications.md#maintenance-cutover).
Migrated email work remains visibly unavailable until #1525's adapter is installed;
it is not silently changed to in-app. Organizer-only legacy email alerts are also
unavailable. This slice does not claim the broader communications capability or
email transport complete.

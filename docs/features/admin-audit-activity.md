# Audit and activity history

The audit and activity history surface lets an administrator answer who changed
what and when across a shared deployment. It lives under **Administer → Audit**
in the platform navigation and is a read-only view over the platform's immutable
audit record.

## Access

- The surface is visible only to staff accounts and only when the
  `administer_spa` rollout flag is on. When the flag is off, the page and its
  navigation entry are hidden and the route is not served.
- Access requires a staff session. Workspace or organization roles, model
  permissions, and API tokens do not grant access to the audit history, and the
  server rechecks the staff session on every request.
- The audit history is deployment-wide. It is not scoped to a workspace, so the
  workspace switcher in the organization console does not change what the audit
  history shows.

## What it shows

Each row is one recorded event and carries its time, action, the entity the
event was recorded against, and the actor that triggered it. The history covers
the significant administrative events other parts of the platform record,
including authentication, membership and role changes, invitations,
user-lifecycle changes, and policy changes. Events appear here as the owning
features record them, so an event type shows up once that feature starts
recording it.

## Filtering

The structured filters are the way to search the history:

- **Event type (action)** and **entity type** match the recorded values.
- **Entity id** and **actor id** match the numeric identifiers on the event.
- **Actor type** matches the kind of actor, such as a user or the system.
- **From** and **To** bound the time range. The start must not be later than the
  end.

Filters are held in the page address, so a filtered view can be bookmarked or
shared as a link and reopens with the same filters. Invalid input, such as an
inverted time range, is reported so it can be corrected.

## Event details

Each row can expand to show the additional evidence recorded with the event,
such as the request identifier, source address, and the before and after state.
This detail is sensitive and is shown only when the row is expanded.

## Related administration

The audit record is also available through the Django admin escape hatch under
**Administer**, which stays available for the deeper or rarely used inspection
the console does not duplicate.

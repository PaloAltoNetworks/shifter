# Audit system architecture

Shifter records security-relevant platform events in a durable, append-only
audit log owned by the `shared` Django app. Audit logging is a cross-cutting
platform capability; it is not coupled to a product feature.

## Ownership

| Concern | Owner |
| --- | --- |
| Event vocabulary and emission policy | `shared.audit` |
| Durable row model | `shared.models.AuditLog` |
| Django persistence writer | `shared.audit_adapter` |
| Archive command | `shared.management.commands.audit_archive` |
| Operator read access | Django admin and `shared.api.audit` |
| Process health state | `shared.audit.health` |

Emitters construct an `AuditEvent` through the helpers exported by
`shared.audit`. The writer bound during Django startup persists the event to
`shared_auditlog`. Best-effort events record a bounded degraded-health signal
when persistence fails; controls explicitly marked strict propagate the
failure.

## Read boundary

Audit rows contain operational and security evidence. The DRF endpoint is
therefore deliberately narrow:

- `/api/v1/audit/` supports list and retrieve only.
- Authentication is a Django browser session.
- The authenticated user must be staff or a superuser.
- API tokens are not accepted and there is no audit-read token scope.
- Denied reads emit an `access_denied` audit event.

Django admin exposes the same rows as read-only records. Neither interface
offers update or delete operations.

The API accepts filters for `entity_type`, `entity_id`, `action`, `actor_type`,
`actor_id`, `request_id`, `from_date`, and `to_date`. Action and entity values
are serialized as strings so rows written with historical vocabulary remain
readable after the active vocabulary changes.

## Retention

The `audit_archive` management command compresses old rows as JSONL, uploads
them to the configured logs bucket, and deletes only rows from a successfully
uploaded batch. Operators choose the retention cutoff and may use dry-run or
no-delete modes.

## Schema migration

The audit store moved to `shared` when the former feature that originally
hosted it was removed. Migration `shared.0006_rehome_audit_log` handles both
supported database states:

- An upgraded installation has its existing audit table renamed in place, so
  row identity, timestamps, and evidence remain intact.
- A clean installation creates `shared_auditlog` directly.

The migration removes the retired feature's non-audit tables. It does not
create compatibility views, model aliases, routes, permissions, scopes, or
settings.

## Adding an event

Use the nearest helper in `shared.audit` and the existing entity/action
vocabulary. Add a new vocabulary value only when no current value accurately
describes the event, and include persistence and authorization tests. Do not
write `AuditLog` directly from feature code.

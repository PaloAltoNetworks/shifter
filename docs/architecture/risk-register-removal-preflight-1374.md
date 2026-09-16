# Feature removal and audit rehome — issue 1374

## Decision

The Risk Register is removed from Shifter. Its models, routes, templates,
frontend workspace, navigation, API-token scopes, permissions, settings, MCP
tools, documentation, and tests are deleted rather than hidden behind a flag.
There is no compatibility façade.

Audit logging survives because other platform areas already use it as durable
operational evidence. The audit model, writer, archive command, read-only
admin, health state, and read API are owned by `shared`.

## Database transition

`shared.0006_rehome_audit_log` is the single transition:

- On upgrade, rename the existing audit table to `shared_auditlog` and retain
  every row.
- On a clean install, create `shared_auditlog`.
- Drop the removed feature's risk, comment, and API-key tables.
- Remove its old index names after the audit table is adopted.

The reverse migration restores the legacy audit table name so migration
rollback does not destroy audit evidence. Removed product data is intentionally
not recreated.

## Access

Audit rows remain read-only. Django admin and `/api/v1/audit/` require a staff
or superuser Django session. Bearer tokens are rejected; there is no audit
token scope. Denied reads are themselves audited.

## Deliberate break

All former product URLs and API operations return 404. Tokens whose only scope
was a removed scope authenticate as unusable. Historical audit action and
entity strings remain serializable, but they do not restore any feature
surface.

## ADR reconciliation

- ADR-013 no longer lists the removed surface in platform navigation.
- ADR-023 is retired with the product because its internal finding store,
  scopes, and workflow no longer exist.
- ADR-029 retains the SPA architecture but no longer prescribes the deleted
  workspace or its rollout order.
- ADR-045 records this removal and the narrow audit ownership that remains.

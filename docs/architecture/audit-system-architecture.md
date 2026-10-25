# Audit system architecture

Shifter records security-relevant platform events in a durable, append-only
audit log owned by the `shared` Django app. Every row belongs to a versioned
SHA-256 chain serialized by a database-owned head, so offline verification
detects changed, deleted, inserted, reordered, or cross-deployment evidence.
PostgreSQL triggers reject committed-row mutation and constrain each head
advance to the matching appended record. Audit logging is a cross-cutting
platform capability; it is not coupled to a product feature.

This hot-ledger guarantee does not by itself provide externally anchored
immutable compliance evidence. The legacy S3 export is deterministic and
create-only, but its destination is not yet a provider-enforced write-once
checkpoint. The command therefore retains every database row. The full trust
boundary and future evidence-store seam are documented in
[`audit-tamper-detection-preflight-327.md`](audit-tamper-detection-preflight-327.md).

## Ownership

| Concern | Owner |
| --- | --- |
| Event vocabulary and emission policy | `shared.audit` |
| Durable row model | `shared.models.AuditLog` |
| Chain serialization state | `shared.models.AuditChainHead` |
| Canonical bytes and verification | `shared.audit.integrity` |
| Django persistence writer | `shared.audit_adapter` |
| Verification command | `shared.management.commands.audit_verify` |
| Export command | `shared.management.commands.audit_archive` |
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
`actor_id`, `actor_principal_uuid`, `request_id`, `from_date`, and `to_date`. Action and entity values
are serialized as strings so rows written with historical vocabulary remain
readable after the active vocabulary changes.

## Integrity chain

The bound writer validates each `AuditEvent`, locks the singleton chain head in
the same database transaction, and assigns the next sequence. Canonical JSON
version 1 covers the stable event id, deployment scope, chain generation,
sequence, recorded time, predecessor digest, target and actor attribution,
request correlation, state summaries, context, source IP, and user agent. JSON
object keys are sorted, timestamps are UTC with microsecond precision, NaN and
non-JSON values are rejected, and the encoded bytes are hashed with SHA-256.

Version 2 adds `actor_principal_uuid` to the hashed payload. Neutral credential
mutations use `actor_type=principal`, a nonzero principal UUID and no integer
actor ID. HTTP user/API-key attribution keeps its incumbent type and integer ID
and supplements it with the authenticated principal UUID. System events cannot
carry a principal UUID. This indexed field is validated by the writer, exported
with each record, and available through the staff API and audit UI; it is never
inferred from client-provided actor fields or buried in state summaries.

The verifier supports historical v1 followed by v2 in the same chain, refuses
version regression or unknown versions, and preserves the exact v1 byte profile.

The event validator accepts only active vocabulary for new writes, bounded
single-line context/reference fields, non-negative identifiers, recursively
bounded JSON state, and no direct secret-bearing fields. Historical rows keep
their original vocabulary. UUID and other opaque target identities use
`entity_ref`; the integer `entity_id` remains for v1 compatibility.

`AUDIT_DEPLOYMENT_SCOPE` binds the chain to the installed control plane rather
than to a pod, VM, database, or client value. AWS EKS renders
`aws:<account>:<region>:<profile>`, the legacy AWS portal renders
`aws:<account>:<region>:<environment>`, and GCP renders
`gcp:<project-id>`. Deployed configurations that expose cloud secret references
fail closed if they would use the local-development sentinel. Existing GCP and
warm-pool deployment identities remain compatible inputs for installations
that have not yet adopted the explicit setting.

Run the complete hot-ledger verifier with:

```bash
python manage.py audit_verify
```

It checks every sequence and predecessor, recomputes every digest, checks the
deployment/generation/version binding, and compares the terminal record with
the chain head. Any mismatch exits non-zero. Verification never repairs rows,
recalculates stored digests, or starts another genesis.

PostgreSQL supplies the production concurrency and append-only guarantees.
`portal_runtime` can read and insert audit rows and can advance the chain head;
it cannot update or delete committed evidence, insert/delete a head, or advance
the head by anything other than one matching record. AWS already separates its
runtime and migration database principals. GCP now creates `portal_runtime`
separately from the schema owner and runs migrations as a one-off hardened Job
through the dedicated `migrator` workload identity. Long-lived portal and worker
pods receive only the runtime database secret and set `SKIP_MIGRATIONS=1`; the
migrator alone receives the schema-owner secret.

The migration/schema owner remains privileged break-glass authority, so
independent write-once checkpoint storage is still needed to detect an owner
who disables database enforcement. Tests exercise the effective
`portal_runtime` role against real PostgreSQL and prove that it cannot disable
the append-only trigger or rewrite committed evidence.

## Export and retention

The `audit_archive` management command renders old rows as deterministic
canonical JSONL, applies gzip with fixed metadata, uploads with a SHA-256
checksum and create-only precondition, and uses a key bound to the sequence
range and terminal chain digest. Operators choose the export cutoff and may use
dry-run mode. The legacy `--no-delete` flag remains accepted as a compatibility
no-op.

This remains an AWS-only export utility, not a write-once compliance store. The
current central logs bucket is overwrite/delete capable under its retention
model, so the command never deletes hot rows. Do not treat successful export as
an immutable checkpoint or tamper-verification result.

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

Migration `shared.0020_audit_integrity_chain` backfills stable event ids and one
contiguous chain in `(timestamp, id)` order, records the deployment-bound head,
installs the PostgreSQL mutation guards, and narrows `portal_runtime` effective
privileges. It resolves the audit table's owned identity sequence instead of
assuming a sequence name, preserving upgrades whose table was renamed from the
retired app. It fails the migration rather than omitting an uncanonicalizable
legacy row.

Migration `shared.0029_principal_audit_attribution` adds the nullable, indexed
actor UUID and advances only the head's future append profile to v2. It never
rewrites historical rows or digests. The migration owner briefly changes the head
under its exclusive lock inside the atomic migration and reinstates the same
guard before commit; runtime privileges are unchanged. Downgrade refuses once
any v2 record exists because dropping the UUID would destroy committed evidence.
The corresponding workspace journal migration also refuses downgrade after
principal attribution has been recorded in an authorization operation.
This source ships under ADR-066's coordinated S8 cutover: old writers reject a
v2 head, so a mixed-writer rolling deployment is not supported.

## Adding an event

Use the nearest helper in `shared.audit` and the existing entity/action
vocabulary. Add a new vocabulary value only when no current value accurately
describes the event, set `entity_ref` for UUID/opaque targets, and include
persistence and authorization tests. Do not write `AuditLog` directly from
feature code.

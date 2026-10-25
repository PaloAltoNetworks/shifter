# Audit tamper detection preflight (#327)

Status: accepted implementation guidance; hot-ledger integrity implemented

Date: 2026-09-16

Issue: GitHub #327, "Audit logging"

This issue is requirement-free. The GitHub issue is the shipping contract. This
note sets architecture boundaries for immutable compliance evidence; it is not
an implementation plan.

The implemented phase adds the deployment-bound hash chain, database mutation
guards, offline verifier, deterministic create-only export, opaque target
references, and separate GCP runtime/migration database identities. The
provider-native write-once evidence store described below remains a future
extension; until it exists, export never deletes hot rows and is not an
immutable checkpoint.

## Current state and gap

The repository already has one cross-cutting audit subsystem:

- `shared.audit` owns the event, vocabulary, attribution, write policy, writer
  port, and degraded-health state.
- `shared.models.AuditLog` and `shared.audit_adapter` own the hot durable rows.
- `shared.api.audit` and `shared.admin.AuditLogAdmin` are read-only operator
  surfaces.
- `shared.management.commands.audit_archive` exports old rows.
- Authentication, account administration, workspaces, CTF, CMS, Engine, API
  tokens, sessions, and provisioning result application already emit many of
  the required user, resource, and provisioning events.

That is application-level auditability, not yet immutable compliance evidence.
The API and admin prevent edits, but the runtime database role currently has
schema-wide `UPDATE`/`DELETE`; ORM `QuerySet.update()` bypasses model methods;
and no database guard or integrity chain detects row updates, deletion, gaps,
or reordering. The archive command is AWS-specific, reads undeclared environment
aliases directly, uses overwrite-capable keys, and deletes rows after an S3 PUT
without a write-once retention or end-to-end integrity receipt. The AWS
log-aggregation bucket is intentionally ephemeral and non-versioned. The GCP
`audit-logs` bucket is a 30-day Cloud Storage access-log sink, not the
application audit archive. Neither is the compliance root #327 needs.

`shared.audit.health` detects write failures observed by one process. It does
not prove chain integrity, export freshness, object retention, or archive
readability.

## Architecture decisions

### One audit ledger, with distinct operational records

`shared.audit` remains the only application audit contract and
`shared.models.AuditLog` remains the only hot audit ledger. Do not add an
`ActivityLog` replacement, per-domain audit tables, a second action vocabulary,
or an event-sourced copy of domain state. `management.ActivityLog` remains a
deprecated historical compatibility surface and receives no new callers.

`RangeEventOutbox`, `ProvisionerLaunchIntent`, `OperationResultInbox`, RAES
operation/participant records, queue messages, provider logs, and structured
application logs retain their current operational meanings. They may supply a
trusted correlation or lifecycle fact to an audit emitter, but none is a
fallback audit ledger or a substitute for immutable evidence.

### Integrity model

Treat the PostgreSQL table as the transactional hot ledger and a dedicated
provider-native write-once object store as the retained compliance evidence.
Do not call evidence immutable until a chain checkpoint has been committed to
that store. Publish and monitor a bounded maximum checkpoint age so an attacker
cannot remove an unanchored tail without a freshness failure becoming visible.

Every new row belongs to one versioned chain generation and carries a monotonic
sequence, stable event id, server-owned deployment scope, explicit recorded
time, previous-record digest, canonicalization version, and record digest. The
digest covers every evidentiary field, including actor/target attribution,
request correlation, state summaries, sequence, deployment scope, and previous
digest. A deterministic migration backfills existing rows in `(timestamp, id)`
order and records the legacy-to-chained boundary; it must not silently omit an
unserializable historical row or start an unexplained second genesis.

The canonical byte profile belongs in `shared.audit` and is versioned. It must
use fixed field names, UTC timestamp normalization, sorted JSON object keys,
compact separators, UTF-8, and rejection of NaN/non-JSON values. Do not reuse
`shared.model_access.digest`: that profile deliberately removes fields named
`digest` and `definition_digest`, which is wrong for generic audit state. Do not
reuse RAES record validation as the audit schema either. A neutral secret-value
scanner may be extracted and shared if that avoids duplicate detection logic.

Concurrent writers serialize only on a shared-owned chain-head row inside the
same database transaction as the `AuditLog` insert. A process-local lock,
`MAX(id)`, timestamp ordering, or insert-then-update digest cannot provide a
correct chain across web and worker processes. Strict audit calls remain atomic
with the domain mutation they protect.

### Database append-only enforcement

The application API remains read-only, and PostgreSQL must enforce the same
boundary. The ordinary runtime role gets `SELECT` and the narrow insert/sequence
authority needed by the shared writer, but no direct `UPDATE` or `DELETE` on
audit evidence or chain state. A database trigger/backstop rejects mutation of
committed evidence. Retention deletion, if enabled, goes through a narrow
archive-owned database operation that can delete only a verified contiguous
prefix whose immutable evidence checkpoint is durable and whose online
retention has elapsed.

The migration/schema owner remains a privileged break-glass principal. Database
permissions cannot make evidence safe from that owner, a cloud-account root, or
a destroyed encryption key; the external write-once chain checkpoint is what
makes privileged database tampering detectable. AWS and GCP runtime database
postures must provide equivalent effective restrictions. Do not claim this from
an ORM `save()` override or Django admin permissions.

### Event shape and validation

Keep `AuditEvent` as the emitter contract and add one shared validation gate
before persistence and hashing. New events must use the active action/entity/
actor vocabulary, a non-negative identity, a bounded stable entity reference,
bounded single-line context and request references, and bounded recursively
JSON-safe state. Historical rows remain readable even when their vocabulary is
retired.

The current integer `entity_id` cannot faithfully identify UUID-backed
resources; truncating or hashing a UUID into an integer can collide. Preserve
the published integer field for compatibility and add a bounded string
`entity_ref` for canonical UUID or other opaque identities. Do not change the
v1 field type or invent per-domain target columns.

The validator is also the single secret-minimization boundary. It must reject
tokens, cookies, passwords, private keys, signed URLs, credentials, raw
headers, provider payloads, scripts/transcripts, and unbounded exception text.
Source IP, user agent, verified identity references, and selected PII are
sensitive evidence, not secrets; retain them only when the event requires them
and never duplicate them into logs, metrics, URLs, argv, or environment values.
Because write-once retention conflicts with later deletion, emit stable internal
ids and bounded reason/outcome codes instead of names, email addresses, or full
object snapshots whenever those values are not essential evidence.

### What must be audited

"All user actions" means security-relevant and state-changing commands, not
every HTTP GET, mouse gesture, health probe, websocket frame, or successful
audit-feed read.

- Authentication/session decisions, denied privileged access, API-token
  lifecycle, downloads/delivery of sensitive material, and administrator
  authority changes emit at their existing auth or delivery boundary.
- Database-only resource mutations emit once from the owning service in the
  same transaction. Privileged, destructive, policy, ownership, and authority
  changes are strict and roll back if the audit insert fails.
- Non-rollbackable provisioning and external side effects strictly record a
  bounded intent before the first external mutation and record a correlated
  terminal outcome from the authoritative result/applier boundary. Do not hold
  a database transaction across a cloud call.
- Retries audit committed transitions, not attempts that changed no state.
  `request_id` remains correlation, not a generic idempotency key.

Coverage is owned by the service/controller that authorizes and commits the
operation. Do not use blanket request middleware, Django model signals, database
change capture, or parsing of log prose: those paths lack authoritative actor,
outcome, transaction, and secret-redaction semantics and commonly double-count
events.

### Immutable evidence store

Create a dedicated per-deployment audit-evidence bucket; do not reuse the AWS
log-aggregation bucket, the ALB-log bucket, the GCP access-log sink, the assets
bucket, release evidence, Terraform state, or a user-upload bucket.

- AWS uses a versioned bucket with S3 Object Lock in compliance mode, an
  explicit default retention, encryption using the repository's CMK patterns,
  public-access blocking, `force_destroy`-equivalent protection, and a bucket
  policy that allows the exporter to create only its audit prefix. The exporter
  receives no delete, overwrite, retention-bypass, or bucket-policy authority.
- GCP uses uniform bucket-level access, public-access prevention, a locked
  retention policy, non-destructive lifecycle, encryption/key lifecycle aligned
  with retention, and an exporter identity limited to object creation. It is
  separate from `google_storage_bucket.audit_logs`, whose current purpose and
  30-day lifecycle are unrelated.
- A read-only verifier identity is distinct from the create-only exporter where
  the runtime supports process-specific workload identity. Deploy/destroy and
  key administration remain separately reviewable privileged operations.

Retention locking is irreversible and provider behavior is not interchangeable.
The retention duration is an explicit environment/root input with validation
and reviewed plan/readback evidence; application defaults must not silently set
an organization's legal retention policy.

Evidence batches use deterministic canonical JSONL and deterministic compression
(including fixed gzip metadata). Their create-only key contains the deployment
scope, schema/canonicalization version, first and last sequence, and terminal
chain digest. The body/manifest carries record count, predecessor checkpoint,
terminal digest, and a content checksum. A retry either observes exactly the
same immutable object identity/checksum and succeeds idempotently or fails
closed; it never overwrites, chooses a new key for different bytes, or treats an
ambiguous provider response as success.

The generic `ObjectStorage.upload_file()` contract is insufficient because it
allows overwrite and returns no immutable identity or retention receipt. Add a
narrow audit-evidence write-once port, but select its AWS/GCP adapter through
the existing validated `CLOUD_PROVIDER` / installation registry and reuse the
existing provider SDK, exception, owner/project binding, and log-sanitization
patterns. Do not add a third provider selector or leave `boto3` branching in the
management command. A backend must not advertise immutable-audit capability
merely because it supports ordinary object storage.

### Export, verification, and health

Use the existing dedicated-worker/deployment conventions for one exporter. Its
mutable checkpoint/lease is operational coordination, not audit evidence, and
must live outside the hashed rows. It writes and obtains a provider receipt
before advancing the checkpoint. Hot-row deletion is a later operation and
never occurs after an unknown, partial, mismatched, or unlocked upload.

Verification checks database sequence/digest continuity, archive batch
continuity, deterministic content checksums, immutable object identity,
retention posture, deployment scope, and checkpoint freshness. Verification
failure never auto-repairs, rehashes, deletes, or starts a fresh chain. It stops
archive deletion, exits non-zero for operator/drill use, and emits a bounded
metric/alert and sanitized log. Provider access/audit logs are corroborating
evidence, not the sole alert or ledger.

Reuse `shared.audit.health` and `config.health_checks` for audit-subsystem
signals, but keep writer degradation, export lag, and verified tamper distinct
internally. Public `/health` stays coarse and never reveals bucket names,
digests, row contents, provider errors, or database details. A full verifier is
not run on every API read or health request.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Audit contract and policy | `shared.audit.{events,vocabulary,attribution,policy,port}` | Extend once; preserve strict versus explicitly degraded behavior. No per-domain writer or vocabulary. |
| Persistence adapter | `shared.models.AuditLog`, `shared.audit_adapter`, `config.apps.PortalConfig.ready` | Chain and persist behind the existing bound writer. No ORM writes from feature code. |
| Actor/request attribution | `get_actor_from_request`, `get_client_ip`, `get_request_id`, `RequestIDMiddleware` | Preserve trusted-hop and bearer/session attribution; do not parse headers again. |
| Auth/read authority | `ApiTokenAuthentication`, `SessionAuthentication`, `IsStaffSession`, `shared.api.audit` | Keep list/retrieve staff-session only, bearer-first fail-closed, and denied-read auditing. |
| Domain mutation ownership | Public `*.services` facades, Engine operation-result applier, CTF audit helpers | Emit where authority and committed outcome are known; no middleware/signals/DB CDC. |
| Workflow truth | ADR-025 outboxes, `ProvisionerLaunchIntent`, `OperationResultInbox`, RAES records | Correlate to them; never copy their schemas or use audit as queue/replay state. |
| Cloud selection and SDK boundaries | `config._cloud`, `installation.registry`, `shared.cloud`, `shared.cloud.{aws,gcp}` | One validated provider choice and provider-neutral evidence receipt/error contract. |
| Deployment identity | `shared.deployment.resolve_deployment_scope` | Bind chains and object keys to stable resource ownership, not hostname, workspace, or a client value. Deployed evidence must not use the local fallback. |
| Settings/env shape | Split settings modules, `_env_*` validation, `config._env_manifest`, Helm values schema, GCP runtime renderer | Non-secret bounded knobs only; bucket/key credentials stay in workload identity. |
| Workload identity | EKS workload identity map/IRSA, GKE service accounts and Workload Identity, legacy EC2 instance-role boundary | Prefer a dedicated exporter identity; grant create-only evidence access, never broad storage admin. |
| Infrastructure hardening | Existing S3/GCS PAP/UBLA/encryption/retention patterns and Terraform environment roots | Dedicated WORM evidence resources; do not weaken the current log/archive exceptions to reuse a bucket. |
| Errors/logs/health | `shared.api.errors`, `shared.errors`, `shared.cloud.exceptions`, `shared.log_sanitize`, ECS logging, coarse health | Fixed client/command messages and bounded telemetry; no raw provider/DB/payload details. |
| API publication | `shared.api.audit`, `openapi/v1.json`, generated frontend schema/types, ADR-040 gates | Any exposed fields are additive/read-only; historical vocabulary stays string-readable. |
| Tests/enforcement | `test-platform-postgres`, existing audit tests, Terraform/Helm/Kubernetes tests, `.importlinter`, ADR guard | Real PostgreSQL concurrency/privilege/tamper tests and provider retention/IAM assertions; mock-only storage tests are insufficient. |

## Cross-cutting layers the design must pass

1. **Authentication and authorization.** Existing OIDC/Identity Platform and
   API-token validation still establish the actor. Audit reads remain
   staff/superuser session-only via the bearer-first chain and `IsStaffSession`;
   the verifier/exporter exposes no new HTTP credential or public endpoint.
2. **Request attribution and event validation.** Every request-bound write uses
   the canonical actor, trusted source-IP, user-agent cap, and request-id
   helpers, then the single audit shape/secret/size validator. Client bodies and
   headers cannot choose actor, timestamp, sequence, digest, deployment scope,
   or evidence key.
3. **Database and transaction boundary.** The bound writer allocates chain
   sequence/digest under PostgreSQL locking in the caller's transaction.
   Runtime effective privileges and a trigger permit append/read, not arbitrary
   mutation. PostgreSQL-specific guarantees have a real-PostgreSQL CI lane;
   SQLite success is not evidence.
4. **Archive/storage boundary.** The exporter uses the validated provider
   adapter, deterministic bytes, create-only preconditions, checksum/identity
   receipts, and provider retention readback. S3 Object Lock/GCS retention and
   IAM are the enforcement, not an object naming convention or application
   boolean.
5. **Secret and privacy boundary.** Workload identity supplies credentials;
   no static cloud credential, audit body, raw error, token, signed URL, DB
   password, KMS material, or provider response enters environment dumps,
   ConfigMaps, argv, logs, metrics, API errors, or archive keys. Evidence keeps
   only necessary bounded PII.
6. **Configuration shape.** Bucket name, batch/lease bounds, online retention,
   and checkpoint freshness are typed settings rendered through existing
   deployment surfaces and committed in `env-manifest.json`. Legal/WORM
   retention is Terraform-owned, explicitly validated, and read back; command-
   local `os.environ` fallbacks are not authoritative.
7. **OS/container exposure.** Export runs as the existing hardened non-root,
   read-only-root-filesystem worker pattern with provider workload identity.
   Payload bytes stream through the SDK; they are not shell arguments or
   world-readable local files. Any unavoidable temporary file is bounded,
   mode-restricted, and removed on every outcome.
8. **Errors, health, and observability.** HTTP continues using the shared error
   envelope and request id. Management/worker failures use fixed categories,
   non-zero status, sanitized logs, and low-cardinality metrics. Tamper findings
   are never written only into the ledger suspected of tampering.
9. **Workflow and architecture gates.** Shared remains the owner, config remains
   the composition root, and provider code stays behind shared cloud seams.
   Changes pass import/layer guards, ADR guard, real-PostgreSQL tests, Terraform
   validation/TFLint/Checkov, Helm tests, kube-linter/kubeconform, actionlint if
   workflows change, and live provider retention/IAM readback before an
   immutability claim is made.

## Extensibility seam

The durable seam is a versioned `AuditEvidenceStore` operation parameterized by
deployment scope, canonicalization version, contiguous sequence range, terminal
chain digest, checksum, and retention class, returning a provider-neutral
immutable identity/retention receipt. AWS and GCP implement that semantic
contract; ordinary `ObjectStorage` remains unchanged for mutable assets.

The next provider or a new retention class should add an adapter and
conformance evidence, not change emitters, the `AuditEvent` shape, hash profile,
archive command, or every Terraform call site. Batch size, online-retention
window, checkpoint cadence/max age, and immutable retention are distinct
parameters: changing one must not silently change the others.

## Whole-repository scope for the implementation

Expected ownership surfaces include:

- `shifter/shifter_platform/shared/audit/`, `shared/models.py`,
  `shared/audit_adapter.py`, shared migrations, admin/read API, archive command,
  and shared audit tests;
- `config` audit settings/env manifest, startup binding, health/metrics, and
  provider composition; `installation` capability declarations if immutable
  evidence becomes an advertised backend capability;
- domain service boundaries only where a material operation has no canonical
  audit emission or uses a lossy UUID-to-integer target;
- AWS Terraform environment roots, EKS workload identities, legacy portal role
  policy, and a dedicated evidence-bucket owner; GCP platform-core portal
  storage/IAM and environment roots;
- Helm values/schema, service accounts, hardened worker deployment, GCP base
  manifests/overlays and runtime-env rendering, plus legacy AWS container env
  rendering while that deployment remains supported;
- operator documentation, disaster-recovery/teardown behavior, ADR-045 evidence
  and rules when enforcement lands, and focused repository guards if retention
  or IAM invariants cannot be proven by native tests alone.

The current `platform/terraform/modules/log-aggregation`, GCP access-log bucket,
RAES schemas, message/outbox schemas, public auth contract, and SPA need no
semantic redesign to implement #327.

## Gotchas and anti-patterns

- A plain per-row hash, HMAC whose key is available to the same compromised
  process, database trigger, backup, versioning, encryption, or read-only UI is
  not by itself tamper-evident immutable evidence.
- Do not call the existing AWS/GCP log buckets immutable or broaden their
  exceptions to fit this use case.
- Do not use `AuditLog.id`, wall-clock timestamps, or a process-local counter as
  the chain sequence; do not compute the digest in a second update.
- Do not use `json.dumps(..., default=str)`, nondeterministic gzip metadata, or
  mutable key names. Canonicalization changes require a new explicit version.
- Do not truncate/hash UUIDs into `entity_id`, parse identity from `context`, or
  require referenced domain rows to survive for the evidence to remain useful.
- Do not archive the same rows concurrently without a database lease/checkpoint;
  never delete hot rows on timeout, partial response, checksum mismatch,
  precondition failure, or unverifiable retention.
- Do not auto-repair a gap, recalculate hashes after detection, edit an archived
  object, or hide a fork by starting a new genesis.
- Do not make audit the workflow queue, retry ledger, current-resource state,
  analytics warehouse, SIEM transport, or provider event store.
- Do not log/audit exporter payloads or provider exception bodies. Audit-system
  failure telemetry must be value-free and independently observable.
- Do not run a full-chain/provider verification in request paths or public
  health probes.
- Locked retention and Object Lock are difficult or impossible to undo. Review
  duration, destroy behavior, key lifecycle, cost, and legal ownership before
  applying, and prove the installed posture rather than trusting Terraform
  source alone.
- Do not weaken runtime DB isolation on GCP because the current single SQL user
  is convenient, or weaken AWS's separate migration/runtime principal. Provider
  parity is an effective-permission property.

## Non-goals and implementation boundaries

- No new public mutation API, audit-read token scope, public verifier endpoint,
  workspace-scoped audit feed, or successful audit-read logging.
- No migration/backfill of deprecated `ActivityLog` or reconstruction of events
  that were never recorded historically.
- No capture of every read, keystroke, terminal byte, queue retry, health probe,
  or unchanged/idempotent request.
- No replacement of domain outboxes, RAES records, provider audit logs,
  PostgreSQL backups, or structured application logs.
- No SIEM/XDR exporter, archive browser/search, legal-hold UI, external timestamp
  authority, or cross-account/cross-project evidence escrow in this issue.
- No universal legal retention duration is selected here. Each deployment must
  supply an accepted retention policy before locking its evidence bucket.
- No claim of protection against an actor that controls the database owner,
  evidence-store administrator, encryption-key administrator, verifier, and
  cloud account/project simultaneously. The design provides least privilege,
  append-only enforcement, durable external anchoring, and detectable tampering
  within the documented trust boundary; stronger independent custody is a
  separate compliance decision.

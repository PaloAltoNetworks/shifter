# ACES Snapshot Retention, Redaction, And Audit Preflight

Issue: GitHub #1277, "18 - ACES migration: implement snapshot retention,
redaction, and audit rules."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, APIs, cleanup jobs, deployment wiring, or tests, and it is
not an implementation plan. This is a requirement-free run; the GitHub issue is
the shipping contract.

## Boundary

The controlling decisions remain ADR-024, ADR-025, ADR-027, and the parent
#1234 operation persistence/projection design. #1277 is the policy hardening
slice for ACES runtime snapshots and adjacent operation-record visibility:

- runtime snapshots are operational observation records, not archival
  experiment records;
- retention and cleanup must be explicit, bounded, settings-backed, and
  operator-visible;
- redaction must happen before persistence and again at response/log/audit
  boundaries where a narrower public view is required;
- Shifter lifecycle audit remains in `risk_register.AuditLog`; ACES receipts
  and snapshots may be evidence references, but are not audit rows.

## Architecture Decisions

- Keep using the first-class ACES sidecar. Snapshot rows are
  `shared.models.AcesOperationRecord` records with
  `record_kind=runtime_snapshot`, keyed by `request_id`, contract profile,
  contract version, source timestamp, payload digest, and idempotency key.
  Do not create a second snapshot table, stash snapshots in range JSON fields,
  or put snapshot bodies in events, audit JSON, logs, or API passthroughs.
- Enforce redaction at the write boundary. The canonical gate is
  `shared.schemas.aces_operation.validate_aces_operation_record`, including
  record-kind payload allowlists, diagnostic reference allowlists,
  single-line/size limits, forbidden secret-bearing keys, and high-confidence
  secret value rejection. API serializers and log helpers are defense-in-depth,
  not the primary control.
- Keep API response redaction in `shared.aces.projections`. Product APIs
  receive serializer-ready projections from `list_operation_records`; they must
  not import `AcesOperationRecord` directly or serialize raw `payload`.
- Model retention as an explicit policy on the sidecar surface: latest
  projection, optional short operational history, cleanup cadence, and cleanup
  batch size are separate parameters. `retention_expires_at` is the indexed row
  deletion boundary; newest/latest projection selection remains based on
  `request_id`, `record_kind`, `contract_profile`, `contract_version`, and
  `source_timestamp`, not on an unbounded archive.
- Reuse the existing pruning-service pattern if deployment wiring is needed:
  settings-backed interval and batch size, bounded delete batches, a management
  command loop with signal handling, `close_old_connections()`, heartbeat
  liveness, and non-secret ConfigMap env. The closest incumbent is
  `run_guacamole_bootstrap_prune`; simple one-shot cleanup can mirror
  `prune_notifications`.
- New knobs must be Django settings and runtime inventory entries, not
  handler-local `os.environ` reads. If added, they must flow through
  `config/settings.py` or a split `config/_*.py`, `config/_env_manifest.py` when
  helper reads are invisible to the extractor, committed `config/env-manifest.json`,
  `shifter/installation/runtime_inventory.py`, and the relevant GCP/Helm/K8s
  runtime env surfaces.
- Audit visibility is reference-only. Real Shifter lifecycle actions continue
  through `risk_register.services.audit_log` / `audit_log_from_request`.
  Audit `previous_state` / `new_state` may include bounded identifiers such as
  operation record id, request id, digest, status, or diagnostic reference id
  when they describe a Shifter action. They must not carry ACES payloads,
  runtime snapshots, receipts, transcripts, provider diagnostics, commands, or
  package bodies.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Parent operation design | `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md` | Keep snapshots bounded observations and ACES evidence separate from Shifter runtime authority. |
| Sidecar persistence | `shared.models.AcesOperationRecord`, migration `shared/0003_acesoperationrecord.py` | Use first-class fields, indexes, unique idempotency, and `retention_expires_at`; do not hide policy in JSON. |
| Write validation/redaction | `shared.schemas.aces_operation` | Extend the existing allowlist/denylist gates when needed; do not add app-local snapshot validators. |
| Idempotent writes | `shared.aces.operations.persist_aces_operation_record`, `AcesOperationRecordWrite`, `canonical_aces_payload_digest` | Preserve deterministic replay semantics and digest checks. |
| Read projections | `shared.aces.projections.list_operation_records`, `RESPONSE_PAYLOAD_KEYS_BY_RECORD_KIND` | Centralize response allowlists and bounded history limits in the shared read seam. |
| API/auth/errors | `mission_control.api.aces`, `MissionControlReadAPIView`, `AcesRecordQuerySerializer`, `shared.api.errors`, `shared.errors` | Keep session/API-token auth, exact scopes, ownership checks before sidecar lookup, serializers, and safe error envelopes. |
| Audit | `risk_register.services.AuditEvent`, `audit_log`, `audit_log_from_request`, `AuditLog` | Use the service facade for Shifter lifecycle audit; store references only. |
| Logging | `shared.log_sanitize`, provisioner `log_redact`, `config._logging_config.ECSFormatter` | Log IDs, statuses, counts, digests, and fingerprints; never payloads or raw diagnostics. |
| Cleanup precedent | `mission_control.guacamole_bootstrap.prune_expired_bootstrap_requests`, `run_guacamole_bootstrap_prune`, `shared.notifications.prune_expired_notifications` | Reuse bounded-delete, settings-backed, heartbeat/liveness, and management-command conventions. |
| Runtime config | `config/settings.py`, `config/_env_manifest.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, `scripts/gcp/render_runtime_env.py`, Helm `runtimeEnv` | Keep knobs explicit, typed, inventoried, rendered, and non-secret. |
| Events/DLQs | `RangeEventOutbox`, `shared.messages.events`, `shared.management.commands.run_worker`, cloud queue adapters | Event and DLQ payloads carry ids/status/reference fields only, not snapshots or receipts. |
| Enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/**`, `.gitleaks.toml` | Preserve layer, architecture, and secret-scanning checks. |

## Cross-Cutting Layers The Design Must Pass

- Contract/profile shape: operation records must use supported
  `record_kind`/contract-version pairs from `shared.aces.contracts` and
  `SHIFTER_BACKEND_PROFILE`. Unsupported profile/version values fail closed.
- Sidecar metadata validation: `AcesOperationRecord.save()` and shared write
  helpers must keep enforcing UUIDs, aware timestamps, digest shape, payload
  size, diagnostic reference keys, single-line refs, and secret-pattern
  rejection before a row can exist.
- Persistence and cleanup: retention is expressed through
  `retention_expires_at` plus indexed, bounded deletes. Cleanup must not be
  correctness-critical for redaction; unsafe content is rejected before
  persistence. Cleanup must avoid unbounded query/delete loops and must not run
  as a hidden side effect of API reads.
- Product auth: Mission Control reads still pass `ApiTokenAuthentication` /
  session auth, exact `mission_control:range:read` scope, actor resolution, and
  range ownership checks before any sidecar lookup. Unknown and not-owned
  request ids remain indistinguishable.
- Response redaction: API payloads come from the shared response allowlist.
  They exclude transcripts, prompts, command strings, generated scripts, CTF
  flags, provider dumps, Terraform/SSM/SSH output, raw package bodies, tokens,
  private keys, credentials, and token-bearing URLs.
- Audit visibility: Shifter lifecycle audit writes go through
  `risk_register.services` and contain only bounded references. ACES receipts
  may be cited as evidence references; they are not `AuditLog` rows and
  `AuditLog.new_state` is not an ACES receipt/snapshot store.
- Logging and observability: logs use `safe_log_value`,
  `safe_log_fingerprint`, or provisioner `log_redact`; log lines may include
  request id, operation id, record kind, status, counts, duration, digest, and
  reference ids only.
- Event, queue, and DLQ exposure: Range events, worker messages, and failed
  queue payloads must not carry snapshots, receipts, provider dictionaries,
  raw exceptions, command text, or package bodies. Put durable ACES data in the
  sidecar and queue only a reference when needed.
- OS/process exposure: management commands, task runners, Kubernetes args,
  workflow command lines, and subprocess argv carry operation names, ids,
  batch sizes, and cadence settings only. Snapshot bodies, credentials,
  diagnostics, package bodies, and generated scripts must not travel through
  argv, shell strings, or plain env vars.
- Config/env binding: every new retention/cadence/batch setting must appear in
  settings, env manifest, runtime inventory, and deployment/runtime env wiring
  if it affects deployed behavior. Operator visibility comes from those
  canonical surfaces, not from comments in a handler.
- Error envelopes: DRF/browser errors use `shared.api.errors` and
  `classify_user_message` / `safe_user_message`. Raw validation, DB, provider,
  parser, Terraform, SSM, SSH, queue, or cleanup exceptions must not become
  response text.
- Import boundaries: non-`shared` apps reach sidecar behavior through
  `shared.aces` helpers and existing service facades. Mission Control, CMS,
  CTF, and workers must not import ACES SDL/runtime packages or app-private
  model internals directly.

## Extensibility Seam

The seam is the retention/redaction policy around the existing sidecar helpers,
parameterized by record kind, contract profile/version, latest-vs-history
selection, retention TTL, cleanup interval, and cleanup batch size. The next
reasonable variation is a new ACES profile, provider-specific diagnostic
reference, or different short-history window; that should add a profile/key
allowlist or setting behind the shared validator/projection/cleanup seams, not
copy snapshot rules into handlers, serializers, templates, tests, or deployment
scripts.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/aces-operation-sidecar-persistence-preflight-1273.md`
- `docs/architecture/aces-operation-api-projections-preflight-1275.md`
- `docs/architecture/aces-migration-adr.md`
- `docs/adr/index.yaml` entries for ADR-024, ADR-025, and ADR-027
- `shifter/shifter_platform/shared/models.py`
- `shifter/shifter_platform/shared/aces/**`
- `shifter/shifter_platform/shared/schemas/aces_operation.py`
- `shifter/shifter_platform/shared/management/commands/**`
- `shifter/shifter_platform/mission_control/api/aces.py`
- `shifter/shifter_platform/mission_control/api/serializers.py`
- `shifter/shifter_platform/risk_register/{models,services}.py`
- `shifter/shifter_platform/config/settings.py`, `config/_env_manifest.py`,
  and `config/env-manifest.json`
- `shifter/installation/runtime_inventory.py`
- `scripts/gcp/render_runtime_env.py`,
  `platform/k8s/gcp/overlays/gcp-dev/platform-runtime.env`, Helm
  `runtimeEnv`, and platform worker/prune deployment templates if deployment
  wiring changes
- `shared.messages`, `RangeEventOutbox`, workers, and cloud queue adapters if
  any events/reference messages change
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, and `.gitleaks.toml`

## Regression Evidence Expectations

- Schema/model tests prove forbidden snapshot fields and secret-like values are
  rejected before persistence, including transcripts, prompts, command strings,
  generated scripts, flags, raw provider diagnostics, Terraform/SSM/SSH output,
  package bodies, token-bearing URLs, private keys, and credentials.
- Persistence tests prove idempotent writes, digest enforcement, record-kind
  allowlists, diagnostic-reference allowlists, and `retention_expires_at`
  behavior.
- Cleanup tests prove expired rows are deleted in bounded batches, unexpired
  rows are retained, newest/latest projection semantics are preserved as
  designed, and cleanup emits only sanitized counts/statuses.
- API tests prove Mission Control responses use the shared projection allowlist,
  enforce session/token/ownership checks before sidecar lookup, preserve
  non-ACES behavior, and do not leak raw payload fields.
- Audit tests prove Shifter lifecycle audit rows contain references only and
  ACES receipts/snapshots are not persisted as `AuditLog` rows or JSON blobs.
- Log and queue tests use `caplog` or message-body assertions where practical
  to prove payloads, raw diagnostics, commands, flags, transcripts, and tokens
  do not appear in logs, events, DLQs, docs examples, or fixtures.
- Config tests prove new settings are in `env-manifest.json`, runtime
  inventory allowlists/renderers, and deployment env surfaces when used.

## Gotchas And Anti-Patterns

- Do not rely on serializer redaction after storing unsafe snapshot content.
  Reject unsafe content before persistence.
- Do not turn `runtime_snapshot.payload`, `diagnostic_refs`, `AuditLog.new_state`,
  `RangeEventOutbox.payload`, queue messages, docs examples, or test fixtures
  into places for transcripts, prompts, command strings, generated scripts,
  flags, raw provider diagnostics, Terraform output, SSM/SSH output, token URLs,
  or package bodies.
- Do not add handler-local `os.environ` reads, magic constants, or environment
  variables absent from the env manifest/runtime inventory.
- Do not run cleanup opportunistically inside read APIs or write handlers as
  the only retention mechanism.
- Do not add an ACES audit table, ACES-only API namespace, parallel error
  envelope, duplicate validation schema, duplicate exception hierarchy, or
  sidecar access path per app.
- Do not make `range_id` the cleanup/audit/API identity. `request_id` remains
  the operation correlation key; `range_id` is optional projection metadata.
- Do not pass snapshots, diagnostics, package bodies, or secrets through
  process argv, shell strings, Kubernetes command arrays, workflow logs, or
  plain env vars.
- Do not weaken import-linter, ADR guard, API-token scope validation, worker
  retry/DLQ behavior, or secret-scanning policy for the ACES path.

## Non-Goals

- No implementation in this preflight note.
- No new ACES persistence model, public product, mutation API, lifecycle enum,
  event bus, websocket topic, audit store, or experiment evidence archive.
- No replacement of `engine.Range`, `cms.RangeInstance`, `ResourceStatus`,
  `RangeEventOutbox`, Mission Control range UX, CMS authoring policy, or CTF
  range workflows.
- No archival storage of historical experiments, transcripts, prompts,
  generated scripts, package bodies, raw diagnostics, or flags in runtime
  snapshots.
- No new Ground Control requirement UID for this requirement-free run.
- No changelog fragment for this docs-only preflight note.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation touching `shifter/shifter_platform` should also
run the focused shared ACES schema/projection/cleanup tests, Mission Control
ACES API tests, audit tests, config/runtime-inventory tests, import/layer
checks, and any stack-native checks required by `AGENTS.md` and
`.gc/plan-rules.md` for the files it touches.

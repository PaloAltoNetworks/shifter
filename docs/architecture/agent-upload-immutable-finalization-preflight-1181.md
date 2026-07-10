# Agent Upload Immutable Finalization Preflight (#1181)

Status: pre-implementation guidance

Date: 2026-07-05

Issue: GitHub #1181, "[Security][Medium] Agent uploads can be overwritten after
validation with the still-valid signed PUT URL"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as hardening the existing agent direct-upload finalization boundary,
not as a redesign of uploads or portal storage durability.

The security invariant is:

> The bytes installed as an `AgentConfig` must be the same object version that
> CMS validated during completion.

The current workflow stays conceptually intact:

1. Mission Control authenticates and validates the HTTP request.
2. `cms.services.initiate_upload` issues a signed upload token and presigned PUT.
3. The browser PUTs to the provider staging object.
4. `cms.services.complete_upload` verifies the token, validates storage metadata
   and content, then creates the `AgentConfig`.

The fix belongs at step 4 and, if needed, at the signed PUT generation seam. It
must not introduce a second upload workflow, second token schema, or app-local
provider client.

## Architecture Decisions

- The staging object key from `cms.assets.upload_token` is upload authority, not
  installed-asset identity. Completion must either bind all validation and
  install operations to the same provider object identity, or conditionally copy
  the validated bytes to a fresh install key and persist only that install key.
- Prefer a conditional immutable-copy/install-key design when the provider
  supports it: validate the staging object, perform a provider-side copy whose
  source precondition matches the validated identity and whose destination is
  absent, then create `AgentConfig` from the destination key. A still-valid
  presigned PUT can then only mutate the staging key.
- A second `HEAD` after inspection is not sufficient if `AgentConfig.s3_key`
  still points at the mutable presigned PUT key. The object can change after the
  re-check and before URL expiry.
- Do not enable S3 bucket versioning, cross-region replication, or a durable
  retention posture as this issue's fix. Portal uploads are intentionally
  ephemeral per `docs/architecture/s3-bucket-hardening-preflight.md`,
  `docs/ops/disaster-recovery.md`, and `docs/adr/exceptions.yaml`.
- ETag may be used as a provider concurrency validator, not as a cryptographic
  content hash. S3 multipart ETags are not SHA-256. GCS generation is the
  strongest object identity when available; metageneration is metadata identity.
- Provider-specific conditional behavior belongs behind
  `shared.cloud.types.ObjectStorage` and the AWS/GCP adapters, surfaced through
  `cms.assets.s3` compatibility wrappers. CMS service code must not import boto3
  or google-cloud-storage directly.
- Completion failures from identity/precondition mismatch are validation
  failures at the CMS service boundary: raise `CMSError` with an authored
  message, log sanitized context, and do not tag, audit, or create `AgentConfig`.
- No new ADR is needed unless the implementation changes enforceable guardrails,
  bucket durability, workflow policy, import boundaries, or global API/auth
  settings.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| HTTP/API surface | `mission_control.api.uploads.UploadInitiateView`, `UploadCompleteView`, `UploadCancelView` | Keep the existing DRF route families and legacy response compatibility. |
| Request validation | `mission_control.api.serializers.UploadInitiateSerializer`, `UploadCompleteSerializer`, `_validated(...)` | Do not parse completion payloads by hand or add view-local DTOs. |
| Auth and scope | `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `_upload_write_permission()` | Session/API-token admission stays at the existing Mission Control boundary. |
| Upload token | `cms.assets.upload_token.generate_upload_token`, `verify_upload_token` | Keep HMAC token verification as the authority for user id, staging key, filename, expected size, OS, agent type, and expiry. |
| Upload service | `cms.services._uploads.complete_upload` and helper split | Add the identity gate around existing size/header validation and before `tag_s3_object` / `create_agent`. |
| Format validation | `cms.assets.validation.validate_file_extension` and `shared.uploads.inspection.validate_magic_bytes` | Do not create a second file-type or magic-byte registry. |
| CMS storage wrappers | `cms.assets.s3.verify_s3_object_exists`, `read_agent_header`, `tag_s3_object`, `delete_agent` | Preserve `S3Error` compatibility while delegating new provider operations to `shared.cloud`. |
| Provider seam | `shared.cloud.types.ObjectStorage`, `AWSObjectStorage`, `GCPObjectStorage` | Extend the protocol once for object identity/precondition/copy behavior; implement both providers. |
| Persistence | `cms.assets.services.AgentUploadSpec`, `create_agent`, `AgentConfig` | Persist the final installed key only. Do not overload `sha256_hash` with ETag/generation. |
| Audit | `risk_register.services.audit_log` via `create_agent` | Creation audit happens only after immutable finalization succeeds. |
| Error envelope | `MissionControlAPIView.bad_request/error_response`, `shared.api.errors`, `shared.errors.classify_user_message` | Return sanitized authored errors; never serialize provider diagnostics. |
| Logging | module loggers plus `shared.log_sanitize.safe_log_value` / `safe_log_fingerprint` | Log action, user id, sanitized object keys, and outcome only. |
| Tests | `tests/cms/test_services_upload_complete.py`, `tests/cms/assets/test_s3.py`, `tests/shared/cloud/test_aws_storage.py`, `test_gcp_storage.py`, `tests/mission_control/test_views_uploads.py`, `static/js/upload.test.js` | Drive real first-party flow and mock only cloud/browser boundaries, following existing tests. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: completion requests still pass through Django/DRF auth,
  `HasMissionControlActor`, and upload-write scope admission. Service-layer token
  verification remains required because HTTP auth alone does not bind a request to
  a staging object.
- CSRF surface: unsafe session-authenticated calls stay CSRF-protected through
  the existing DRF/session stack. Do not add `csrf_exempt`, CORS broadening, or
  cookie-setting changes for this storage fix.
- Upload-token surface: `verify_upload_token` must run before any object read,
  copy, tag, delete, or DB write. Completion must not trust request JSON for
  object key, size, filename, OS, or agent type.
- Object metadata surface: `head_object` / `verify_s3_object_exists` remains the
  size and identity capture gate. The captured identity must flow into the later
  provider precondition; it is not just diagnostic metadata.
- Object content surface: header inspection still uses bounded range reads via
  `read_object_header` and `UPLOAD_INSPECTION_MAX_HEADER_BYTES`. Do not download
  full installer objects into Django memory to solve the race.
- Provider precondition surface: AWS behavior must use S3-native conditional
  semantics such as source ETag match and destination-absent checks for copy, or
  a signed create-only PUT if that path is chosen. GCP behavior must use GCS
  generation preconditions. Missing provider support fails closed.
- Persistence surface: `AgentConfig.s3_key` must reference the object whose bytes
  were protected by the identity/precondition gate. Existing soft-delete and
  quota semantics remain in `AgentConfig` / `AgentConfig.active_for_user`.
- Secret-handling surface: upload tokens and presigned URLs are bearer
  credentials. Keep them out of logs, audit JSON, non-protocol response fields,
  app URL query strings, process argv, env vars, CI output, and docs examples.
  They may appear only in the existing initiate/complete protocol fields needed
  for the browser upload flow. Object keys should be sanitized when logged.
- Error-envelope surface: legacy Mission Control routes keep flat `{"error":
  "..."}` payloads; canonical `/api/v1/` routes use the shared DRF envelope.
  Provider mismatch, stale object, or conditional-copy failure should surface as a
  generic invalid/stale upload class, not raw S3/GCS text.
- Config/env surface: reuse `CLOUD_PROVIDER`, `CLOUD_REGION`,
  `STORAGE_BUCKET_NAME` / `AWS_S3_BUCKET_NAME`, `AGENT_UPLOAD_URL_EXPIRES`, and
  `UPLOAD_INSPECTION_MAX_HEADER_BYTES`. Add a setting only for a real
  provider-neutral policy knob and then update `config/env-manifest.json` plus
  tests.
- OS/runtime exposure: do not shell out to `aws`, `gsutil`, or `gcloud`, do not
  pass tokens or object keys through process argv, and do not spool object bytes
  to `/tmp`.
- Import-boundary surface: Mission Control calls the public `cms.services`
  facade; CMS calls `shared.cloud` through `cms.assets.s3`; no direct CMS import
  of Mission Control/CTF and no direct `cyberscript` imports outside `shared`.
- Architecture guardrails: `.importlinter`, `scripts/adr_guard/adr_guard.py`,
  `docs/adr/index.yaml`, `docs/adr/exceptions.yaml`, and
  `docs/architecture/s3-bucket-hardening-preflight.md` remain the whole-repo
  checks and policy context.

## Extensibility Seam

The seam belongs in the provider-neutral object-storage contract, not in
Mission Control views:

- object identity captured from `head_object` should include content length plus
  provider identity fields such as `etag`, `generation`, or `version_id` when
  available;
- conditional installation should accept an expected source identity and a
  destination-absent precondition;
- key strategy should be parameterized as a staging key versus installed key
  decision, so future quarantine, antivirus, SHA-256 calculation, or provider
  migration does not require changing API views or token parsing.

Keep the provider vocabulary at the adapter edge. CMS service code may reason
about "expected object identity" and "install destination absent"; it should not
branch on S3 `CopySourceIfMatch` versus GCS `if_generation_match` directly.

## Gotchas And Anti-Patterns

- Do not rely on tagging `status=completed` on the mutable upload key as an
  integrity boundary.
- Do not treat ETag as a digest, do not persist it in `sha256_hash`, and do not
  promise malware or signature verification.
- Do not compare `HEAD` metadata before and after inspection and call the race
  closed while persisting the same mutable key.
- Do not create a duplicate upload-token schema, storage client, magic-byte
  registry, exception hierarchy, or response envelope.
- Do not add direct boto3/google-cloud imports in `cms.services` or
  `mission_control.api`.
- Do not leave partially finalized rows when provider preconditions fail. The DB
  row, object tag, and audit event are all after the immutable finalization gate.
- Do not silently swallow provider conditional-copy failures as cleanup warnings;
  they are the security signal for this finding.
- Do not log presigned URLs, upload tokens, request bodies, object bytes, raw
  provider exception payloads, Authorization/Cookie headers, or CSRF tokens.
- Do not broaden upload bucket CORS, public access, IAM read/write policy,
  lifecycle, or versioning to make the implementation easier.

## Non-Goals

- No implementation in this preflight note.
- No new Ground Control requirement or traceability for this requirement-free
  issue.
- No redesign away from presigned direct uploads.
- No durable upload-job model, background scanner, quarantine state, or worker
  queue unless a follow-up issue scopes it.
- No bucket versioning, CRR, retention, access logging, lifecycle, KMS, Terraform,
  Kubernetes, or IAM expansion unless the chosen provider precondition requires a
  narrow, reviewed permission update.
- No antivirus scanning, package-signature validation, full-file hashing, or
  execution safety guarantee.
- No changes to OIDC, API-token scope vocabulary, CSRF trusted origins, CORS,
  cookie policy, global DRF defaults, or SPA/API migration policy.

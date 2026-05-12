# Server-Side Upload Inspection Preflight

Issue #696 closes the upload validation gap for direct-to-S3 uploads by making
backend finalization verify object content, not just client-side checks or S3
metadata. This is a validation-boundary change, not a new upload workflow.

## Boundary

- The canonical upload flow remains: authenticated view -> `cms.services`
  service boundary -> `cms.assets` storage/token/validation helpers ->
  `shared.cloud.ObjectStorage` provider adapter.
- Finalization is the enforcement point for server-side content inspection.
  The backend must validate the uploaded object's size, extension-derived
  expected format, and magic bytes before tagging the object as completed or
  creating `AgentConfig`.
- Object inspection should read only the minimum header bytes needed for the
  expected format. Do not download multi-GB agent objects into Django memory.
- The `ObjectStorage` protocol is the provider seam. If header reads are needed,
  add a small range-read capability there and implement it in both AWS S3 and
  GCS adapters instead of reaching for raw boto3 in CMS code.
- The existing experiment script upload path is related but separate. Scripts
  are text assets validated by `cms.experiments.schemas.ScriptUploadInput` and
  the experiment service; do not merge agent installer and Python script
  validation concepts.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Upload workflow | `mission_control.views.initiate_upload`, `complete_upload`, `cancel_upload`; `cms.services.initiate_upload`, `complete_upload` | Preserve the three-step direct upload flow and session upload lock. |
| Upload token | `cms.assets.upload_token` | Keep HMAC token verification as the authority for user, key, filename, expected size, expected OS, and expiry. |
| File format rules | `cms.assets.validation.ALLOWED_FORMATS`, `validate_file_extension`, `validate_magic_bytes` | Reuse the same `FileFormat` registry for backend object inspection; do not create a second magic-byte table. |
| Storage operations | `cms.assets.s3` wrappers over `shared.cloud.get_object_storage()` | Keep CMS-facing `S3Error` compatibility, but implement provider operations in `shared.cloud` adapters. |
| Cloud seam | `shared.cloud.types.ObjectStorage`, `shared.cloud.aws.storage.AWSObjectStorage`, `shared.cloud.gcp.storage.GCPObjectStorage` | Add any range/header read once at the protocol and adapter layer. |
| Config | `config.settings` upload limits and bucket aliases: `AGENT_MAX_FILE_SIZE_MB`, `AGENT_USER_STORAGE_QUOTA_MB`, `AGENT_UPLOAD_URL_EXPIRES`, `STORAGE_BUCKET_NAME` / `AWS_S3_BUCKET_NAME` | Reuse existing settings unless a real inspection limit is needed. If added, make it provider-neutral. |
| Errors | `cms.exceptions.CMSError`, `cms.assets.s3.S3Error`, `cms.assets.validation.ValidationError`, `shared.cloud.exceptions.CloudStorageError` | Bridge cloud errors to `S3Error`, then to existing service/view error envelopes. |
| Logging | `logging.getLogger(__name__)`, `shared.log_sanitize.safe_log` where object keys or provider errors are logged | Log user id, object key, expected/actual size, and result; never log presigned URLs, tokens, raw object bytes, or full provider exception payloads without sanitizing. |
| Audit | `risk_register.services.audit_log`, existing agent create audit | Audit creation only after inspection succeeds; failed validation should be observable in logs but should not create an agent record. |

## Security Layers

- Auth surface: `mission_control.views.complete_upload` must remain
  `@login_required` and must call `cms.services.complete_upload` with
  `_get_user(request)`. Authentication only identifies the caller; inspection
  must still run for every upload.
- Token shape: `cms.assets.upload_token.verify_upload_token` must continue to
  validate signature, expiry, user id, S3 key, filename, expected size, OS, and
  agent type before any object read. The implementation must not trust request
  JSON for these values during finalization.
- Extension and format policy: `cms.assets.validation.validate_file_extension`
  should derive the expected `FileFormat` from the signed filename, and
  `validate_magic_bytes` should remain the single magic-byte comparator.
- Object metadata gate: `cms.assets.s3.verify_s3_object_exists` / `head_object`
  must still fail closed on missing objects and exact size mismatch before DB
  creation. Header inspection is an additional gate, not a replacement.
- Object content gate: the backend must fetch only a bounded byte range from the
  object under the token's S3 key and validate it against the expected
  `FileFormat.magic_bytes`. Reads must go through `ObjectStorage` so AWS and GCP
  remain aligned.
- Secret-handling surface: upload tokens and presigned URLs are bearer
  credentials. They must stay out of logs, audit state, exception messages, task
  env vars, process argv, and persisted model fields.
- Config/env binding: storage bucket and provider selection must continue
  through `STORAGE_BUCKET_NAME` / `AWS_S3_BUCKET_NAME`, `CLOUD_REGION`, and
  `CLOUD_PROVIDER`; do not introduce an upload-inspection bucket or provider
  side channel.
- OS/runtime exposure: this inspection should happen in the Django backend or a
  purpose-built worker with scoped object-read permission. Do not shell out to
  `aws s3 cp`, pass tokens or keys through process argv, or write uploaded
  headers to `/tmp`.
- Error envelope: HTTP responses should continue returning the existing JSON
  `{"error": ...}` shape. Validation failures may say the uploaded content does
  not match the expected type, but must not echo object bytes, presigned URLs,
  tokens, bucket names, or raw provider diagnostics.
- Infrastructure policy: if the implementation chooses an S3 event/Lambda
  scanner instead of synchronous finalization, it must add least-privilege
  object read/tag permissions, dead-letter/visibility semantics, and lifecycle
  cleanup for rejected objects. It must not finalize the DB row before the
  scanner verdict is durable.

## Extensibility Seam

Keep the seam as an object-inspection helper shaped by a signed upload contract:
`s3_key`, expected size, expected `FileFormat`, and a configurable header byte
budget. That allows the next reasonable change, such as SHA-256 calculation,
antivirus scanning, or script text validation, to compose behind the same
finalization gate without re-editing views or duplicating token parsing.

If a new setting is needed, prefer a provider-neutral
`UPLOAD_INSPECTION_MAX_HEADER_BYTES` defaulted from the largest registered magic
signature plus small slack. Do not hard-code AWS `Range` header semantics above
the cloud adapter.

## Gotchas And Anti-Patterns

- Do not treat MIME type, `ContentType`, extension, ETag, or client-side
  JavaScript checks as proof of file type.
- Do not validate magic bytes at initiate time only; direct S3 upload means the
  backend has not seen the bytes yet.
- Do not create a duplicate `ALLOWED_MAGIC_BYTES`, `FileType`, exception
  hierarchy, or upload DTO in a view, Lambda, or Terraform-adjacent script.
- Do not finalize, tag `status=completed`, audit creation, or expose the agent
  to range launch until inspection succeeds.
- Do not delete a suspect object before recording enough sanitized context to
  debug user-facing failures; also do not leave rejected objects permanently
  retained without lifecycle cleanup.
- Do not use a broad background scanner that races finalization unless the model
  has an explicit pending/quarantine state. The current `AgentConfig` flow has
  no such state.
- Do not widen CORS, bucket public access, or range-instance S3 read policy to
  solve backend inspection.

## Non-Goals

- Redesigning uploads away from presigned URLs.
- Replacing `cms.assets` with experiment script upload code or CTF attachment
  code.
- Adding antivirus, sandbox execution, package signature verification, or full
  file hashing unless explicitly scoped by a follow-up issue.
- Changing storage bucket encryption, CORS, lifecycle, Terraform state, range
  instance download behavior, or experiment artifact downloads.
- Making uploaded agents safe to execute; this only verifies that the object
  matches the claimed installer/archive container format before persistence.

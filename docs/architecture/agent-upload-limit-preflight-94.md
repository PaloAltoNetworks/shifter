# Agent Upload Limit Preflight (#94)

Status: pre-implementation guidance

Date: 2026-09-05

Issue: GitHub #94, "Mission Control: enforce agent upload limit before
transfer"

This issue is requirement-free. The GitHub issue is the shipping contract. This
note records boundary decisions and guardrails; it is not an implementation
plan.

## Scope Boundary

Keep the existing direct-upload workflow and enforce one server-owned per-file
policy at three trust levels:

1. the SPA gives an early, advisory rejection before initiation;
2. `cms.services.initiate_upload` authoritatively rejects the declared size
   before quota lookup or presigned-URL issuance; and
3. `cms.services.complete_upload` checks the current policy against the
   provider-reported object length before inspection, immutable installation,
   tagging, persistence, or creation audit.

These checks are deliberately repeated at distinct trust boundaries, but the
limit calculation and comparison are not. Extend the existing
`cms.assets.validation` size policy with a byte-oriented helper and make the
legacy file-object validator delegate to it. Do not copy
`AGENT_MAX_FILE_SIZE_MB * 1024 * 1024` into the service, serializer, view, cloud
adapter, or SPA.

## Architecture Decisions

- The machine contract is bytes. The existing setting's historical `MB` name
  has binary semantics: `2048 * 1024 * 1024` bytes (2 GiB). The exact limit is
  allowed; one byte over is rejected. User documentation must state the unit
  unambiguously.
- Per-file size and per-user storage quota are separate policies. A request over
  both limits receives the per-file decision first; a request within the file
  limit then passes the existing active-agent quota check. Do not combine the
  values or error concepts.
- `file_size` is a positive JSON integer, not an arbitrary JSON value. The DRF
  request shape and the callable CMS boundary must reject booleans, strings,
  floats, zero, and negative values. Python's `bool`-is-`int` behavior must not
  admit `true` as one byte.
- Publish `max_file_size_bytes` on the existing authenticated Mission Control
  agent-list response, which the Agents page already loads. This keeps upload
  policy with the agent surface and avoids widening the global principal/mode
  bootstrap contract or adding a policy-only endpoint. The upload form must not
  render an independent fallback constant when that response is unavailable.
- The runtime serializer is the public contract. Regenerate the committed
  `openapi/v1.json` and SPA `api/schema.d.ts`; do not add a handwritten response
  interface. Contract parity means the API value comes from the same CMS policy
  helper as enforcement, not that two constants happen to be equal in a test.
- Presigned upload hardening is defense in depth. Pass the declared byte length
  through `cms.assets.s3` into `shared.cloud.types.ObjectStorage`. Each provider
  adapter should bind the exact `Content-Length` into its V4 signed request when
  its supported SDK semantics are proven. Keep the current cross-provider PUT
  protocol; do not introduce an AWS-only POST response merely to use an S3 POST
  range policy.
- A provider constraint never replaces finalization. A signed header is still
  client/request metadata, and a stale token may have been issued under a
  different cap. Completion compares the authoritative `head_object`
  `content_length` with the current server policy independently of the token's
  declared size, then retains the existing exact declared-size match.
- On an oversized object, completion verifies the HMAC token and actor binding
  before using its staging key, records sanitized rejection context, attempts
  `cms.assets.s3.delete_agent`, and rejects even if cleanup fails. It must not
  inspect, copy, tag, create `AgentConfig`, or emit the existing creation audit.
- The absolute-cap check precedes the token-declared-size equality check. This
  gives stale, server-signed tokens above the current cap the cleanup path rather
  than treating them only as ordinary size mismatches.
- No ADR update is needed. The design reuses the service facade, validation
  policy, generated API contract, provider adapter, error envelope, and immutable
  finalization rules already governed by ADR-001 and ADR-029 and by the #696,
  #1181, and #317 preflight notes.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Size policy | `cms.assets.validation.validate_file_size` and `config.settings.AGENT_MAX_FILE_SIZE_MB` | Add one byte-oriented policy seam; keep one conversion and `size > limit` rule. |
| HTTP shape | `UploadInitiateSerializer` and `_validated(...)` | Use an integer field/validator; do not parse request JSON in the view. |
| Service boundary | `cms.services.initiate_upload`, `complete_upload`, `_validate_positive_int` | Keep enforcement callable-safe and explicitly reject booleans. Mission Control imports only the public facade. |
| Policy delivery | `AgentListView`, `AgentListResponseSerializer`, `useAgents()` | Add the safe byte value to this existing response; do not put it in global bootstrap or a frontend constant. |
| API contract | DRF serializers -> `openapi/v1.json` -> `frontend/src/api/schema.d.ts` / `api/types.ts` | Regenerate; never hand-copy the response shape. |
| Quota | `cms.assets.services.get_storage_used`, `AgentConfig.active_for_user`, `AGENT_USER_STORAGE_QUOTA_MB` | Preserve active-row aggregation and exact-quota behavior; it is not the file-size policy. |
| Token authority | `cms.assets.upload_token.verify_upload_token` | Preserve HMAC, expiry, and user binding. Token claims identify staging state but do not define the current cap. |
| Object truth | `cms.assets.s3.verify_s3_object_exists` -> `ObjectStorage.head_object` | Use provider-reported `content_length`; do not trust the browser, token, filename, MIME type, or PUT response. |
| Cleanup | `cms.assets.s3.delete_agent` | Best effort after an authorized oversize finding; cleanup failure never permits finalization. |
| Immutable install | `_install_validated_upload_or_raise` and `copy_object_conditional` | Keep identity-bound staging-to-install copy after every validation gate. |
| Provider seam | `ObjectStorage`, `AWSObjectStorage`, `GCPObjectStorage` | Add the declared length once to the provider-neutral presign method; provider vocabulary stays in adapters. |
| Content validation | `validate_file_extension`, `shared.uploads.inspection.validate_magic_bytes`, bounded header reads | Preserve extension and signature gates after metadata checks; do not download multi-GiB files through Django. |
| Errors | `CMSError`, `MissionControlAPIView`, `shared.api.errors`, `classify_user_message` | Preserve the canonical envelope and authored/sanitized messages; do not serialize cloud exceptions. |
| Logging | module loggers and `shared.log_sanitize` | Log actor id, sanitized key, actual bytes, cap bytes, and cleanup outcome; never log bearer capabilities. |
| Persistence/audit | `AgentUploadSpec`, `create_agent`, `AgentConfig`, `shared.audit` | No row, completed tag, or creation audit exists before all finalization gates pass. |
| Browser upload | `useAgentUpload`, `uploadFileToPresignedUrl`, shared `apiFetch` | Use the server-provided cap before initiation; keep the storage PUT credential-free and cross-origin. |

## Cross-Cutting Layers The Design Must Pass

- Authentication and authorization: API requests retain
  `ApiTokenAuthentication` before session authentication,
  `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, and the existing
  range-read or upload-write scope as appropriate. A malformed bearer token
  remains fail-closed and cannot fall through to a session. Unsafe session calls
  remain CSRF protected.
- Request and callable shapes: DRF rejects malformed JSON types; the CMS service
  repeats non-HTTP type/value checks because it is also a public Python boundary.
  Neither layer is allowed to rely on JavaScript preflight.
- Policy/config shape: `AGENT_MAX_FILE_SIZE_MB` remains the code-owned source and
  is converted to a positive byte count in one CMS policy helper. This work adds
  no direct `os.environ` read or new environment variable, so
  `config/env-manifest.json`, Terraform, Kubernetes, and secret bindings do not
  change. A future environment-bound limit must use the centralized settings
  parser/validation and manifest path rather than an app-local env read.
- Upload-token parser: signature, expiry, and actor match run before storage
  access or deletion. The signed `file_size` remains the exact expected-size
  claim; it is never treated as evidence that the current cap permits the file.
- Presign/provider gate: CMS passes provider-neutral expected content length;
  AWS and GCP adapters encode supported signed-header constraints and fail closed
  on presign errors. CMS and Mission Control must not branch on provider or import
  boto3/google-cloud-storage directly.
- Browser/security-policy gate: the SPA keeps using the existing exact storage
  origins from `config._browser_security`, the deployment's bucket CORS, HTTPS,
  and no cookies, CSRF token, Authorization header, or platform credential on the
  object-store PUT. Do not broaden CSP, CORS, public access, or IAM.
- Finalization metadata/content/identity gates: HMAC verification is followed by
  authoritative HEAD size, current cap, exact signed size, bounded magic-byte
  inspection, and conditional immutable copy in that order. Only the installed
  key reaches tagging and persistence.
- Error-envelope gate: validation/provider failures return the shared
  `{error: {code, message, details?, request_id?}}` shape. The normal SPA size
  error is clear and local because it uses the server-delivered cap; responses
  must not echo tokens, signed URLs, bucket names, keys, or raw provider text.
- Secret-handling and OS exposure: upload tokens and presigned URLs are bearer
  capabilities. Keep them out of logs, audits, OpenAPI examples, query strings,
  process argv, environment variables, CI output, docs examples, and temporary
  files. Do not shell out to `aws`, `gcloud`, `gsutil`, or `curl`, and do not spool
  uploaded object bytes through the portal filesystem.
- Persistence and observability: `AgentConfig.active_for_user` and its
  soft-delete semantics remain the quota source. Oversize attempts are
  observable through sanitized application logs; they do not create persistence
  or reuse the agent-creation audit event.
- Whole-repo enforcement: `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/adr_guard.py`, `.github/workflows/_quality.yml`,
  `config/env-manifest.json`, the AWS/GCP portal bucket modules, and
  `config._browser_security` remain the relevant architectural/runtime checks.

## Extensibility Seam

The policy seam is a byte-oriented CMS helper, and the transport seam is the
provider-neutral `content_length` presign parameter. This lets a future limit
change, or a future agent-type-specific policy, select a byte cap in CMS without
changing comparison rules, API views, upload-token parsing, or provider code.
The response may later grow an explicit per-type map while retaining
`max_file_size_bytes` as the current default; do not place agent-type policy in
the S3/GCS adapters.

## Required Test Boundaries

- Policy/service: exact cap accepted, one byte over rejected before quota or
  presign, within-cap quota rejection retained, both-exceeded precedence pinned,
  and boolean/string/float/zero/negative inputs rejected.
- HTTP/contract: crafted initiation JSON cannot obtain a URL; the agent-list
  response value equals the CMS policy helper; OpenAPI and generated TypeScript
  contain the field.
- Finalization: authoritative actual size at the cap succeeds; one byte over is
  deleted and rejected even when the signed token declares that same size; delete
  failure still rejects; inspection/copy/tag/DB/audit are not reached.
- Providers/browser: AWS and GCP adapter tests pin the expected signed
  `Content-Length`; the existing browser PUT keeps only application content type
  and no platform credentials. Provider smoke tests must prove the supported
  browser supplies a matching length and that mismatches are rejected.
- SPA: the displayed value and preflight comparison come from the response,
  exact cap can initiate, one byte over cannot initiate or PUT, and absence of
  policy data does not fall back to 2048.

## Gotchas And Anti-Patterns

- Do not rename the existing setting as part of this issue, but do not expose its
  ambiguous `MB` unit on the wire.
- Do not use the per-user quota as a per-file maximum or re-check aggregate quota
  at finalization; quota reservation/concurrency is a separate problem.
- Do not trust `Content-Length`, the signed token, the SPA, or provider policy as
  the sole boundary. The final HEAD/current-policy check is mandatory.
- Do not compare only token-declared and actual size; two equal oversized values
  still violate current policy.
- Do not delete any key until token signature, expiry, and actor binding pass.
- Do not let cleanup failure continue to header inspection or installation.
- Do not create a second size constant, DTO hierarchy, validation module,
  exception family, response envelope, upload workflow, or cloud client.
- Do not switch only AWS to multipart POST or make the SPA understand provider
  field sets unless a separately reviewed compatibility requirement demands it.
- Do not use ETag as size or content-integrity proof, and do not weaken the
  conditional immutable-install boundary from issue #1181.
- Do not update only the retained legacy template/JavaScript uploader. The active
  route is the SPA; legacy assets are not the server-owned policy contract.

## Non-Goals

- No implementation in this preflight note and no new Ground Control
  requirement.
- No redesign away from direct-to-storage PUT uploads, no portal request-body
  limit, and no Gunicorn/Django streaming path.
- No upload reservation model, transactional aggregate-quota redesign,
  background cleanup queue, quarantine state, malware scan, package-signature
  verification, or full-file hash.
- No bucket-policy, CORS, CSP, IAM, versioning, lifecycle, retention, KMS,
  Terraform, Kubernetes, or global DRF/authentication change.
- No general upload-token schema redesign or new token revocation mechanism.
- No promise that deleting a staging object revokes an unexpired presigned URL;
  every later finalization attempt must still fail the current-cap check.

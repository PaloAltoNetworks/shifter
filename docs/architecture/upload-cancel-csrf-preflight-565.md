# Upload Cancel CSRF Hardening Preflight (#565)

Status: pre-implementation guidance

Date: 2026-06-27

Issue: GitHub #565, "Architecture review: replace or harden the CSRF-exempt
upload cancel endpoint"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

ADR-027 note: legacy experiment script uploads were removed by issue #1195.
References below to script-upload distinctions describe the pre-removal state
and are not current implementation guidance.

## Scope Boundary

Treat this as hardening the existing agent-upload cancel boundary, not as a
redesign of direct-to-storage uploads, API authentication, script uploads, or
storage cleanup.

Keep these concepts separate:

1. HTTP admission: session/API-token authentication, token scopes, and CSRF.
2. Upload authority: the signed `cms.assets.upload_token` payload bound to the
   acting user.
3. Session coordination: the Mission Control upload lock that prevents
   concurrent uploads in one browser session.
4. Storage cleanup: best-effort deletion of the token's S3 object.
5. Browser unload UX: an opportunistic cancel signal that may be dropped.

## Architecture Decisions

- The live upload HTTP surface is the DRF layer in
  `mission_control.api.uploads`. Legacy `/mission-control/api/...` routes are
  compatibility wrappers around the same DRF view classes. Do not fix only the
  older private function-view module and call the issue closed.
- Browser session calls to upload cancel must use the normal Django/DRF CSRF
  path. Remove local session-auth CSRF bypasses for this endpoint rather than
  adding another `csrf_exempt` wrapper.
- API-token callers remain CSRF-free only when authenticated by
  `shared.api_tokens.authentication.ApiTokenAuthentication` and authorized by
  the existing upload-write scope gate.
- `navigator.sendBeacon()` support, if retained, should send a form-encoded or
  multipart body that includes both `upload_token` and Django's
  `csrfmiddlewaretoken`. A JSON `Blob` cannot carry the custom `X-CSRFToken`
  header and should not be the unload transport for session-auth mutation.
- State mutation must be bounded to a validated cancel: a non-empty signed
  upload token for the acting user, accepted by `cms.services.cancel_upload`,
  and correlated with the current session upload lock. Missing, blank,
  malformed, expired, wrong-user, or stale-token requests must not clear the
  session lock.
- Empty-body unload cleanup is not a contract. If the browser cannot provide a
  token and CSRF value during unload, the existing `UPLOAD_LOCK_TIMEOUT` fallback
  is the bounded recovery path.
- S3 delete remains best effort after token validation. A storage-delete failure
  may be logged and still allow the current session lock to clear, because the
  cancel authority was already validated and object deletion is cleanup.
- No new ADR is needed unless the implementation changes enforceable guardrails,
  auth defaults, import boundaries, or workflow policy.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #565 |
| --- | --- | --- |
| HTTP/API surface | `mission_control.api.uploads.UploadCancelView`, `mission_control.api.views`, `mission_control.views.__init__` lazy wrappers, `/api/v1/mission-control/upload/cancel/` and legacy `/mission-control/api/upload/cancel/` routes | Fix the live DRF class and leave both route families consistent. Do not fork behavior by URL namespace. |
| Session auth and CSRF | `config.settings.MIDDLEWARE` with `CsrfViewMiddleware`, DRF `SessionAuthentication`, template `{% csrf_token %}` and existing `X-CSRFToken` fetch pattern | Session-cookie mutation remains CSRF-protected. Do not use `@csrf_exempt` or `CsrfExemptSessionAuthentication` for this endpoint. |
| API-token auth | `shared.api_tokens.authentication.ApiTokenAuthentication`, `shared.api.permissions.IsAuthenticatedSessionOrApiToken`, `mission_control.api.permissions.HasMissionControlActor`, `_upload_write_permission()` | Token callers require `mission_control:upload:write`; invalid bearer input fails closed before session fallback. |
| Request shape | `mission_control.api.serializers.UploadCancelSerializer` and `_validated(...)` | Tighten the canonical serializer/request gate instead of parsing a second cancel DTO in the view. |
| Upload authority | `cms.services.cancel_upload`, `cms.assets.upload_token.verify_upload_token` | The signed upload token remains the authority for user id, S3 key, filename, expected size, OS, agent type, and expiry. |
| Session lock | `mission_control.upload_session.check_upload_in_progress`, `set_upload_in_progress`, `UPLOAD_LOCK_TIMEOUT` | Keep lock semantics centralized here. If the lock needs an upload fingerprint or cancel nonce, add it to this module rather than scattering session keys. |
| Browser client | `shifter/shifter_platform/static/js/upload.js` and `upload.test.js` | Keep cancel payload construction in one client helper. `DirectUploader` is shared by agent and script uploads, so unload-cancel behavior must be optioned or scoped to endpoints that actually support cancel. |
| Script upload distinction | `mission_control.api.resources.ScriptUploadView`, `cms.experiments` script-upload services | Do not conflate agent cancel with script upload completion. The script page currently reuses `DirectUploader` with one upload URL and no agent cancel endpoint. |
| Error envelopes | `MissionControlAPIView.bad_request/error_response`, `shared.api.errors.api_error_response`, legacy flat `{"error": ...}` compatibility | Return fixed/sanitized errors. Do not serialize raw token, CSRF, S3, or exception details. |
| Logging | module loggers plus `shared.log_sanitize.safe_log_value` | Log route/action, user id/email, sanitized S3 key where needed, and outcome. Never log upload tokens, CSRF tokens, cookies, presigned URLs, request bodies, or raw provider payloads. |
| Tests | `tests/mission_control/test_views_uploads.py`, API-token tests, `tests/cms/test_services_upload_cancel.py`, `tests/mission_control/test_upload_session.py`, `static/js/upload.test.js` | Drive real view/service behavior with real signed upload tokens where practical; patch only browser/AWS boundaries. Retire tests that enshrine empty-body lock clearing. |

## Cross-Cutting Layers

- Auth surface: requests pass through Django `AuthenticationMiddleware` and DRF
  authenticators. Browser sessions use DRF `SessionAuthentication` and must
  satisfy CSRF on unsafe methods. Programmatic clients use bearer tokens through
  `ApiTokenAuthentication`; a bad bearer token must not fall through to session
  auth on the same request.
- Scope authorization surface: token requests pass through
  `_upload_write_permission()` backed by `mission_control:upload:write`. Session
  requests pass through the token scope permission but still need
  `HasMissionControlActor` and service-layer user ownership checks.
- CSRF surface: the cancel button/error path may keep JSON plus `X-CSRFToken`.
  The unload path must use a body format Django can parse for
  `csrfmiddlewaretoken`, such as `URLSearchParams` or `FormData`. Do not put CSRF
  tokens in query strings, schema examples, logs, or command-line examples.
- Request validation surface: DRF parsing plus `UploadCancelSerializer` should
  reject missing/blank `upload_token` for cancel mutation. Malformed bodies
  should return a bounded validation error and leave the session lock untouched.
- Upload-token surface: `cms.assets.upload_token.verify_upload_token` verifies
  signature, expiry, and user id before any storage cleanup or session unlock.
  The view must not trust request JSON/form fields for S3 key, filename, size,
  OS, or agent type.
- Session-lock surface: clearing a lock should require both a validated upload
  token and a match to the current session's initiated upload, preferably via a
  non-secret token fingerprint or a cancel nonce managed by
  `mission_control.upload_session`. Do not store raw upload tokens in session
  state.
- Storage surface: deletion goes through `cms.services.cancel_upload` and
  `cms.assets.s3` wrappers. Do not shell out to cloud CLIs, pass tokens or S3
  keys through process argv, or introduce provider-specific cleanup paths in the
  view.
- Error-envelope surface: legacy routes retain flat `{"error": "..."}` strings;
  canonical `/api/v1/` routes use the platform DRF error envelope. Both must use
  authored/sanitized messages and must not reveal token validity internals beyond
  a generic invalid-request class.
- Secret-handling surface: upload tokens, presigned URLs, CSRF tokens, session
  cookies, bearer tokens, S3 keys, and provider diagnostics are secret-bearing or
  sensitive. Keep them out of logs, audit JSON, response details, URL query
  strings, process argv, environment files, ConfigMaps, CI summaries, and docs
  examples.
- Config/env surface: this issue should not add settings. If a future policy
  knob is unavoidable, bind it through `config.settings` and update the env
  manifest/runtime surfaces; do not special-case CSRF trusted origins, CORS, or
  cookie settings for cancel.
- Import-boundary surface: API code may import `shared` helpers and public
  service facades such as `cms.services`. Do not import private CMS service
  submodules from Mission Control or add cross-app dependencies to solve cancel.

## Extensibility

The extension seam belongs in two places:

- `mission_control.upload_session` for the cancel/session correlation value
  (`upload_token` fingerprint or `cancel_nonce`) and timeout policy.
- `DirectUploader` for cancel transport selection and payload construction.

That keeps the next reasonable variations local: switching unload from
`sendBeacon()` to `fetch(..., {keepalive: true})`, supporting an explicit
cancel-only endpoint for script uploads, or adding a current-upload nonce without
rewriting the CMS storage service or duplicating serializers.

The seam should be data-shaped, not endpoint prose: a cancel-capable uploader
instance knows whether unload cancel is enabled and how to encode `{upload_token,
csrfmiddlewaretoken}`. Non-cancel-capable uploaders should not send unload
beacons to endpoints that interpret `upload_token` as completion.

## Whole-Repo Scope

Likely implementation will touch some of these surfaces:

- `shifter/shifter_platform/mission_control/api/uploads.py`
- `shifter/shifter_platform/mission_control/api/authentication.py`
- `shifter/shifter_platform/mission_control/api/serializers.py`
- `shifter/shifter_platform/mission_control/api/_base.py`
- `shifter/shifter_platform/mission_control/views/__init__.py`
- `shifter/shifter_platform/mission_control/views/_uploads.py`
- `shifter/shifter_platform/mission_control/upload_session.py`
- `shifter/shifter_platform/static/js/upload.js`
- `shifter/shifter_platform/templates/mission_control/agents.html`
- `shifter/shifter_platform/templates/mission_control/files.html`
- `shifter/shifter_platform/cms/services/_uploads.py`
- `shifter/shifter_platform/cms/assets/upload_token.py`
- `shifter/shifter_platform/shared/api_tokens/*`
- `shifter/shifter_platform/shared/api/errors.py`
- `shifter/shifter_platform/shared/errors.py`
- `shifter/shifter_platform/shared/log_sanitize.py`
- `shifter/shifter_platform/config/_drf_settings.py`
- `shifter/shifter_platform/config/settings.py`
- tests under `shifter/shifter_platform/tests/mission_control`,
  `tests/cms`, `tests/shared`, `tests/config`, and
  `shifter/shifter_platform/static/js/upload.test.js`

Whole-repo checks in scope include ADR-001 import boundaries, ADR-003
architecture gates, DRF settings invariants, `/api/v1/` route conventions,
legacy Mission Control route compatibility, and the shared JavaScript uploader's
script-upload caller.

## Gotchas And Anti-Patterns

- Do not keep `CsrfExemptSessionAuthentication` as the cancel endpoint's session
  authenticator and claim the upload token alone solves CSRF.
- Do not accept empty or malformed unload bodies as successful cancel requests.
- Do not clear the session lock before upload-token verification succeeds.
- Do not let a valid old same-user token clear an unrelated current upload lock.
- Do not add a second upload-token schema, second upload-lock session key, second
  exception hierarchy, or app-local API-token permission.
- Do not log upload tokens, CSRF tokens, request bodies, presigned URLs, raw S3
  errors, or full Authorization/Cookie headers.
- Do not put upload tokens or CSRF tokens in URL query strings to make unload
  cancel convenient.
- Do not broaden `CSRF_TRUSTED_ORIGINS`, CORS, `ALLOWED_HOSTS`, SameSite cookie
  policy, WAF, or ingress rules to make cancel pass.
- Do not make script upload completion share agent-upload cancel semantics by
  accident through `DirectUploader`.
- Do not depend on unload delivery for correctness. Browser unload beacons are
  best effort; timeout-based recovery remains required.
- Do not solve static-analysis findings with `# NOSONAR` or comments while the
  live endpoint still bypasses CSRF.

## Non-Goals

- Replacing presigned direct-to-storage uploads.
- Reworking server-side content inspection, file type validation, storage quota,
  agent creation, or script-upload validation.
- Adding a durable upload-job model, background cleanup worker, object lifecycle
  policy, or audit table.
- Changing API-token scope vocabulary, OIDC/Identity Platform behavior, global
  DRF defaults, CSRF trusted origins, cookie settings, or storage provider
  adapters.
- Guaranteeing cleanup on every browser/tab close. The unload signal is
  opportunistic; correctness comes from validated cancel plus lock timeout.
- Adding Ground Control requirements or traceability for this requirement-free
  issue.

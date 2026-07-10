# CMS DRF API Migration Preflight (PLAT-106 / #1122)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: PLAT-106, "Unified DRF API Surface"

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1122>

Superseded note: ADR-027 / issue #1195 removed the legacy experiment API and
script-upload surfaces. The scenario-editor DRF guidance remains active; the
experiment portions are historical.

This note narrows the repo-wide PLAT-106 DRF conventions to the CMS
experiments and scenario-editor JSON API migration. It is intentionally not an
implementation plan.

## Scope Boundary

Issue #1122 migrates non-public CMS HTTP/JSON endpoints from ad-hoc Django
function views onto the platform DRF surface. DRF owns only HTTP concerns:
authentication, scope admission, request/response serializers, parser
selection, error envelope, pagination/filter query validation where applicable,
and OpenAPI metadata.

Application behavior stays in the existing CMS service seams:

- `cms.experiments.services` owns experiment scenario access, script upload
  initiation/completion/deletion, S3 wrapper calls, and experiment audit.
- `cms.scenario_editor.services` owns YAML parsing, scenario create/update,
  clone/delete/toggle behavior, editable/default scenario policy, validation,
  persistence, and scenario audit.
- `cms.scenarios.registry` and `cms.scenarios.schema` remain the authoritative
  scenario lookup and Pydantic domain schema.
- `shared.auth` remains the authoritative CMS authoring policy.

Server-rendered CMS authoring pages stay as HTML routes. Existing HTML views may
keep form rendering, redirects, Django messages, and browser-only templates.
The canonical JSON API should live under `/api/v1/` and return platform API
responses.

## Architecture Decisions

- Mount the canonical CMS API under `/api/v1/cms/` through `config/api_urls.py`.
  Do not add app-local schema or docs routes.
- Reuse the platform DRF defaults from `config/_drf_settings.py`:
  `shared.api_tokens.authentication.ApiTokenAuthentication` first, then DRF
  `SessionAuthentication`, with `shared.api.errors.api_exception_handler`.
- Use `shared.api.permissions.IsAuthenticatedSessionOrApiToken` and
  `shared.api_tokens.permissions.require_scope(...)` with
  `shared.api_tokens.scopes.CMS_AUTHORING_READ` and
  `CMS_AUTHORING_WRITE`. Scopes admit token callers to an endpoint class; they
  do not prove CMS authoring permission or scenario/script ownership.
- Preserve the existing second-stage authorization by reusing
  `shared.auth.can_edit_cms_authoring` at the DRF permission layer and
  `shared.auth.validate_cms_authoring_user` in the services. Do not apply the
  `threat_research_required` HTML decorator directly to DRF API views because
  it redirects and writes Django messages instead of returning API errors.
- Resolve the CMS actor from an authenticated session user or from
  `ApiToken.created_by`, mirroring the Mission Control and CTF DRF actor
  pattern without importing either app. Token requests whose owner is missing,
  inactive, or not a CMS authoring user must fail before CMS services run.
- Keep serializer validation HTTP-shaped. DRF serializers may validate body,
  path, query, and response shapes, but scenario definition rules stay in
  `cms.scenario_editor.services`, `cms.scenario_editor._validation`, and
  `cms.scenarios.schema`.
- Treat YAML validation as a domain operation. A syntactically valid request
  whose YAML is invalid may keep a `valid: false` style domain response for the
  editor contract; malformed HTTP bodies and serializer failures use the shared
  DRF error envelope.
- Treat script-upload initiation as secret-bearing JSON if it is included in
  #1122. It returns presigned URLs, S3 keys, and upload tokens through
  `cms.experiments.services.initiate_script_upload`; do not duplicate that flow
  in serializers or confuse upload tokens with platform API tokens.
- Preserve the existing `EXPERIMENTS_ENABLED` exposure boundary. The current
  experiments HTML routes are only registered when the feature flag is on; a
  canonical API mount must not make unfinished experiment surfaces reachable
  when that flag is false.
- No new ADR is needed unless the implementation changes enforceable
  guardrails, import boundaries, workflow policy, token semantics, or global
  DRF settings.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1122 |
| --- | --- | --- |
| API mount and schema | `config/api_urls.py`, `/api/v1/`, `drf_spectacular` | Register CMS once through the platform v1 mount; no app-local schema/docs route. |
| DRF auth and errors | `config/_drf_settings.py`, `shared.api.errors`, `shared.api.permissions` | Use shared defaults and envelope; no CMS-local authenticator or exception framework. |
| Token scopes | `shared.api_tokens.scopes`, `shared.api_tokens.permissions.require_scope` | Use `cms:authoring:read` and `cms:authoring:write` centrally; no hard-coded scope strings in method bodies. |
| Session/domain authorization | `shared.auth.can_edit_cms_authoring`, `validate_cms_authoring_user`, `threat_research_required` semantics | API permission reuses the predicate; services keep the validator. Do not return HTML redirects from API routes. |
| Token actor | `shared.api_tokens.models.ApiToken.created_by` | A token acts as its owning active user for CMS authoring checks; the scope alone is insufficient. |
| Experiment services | `cms.experiments.services` public facade | DRF views call public service functions such as `get_scenario_instances`, `initiate_script_upload`, `complete_script_upload`, and `delete_script`. |
| Scenario editor services | `cms.scenario_editor.services` public facade | DRF views call YAML/create/update/delete/toggle helpers instead of importing private modules or duplicating workflow logic. |
| Scenario schema | `cms.scenarios.schema.ScenarioTemplate`, `cms.scenarios.registry` | Pydantic/domain validation remains authoritative; serializers do not fork scenario rules. |
| Script upload shape | `cms.experiments.schemas.ScriptUploadInput`, `cms.experiments.s3`, `shared.uploads.inspection` | DRF serializers validate HTTP input only; service validation, signed upload tokens, S3 verification, and full-body script inspection remain service-owned. |
| Feature flag | `config.settings.EXPERIMENTS_ENABLED`, `config.urls` route gating | API exposure for experiment endpoints must preserve the same disabled-by-default boundary. |
| Audit and persistence | `risk_register.services.audit_log`, `AuditEvent`, CMS models/services | Mutations stay audited by services; do not add a second CMS API audit path. |
| Logging hygiene | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Log action, request id, user id, and sanitized identifiers only. Never log tokens, YAML bodies, presigned URLs, or upload bodies. |
| Tests | `rest_framework.test.APIClient`, existing CMS/scenario-editor behavior tests, shared token tests | Add HTTP-boundary DRF coverage plus focused serializer/permission tests; keep service tests service-shaped. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: requests pass through Django authentication middleware and DRF
  authenticators. Browser/SPA callers use session cookies and
  `SessionAuthentication`; programmatic callers use `Authorization: Bearer
  shf_...` through `ApiTokenAuthentication`. A malformed, revoked, expired, or
  wrong-prefix bearer token returns 401 and must not fall through to a logged-in
  session on the same request.
- Scope surface: every non-public CMS API endpoint declares central scopes.
  Reads use `cms:authoring:read`; mutations use `cms:authoring:write` unless a
  future reviewed split introduces more specific CMS scopes. Session requests
  pass through the token-scope gate but still need CMS authoring permission.
- CMS authoring surface: after scope admission, the actor must be an active
  staff user or active Threat Research member through `can_edit_cms_authoring`.
  Services still call `validate_cms_authoring_user`, so a scoped token owned by
  a regular, inactive, or deleted user cannot reach CMS behavior.
- CSRF surface: unsafe session-authenticated API calls remain CSRF-protected by
  Django `CsrfViewMiddleware` and DRF `SessionAuthentication`. Token-authenticated
  programmatic calls are cookie-free and do not require CSRF. Do not add
  `csrf_exempt` or a CSRF-exempt session authenticator.
- Feature-flag/config surface: experiment API routes must preserve
  `EXPERIMENTS_ENABLED`. This issue should not add settings; if a setting is
  unavoidable, bind it through `config.settings` and update
  `config/env-manifest.json` plus tests.
- Payload and query validation surface: DRF serializers validate HTTP body,
  path, and query shapes. Domain validation stays in `ScriptUploadInput`,
  `ScenarioTemplate`, `validate_yaml`, `validate_scenario_payload`, upload-token
  verification, and service-layer ownership/state checks.
- YAML parser surface: YAML parsing stays in `cms.scenario_editor.services`
  through `yaml.safe_load` and Pydantic validation. The API layer must not log
  `yaml_content`, echo stack traces, or create a second YAML parser/validator.
- Upload-token and storage surface: script-upload initiation/completion stays
  behind `cms.experiments.services`, `cms.experiments.s3`, `cms.assets` patterns,
  and `shared.cloud` storage adapters. Do not shell out to cloud CLIs or pass
  upload tokens, S3 keys, or signed URLs through process argv.
- Error-envelope surface: canonical `/api/v1/cms/` errors use
  `shared.api.errors.api_error_response` or DRF exceptions wrapped by the shared
  handler. Field details may come from serializers. Unknown exceptions, raw
  provider payloads, raw YAML parser exceptions, upload-token internals, and
  object-ownership details must not be serialized.
- Secret-handling surface: Authorization headers, raw platform tokens, session
  cookies, CSRF tokens, script upload tokens, presigned URLs, uploaded script
  bodies, scenario YAML bodies, S3 provider diagnostics, and future secret-like
  scenario content must stay out of logs, audit JSON, OpenAPI examples, docs
  snippets, URL query strings, process argv, environment files, and CI output.
- Audit/observability surface: service-owned audit calls remain the durable
  audit trail. Logs use request correlation from middleware and sanitized IDs.
  Do not add per-request API audit writes or a CMS-specific audit table without
  a separate volume and retention decision.
- Import-boundary surface: CMS API modules may import `shared` and CMS public
  service facades. Per `.importlinter` and ADR-001, CMS must not depend on
  Mission Control or CTF, and API work must not introduce direct `cyberscript`
  imports outside `shared`.
- OpenAPI surface: generated schema must see the canonical CMS routes,
  serializers, auth, and required scopes. Examples must use placeholders only
  and must not include real bearer tokens, upload tokens, scenario YAML bodies,
  presigned URLs, S3 keys, or script content.

## Extensibility Seams

- Actor seam: centralize session/token-to-CMS-actor resolution once in the CMS
  API boundary so future service-account or delegated-authoring decisions have
  one place to extend.
- Scope declaration seam: keep required read/write scopes as class-level or
  data-like declarations that both permissions and OpenAPI metadata can read.
  This keeps a future split such as script-specific CMS scopes from requiring
  service rewrites.
- Route seam: versioned routing belongs in `config/api_urls.py` and an app-local
  CMS API URL module. A future `/api/v2/cms/` should be route/schema work, not a
  CMS service rewrite.
- Feature-flag seam: keep experiment API exposure gated at route registration or
  a single API boundary helper so graduating experiments from disabled-by-default
  changes one canonical place.
- Compatibility seam: if legacy HTML/AJAX URLs must remain temporarily, adapt
  response shape at the route edge. Do not move compatibility envelopes into CMS
  services or fork the service behavior by URL family.

## Whole-Repo Scope

Likely in-scope surfaces for the implementation are:

- `shifter/shifter_platform/config/api_urls.py`, and existing route exposure in
  `config/urls.py` for the experiments feature flag.
- `shifter/shifter_platform/shared/api/*`,
  `shared/api_tokens/*`, `shared/auth.py`, `shared/errors.py`, and
  `shared/log_sanitize.py`.
- Future CMS API modules under `shifter/shifter_platform/cms/`.
- `shifter/shifter_platform/cms/experiments/urls.py`,
  `cms/experiments/views/_ajax.py`, `cms/experiments/views/_scripts.py`,
  `cms/experiments/services/*`, `cms/experiments/schemas.py`, and
  `cms/experiments/s3.py`.
- `shifter/shifter_platform/cms/scenario_editor/urls.py`,
  `cms/scenario_editor/views_yaml.py`, `views_actions.py`, `services.py`,
  `_post_helpers.py`, `_validation.py`, and `view_support.py`.
- `shifter/shifter_platform/cms/scenarios/registry.py` and
  `cms/scenarios/schema.py`.
- Browser callers in CMS templates/static JavaScript that currently target
  legacy JSON URLs.
- Tests under `shifter/shifter_platform/tests/cms`,
  `tests/scenario_editor`, `tests/shared`, and `tests/config`.

Whole-repo checks in scope include ADR-001 import boundaries, ADR-003
architecture gates, DRF settings invariants, `/api/v1/` route/schema
conventions, CMS feature-flag exposure, API-token scope behavior, and shared
error-envelope behavior.

## Gotchas And Anti-Patterns

- Do not treat `cms:authoring:*` as staff or Threat Research membership.
- Do not let a scoped API token owned by a non-authoring user call CMS services.
- Do not apply `threat_research_required` directly to API views; it is an HTML
  decorator with redirects/messages, not a DRF permission.
- Do not expose experiments under `/api/v1/` while `EXPERIMENTS_ENABLED` is
  false.
- Do not duplicate `ScenarioTemplate`, `ScriptUploadInput`, YAML validation, or
  scenario ID rules in DRF serializers.
- Do not parse JSON/YAML by hand in views when a serializer and the existing
  service validator already cover the shape.
- Do not return raw `str(exc)` for `ScenarioEditorError`, `ExperimentError`,
  YAML parser errors, storage errors, or unexpected exceptions.
- Do not log `yaml_content`, script upload bodies, upload tokens, bearer tokens,
  CSRF tokens, cookies, presigned URLs, or full provider diagnostics.
- Do not put bearer tokens, upload tokens, presigned URLs, or CSRF tokens in
  query strings, OpenAPI examples, shell commands, or docs snippets.
- Do not confuse platform `ApiToken` scopes with HMAC script upload tokens; they
  solve different authorization problems.
- Do not import Mission Control or CTF helpers into CMS API modules to reuse an
  actor/permission shortcut.
- Do not move service audit, persistence, S3 verification, or full-body script
  inspection into serializers.
- Do not make the OpenAPI schema public as a side effect of adding CMS routes.

## Non-Goals

- No implementation in this preflight note.
- No new ADR unless implementation changes enforceable architecture policy.
- No migration of Mission Control, CTF, risk-register legacy API keys, or token
  management.
- No redesign of CMS authoring roles, scenario registry/schema, experiment
  lifecycle, script-upload storage, upload-token format, audit storage, or
  service package structure.
- No completion or redesign of the experiments feature beyond preserving its
  current exposure boundary.
- No public unauthenticated CMS API.
- No changes to OIDC, Django sessions, CSRF trusted origins, CORS, cookie
  policy, Terraform/Kubernetes, or runtime secret delivery unless a later issue
  explicitly scopes them.

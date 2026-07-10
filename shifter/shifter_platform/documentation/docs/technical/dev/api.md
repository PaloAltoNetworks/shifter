# Platform API Development

Shifter's non-public HTTP/JSON API is a Django REST Framework surface mounted
under `/api/v1/`. New API endpoints should join that surface instead of adding
ad-hoc `JsonResponse` function views.

## Endpoint Shape

- Put request and response validation in DRF serializers.
- Put application behavior in the existing service layer (`cms.services`,
  `ctf.services`, `engine.services`, `risk_register.services`, or the owning
  app's public facade).
- Use `APIView` or `ViewSet` for HTTP concerns only: authentication,
  permissions, serializer selection, response status, pagination, filtering, and
  OpenAPI metadata.
- Mount app routers through `config/api_urls.py` so the public path remains
  `/api/v1/...` and the OpenAPI schema sees every migrated route.

## Authentication And Scopes

The platform DRF defaults authenticate in this order:

1. `shared.api_tokens.authentication.ApiTokenAuthentication`
2. `rest_framework.authentication.SessionAuthentication`

New endpoints should use platform bearer tokens and session auth. Do not accept
new API key formats outside the shared token model. The legacy risk-register
`X-API-Key` (`rr_live_`) credential was retired (PLAT-106 / #1124): it no longer
authenticates, its management endpoints and UI are removed, and it is gone from
the OpenAPI schema. The `risk_register` `/api/v1` surface authenticates only via
platform `ApiToken` (`risk:read` / `risk:write`) and session.

Token scopes come from `shared.api_tokens.scopes`. Compose
`shared.api_tokens.permissions.require_scope(read_scope, write_scope)` with the
endpoint's session/domain permission. Scopes admit a token to an endpoint class;
they do not replace object ownership, event membership, staff checks, CMS
authoring checks, or service-layer state validation.

Active Mission Control scopes:

| Scope | Grants |
| --- | --- |
| `mission_control:range:read` | Current range, agents, and scenarios reads. |
| `mission_control:range:write` | Range launch and lifecycle mutations. |
| `mission_control:upload:write` | Agent upload initiate, complete, and cancel. |
| `mission_control:guacamole:read` | Guacamole RDP/SSH bootstrap, status, and opener endpoints. |
| `mission_control:ngfw:read` | NGFW listing. |
| `mission_control:ngfw:write` | NGFW create and destroy. |
| `mission_control:credentials:write` | Mission Control credential create and delete. |

Active CMS authoring scopes:

| Scope | Grants |
| --- | --- |
| `cms:authoring:read` | CMS authoring reads such as scenario-editor YAML validation, subject to CMS authoring checks. |
| `cms:authoring:write` | CMS authoring mutations such as YAML scenario creation, subject to CMS authoring checks. |

## CMS Migration Guardrails

CMS JSON endpoints that move under `/api/v1/cms/` should register through
`config/api_urls.py`; server-rendered scenario-editor pages stay on their
existing HTML routes. DRF views may translate request/response shape, status
codes, and schema metadata, but must continue to call
`cms.scenario_editor.services` for business behavior.

Preserve the second-stage CMS authoring gate after scope admission. API-token
requests act as `ApiToken.created_by`, and the resolved actor must still be an
active staff user or active `Threat Research` group member through
`shared.auth.can_edit_cms_authoring`. Services keep using
`shared.auth.validate_cms_authoring_user`; do not recreate group checks in
serializers or treat `cms:authoring:*` as a role.

YAML parsing, scenario schema validation, audit, and persistence stay
service-owned. Keep bearer tokens, CSRF tokens, YAML bodies, examples, docs
snippets, and process arguments out of logs.

## Mission Control Migration Guardrails

Mission Control JSON endpoints that move under `/api/v1/` should register
through `config/api_urls.py`; `mission_control/urls.py` remains for
server-rendered pages and temporary legacy compatibility only. DRF views may
translate request/response shape, status codes, and schema metadata, but must
continue to call the canonical service facades: `cms.services` for range,
agent, upload, credential, NGFW, scenario, and script workflows; `engine.services`
for terminal/Guacamole connection resolution already exposed through the
Mission Control helpers; and `mission_control.guacamole_bootstrap` for the
pollable signed-URL flow.

Preserve the existing second-stage authorization after scope admission. Range
lifecycle mutations still enforce `shared.auth.block_ctf_participant_only(...)`
semantics and service-layer ownership/state checks. Staff or Threat Research
authoring checks should use the shared predicates in `shared.auth`; do not
recreate group-name logic in serializers or view classes. Token scopes stay in
`shared.api_tokens.scopes`; add explicit new scopes there when a Mission Control
subsurface needs a different token audience instead of hard-coding strings or
overloading `mission_control:range:*`.

Reuse existing request/domain contracts. Serializer fields may wrap current
`shared.schemas` Pydantic contracts such as credential and app specs, but should
not fork their validation rules. Upload and Guacamole responses carry secret or
secret-adjacent material: presigned URLs, upload tokens, and signed Guacamole
URLs must never be logged, included in OpenAPI examples, or returned more
broadly than the current flow allows. The Guacamole bootstrap status endpoint
must keep owner-scoped polling, single-use URL delivery, expiry handling,
`Retry-After`, and worker-capacity behavior.

## Errors

DRF exceptions use the platform envelope:

```json
{
  "error": {
    "code": "invalid",
    "message": "Invalid request",
    "details": {
      "field": ["This field is required."]
    },
    "request_id": "req-123"
  }
}
```

Use `shared.api.errors.api_error_response(...)` for explicit DRF error
responses. Do not return raw exception text, provider payloads, bearer tokens,
cookies, CSRF tokens, presigned URLs, or signed Guacamole URLs.

## Schema And Docs

OpenAPI is served from `/api/v1/schema/`; Swagger UI is served from
`/api/v1/docs/`. These endpoints use the same platform authentication posture
as the non-public API: an authenticated session user or a valid platform API
token can read the contract. Swagger UI assets are served from the pinned local
`drf-spectacular-sidecar` package, not from a third-party CDN.

Keep examples secret-free. Show header names and placeholder values, not real
tokens or signed URLs.

## Pagination And Filtering

The default list behavior is page-number pagination with page size 50. The
platform enables DRF's search and ordering filter backends globally, but each
endpoint must declare its supported `search_fields` and `ordering_fields`.
Prefer serializer- or filterset-shaped query validation for new filters instead
of parsing unbounded query parameters in `get_queryset()`.

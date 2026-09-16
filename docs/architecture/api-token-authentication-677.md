# API Token Authentication — Decision Record (PLAT-102 / #677)

Status: implemented (foundation)

Date: 2026-06-23

Companion to the binding preflight guardrails in
[`api-token-authentication-preflight-677.md`](api-token-authentication-preflight-677.md).
This record captures the decisions made implementing the PLAT-102 foundation
and the platform direction (PLAT-106) it serves.

## Context

The platform had both Django REST Framework endpoints and ad-hoc Django
function views returning `JsonResponse` (Mission Control, CTF, CMS). PLAT-102
requires platform-wide API authentication via session cookies (browser/SPA) and
scoped programmatic tokens. A single, coherent, scoped DRF API is the desired
end state (PLAT-106).

## Decisions

1. **One platform token principal, owned by `shared`.** The scoped token model,
   scope registry, DRF authentication class, scope permission, and Django-admin
   surface live in `shared/api_tokens/`. `shared` is the only layer every app may
   import, so apps can enforce scopes without a cross-app dependency. The model
   belongs to the `shared` Django app (migration under `shared/migrations/`).

2. **Audit at the edge.** The token model is free of app-layer imports. Audit
   writes (create / revoke / auth-failure) use the canonical shared audit port
   through `shared/api_tokens/audit.py`. This keeps the principal layer
   import-clean. Successful authentication is not audited per request
   (write-amplification); coalesced `last_used_at` provides liveness instead.

3. **Opaque token, non-reversible verifier.** Format `shf_<token_id>.<secret>`.
   `token_id` is the public lookup id (fixing the legacy single-prefix
   uniqueness defect); `secret` is 32 bytes of CSPRNG output; only its SHA-256
   verifier is stored and compared in constant time. The raw token is shown once
   at creation and never persisted, logged, or placed in audit/URLs/env.

4. **Scopes are additive HTTP-boundary admission.** `<resource>:<operation>`
   scopes live in one central registry. The DRF `RequireScope` permission checks
   the token dimension; existing service-layer ownership/role/state
   authorization still runs. No wildcard scopes.

5. **Fail closed.** A supplied-but-invalid bearer token is an authentication
   failure (401) and never falls through to a session on the same request. No
   bearer credential falls back to session auth.

6. **Session auth and CSRF unchanged.** Browser/SPA clients keep DRF
   `SessionAuthentication` + CSRF. The requirement's session/token split is
   SPA-ready as written.

7. **Admin UI via Django admin.** Staff/superuser create (display-once) and
   revoke tokens. Creation defaults expiry to a bounded ceiling
   (`API_TOKEN_MAX_TTL_DAYS`) so tokens are not indefinitely valid.

8. **One token model.** The retired feature-local `APIKey` model and
   `X-API-Key` authentication path were removed with the feature under ADR-045.
   `ApiToken` is the sole programmatic token principal.

## Scope of this change vs. the direction

This issue shipped the foundation. Migrating the CTF / Mission Control / CMS
function-view JSON APIs onto DRF + scopes is tracked under PLAT-106 and the
*Unified DRF API Surface* milestone (#1119 conventions/OpenAPI, #1120 Mission
Control, #1121 CTF, #1122 CMS). The scope registry reserves the names those
migrations enforce, so they extend the registry without touching the token
model.

## Consequences

- A single, reusable token + scope primitive every app can adopt.
- No enforcement-guardrail files changed, so no `docs/adr/index.yaml` entry is
  required; this prose record lives with the other architecture notes.
- The per-app DRF migration remains incremental and independently shippable.

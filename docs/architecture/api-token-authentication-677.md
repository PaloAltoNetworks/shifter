# API Token Authentication — Decision Record (PLAT-102 / #677)

Status: implemented (foundation)

Date: 2026-06-23

Companion to the binding preflight guardrails in
[`api-token-authentication-preflight-677.md`](api-token-authentication-preflight-677.md).
This record captures the decisions made implementing the PLAT-102 foundation
and the platform direction (PLAT-106) it serves.

## Context

The platform had two API styles: Django REST Framework (risk-register
`/api/v1`) and ad-hoc Django function views returning `JsonResponse` (Mission
Control, CTF, CMS). Only risk-register had any token scheme, and that token was
denied on every endpoint. PLAT-102 requires platform-wide API authentication via
session cookies (browser/SPA) and scoped programmatic tokens. A future SPA
frontend makes a single, coherent, scoped DRF API the desired end state
(PLAT-106).

## Decisions

1. **One platform token principal, owned by `shared`.** The scoped token model,
   scope registry, DRF authentication class, scope permission, and Django-admin
   surface live in `shared/api_tokens/`. `shared` is the only layer every app may
   import, so apps can enforce scopes without a cross-app dependency. The model
   belongs to the `shared` Django app (migration under `shared/migrations/`).

2. **Audit at the edge.** The token model is free of app-layer imports. Audit
   writes (create / revoke / auth-failure) reuse the canonical
   `risk_register.services` audit store via a lazy, call-local import in
   `shared/api_tokens/audit.py`. This keeps the principal layer import-clean while
   avoiding a risky relocation of the audit model. Successful authentication is
   not audited per request (write-amplification); coalesced `last_used_at`
   provides liveness instead.

3. **Opaque token, non-reversible verifier.** Format `shf_<token_id>.<secret>`.
   `token_id` is the public lookup id (fixing the legacy single-prefix
   uniqueness defect); `secret` is 32 bytes of CSPRNG output; only its SHA-256
   verifier is stored and compared in constant time. The raw token is shown once
   at creation and never persisted, logged, or placed in audit/URLs/env.

4. **Scopes are additive HTTP-boundary admission.** `<resource>:<operation>`
   scopes (e.g. `risk:read`, `risk:write`) live in one central registry. The DRF
   `RequireScope` permission checks the token dimension; existing service-layer
   ownership/role/state authorization still runs. No wildcard scopes.

5. **Fail closed.** A supplied-but-invalid bearer token is an authentication
   failure (401) and never falls through to a session on the same request. No
   bearer credential falls back to session auth.

6. **Session auth and CSRF unchanged.** Browser/SPA clients keep DRF
   `SessionAuthentication` + CSRF. The requirement's session/token split is
   SPA-ready as written.

7. **Admin UI via Django admin.** Staff/superuser create (display-once) and
   revoke tokens. Creation defaults expiry to a bounded ceiling
   (`API_TOKEN_MAX_TTL_DAYS`) so tokens are not indefinitely valid.

8. **Legacy risk-register `APIKey` deprecated, not removed.** It stays functional
   for existing `/api/v1` `X-API-Key` consumers; retirement is tracked in #1124.
   No second *active* token system is introduced — `ApiToken` is the
   going-forward principal.

## Scope of this change vs. the direction

This issue ships the foundation and proves it end-to-end on the already-DRF
risk-register surface. Migrating the CTF / Mission Control / CMS function-view
JSON APIs onto DRF + scopes is tracked under PLAT-106 and the *Unified DRF API
Surface* milestone (#1119 conventions/OpenAPI, #1120 Mission Control, #1121 CTF,
#1122 CMS, #1124 legacy-key retirement). The scope registry reserves the names
those migrations will enforce, so they extend the registry without touching the
token model.

## Consequences

- A single, reusable token + scope primitive every app can adopt.
- No enforcement-guardrail files changed, so no `docs/adr/index.yaml` entry is
  required; this prose record lives with the other architecture notes.
- The per-app DRF migration remains incremental and independently shippable.

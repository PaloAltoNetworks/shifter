# CTF Invite Token Delivery Preflight (#1088)

Status: pre-implementation guidance

Date: 2026-06-22

Issue: GitHub #1088, "security: move CTF invite token off the URL query string
(SonarCloud S8435)"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as hardening the existing CTF email magic-link flow, not as a new
identity provider, registration lifecycle, RBAC model, or notification system.

Keep these concepts separate:

1. The invite credential: `CTFParticipant.invite_token`, its expiry, and optional
   single-use clearing.
2. The delivery URL: the email link generated from `SITE_URL` and
   `reverse("ctf:ctf_register")`.
3. The exchange request: the browser-to-Django request that consumes the invite
   credential and creates the normal Django session.
4. Participant authorization after login: existing CTF participant predicates and
   view decorators.

## Architectural Decisions

- Use a fragment-carried token plus a CSRF-protected POST exchange. The email URL
  should be `.../ctf/register/#token=<encoded-token>`, not
  `...?token=<token>`. The URL fragment is not part of the HTTP request target,
  so Django, ALB/proxy access logs, the ECS request formatter, and normal
  referrer headers do not receive the token.
- Keep the magic-link UX: the user clicks one email link, lands on the CTF
  registration surface, and the browser exchanges the token automatically.
- The GET registration surface must render only a minimal exchange page and set a
  CSRF cookie. It must not read `request.GET["token"]`, perform login, or put
  the invite token into server-rendered context.
- The browser should read `window.location.hash`, validate a bounded string token,
  remove the fragment from history with `history.replaceState`, and POST JSON to
  the exchange endpoint with `credentials: "same-origin"` and `X-CSRFToken`.
- The POST exchange consumes the token from the JSON body, validates it against
  `CTFParticipant.is_invite_valid`, calls Django `login(...)`, and preserves the
  existing `MAGIC_LINK_SINGLE_USE` clearing behavior.
- Registration-denial responses should use fixed, authored messages or the
  existing JSON error-envelope style. They must not echo the submitted token,
  upstream exception text, SQL, or stack traces.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1088 |
| --- | --- | --- |
| Invite token source of truth | `CTFParticipant.invite_token`, `invite_token_expires`, `is_invite_valid`, `MAGIC_LINK_SINGLE_USE` | Do not add a second token table, duplicate expiry calculation, or a parallel registration lifecycle unless deliberately migrating the model. |
| Token generation and refresh | `CTFParticipant.save()` and `ctf.services.participant.resend_invite()` | Keep token creation/refresh in the participant lifecycle area, not in templates or views. |
| Invite URL construction | `ctf.services.notification._build_registration_url()` | Keep one URL builder using `SITE_URL` and `reverse()`. Do not build provider-specific URLs in email callers. |
| Email rendering/delivery | `ctf.services.notification._render_email()`, `_send_email()`, `shared.email` | Keep both bulk invite and resend invite on the same rendering path. Be careful that custom DB templates can reference any context variable provided. |
| JSON request parsing | `ctf.views._parse_body_object()` and `_get_body_str()` | Reuse the existing body-shape gates for the POST exchange. Do not add endpoint-local JSON parsing. |
| Auth/session creation | Django `login(...)` with `ModelBackend`; existing Django session middleware | The invite exchange creates the normal app session only after token validation. Do not route this through OIDC or Identity Platform. |
| Participant access control | `ctf.services.participant.is_active_participant`, `eligible_participant_q`, `ctf_participant_required` | After login, downstream authorization stays with existing participant predicates and event-scoped lookup helpers. |
| CSRF | `CsrfViewMiddleware`, `ensure_csrf_cookie`, existing `csrftoken` JavaScript pattern | Do not use `csrf_exempt` for the exchange that creates a session. |
| Runtime URL/config | `config.settings.SITE_URL`, `_oidc_settings.MAGIC_LINK_*`, `config/env-manifest.json`, AWS/GCP runtime renderers | Avoid new env knobs. If a knob is unavoidable, parse it in settings and update the manifest/runtime surfaces. |
| Logging | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint` | Never log invite tokens, cookies, CSRF tokens, request bodies, or full secret-bearing URLs. |
| Error leakage controls | `shared.errors.safe_user_message`, `classify_user_message`, existing CTF JSON envelopes | Return bounded authored errors; keep details server-side and sanitized. |
| Import boundaries | `.importlinter`, `ctf.bridges`, `shared.auth`, `management.services` | Do not make CTF depend on Mission Control or Engine, and do not hide cross-layer dependencies in a new helper. |
| Tests | `tests/ctf/test_auth_registration.py`, `tests/ctf/test_services/test_notification.py`, participant view/API tests, ADR-019 boundary-mock policy | Drive real view/service behavior where practical; patch only framework/network/email boundaries already accepted by the repo. |

## Cross-Cutting Layers

- Auth surface: the GET registration page remains unauthenticated but performs no
  login. The POST exchange is unauthenticated but credential-gated by the invite
  token and CSRF-gated by the cookie set on GET. Successful exchange creates a
  normal Django session; all later CTF access remains behind `@login_required`
  plus existing CTF role/participant gates.
- Secret-handling surface: invite tokens, Django session cookies, CSRF tokens,
  email body URLs, and request bodies are secret-bearing. Keep them out of query
  strings, logs, audit rows, local/session storage, screenshots, GitHub comments,
  artifacts, process argv, and shell history.
- URL/referrer surface: the token may appear in the email hyperlink fragment and
  temporarily in the browser address bar. It must not appear in `request.GET`,
  server-rendered HTML context, redirects, `Location` headers, full request URLs,
  or copied error messages. Add a registration-page `Referrer-Policy` response
  header, preferably `no-referrer`, as defense in depth.
- Request validation surface: the POST body must be a JSON object, the token must
  be a string, and missing/malformed bodies must return a 400 JSON envelope. Use
  existing CTF body parsing helpers for that shape check.
- Persistence surface: validate against the existing participant row and clear
  `invite_token` only through the current `MAGIC_LINK_SINGLE_USE` branch. Do not
  touch scoring, participant status, `registered_at`, team membership, range
  state, or user profile state as part of token exchange unless existing behavior
  already does.
- Config/env surface: `SITE_URL` is already rendered by AWS and GCP runtime paths
  and inventoried by installation tooling. `MAGIC_LINK_EXPIRY_HOURS` and
  `MAGIC_LINK_SINGLE_USE` already live in `_oidc_settings.py` and
  `config/env-manifest.json`. This issue should not add provider-specific
  runtime variables.
- OS/runtime exposure: do not pass invite tokens through CLI arguments,
  management-command options, generated ConfigMaps, Terraform outputs, Kubernetes
  values, process-global debug state, or shell-visible env dumps.
- Error-envelope surface: invalid, missing, expired, and already-consumed tokens
  should not be distinguishable in a way that helps token probing beyond the
  minimum user experience needed. No response may include the token value.
- Observability: use existing ECS JSON logs and sanitized module loggers. Log
  low-cardinality outcomes, participant IDs only when necessary, and token
  fingerprints only if correlation is truly needed.

## Extensibility

The extension point belongs at the invite delivery/exchange boundary: a single
named token transport mode owned by the URL builder and the registration
exchange surface. The obvious future variation is a server-side one-time
preflight handle or manual fallback code for email clients that strip URL
fragments. That should be a mode/parameter on the same URL-builder and exchange
contract, not a second notification path or second participant credential model.

If browser support needs a no-JavaScript fallback, prefer a manual code entry
flow that POSTs the token/code in the body. Do not reintroduce query-string
credentials for fallback usability.

## Gotchas And Anti-Patterns

- Do not move the token from the query string to a path segment. Path segments
  are still logged as URLs by proxies, app servers, browser history, and many
  observability systems.
- Do not use a hidden form field rendered by Django. The server cannot receive a
  fragment, and rendering the raw token back into HTML recreates a leak surface.
- Do not put the token into `localStorage`, `sessionStorage`, cookies, data
  attributes, console logs, alerts, or analytics events.
- Do not mark the exchange `csrf_exempt`. Login CSRF is still a real issue even
  when the posted credential is an invite token.
- Do not leave `invite_token` in custom email template context unless there is a
  deliberate compatibility reason. Prefer exposing only `registration_url` so
  organizer-authored templates do not keep using raw token variables.
- Do not broaden `ALLOWED_HOSTS`, CSRF trusted origins, WAF, ingress, or
  `SITE_URL` behavior to make the exchange work.
- Do not add a new exception hierarchy, DTO package, notification renderer,
  auth backend, audit model, or CTF authorization predicate for this issue.
- Do not solve Sonar by adding or moving `# NOSONAR`; the token read from
  `request.GET` and the documented suppression should disappear.

## Non-Goals

- Replacing OIDC, Identity Platform, or regular platform login.
- Changing participant invitation semantics, event registration deadlines,
  participant status transitions, teams, scoring, range provisioning, or CTFd
  integration.
- Hashing/encrypting stored invite tokens. That can be a later hardening step,
  but it is not required to remove the URL-query leak.
- Building an email delivery abstraction, link tracking service, short-link
  service, or cross-app magic-link framework.
- Adding Ground Control requirements or traceability for this requirement-free
  issue.

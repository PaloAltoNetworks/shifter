# CTF Invite Token Expiry Preflight - Issue 556

Issue 556 is a native Django CTF authentication fix: participant invite tokens
are bearer credentials and registration must reject tokens whose
`CTFParticipant.is_invite_valid` policy has expired. There is no Ground Control
requirement for this run; the GitHub issue is the contract.

This note is intentionally not an implementation plan. It records the
cross-repo boundaries the implementation must preserve.

## Architecture Decisions

- `CTFParticipant.is_invite_valid` is the canonical validity check for invite
  token expiry. Views and services must not duplicate timestamp comparisons.
- Participant registration remains a CTF-specific magic-link authentication
  path, separate from OIDC / Identity Platform login. It uses
  `django.contrib.auth.login(..., ModelBackend)` after the invite token passes
  CTF policy.
- Invite-token reuse is a product/security policy, not an accident. The current
  default is reusable tokens; `MAGIC_LINK_SINGLE_USE` is the existing parameter
  for a stricter future policy and must remain covered by tests.
- Event-backed invite links may default to the event end so participants can
  reuse links for the active CTF window, but the design must preserve an
  explicit operator ceiling for unusually long or misconfigured events.
- Token expiry generation belongs with the participant model/service lifecycle
  (`CTFParticipant.save()` and `ctf.services.participant.resend_invite()`), not
  in the registration view.
- Registration-token transport must stay fragment-first: invitation emails carry
  `#token=...`, the GET page never authenticates, and the POST exchange consumes
  the token from the JSON body.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Token validity | `CTFParticipant.is_invite_valid` | Use for expiry enforcement before `login()`. |
| Expiry defaults | participant model lifecycle, `resend_invite()`, `MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS` | Keep new and rotated tokens on one expiry policy with an explicit stricter ceiling when configured. |
| JSON request parsing | `ctf.views._parsing._parse_body_object()` and `_get_body_str()` | Preserve 400 JSON envelopes for malformed/non-object/non-string bodies. |
| Registration transport | `ctf.services.notification._build_registration_url()` and `static/js/ctf-register.js` | Keep tokens in URL fragments, scrub browser history, POST with CSRF. |
| Public auth exemption | `config._oidc_settings.OIDC_EXEMPT_URLS` | Keep only `/ctf/register/` and `/ctf/register/exchange/` exempted for this flow. |
| Error envelope | CTF `JsonResponse({"error": ...}, status=...)` convention | Never return raw exceptions, traces, tokens, cookies, or provider payloads. |
| Logging | `shared.log_sanitize.safe_log_value` where logging is needed | Do not log raw invite tokens or full registration URLs. |
| Rate limiting | `ctf.views._access._check_invite_rate_limit()` | Reuse for invite generation/resend; do not rate-limit token exchange ad hoc in this issue. |
| Test policy | `tests/ctf/test_auth_registration.py`, ADR-019 boundary-mock policy | Prefer behavior tests around the view/model contract; do not grow first-party internal patch debt. |

## Security Layers

- Auth surface: the invite token is the credential. The exchange view must
  accept only a linked participant whose token lookup succeeds and whose
  `is_invite_valid` property is true before calling `login()`.
- Token transport: `_build_registration_url()` must keep the token in the URL
  fragment, not the query string; the register page and JavaScript must keep
  `Referrer-Policy: no-referrer`, immediate history scrubbing, and same-origin
  CSRF-protected POST exchange.
- Request shape: the exchange endpoint must pass through `_parse_body_object()`
  and `_get_body_str(..., required=True)` so malformed JSON, non-object bodies,
  missing token fields, and non-string token values fail with controlled 400s.
- Persistence shape: `invite_token` stays the opaque `secrets.token_urlsafe(32)`
  value stored on `CTFParticipant`; `invite_token_expires` stays the durable
  expiry field and must be updated when a token is rotated.
- Config shape: `MAGIC_LINK_EXPIRY_HOURS`, `MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS`,
  and `MAGIC_LINK_SINGLE_USE` stay bound in `config._oidc_settings`; do not add
  a parallel setting or env parser.
- OS/log exposure: tokens must not be accepted through process argv, management
  command arguments, query strings, log messages, request IDs, or rendered error
  text. If a failure is logged, log participant/event IDs through
  `safe_log_value`, not the credential.
- Error envelope: invalid, expired, missing, oversize, or unlinked tokens should
  return the CTF JSON error envelope without echoing the submitted token.

## Extensibility

The intended seam is token policy, not another authentication system. The next
reasonable variation is tighter invite semantics: single-use tokens, shorter
fallback TTLs for non-event links, or an event-link maximum. Those should hang
off the existing `MAGIC_LINK_SINGLE_USE` / expiry-default policy path,
`MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS`, and the model property, not a second
invite-token validator in the view.

## Gotchas And Anti-Patterns

- Do not compare `timezone.now()` to `invite_token_expires` directly in
  `ctf_register_exchange`; use `is_invite_valid`.
- Do not move this endpoint to a generic platform API token or OIDC flow.
- Do not add a duplicate invite-token DTO, exception hierarchy, or service
  facade for this narrow fix.
- Do not echo token values in responses, logs, OpenAPI examples, docs examples,
  or organizer-authored template context.
- Do not change token-reuse behavior implicitly while fixing expiry. Reusable by
  default and optional single-use must both be explicit in tests.
- Do not make `MAGIC_LINK_EXPIRY_HOURS` mean different things in model creation
  and resend paths.

## Non-Goals

- No registration UX redesign beyond preserving the existing fragment exchange.
- No DRF migration for the existing CTF register exchange endpoint.
- No database schema or migration unless the chosen policy truly requires a new
  durable field.
- No changes to participant eligibility, scoring, range provisioning, CTFd /
  Polaris, OIDC provider configuration, or platform API token scopes.

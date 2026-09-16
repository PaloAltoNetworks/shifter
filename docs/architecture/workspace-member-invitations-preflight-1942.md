# Workspace member invitations and onboarding preflight (#1942)

Status: pre-implementation guidance

Date: 2026-08-12

Requirements: PLAT-235 (implements), PLAT-241 (constrains)

This note fixes the repository-wide security and domain boundaries for the
workspace invitation slice. It is not an implementation plan and adds no
application behavior, API, model, route, token, email, or SPA surface.

## Decision boundary

Member invitations extend the existing `workspaces` domain. They are not a new
authentication system, a variant of CTF participation, an API token, or an
email-delivery workflow engine.

Keep four concepts separate:

1. A workspace invitation is a durable, revocable grant addressed to one
   validated email address and one closed `WorkspaceRole` in one non-personal
   workspace.
2. A signed invitation token is a short-lived bearer proof for one generation
   of that invitation. It is not persisted in plaintext and does not itself
   authenticate a platform user.
3. Platform authentication and account provisioning remain owned by the
   configured AWS Cognito/OIDC or GCP Identity Platform adapter. The invitation
   flow consumes the normal Django session only after the existing provider
   verification and identity-binding gates have run.
4. Membership is still the single `WorkspaceMembership` authority row. An
   accepted invitation creates exactly one row through the existing membership
   mutation boundary; it never becomes a second membership or role store.

The invitation link must not create a Django session, set a password, bypass
MFA/domain admission, or bind an account by email alone. For a new person, the
normal first provider login provisions and immutably binds the Django account;
the authenticated acceptance then links that exact active account to the
invitation. For an existing person, normal subject-first login resolves the
already-bound account. The final acceptance requires fresh `VerifiedIdentity`
email evidence from the provider authentication transaction to match the
invitation under one domain-owned case-insensitive comparison policy. It must
not trust `request.user.email` alone: that persisted field can be stale or
locally mutable even though the provider identity is bound correctly.
Acceptance must also fail closed if active platform-account resolution is
ambiguous. A temporary CTF account is never an eligible acceptance principal.

This boundary is required for AWS/GCP parity. Implementing token-login or local
account activation in `workspaces` would silently create a third production
identity path and bypass `config.oidc`, `config.identity_platform`,
`shared.verified_identity`, and `management.services.bind_provider_identity`.

## Invitation aggregate and state

The invitation record belongs beside `WorkspaceMembership` in the `workspaces`
domain and is exposed to all other layers only through `workspaces.services`.
It relates internally to the workspace and, after acceptance, may retain the
accepted Django user identity needed for diagnostics. No other domain gets a
model import or cross-layer foreign key.

Use the existing public workspace UUID at every HTTP boundary and a separate
opaque public invitation UUID in the signed payload. Internal integer IDs stay
inside persistence, audit, and service code. The token payload is deliberately
small: invitation UUID, token-generation/version, and a schema/purpose version
are sufficient. Email, role, workspace name, organization name, actor identity,
and provider data do not belong in it because a Django signature authenticates
but does not encrypt its payload.

The externally visible state vocabulary is closed:

- `pending`: the current generation is neither accepted nor revoked and its
  durable expiry is still in the future;
- `expired`: the same open state after its durable expiry;
- `accepted`: the invitation was consumed by one authenticated matching user;
- `revoked`: an administrator invalidated it before acceptance.

`expired` should be derived by one service projection from durable timestamps,
not maintained by a request-time write, periodic sweeper, SPA clock, or second
status calculation. Resend rotates the generation and expiry on the same
current invitation aggregate, making every earlier token invalid. Revocation
also invalidates the current generation. The persistence shape must prevent
impossible accepted-and-revoked states and duplicate current invitations for
the same workspace plus case-insensitive address; service validation alone is
not a concurrency boundary.

The role field reuses `workspaces.roles.WorkspaceRole` for serializer choices,
service validation, and a database check constraint. It must not define an
invitation-only role enum or copy role strings into the frontend. Personal
workspaces reject invitations. Issuance, resend, and acceptance also apply the
workspace's live archival/protection rules rather than inventing an invitation
interpretation of workspace state.

## Token and browser transport

There is no repository-local, general invitation signer to extend. The proven
incumbent is Django's signing framework over the already-required
`DJANGO_SECRET_KEY` and bounded `SECRET_KEY_FALLBACKS` rotation contract.
Use `django.core.signing.dumps` / `loads` (the timestamped JSON signer), an
invitation-specific salt, a bounded `max_age`, and strict post-signature payload
shape checks. Do not write HMAC/JWT/crypto code, use pickle serialization, reuse
an API token, reuse the retired CTF invite-token model, or borrow CTF-specific
`MAGIC_LINK_*` settings.

Expiry and single use are durable workflow properties as well as signature
properties. Verification must satisfy all of the following before acceptance:

- signature, purpose salt, timestamp age, and exact JSON payload shape;
- current invitation UUID and generation;
- live `expires_at`, not accepted, and not revoked;
- matching authenticated active platform account;
- live workspace eligibility; and
- atomic membership creation plus invitation consumption.

The token travels in the email URL fragment, following the security precedent
in `docs/architecture/ctf-invite-token-delivery-preflight-1088.md`, but it does
not reuse CTF persistence or authentication. A minimal public landing page
reads a bounded fragment value, immediately removes it from browser history,
and sends it in the body of a same-origin, explicitly CSRF-protected POST. It
must not enter a query string, path segment, redirect/`next` value, `Location`
header, server-rendered context, cookie, local/session storage, analytics event,
or service-worker cache. The landing/exchange response is `private, no-store`
with `Referrer-Policy: no-referrer`.

That landing/exchange is an exact Django-owned public route, not a child of the
staff/authenticated `/administer` SPA host. It remains reachable when the SPA
rollout flag changes after an email was sent, and only its exact paths join the
OIDC/public-route exemption contract--never an invitation prefix. The Administer
SPA owns issuance and status management; the recipient handoff is deliberately
independent of staff navigation and `ADMINISTER_SPA_ENABLED`.

Anonymous DRF `SessionAuthentication` does not by itself enforce CSRF, so a
public token-staging POST must use Django's explicit CSRF protection rather than
assuming the DRF class covers it. Invalid, expired, revoked, already-used,
oversize, and malformed credentials share a bounded response and never echo the
token or distinguish persisted invitation details.

The token must be staged before provider authentication because provider
redirects do not preserve the fragment. Only the non-secret invitation UUID and
generation may be retained in the server-side Django session; the raw token is
discarded. Final consumption occurs only after normal login. The current
`platform_login` / OIDC callback path uses a fixed dashboard redirect and does
not preserve a safe invitation continuation, so the implementation must add
one provider-neutral composition-root continuation contract. It must accept
only an allowlisted relative application path validated with Django's redirect
safety utility, work for both providers, and never put the token in `next`.
The handoff to final acceptance must carry fresh server-authenticated
`VerifiedIdentity` email assurance (or consume acceptance while that value is
in hand), not raw claims or a later reread of `User.email`.
Provider-specific return logic in the workspaces domain or two separate AWS/GCP
invitation callbacks is prohibited.

## Authorization, transactions, and idempotency

The staff-only Administer SPA and invitation administration API retain two
additive gates:

- a bearer-first, fail-closed authenticated staff Django session admits the
  console/API and rejects platform API-token principals; and
- `workspaces.services` authorizes the exact live workspace operation.

Extend the central `WorkspaceOperation`/`ROLE_OPERATIONS` policy with explicit
invitation read, issue, resend, and revoke operations as needed. Do not infer
these operations from role strings in a view or React component. Owner/admin
may manage ordinary invitations under the same membership-management posture;
only an owner may issue, rotate, or revoke an invitation that grants `owner`.
Adding an API-token automation path later requires deliberately accepted exact
scopes; it must not be smuggled into this session-only console slice.

Acceptance is different: the invitee cannot already be required to hold a
workspace role. Its authority is the valid single-use invitation plus a normal
matching authenticated platform session. That narrow bearer-grant boundary
must stay inside the invitation service and must not weaken
`authorize_workspace` for ordinary resource operations.

Every mutation uses the existing workspace row as the stable per-workspace
mutex. Under one `transaction.atomic()` boundary, re-read the invitation and
actor/account evidence, validate the current generation and state, create the
membership through a factored version of the existing membership insertion
logic, consume the invitation, and write strict audit. The existing
`(workspace, user)` unique constraint is the final exactly-one-membership proof.
A raw `IntegrityError`, duplicate role change, or competing direct add is mapped
to a bounded conflict; acceptance never silently changes an existing
membership's role.

The exact same consumed token is rejected after the first successful commit.
Concurrency is serialized at the database boundary, not through an in-process
flag or optimistic SPA state. PostgreSQL behavior tests must cover simultaneous
accept/accept, accept/revoke, resend/accept, and direct-add/accept races; SQLite
tests do not prove `select_for_update` semantics.

Invitation issue/resend is a credential-delivery abuse surface. Reuse the
cross-worker `shared.credential_delivery.credential_delivery_allowed` /
`shared.rate_limit.consume_fixed_window` cache-backed budget after authority is
established, and map cache failure/exhaustion through controlled 503/429
responses. Do not import the CTF-private invite limiter or add process-local
counters. The public exchange also needs bounded input before signature work
and a cache-backed source/session abuse budget; it must never use the token or
email itself as a metric/cache/log label.

## Email delivery and audit boundary

Trusted filesystem template pairs render through `shared.email.render_template`
and dispatch through `shared.email.send_email_async`. Provider selection,
credentials, sender behavior, MIME assembly, and delivery error handling remain
in `config/_email.py` and the Django email backends:

- AWS uses `django-ses` and its IAM/VPC endpoint posture;
- GCP uses the configured django-anymail SendGrid/Mailgun adapter and runtime
  secret hydration.

Workspaces code must not import a provider SDK, branch on `CLOUD_PROVIDER`, add
SMTP credentials, or implement egress/network checks. Build the public link
from validated `settings.SITE_URL` plus `reverse()`, never from an untrusted
request `Host`. Use a new trusted application-owned invitation template pair;
CTF organizer-authored templates and their placeholder grammar are unrelated.
Template context is a closed scalar projection and contains only the final
fragment URL, display-safe workspace/organization names, role label, and expiry
copy needed by the message.

Commit invitation state and strict audit before dispatch. Register email
render/send with `transaction.on_commit` so rolled-back grants never send. The
current shared thread pool is best-effort and non-durable: delivery failure does
not roll back or change invitation state, and `pending` means awaiting
acceptance, not successfully delivered. Do not add a misleading `sent` status,
retry loop, scheduler row, range-event outbox message, or provider delivery
state. If guaranteed delivery becomes a requirement, the extension is a
separate generic email outbox/worker contract behind `shared.email`.

Use `shared.audit` with one invitation entity vocabulary and the existing
generic create/update actions; do not label an invitation as a membership before
acceptance or create a second audit table. Issue, resend, revoke, and accept
record request attribution, internal invitation/workspace ids, role, generation,
and bounded before/after state only. Acceptance also emits the canonical
membership-create event in the same transaction. Token, URL, email address,
email body, session key, provider identity, headers, and raw request data never
enter audit.

One incumbent needs hardening as part of the eventual implementation:
`shared.email.send_email()` currently logs `safe_log_value(recipient)` when
delivery fails. That prevents log injection but still emits the raw email/PII,
contrary to ADR-046-R6 for tenancy workflows. Fix the shared choke point to log
a bounded recipient fingerprint or no recipient before this feature relies on
it; do not bypass `shared.email` with a feature-local sender or duplicate error
handler.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail for #1942 |
| --- | --- | --- |
| Tenancy persistence | `workspaces.models`, `workspaces.services`, workspace mutex, membership uniqueness | Invitation belongs in this domain and acceptance factors/reuses membership insertion; no repository or second membership store. |
| Role policy | `workspaces.roles.WorkspaceRole`, `WorkspaceOperation`, `ROLE_OPERATIONS` | Extend one operation matrix; never compare roles in controllers or TypeScript. |
| Account identity | `config.oidc`, `config.identity_platform`, `shared.verified_identity`, `management.services.bind_provider_identity` | Normal provider login provisions/binds the account and supplies fresh verified-email evidence to acceptance. Invitation tokens do not authenticate, create passwords, bind by email, or make stale `User.email` authoritative. |
| Session and CSRF | Django auth/session middleware, `SessionAuthentication`, `IsStaffSession`, `CsrfViewMiddleware` | Admin calls are staff-session-only. Public token staging needs explicit CSRF; final acceptance requires a normal matching session. |
| Token signing | Django `django.core.signing`, `DJANGO_SECRET_KEY`, `SECRET_KEY_FALLBACKS` | Timestamped JSON, unique salt, bounded age, exact shape, row generation and revocation. No custom crypto/JWT. |
| Email config/delivery | `config/_email.py`, runtime renderers/secret hydration, `shared.email` | One provider-neutral send path; harden recipient logging, do not call SES/SendGrid/Mailgun directly. |
| URL/browser security | `SITE_URL`, `reverse`, global CSP/Referrer policy, CTF fragment-exchange precedent | Fragment transport, history scrub, no-store/no-referrer, body POST, no token in redirects or persistence. |
| Request validation | Explicit DRF serializers and service revalidation | Serializer owns email/UUID/body shape; service owns state, role, account match, expiry, and concurrency; DB owns constraints. |
| Errors | `shared.api.errors`, `ApiErrorSerializer`, request ID middleware | Stable bounded codes/envelopes; no signer/provider/database/email exception text or credential distinctions. |
| Abuse control | `shared.credential_delivery`, `shared.rate_limit`, `launch_rate_limit` cache | Cross-worker limits and fail-closed dependency handling; no CTF-private or process-local limiter. |
| Audit/logging | `shared.audit`, request attribution, `shared.log_sanitize` | Strict in-transaction mutation audit; ids/outcomes only, never token/email/link/body. |
| API contract | canonical `/api/v1/`, drf-spectacular, `openapi/v1.json`, generated `schema.d.ts` | Runtime serializers are authoritative; no hand-authored OpenAPI or duplicate frontend DTO/status/role enum. |
| SPA state | `frontend/src/api/client.ts`, `errors.ts`, `queryClient.ts`, TanStack Query | Same-origin cookie/CSRF/request IDs; queries own lists, mutations do not auto-retry, invalidation is centralized. |
| Admin escape hatch | `/admin/` and existing Django admin | Do not duplicate rare framework administration in the SPA. Any invitation admin exposure is read-only or uses service-backed audited actions, never direct authority edits. |

## Cross-cutting layers the design must pass

1. **Provider identity and account admission.** Cognito/OIDC verifies signature,
   issuer, audience, authorized party, subject, and verified email. Identity
   Platform verifies the revoked token, literal verified email, allowed
   domain/address, enrolled MFA, issuer/subject, and account record. Both bind
   once through `management.services`. The invitation acceptance boundary
   receives the resulting Django user plus fresh `VerifiedIdentity` email
   assurance and never parses raw claims or provider responses.
2. **Session and temporary-account boundary.** Django reloads the authenticated
   user through the configured backend; `CTFAccountBoundaryMiddleware` keeps
   temporary accounts outside platform administration. Admin operations require
   `IsStaffSession`; acceptance requires an active normal session and repeats
   the invitation/account match against fresh provider-verified email evidence
   rather than trusting route visibility or persisted user email alone.
3. **HTTP shape and CSRF.** Explicit serializers bound email, role, UUID, token
   length, and exact request keys. Session writes carry `X-CSRFToken`; the
   anonymous staging POST is explicitly CSRF-protected. No `csrf_exempt`, ad-hoc
   JSON parser, writable `ModelSerializer`, or browser bearer token is allowed.
   Public admission is limited to exact root URL/OIDC-exemption entries; the
   authenticated SPA catch-all is not widened.
4. **Token parser and secret handling.** Fragment JavaScript bounds/scrubs the
   credential; Django signing checks salt/timestamp/signature using JSON, then a
   service checks exact payload shape, generation, durable state, and expiry.
   Tokens and full links remain outside URLs seen by the server, logs, audit,
   exceptions, session data, OpenAPI examples, test snapshots, and telemetry.
5. **Workspace authorization.** Staff is admission, not tenancy authority.
   Administrative actions repeat the exact central workspace-operation check;
   owner-grant rules and personal/archive constraints remain domain-owned.
   Acceptance uses only its narrow invitation grant and never broadens ordinary
   workspace or range authorization.
6. **Persistence and concurrency.** Workspaces owns the invitation FK and
   constraints. Case-insensitive current-address uniqueness, closed role,
   valid state combinations, generation, durable expiry, membership uniqueness,
   row locks, and `transaction.atomic` are the durable validators. API/model
   validation does not replace them.
7. **Audit, errors, and logging.** `shared.audit` is strict in the authority
   transaction; `shared.api.errors` authors client output with request ids;
   operational logs use fixed outcomes and safe ids/fingerprints. Raw signer,
   SMTP/provider, cache, ORM, `IntegrityError`, and identity exceptions never
   cross the public envelope.
8. **Email configuration and secret hydration.** `EMAIL_BACKEND`,
   `DEFAULT_FROM_EMAIL`, ESP secret references/`EMAIL_API_KEY`, Mailgun domain,
   AWS SES region/IAM, and `SITE_URL` continue through their existing settings,
   env manifest, AWS user-data, GCP renderer, entrypoint, and provider secret
   stores. This feature needs no invitation signing key or cloud-specific env
   binding.
9. **Browser policy and egress.** Existing CSP, same-origin connect policy,
   secure cookies, global headers, ingress/ALLOWED_HOSTS, SES VPC endpoint, and
   GCP SaaS egress remain authoritative. The feature adds no external browser
   origin, CSP exception, egress rule, provider label, or cloud network call.
10. **OS/process exposure.** Token, email, rendered body, session key, email API
    key, and provider evidence never enter argv, shell strings, process listings,
    environment dumps, temp files, management-command arguments, worker payloads,
    Terraform output, Kubernetes objects, CI annotations, or static bundles.
11. **Published/client contracts.** DRF serializers and schema annotations
    regenerate `openapi/v1.json` and `frontend/src/api/schema.d.ts`; frontend
    `types.ts` only re-exports generated shapes. TanStack keys include workspace
    UUID and invalidate invitation lists after issue/resend/revoke without
    seeding membership or principal-context data prematurely.
12. **Repository enforcement.** Preserve `.importlinter`, layer/FK/model guards,
    migration checks, PostgreSQL semantics, OpenAPI drift and compatibility,
    frontend lint/type/unit/accessibility tests, email/config tests, and
    `scripts/adr_guard/adr_guard.py --all --level ci`.

## Extensibility seams

The token seam is one purpose-versioned payload plus a service-owned expiry and
generation policy. The next reasonable change--a shorter invitation TTL or a
new token schema--changes that policy/version without changing providers,
membership persistence, email backends, or SPA DTOs. Operator configurability
is not required now; if later required, it must use one validated provider-
neutral setting represented in the env manifest and both runtime renderers.

The identity seam is a safe relative post-login continuation owned by the
composition/auth layer. Invitations stage only an opaque invitation reference
in Django session state. Future email-confirmed workflows can request the same
continuation without learning whether Cognito or Identity Platform is active;
they do not copy provider callbacks or carry credentials in `next`.

The workflow seam is the invitation service's closed command/state contract
(issue, list, resend, revoke, accept) and immutable scalar projections. A future
bulk invite composes the same per-invitation command under an explicit bounded
batch policy; it does not add CSV-specific role validation, token generation,
email sending, or audit logic. Durable email retry, if required, belongs behind
a separate shared email-outbox contract rather than adding `delivery_failed` to
the invitation authorization state.

## Gotchas and anti-patterns

- Do not let a signed email token log a user in, set a password, mark email as
  provider-verified, bypass MFA/allowlists, or overwrite an issuer/subject bind.
- Do not accept against `request.user.email` alone, a self-asserted email, or a
  cached client value. The matching address comes from the fresh provider-
  verified identity handoff and is then normalized once by the workspaces
  domain.
- Do not conflate invitation email identity, Django username, provider subject,
  organization membership, workspace membership, CTF delivery email, or API
  token ownership.
- Do not call `add_workspace_member` with the inviter during acceptance. Factor
  the canonical membership insert/audit invariant so the authenticated invitee
  receives the one row without impersonating an administrator or duplicating
  persistence logic.
- Do not persist the raw token or a token hash merely to make single use work;
  row UUID + signed generation + terminal state already provide revocation and
  consumption. Do not include mutable/PII fields in the readable signed payload.
- Do not store `expired` from a GET, compare browser time, add a sweeper only to
  maintain display status, or maintain separate status logic in serializer,
  service, SPA, and admin.
- Do not let resend create parallel live grants or leave the old generation
  valid. Do not make email dispatch success the invitation state.
- Do not silently accept an existing membership as a role update. An exact
  concurrent membership is handled idempotently only inside the winning
  acceptance transaction; a pre-existing/different role is an authored conflict.
- Do not put the token in query/path/redirect state, server-side session data,
  logs, audit, analytics, screenshots, error details, clipboard automation, or
  generated examples. A URL path segment is still an access-log leak.
- Do not assume `SessionAuthentication` CSRF-checks anonymous requests. Do not
  use `csrf_exempt` to make the public exchange convenient.
- Do not build links with `request.build_absolute_uri()` or broaden
  `ALLOWED_HOSTS`/CSRF/CSP to compensate for invalid deployment config. Use the
  validated canonical `SITE_URL`.
- Do not import SES, boto, Firebase, SendGrid, Mailgun, `CLOUD_PROVIDER`, CTF
  notification/token helpers, or management models into `workspaces`.
- Do not create feature-local mail clients, crypto helpers, rate limiters,
  exception trees, audit tables, repositories, role/status enums, OpenAPI/DTO
  copies, React server-state stores, routers, or logging redactors.
- Do not expose raw invitation authority editing through Django admin. The
  escape hatch is not permission to bypass service locks and strict audit.

## Non-goals and implementation boundaries

- No replacement or weakening of Cognito/OIDC, Identity Platform, provider MFA
  and allowlists, verified-identity binding, Django sessions, or temporary CTF
  account isolation.
- No password creation/reset, passwordless platform login, local authentication
  backend, identity-provider user provisioning API, provider group mapping, or
  invitation-based staff/superuser/organization-admin elevation.
- No organization invitations, organization-role lifecycle, user deletion,
  range reassignment, range access grant, CTF participation, API-token minting,
  or cloud IAM role assignment.
- No bulk import, domain-wide auto-enrollment, SCIM, directory sync, SMS, push,
  custom organizer templates, link tracking, short-link service, or email-open
  telemetry.
- No guaranteed email delivery, retry/DLQ, new scheduler, Celery deployment, or
  reuse of the range-event outbox. Best-effort post-commit shared email remains
  the current delivery contract.
- No new cloud adapter, provider branch, egress policy, Terraform resource,
  Kubernetes object, secret, signing key, or invitation-specific environment
  variable.
- No broad Django-admin CRUD clone in the SPA. The SPA owns issue/list/status,
  resend, and revoke; deep rare framework administration remains at `/admin/`
  and must not bypass domain services.

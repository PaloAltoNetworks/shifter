# User lifecycle administration preflight (#1943)

Status: accepted and implemented (account lifecycle, password reset, and bounded
ownership transfer under ADR-046-R13)

Date: 2026-08-14

Requirements: PLAT-236 (implements), PLAT-241 (constrains)

This note fixes the repository-wide boundaries for account activation,
deactivation, suspension, administrator-triggered password reset, and eventual
offboarding transfer. It is not an implementation plan and adds no model,
migration, endpoint, email, component, transfer operation, or cloud behavior.

## Readiness decision

The account-state and password-reset parts are architecture-ready under the
guardrails below.

The ownership-transfer scope was originally blocked pending a decision on which
resource kinds are transferable and under what authority. That decision has since
been made and accepted (issue #1943, maintainer-confirmed) and is implemented:
the offboarding transfer is a single composition-root command over a **closed set
of whole resource kinds** (`ranges`, `workspaces`), authorized by a **superuser**
session, delegating per kind to the domain-owned services, and accepted into the
tenancy model by **ADR-046-R13**. It selects whole resource kinds rather than
individual resource ids, and it never uses a wildcard, a generic `owner_id`
rewrite, or a reflective foreign-key scan. The paragraphs below record the
resource-owner analysis that informed that decision.

The repository deliberately has no generic resource owner:

- ordinary workspace ownership is a locked `WorkspaceMembership` role governed
  by `workspaces.services` and is owner-only under ADR-046-R8;
- range ownership is coordinated across CMS request/range and Engine
  request/range projections, remains workspace-scoped, and already has a
  transfer service that refuses unsafe moves;
- CMS `Credential` and `AgentConfig` rows are user-owned assets, but credential
  transfer exposes encrypted secret material and agent object keys/quota are
  tied to the source user;
- `CTFEvent.created_by` is event authority and has no transfer contract;
- scenario authors, invitation creators, notification creators, audit actors,
  package registrars, award grantors, and similar user references are
  provenance, not ownership to rewrite;
- organization/workspace memberships, CTF participation/staff, Django groups,
  and model permissions are assignments, not owned resources; and
- a personal workspace's `personal_for_user` identity is immutable
  compatibility state and is never transferable.

The accepted transfer decision resolves each of those questions. The closed set
of transferable resource kinds is `ranges` and `workspaces`. Range transfer
preserves workspace scope (it reuses the existing CMS reassign authority, which
requires the new owner's membership in the range's workspace and refuses a live
VPN generation) rather than implicitly rehoming. Workspace transfer is a
platform-administrator override of ADR-046-R8's owner-only boundary, accepted by
**ADR-046-R13**, and is authorized by a **superuser** session (not merely
`auth.change_user`, `is_staff`, or a visible Administer button); it requires the
replacement to already hold a membership and never fabricates one. No wildcard
"all resources" operation, generic foreign-key rewrite, or best-effort client
sequence is used.

No new ADR is needed for account state or local password reset while they stay
within ADR-001, ADR-009, ADR-029, ADR-040, ADR-045, and PLAT-241. The transfer
authority/scope decision is recorded in **ADR-046-R13**.

## Account-state decision

Keep Django `User.is_active` as the one authentication-enforcement bit. Do not
add a second persisted `status` enum that can disagree with it. Add only the
minimum suspension discriminator on `UserProfile` (a nullable
`suspended_at`-style fact) and derive the administrator-facing lifecycle state
in one `management` service projection:

| Derived state | Durable facts | Meaning |
| --- | --- | --- |
| active | `is_active=true`, no suspension, not deleted | May authenticate, subject to the existing provider/local/CTF gates. |
| suspended | `is_active=false`, suspension timestamp present, not deleted | Temporary security block; assignments and owned resources are retained. |
| deactivated | `is_active=false`, no suspension, not deleted | Reversible offboarding/login block; it is not deletion, anonymization, provider unbinding, or ownership transfer. |
| deleted | profile `deleted_at` present | Existing soft-delete state; it must also force `is_active=false`. It remains distinct from permanent erasure/anonymization. |

`anonymized_at`, provider identity binding, organizer provenance, temporary CTF
origin, password-change state, and privileges remain separate facts. A
transition service locks the user and profile, derives the current state,
validates a closed transition, updates `is_active` and the suspension marker
together, and writes one request-attributed strict `shared.audit` event in the
same transaction. Audit failure rolls back the state. Repeating the already
current state is an idempotent no-op and must not claim a transition occurred.
Activation clears the suspension marker and is rejected for deleted or
anonymized accounts; deactivation also clears the marker so it cannot be
misreported as suspension.

The current `/set-active/` behavior and `/delete/` copy are not sufficient
evidence for the new contract. `mark_user_deleted()` currently writes
`deleted_at` without disabling the Django user, while the SPA says deletion
blocks sign-in. PLAT-236 must not preserve that contradiction: all paths that
claim to block authentication must converge on `is_active=false`. Existing v1
routes may be retained as compatibility adapters only if they delegate to the
same transition service and keep ADR-040 contract compatibility; they must not
remain a second state machine.

Suspension and deactivation change authentication state only. They do not
silently revoke Django groups/model permissions, remove organization/workspace
memberships, change CTF roles, delete resources, unbind an issuer/subject,
anonymize data, or transfer ownership. API tokens are credentials rather than
assignments: every authentication path must reject a token whose owner is not
active, and a transition may irreversibly revoke the target's live tokens as
defense in depth. Activation must never resurrect a raw token.

Self-suspension/deactivation through the administrator API is forbidden. A
non-superuser may not mutate a superuser merely because it has
`auth.change_user`, and a transition must not remove the last active platform
superuser. Deployment bootstrap and provider reconciliation may restore
approved privilege flags, but must never reactivate a blocked account as a side
effect of login or claims sync.

## Password-reset boundary

"Credential/password reset" in this slice means an administrator-triggered
Django password-reset email for an eligible local, non-CTF platform account.
Use Django's `PasswordResetForm`, default token generator, UID/token encoding,
password validators, reset-confirm view behavior, session invalidation on
password change, and configured email backend. Do not generate a password,
return a secret in JSON, invent a reset token, or assemble a second reset flow.

Account origin is security-significant:

- a provider-bound account (`issuer`/subject binding) must reset at its identity
  provider. Setting a local Django password would create an authentication
  downgrade and would not reset the AWS/GCP provider credential;
- a temporary CTF account remains owned by
  `ctf.services.participant.credentials`, including its event capability gate,
  password validation, one-time reveal, token revocation, and strict audit; and
- an active local non-CTF account may use Django reset only when it has a valid
  email, a usable password, is not deleted, and policy allows the action.

The server exposes eligibility/action hints from the same account projection;
the SPA does not infer reset eligibility from `account_origin`, group strings,
or button state. The endpoint repeats every check.

Reset delivery reuses the cross-worker
`shared.credential_delivery.credential_delivery_allowed` budget, the configured
`EMAIL_BACKEND`/`DEFAULT_FROM_EMAIL`, and the validated public `SITE_URL`
posture already used for invitations. If the SITE_URL validation is extracted
for reuse, it belongs in a neutral shared/config seam; `management` must not
import a private `workspaces` helper or copy a weaker URL validator. Production
links are HTTPS, credential-free, canonical-origin links. Django's standard
reset-confirm redirect removes the raw token from subsequent browser URLs.

Record a strict, secret-free audit event for the administrator's accepted reset
request before scheduling delivery after transaction commit, and record the
eventual password change without a hash, token, URL, email body, or provider
payload. Delivery failure is an operational outcome, not permission to expose
or log the reset link. The API returns only a safe accepted/error envelope; the
SPA mutation does not auto-retry.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| User lifecycle ownership | `management.admin_services`; `management.services`; `management.models.UserProfile` | Extend one locked service/state projection. No signal-owned workflow, repository, second status enum, or direct view/model mutation. |
| Identity and login | `config.auth`; `config.oidc.ShifterOIDCBackend`; `config.identity_platform.IdentityPlatformBackend`; `config.dev_auth`; `management.services.bind_provider_identity` | Every login and session-reload path enforces the same `is_active` result before claims/privilege sync can create a session. Provider binding remains immutable and provider-neutral. |
| Browser/API admission | `ApiTokenAuthentication` then `SessionAuthentication`; `IsStaffSession`; `require_model_permission`; shared CSRF/session client | Administer stays staff-session-only, bearer-first/fail-closed, and operation-permissioned. Token principals remain rejected. |
| HTTP validation/errors | explicit DRF serializers; `shared.api.errors`; `shared.api.schema.ApiErrorSerializer` | Closed command shapes, unknown-field rejection, stable safe codes, request IDs, no writable `ModelSerializer` or new exception hierarchy. |
| Password machinery | Django auth password-reset forms/views/token generator/validators; `config._email`; `SITE_URL` | Use the proven reset lifecycle and configured delivery. Do not reuse invitation or CTF bearer tokens as password tokens. |
| Delivery abuse control | `shared.credential_delivery`; `launch_rate_limit` cache | Bound both administrator-triggered delivery and repeated targeting through the existing cross-worker limiter; fail closed when the budget backend is unavailable. |
| Audit | `shared.audit` event/vocabulary/attribution/policy/port; `shared.models.AuditLog` | Reuse `USER` plus `UPDATE` for bounded before/after lifecycle/reset evidence unless a genuinely new entity/action is accepted. Strict writes stay in the mutation transaction. No `ActivityLog`. |
| Logs/observability | `RequestIDMiddleware`; `config.logging`; `shared.log_sanitize` | Log bounded operation/outcome and numeric correlation only. Never log email, reset material, identity subject/issuer, credential data, or request bodies. |
| Range transfer | `cms.services.reassign_range_owner`; Engine `reassign_range_owner_by_request`; ADR-046 workspace authorization | Reuse only after transfer scope is accepted. Preserve all CMS/Engine projections, target membership, active-range uniqueness, explicit rehome, and live-VPN refusal. |
| Workspace transfer | `workspaces.services.transfer_workspace_ownership`; `workspaces.roles`; ADR-046/048 | Preserve owner-only authority, target membership, last-owner, personal-workspace, locking, and strict-audit rules unless an ADR explicitly accepts an operator override. |
| SPA/data contract | `frontend/src/api/{client,errors,administer,types}.ts`; TanStack Query; generated `schema.d.ts`; existing Administer components | One client/query-key family, generated types, no component fetch, copied DTO/state machine, generic workflow store, or automatic mutation retry. |
| Contract/workflow gates | `api_contract`; `openapi/v1.json`; `openapi/v1.retirements.json`; `.importlinter`; layer/FK checks; `adr_guard` | Runtime serializers are authoritative; preserve v1 compatibility and repo-local architecture rules. |

## Cross-cutting layers the design must pass

1. **Identity proofing and session creation.** OIDC issuer/audience/authorized
   party/subject/email verification and Identity Platform token/revocation,
   email/MFA, and allowlist checks remain unchanged. After identity resolution
   but before binding-side effects, privilege/group reconciliation, login audit,
   or `login()`, both provider backends refuse an inactive Django user. Local
   and CTF password backends keep Django's active-user gate.
2. **Existing-session reload.** `get_user()` in every configured backend must
   return no principal for inactive users. DRF permissions (`IsStaffSession`,
   `RequireModelPermission`, and session/token actor resolution) also fail
   closed on inactive users so test bypasses or a backend regression cannot
   preserve authority. New HTTP requests from an existing session therefore
   stop at the authentication boundary.
3. **API-token authentication.** `ApiTokenAuthentication` remains the only
   parser and continues to reject malformed/revoked credentials before session
   fallback. It must also reject a token with a missing, inactive, or
   soft-deleted owner. No management scope or SPA bearer token is added.
4. **ASGI and remote access.** `AuthMiddlewareStack`,
   `CTFAccountWebSocketBoundary`, terminal/status/notification consumers, and
   the Engine ownership/state/credential checks remain additive. A new socket
   for an inactive session is rejected through backend session reload. Immediate
   teardown of a socket or Guacamole/cloud session established before the
   transition is not implicit; see non-goals rather than claiming suspension
   recalls credentials already outside platform custody.
5. **Request/command shape and CSRF.** The same-origin SPA client supplies the
   session cookie, CSRF header, and request id. Explicit serializers accept only
   the intended target/transition/reset/approved-transfer fields. Server
   service validation repeats domain invariants; route visibility, capabilities,
   confirmations, and disabled buttons are advisory.
6. **Authorization.** Staff session admission is combined with exact Django
   model permissions for account reads/transitions/reset. Superuser and
   last-active-superuser invariants are checked under lock. A future transfer
   additionally passes every selected resource domain's live authority; account
   administration never implies workspace, range, CTF, credential, or cloud
   authority.
7. **Persistence and concurrency.** Lifecycle transitions lock user/profile
   rows and update the enforcement bit, discriminator, credential revocation,
   and strict audit atomically. Transfer services retain their domain locks,
   uniqueness constraints, scope bindings, and all-or-none semantics. Do not
   use check-then-save, bulk `QuerySet.update()` across heterogeneous ownership,
   a model signal, or a client-orchestrated partial offboard.
8. **Secret/privacy surface.** Passwords, hashes, reset UID/tokens/links,
   cookies, CSRF/API/ID tokens, issuer/subject, provider claims, encrypted
   credential data, S3 keys, email bodies, raw headers, and exceptions never
   enter API responses/examples, audit state, logs, browser storage, query
   strings, snapshots, screenshots, CI artifacts, or analytics. Email is the
   only reset-token delivery channel.
9. **Error envelope and observability.** All API failures use
   `{"error":{"code","message","details?","request_id?"}}`; predictable
   ineligible-state, self-action, authority, conflict, throttling, delivery, and
   transfer-blocked outcomes map to bounded safe codes. SQL/provider/email
   exception text and target-sensitive detail do not cross the boundary. Logs
   and audit retain request correlation without copying payloads.
10. **Config/env and cloud providers.** Lifecycle state and ownership transfer
    add no environment binding, secret, feature flag, Terraform/Kubernetes/Helm
    value, cloud SDK, or provider branch. Reset delivery uses the already
    manifested `SITE_URL`, `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, and hydrated
    `EMAIL_API_KEY`/AWS role posture. The DRF/service/SPA contract is identical
    on AWS and GCP.
11. **OS/process exposure.** No target ID, email, token, reset link, password,
    ownership manifest, or credential enters process argv, shell commands,
    environment dumps, temporary files, guest metadata, provider labels, or
    static Vite output. No subprocess or browser-to-provider credential is
    introduced.
12. **Published contract and UI.** Named operations extend the existing
    `/api/v1/administer/users/` surface. OpenAPI and generated TypeScript remain
    the only wire schemas. The detail projection carries one derived lifecycle
    state plus server-derived available actions; the UI renders accessible
    confirmations and loading/denied/conflict/error states but never rebuilds
    transition or origin policy.

## Extensibility seams

The lifecycle seam is a closed desired-state command consumed by one management
service and one derived state projection. The suspension timestamp is the only
additional persisted discriminator; a later approved state extends the service
transition table and projection rather than adding another boolean, endpoint
state machine, or frontend enum copy.

The reset seam is an account-origin-aware credential-reset dispatcher. Its first
accepted implementation is Django local password reset; future provider reset
support must be an explicit provider capability behind a config/shared adapter
and return the same provider-neutral command outcome. It must not add AWS/GCP
conditionals to DRF or React.

The transfer seam, once its scope is approved, is a composition-root command
carrying source user, replacement user, and an explicit bounded list of closed
resource-kind/id selections. Each kind delegates to its domain-owned transfer
service and audit vocabulary. There is no dynamic model registry, arbitrary
app/model name, reflective foreign-key scan, wildcard selection, or generic
`owner_id` updater. Adding the next resource kind means accepting its own
authority, secret, scope, concurrency, and attribution semantics first.

## Gotchas and anti-patterns

- Do not conflate active, suspended, deactivated, deleted, anonymized,
  provider-unbound, password-reset-required, or privilege-revoked state.
- Do not persist both a lifecycle enum and `is_active`, or let views, provider
  adapters, CTF services, and the SPA each derive different state rules.
- Do not claim `deleted_at` blocks login without setting/enforcing
  `is_active=false`; do not let provider login or claims sync reactivate a
  blocked account.
- Do not leave active API tokens usable because the browser account is blocked,
  and do not reactivate revoked credentials later.
- Do not offer Django reset to a provider-bound identity or the generic
  administrator reset to a temporary CTF account. Do not reveal or log a reset
  token/password, put it in JSON, or send it in a query parameter.
- Do not copy Django password-token logic, password validators, email delivery,
  SITE_URL validation, credential-delivery throttling, audit attribution,
  error envelopes, or frontend DTOs.
- Do not authorize a sensitive transition from staff/nav visibility alone,
  permit self-disable, allow a non-superuser to disable a superuser, or strand
  the deployment with no active superuser.
- Do not interpret every user foreign key as ownership. Never rewrite
  provenance/audit history, participant/staff/membership assignments, personal
  workspace identity, or API-token creator history as part of transfer.
- Do not transfer secret-bearing credentials by changing `user_id`, move an
  agent without its storage/quota contract, silently rehome a range, bypass an
  active VPN credential, or bypass workspace target-membership/last-owner rules.
- Do not implement a multi-domain offboard as sequential SPA calls, best-effort
  bulk updates, Celery/provider side effects without durable orchestration, or
  an unbounded transaction over every row a user ever touched.
- Do not add a generic admin CRUD API, writable user/profile serializer,
  repository, role/status/exception/audit hierarchy, workflow engine, client
  store, router, feature flag, cloud branch, or deep Django-admin duplication.

## Non-goals and implementation boundaries

- No hard delete, GDPR erasure, anonymization redesign, identity-provider
  disable/delete, issuer/subject unbinding/rebinding, MFA reset, account merge,
  username/email change, group/permission/organizer management, or admin
  impersonation.
- No API-token rotation UI, cloud credential rotation, CMS encrypted-credential
  transfer, CTF bootstrap-password redesign, invitation flow, or new password
  policy.
- Suspension/deactivation does not itself remove assignments or transfer/delete
  resources. Activation restores login eligibility only; it does not restore
  tokens or erased/revoked state.
- No guarantee that PLAT-236 recalls a downloaded VPN profile, terminates an
  already-established SSH/RDP/Guacamole/cloud session, destroys infrastructure,
  or disconnects every already-open WebSocket. Those need their owning
  credential/session teardown contracts; UI/docs must not claim otherwise.
- Ownership transfer is limited to the accepted closed resource kinds (`ranges`,
  `workspaces`) under superuser authority per ADR-046-R13; credential/agent
  transfer and any other resource kind remain out of scope pending their own
  accepted contracts. Historical attribution and immutable audit evidence are
  never transferable.
- No new feature flag, environment/config schema, provider SDK, infrastructure,
  worker, CLI, OS integration, audit backend, API major, frontend framework, or
  Django-admin replacement.

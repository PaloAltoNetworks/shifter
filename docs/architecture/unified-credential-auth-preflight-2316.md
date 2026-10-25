# Unified credential authentication preflight (#2316)

Status: architecture guidance for the S3 authentication integration; production
authority cutover remains S8

Date: 2026-09-21

Contract: GitHub issue #2316 under the #2308 redesign and ADR-066. This is a
requirement-free run; PLAT-101, PLAT-102, PLAT-106, CTF-006, and CTF-608 are
incumbent clauses to reconcile during implementation, not a substitute contract.

This note fixes the repository-wide boundaries that are not already explicit in
ADR-066 or the #2314/#2315 preflights. It is not an implementation plan and adds
no runtime credential, endpoint, schema, dependency, or cutover behavior.

## Readiness decision

The issue is architecture-ready under ADR-066, with one credential admission
boundary and three deliberately different credential lifecycles:

| Credential | Principal | Admission proof | Credential limit | Renewal/lifecycle owner |
| --- | --- | --- | --- | --- |
| Human browser | human `Principal` | Identity Platform/Firebase Admin verification followed by a Django session | server-derived session ceiling plus live application policy | provider browser SDK for login proof; Django for the application session |
| Personal token | the owning human `Principal` | django-rest-knox opaque-token verification | immutable finite token scopes mapped once to `CredentialCeiling`, intersected with live policy | django-rest-knox plus the owning human's explicit revoke operation |
| GCP workload | independent service `Principal` | Google-verified, exact-audience service-account ID token | server-derived service-credential ceiling intersected with live policy | Google authentication libraries and the workload's attached, impersonated, or federated source credential |

Authentication proves a principal and constructs the existing
`shared.authorization.CredentialCeiling`; it does not grant an application
action. Every protected operation still requires the #2315 live authorization
decision. Cloud IAM, application authorization, event participation, customer
membership, Django staff status, and credential issuance remain distinct facts.

The current `shared.api_tokens.ApiToken` implementation is not the destination.
At S8 its metadata can be mapped to a bounded `reissue_required` outcome, but its
secret verifier cannot be translated into a Knox credential. Old raw tokens must
stop authenticating at the cutover. A legacy validator, dual acceptance window,
or second token implementation is forbidden.

## One request identity and bearer boundary

`PrincipalRef`, not `User`, token owner, service-account email, request claims,
or `request.auth`, is the authenticated application actor. A single shared
request-authentication result must carry the resolved active principal, the
credential kind and stable non-secret identifier, and its server-derived
`CredentialCeiling`. Domain code consumes that result through the existing
principal and authorization ports rather than type-checking Knox, Firebase, or
Google SDK objects.

There must be exactly one DRF bearer owner in
`config._drf_settings.REST_FRAMEWORK`. It parses `Authorization` once and
dispatches to the Knox personal-token adapter or the GCP service-ID-token
adapter by a closed, non-overlapping credential shape. Once a Bearer header is
present, every malformed, unknown, expired, revoked, wrong-type, wrong-audience,
or otherwise invalid credential raises the same authentication failure. No
delegate may return “not mine” and allow `SessionAuthentication` to accept the
request. Session authentication runs only when no Bearer credential was
present.

This dispatcher is a protocol boundary, not a new token verifier. Knox owns
personal-token generation and verification. Firebase Admin owns human Identity
Platform proof. `google-auth` owns service ID-token signature and claim
verification. Unverified JWT decoding may classify only a tightly bounded
candidate shape; it never supplies identity, audience, issuer, expiry, email, or
authority.

An OAuth access token is not accepted as a Shifter application bearer: it is not
bound to the Shifter application audience. The supported agent uses an
audience-bound ID token for Shifter and a separately acquired OAuth access token
for GCP APIs when cloud IAM is also granted. Possession of either credential or
either role implies none of the other authorities.

## Human provider and Django-session boundary

Keep `config.identity_platform`, the Firebase Admin SDK, exact immutable
`(issuer, subject)` management binding, Django authentication/session middleware,
and Django/DRF CSRF enforcement. Before a session is created, the provider proof
must establish signature, expiry, exact project audience, allowed issuer,
configured tenant, nonblank subject, verified email, provider and local
revocation state, and actual MFA use in this authentication event. The current
`mfaInfo` account lookup proves enrollment only and is insufficient by itself;
the verified provider result must carry the provider-documented second-factor
assurance for this sign-in. Missing, ambiguous, or unsupported assurance denies.

Email is an admission and bootstrap selector only. Resolution is by exact
provider tuple, and `management.services` remains the sole binding facade. A
tuple already bound to another principal, a subject under a different issuer,
an email match with conflicting binding, or a disabled `User`/`Principal` denies
without repair or rebind.

The Django session must retain only bounded authentication state: stable
principal UUID, immutable provider tuple reference, authentication time/MFA
proof, and the last successful provider-state check. It must not retain the raw
ID token. A single session-validation hook, shared by HTML, DRF, and Channels
entry points, re-resolves local principal/user activity on use and applies a
configured maximum provider-revocation staleness. Once that interval expires,
official provider state must be rechecked; lookup failure denies rather than
extending stale authority. Local disable, provider-binding disable/revocation,
or lifecycle deletion invalidates existing sessions as well as new logins.

Session absolute/idle lifetime and provider-recheck interval are bounded typed
settings, not view constants. Existing OIDC/SSO, passwordless recovery/magic
link, and email-free temporary participant login mechanisms remain available
through their established Django session path. This slice does not convert
those paths to bearer authentication or invent provider refresh logic.

## Personal-token boundary

django-rest-knox is the only personal-token library and persistence/verifier
authority. Personal tokens belong to a human principal and may use the linked
Django user where Knox requires it; they never represent their creator as a
service identity. Token name, safe display ID, immutable normalized scopes,
finite expiry, creation/revocation/rotation metadata, last-used metadata, and
owner principal are the only management projections. Raw token material is
returned once and is never persisted, logged, audited, placed in a URL, or
stored in frontend cache or browser storage.

Issuance is a session-and-CSRF-only security mutation. It requires a live,
explicit action from the sole `shared.authorization.ACTION_CATALOG`, rejects
temporary CTF principals and service principals, validates requested scopes
through the existing central scope registry, and requires the requested ceiling
to be a subset of the issuer's current live authority. No Bearer credential,
including a valid personal or service credential, may call issuance or rotation.

Use requires all of: valid Knox proof, active human principal, active local user,
unexpired/unrevoked token, immutable token ceiling, owning-domain lifecycle
checks, and the current live OpenFGA decision. A later grant does not expand an
existing token, and a revoked live grant immediately removes usable authority.
Scopes are a credential ceiling, never a second permission database.

An authenticated human may list and revoke their own token after losing the
issuance action. That narrow session-only ownership operation grants no issue,
rotate, inspect-secret, or other credential-management capability. Administrative
revoke remains a separate explicit action. Rotation creates a new Knox token and
revokes the old one atomically from the application's perspective; it does not
mutate scopes or secret material in place.

At S8, every existing custom-token row is deterministically associated with its
mapped human principal, safe metadata, validated scope set, and disposition.
Orphaned owners, temporary CTF owners, invalid scopes, non-finite expiry, or
ambiguous mapping fail closed and cannot produce a new credential. The migration
records reissue need; it never synthesizes or exposes a replacement secret.

## GCP service identity and supported-client boundary

A supported GCP service identity resolves through the existing immutable
`ProviderBinding` tuple to a `Principal(kind="service")`. The verified tuple is
the Google issuer plus stable numeric subject. Service-account email and resource
name are validated/display metadata, not identity keys; creator and responsible
contact remain attribution only. The admission record also fixes the accepted
Shifter audience and a closed application credential-ceiling profile. Audience
and ceiling are not smuggled into `ProviderBinding` as identity.

The service adapter uses `google-auth` verification with exact configured
audience and issuer, signature/expiry checks, `email_verified is True`, stable
subject checks, configured service-account binding, and active-principal/local
revocation checks. A human Firebase token, Google OAuth access token, token for
another deployment or endpoint, provider subject collision, email-only match,
or disabled principal denies. There is no just-in-time service-principal
creation from claims.

The supported agent transport accepts an audience and an official Google
credentials source, not a raw token. It lets Google credential objects refresh
before requests and performs at most the normal bounded retry for a safe request
after authentication refresh; it has no renewal thread, timer, daemon, token
cache format, JWT construction, or signing code. The same seam supports:

- local Application Default Credentials with explicit service-account
  impersonation;
- an attached Compute Engine/GKE workload identity; and
- supported external-account federation, including service-account
  impersonation where the source credential cannot itself mint a Google ID
  token.

Documentation must state the required IAM permissions, audience, source
credential type, impersonation requirement, and cloud/application grants for
each mode. Static service-account keys are not a supported shortcut. A
renewal-boundary integration test uses an expiring credential source and proves
that the official library obtains a different valid token without application
restart or manual intervention.

The service-account API/UI manages Shifter principals, provider admission,
application ceiling, active state, responsible contact, and safe identifiers.
It does not create or download keys, store source credentials, mutate Google
IAM, or imply that an application grant is a cloud role. Cloud IAM remains in
the owning GCP deployment/operator boundary.

## Temporary participant and event boundary

Temporary participants remain provider-free human principals with
`UserProfile.is_ctf_account`, mandatory password-change state, the existing
CTF group and middleware/WebSocket confinement, and exactly one live event
context. They cannot obtain provider bindings, personal tokens, service
credentials, account/platform administration, or installation scope. Existing
login, recovery, and magic-link mechanisms establish a Django session; CTF does
not add an authenticator.

`CTFParticipant` and the CTF participant services remain the owners of event
participation lifecycle. To permit QA automation, the participant authority key
may be the stable scalar principal UUID so a regular service principal can be
explicitly associated with an event. Do not fabricate a Django user for the
service, mark it temporary, or create a second service-participant table. Until
S8, any new source field is mapping-only and cannot be an OR-ed runtime authority.

A service participant receives only the exact live event-participant actions
allowed by the same status, role, team, event, and resource predicates as a
human participant, bounded by its service credential. It gets no local password,
human session, recovery path, personal token, account membership, platform role,
cloud role, or credential issuance right from participation. Event UUID is
always explicit; absence never means installation scope or “current event.”

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Architecture and cutover | ADR-066; `account-principal-scope-preflight-2314.md`; `openfga-authorization-preflight-2315.md` | Preserve one principal, one provider tuple, one action catalog, one policy authority, distinct cloud/application/event authority, and the S8 hard cut. |
| Identity | `management.models.Principal` / `ProviderBinding`; `management.services`; `management.principals`; `shared.identity_scope.PrincipalRef`; `shared.principal_port` | Resolve active human/service identity through the management facade. Keep exact immutable tuple uniqueness and scalar cross-domain references. |
| Human provider | `config.identity_platform`; `shared.verified_identity`; `config.views`; Django auth/session/CSRF; `config.middleware`; `config.websocket_auth` | Extend exact proof and lifecycle validation; do not replace Firebase Admin, Django sessions, or CTF origin gates. |
| Bearer admission | `config._drf_settings`; fail-closed behavior in `shared.api_tokens.authentication`; `shared.api.principals`; `shared.api.permissions` | Preserve bearer-first/no-fallback behavior while replacing token-specific actor inference with one typed principal/credential context. |
| Personal credential | django-rest-knox; `shared.api_tokens.scopes`; current token audit/last-used/coalescing behavior | Let Knox own token secrets and verification. Reuse the central scope vocabulary and safe operational metadata, not the custom verifier/model as a parallel runtime. |
| Application policy | `shared.authorization.ACTION_CATALOG`, `AuthorizationRequest`, `CredentialCeiling`; `workspaces.services` authorization facade and OpenFGA adapter | Add any credential-management action exactly once to the catalog; intersect the admitted ceiling with current policy and owning-domain checks. Do not use `installation.manage_principals` as an undocumented token permission. |
| CTF participation | `CTFParticipant`; `ctf.services.participant`; `ctf.services.authorization`; eligible/viewing participant predicates; `CTFAccountBoundaryMiddleware` and `CTFAccountWebSocketBoundary` | Preserve event lifecycle and confinement. Generalize the actor key to principal identity rather than copying participant logic for services. |
| API and validation | DRF; `ClosedSerializer`; `shared.api.strict_json`; `shared.api.errors`; `shared.api.schema`; versioned OpenAPI | Keep closed/size-bounded input, service-owned business logic, one sanitized error envelope, and generated contracts. |
| Audit and logs | `shared.audit`; `shared.api.audit`; `shared.log_sanitize`; request IDs and ECS logging | Extend one vocabulary, strict-audit credential mutations in their transaction, coalesce usage writes, and emit bounded reason codes/stable IDs only. |
| Persistence | Django migrations, named constraints, `transaction.atomic`, `select_for_update`, PostgreSQL test lane | Enforce binding uniqueness, immutable scopes/expiry, owner/principal shape, idempotent revoke, and race-safe rotate/disable. Model `clean()` or UI validation alone is insufficient. |
| Frontend | `frontend/src/api/client.ts`, Query client/mutations, generated `schema.d.ts`/types, Administer surface registry | Keep same-origin session/CSRF/request IDs and mutation retry disabled. Show a raw token once outside cache/storage; derive all other shapes from OpenAPI. |
| Configuration/deployment | `config/env-manifest.json`, `_env_manifest.py`, settings validators; `shifter/installation` schema/render/runtime inventories; `scripts/gcp/render_runtime_env.py`; GCP Terraform/Kustomize IAM surfaces | Carry typed non-secret IDs, audience, tenant, lifetimes, and secret references consistently. Reuse workload identities and IAM modules; never read ad hoc environment variables. |
| Official Google patterns | `shared.model_access.control_identity`, `shared.model_access.workload_identity`, and `model_broker` provider credentials | Reuse their official-library, exact-audience, bounded-error, and refresh posture as a pattern. Do not import model-access internals into platform authentication or broaden those domain credentials. |
| Workflow/evidence | API schema/type drift checks; import/layer checks; ADR guard; PostgreSQL suite; GCP render/IAM tests | Prove the shared boundary and every negative substitution/collision path across actual route and deployment inventories. |

## Cross-cutting security and runtime layers

1. **Transport and shape.** The web server and DRF impose header/body limits;
   the bearer parser accepts one bounded header with one credential; strict JSON
   and `ClosedSerializer` reject duplicate/unknown fields, invalid UUIDs/enums,
   unregistered scopes/actions, excessive lists, and client-supplied principal,
   ceiling, provider, or actor fields.
2. **Credential proof.** Firebase Admin, Knox, or `google-auth` is selected once
   and performs its native verification. Exact issuer/audience/tenant/token type,
   expiry, revocation, and assurance rules run before lookup. An unrecognized or
   failed Bearer never falls through to a session.
3. **Identity and lifecycle.** `management.services` resolves one immutable
   provider tuple or Knox owner to one active `PrincipalRef`, rejects collisions,
   and rechecks local principal/user state. Creator, contact, email, and cloud
   resource name are never actor aliases.
4. **Credential ceiling.** The server constructs the existing immutable
   `CredentialCeiling` from session kind, immutable Knox scopes, or configured
   service admission. No HTTP field or provider claim supplies it. Credential
   issuance, event participation, and application/cloud roles do not widen it.
5. **Scope and live policy.** `workspaces.services` resolves customer ancestry;
   CTF resolves event/participant state; the #2315 authorization facade checks
   the exact registered action with OpenFGA. All conditions are ANDed. Timeout,
   unavailable state, unknown action, and ancestry disagreement deny.
6. **Session and revocation.** Django CSRF/session middleware, the common session
   validator, provider-state interval, Knox revocation/expiry, service-binding
   disable, and principal lifecycle all apply to already-issued credentials.
   Disabling locally cannot leave a session, token, or service identity usable.
7. **Persistence and races.** Database constraints plus transactions/row locks
   arbitrate tuple collision, issue limits, revoke/rotate, binding changes, and
   S8 mapping. Security mutations and their strict audit record commit together;
   provider network I/O stays outside database transactions.
8. **Secrets, configuration, and OS exposure.** Raw tokens and source credentials
   never enter process arguments, query strings, URLs, Terraform output/state
   values where avoidable, ConfigMaps, environment diagnostics, shell history,
   browser persistence, audit, metrics, or logs. Provider secret stores, ADC,
   attached identity, and mounted secret/file references are the supported
   delivery surfaces.
9. **Errors and observability.** `shared.api.errors` maps authentication and
   authorization failures once to stable 401/403 codes, generic messages, and a
   request ID. Provider responses, token fragments/digests, claims, emails,
   subjects, bindings, and exception text never leave the trust boundary.
   Low-cardinality metrics distinguish credential kind and bounded result/reason,
   not identity values. Authentication-failure audit is rate-limited/best-effort;
   issue, rotate, revoke, bind, disable, and assurance-changing mutations are
   strict-audited.
10. **API/UI and generated contracts.** Management endpoints stay on versioned
    DRF, return only safe IDs/metadata, and declare session-only versus bearer
    admission explicitly. OpenAPI, generated TypeScript, the common frontend
    client, CSRF, and no-retry mutations remain one contract; no handwritten
    credential DTO or alternate frontend fetch path is added.
11. **Host and cloud runtime.** Typed settings and installation inventories carry
    the same audience, tenant, expiry/recheck bounds, and identity references to
    every supported runtime. Terraform/IAM owns workload permissions; Kubernetes
    owns private workload binding. The application does not download keys or
    infer cloud authority from an application role.

## Extensibility seams

- The bearer dispatcher registers a closed credential-kind adapter with a
  verify-and-resolve result; it does not expose provider objects to domains. A
  future native OIDC service provider can implement that seam only with its own
  exact issuer/audience/type validation and the same no-fallback rule.
- Service admission parameterizes audience and official credential source. It
  does not parameterize arbitrary issuers, token formats, validation callbacks,
  or raw bearer suppliers.
- `CredentialCeiling` and the one action catalog are the extension seam for new
  application operations. Scope-to-action mapping lives once; a new action does
  not require edits in each authenticator or domain.
- Stable principal UUID is the actor seam for CTF participation and other owning
  domains. Credential-specific columns, Django-user fabrication, and provider
  identifiers must not leak into those schemas.
- Session revocation interval, personal-token maximum lifetime, accepted service
  audiences, and service credential profile are bounded typed configuration.
  Adding another deployment or lifetime policy does not require editing the
  verifier or canonical DTO.

## Gotchas and anti-patterns

- Do not chain independent Bearer authenticators that can decline a credential;
  this reintroduces session fallback and token-type substitution.
- Do not accept a Google access token as an app ID token, a human Firebase token
  on the service audience, a token minted for another deployment, or a decoded
  JWT claim before official verification.
- Do not treat MFA enrollment, email verification, email match, provider group,
  or an old successful login as proof of current MFA assurance and identity.
- Do not make a service principal equal to its creator/contact, create a fake
  Django user, key it by email, or couple its lifecycle to a personal token.
- Do not copy Knox models, hash token secrets, mint JWTs, implement OAuth, retain
  the `shf_` verifier, add a compatibility validator, or build a renewal daemon.
- Do not make token scopes or cloud IAM a second application-policy engine.
  Credential ceiling, live OpenFGA policy, resource ancestry, and owning-domain
  lifecycle are separate AND-ed gates.
- Do not permit credential issue/rotation from any bearer, infer issue authority
  from Django staff, or block an owner from revoking their own token solely
  because issuance authority was removed.
- Do not mutate scopes, expiry, ownership, provider tuple, or secret in place.
  Reissue/rotate or explicitly disable; retain immutable audit history.
- Do not store raw credentials in Django sessions, database metadata, frontend
  Query cache/local storage, URLs, log context, audit details, metrics labels,
  task payloads, or CLI arguments.
- Do not duplicate serializers, exception hierarchies, audit tables, action
  names, scope validators, participant status predicates, provider-binding
  lookup, or request actor inference in each API/domain.
- Do not OR principal-based participant authority with legacy user authority
  before S8, and do not let a service participant escape its explicit event.
- Do not claim external federation support without naming whether service-account
  impersonation is required and testing the documented official-library path.

## Non-goals and implementation boundaries

- No implementation, runtime activation, data migration, dependency addition,
  endpoint, UI, Terraform/IAM mutation, or requirement update is performed by
  this preflight.
- No custom cryptography, token format, OAuth/JWT issuer, password/MFA mechanism,
  secret broker, renewal service, authorization evaluator, or cloud-IAM proxy.
- No replacement of Django sessions/CSRF, Firebase Admin verification,
  passwordless/recovery paths, temporary participant authentication, OpenFGA,
  or provider-native Google credential refresh.
- No static service-account-key workflow and no UI management of Google keys or
  cloud roles.
- No guarantee that account/application isolation implies separate database,
  project, network, key, or workload boundaries; those retain their owning
  infrastructure controls.
- No mixed-authority rollout. Source and mapping work may land earlier, but old
  tokens cease authentication and principal/policy authority switches only at
  the S8 cutover defined by ADR-066.

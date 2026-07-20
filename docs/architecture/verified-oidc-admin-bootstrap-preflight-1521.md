# Verified OIDC Administrator Bootstrap Preflight (#1521)

Status: pre-implementation guidance

Date: 2026-07-11

Issue: GitHub #1521, "REV1 Security: require verified OIDC email before
administrator bootstrap"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note fixes the trust boundary and the
cross-provider invariant; it is not an implementation plan.

## Scope boundary

This is a hardening of the existing provider-authentication and bootstrap-admin
seams, not a new identity framework. Keep these concepts separate:

1. **Protocol verification** proves that a token was issued for this Shifter
   deployment and request (signature, issuer, audience, expiry, nonce/state, and
   revocation where the provider supports it).
2. **Provider identity** is the case-sensitive `(issuer, subject)` pair from that
   verified evidence. Email and an upstream federation mechanism are attributes,
   not the account key.
3. **Bootstrap eligibility** is the existing runtime email policy in
   `PLATFORM_BOOTSTRAP_STAFF_EMAILS` /
   `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS`. It may select a user only after the
   provider has proved that exact email is verified.
4. **Platform elevation** is the mutation of Django `is_staff` /
   `is_superuser`. CTF user-type and organizer-group synchronization remain
   separate authorization paths with their existing controls.

The privilege invariant is:

> A provider login may bind or change bootstrap-admin flags only after strict
> provider verification has produced a non-empty issuer, subject, email, and the
> literal boolean `email_verified is True`; a previously bound account accepts
> only the same issuer and subject.

Missing, false, string-valued, or otherwise malformed verification evidence must
fail before user lookup, account creation/binding, group synchronization,
staff/superuser mutation, audit state that claims success, or session creation.
Provider-side email configuration is defense in depth and is not this gate.

## Architecture decisions and guardrails

- Both provider paths must converge on one small, immutable,
  provider-neutral verified-identity contract carrying only `issuer`, `subject`,
  `email`, and strict `email_verified` evidence (plus a bounded source label if
  audit attribution needs it). Shared contracts belong under `shared/`; do not
  add parallel OIDC and Identity Platform bootstrap DTOs.
- `config.identity_platform.IdentityUserClaims` is the incumbent normalized
  claims shape. Generalize/relocate that contract rather than leaving it in
  place beside a new OIDC schema; its current truthiness conversion must not
  survive the generalization.
- Provider-specific modules remain responsible for converting verified protocol
  results into that contract. A generic parser must not pretend Cognito UserInfo
  and Firebase token/account records have identical validation semantics.
- `config.bootstrap_admin.apply_bootstrap_admin_flags` is the incumbent policy
  seam. Evolve its input so a caller cannot elevate from a plain email string;
  do not add a second admin-bootstrap helper or move provider verification into
  the email policy.
- `management.models.UserProfile` and `management.services` remain the canonical
  persistence boundary. Extend the existing profile identity state with the
  verified issuer and replace the current overwrite-style subject update with a
  bind-once/compare operation. Do not add provider-specific user models,
  repositories, or a second identity table for this single-provider-per-runtime
  contract.
- `UserProfile.cognito_sub` is already used as subject storage by both providers
  despite its legacy Cognito name. For this issue, preserve the physical column
  compatibility, document it as the provider subject, and widen its Cognito-
  specific 36-character shape if necessary. Do not add a duplicate
  `identity_platform_sub` or `oidc_sub` column. A physical rename/drop is a
  separate compatibility change because historical migrations and the
  `mcp_user` table grant explicitly preserve that table for subject lookups.
- Issuer and subject are opaque, case-sensitive identifiers. Reject blanks; do
  not lowercase subjects or perform ad-hoc URL normalization. Persist the
  already-validated expected issuer, not an unchecked request value. Email may
  use the incumbent trim/lowercase normalization only for bootstrap-list
  comparison.
- Account resolution is identity-first. An exact stored issuer/subject match may
  find a returning user even when their email attribute changes. Email matching
  is allowed only for an unbound legacy account or first bootstrap and must never
  replace a different stored tuple.
- Binding is immutable during ordinary login. Under a database transaction and
  row lock: an exact tuple is idempotent; a legacy stored subject may acquire the
  validated issuer only when the presented subject is identical; an entirely
  unbound eligible account may bind once; any other issuer/subject difference or
  tuple collision fails closed. Never bulk-backfill issuer or subject from email.
- Binding, staff/superuser changes, and their strict audit record are one
  security mutation. Use `transaction.atomic()` and the existing
  `risk_register.services` audit facade so a failed audit or uniqueness check
  cannot leave partial privilege state. Login outcome auditing may retain its
  existing best-effort policy after the security mutation.
- A successful same-tuple login must preserve the incumbent reconciliation
  behavior: current bootstrap lists may grant or revoke staff/superuser. A tuple
  mismatch is rejected before either direction, so a drifted identity cannot
  elevate or de-elevate the existing account.
- Run all claim-derived mutations only after this gate. That includes
  `sync_user_type`, `sync_cognito_groups_from_claims`, and
  `reconcile_provider_privileged_groups`, even though those helpers retain their
  own authorization invariants.

## Provider-specific proof obligations

### Cognito / OIDC

`config.oidc.ShifterOIDCBackend` must continue to build on
`mozilla_django_oidc` for authorization-code exchange, signature/JWKS handling,
state/nonce, and callback/session behavior. Its additional obligations are:

- require a present email, subject, and literal JSON boolean
  `email_verified: true` in trusted provider evidence before the base backend's
  email lookup or user creation runs;
- validate the ID-token issuer exactly against the existing
  `OIDC_ISSUER_URL` runtime value and validate the audience/authorized-party
  relationship against `OIDC_RP_CLIENT_ID` before treating the issuer/subject as
  a binding key;
- require the UserInfo `sub` to equal the verified ID-token `sub`; and
- carry the verified ID-token issuer/subject into account resolution rather than
  deriving identity from the email-only UserInfo lookup.

This repository pins `mozilla-django-oidc` 5.0.2. Its base backend verifies the
JWS and nonce, but its local decode path disables audience verification and is
not passed an expected issuer; the Shifter adapter therefore cannot cite the
base call alone as evidence that the persisted issuer is trusted. Preserve the
library flow and add the missing Shifter deployment checks at the adapter
boundary rather than reimplementing OAuth/OIDC.

### GCP Identity Platform

`config.identity_platform` must keep
`firebase_auth.verify_id_token(..., check_revoked=True)` as the cryptographic
and project-boundary verifier, plus the existing account lookup for verified
email and enrolled MFA. Its additional obligations are:

- parse `iss`, `sub`, `email`, and `email_verified` strictly from the verified
  token; `bool(claims.get("email_verified"))` is not valid because the string
  `"false"` becomes true;
- require the account record's `emailVerified` value to be the literal boolean
  true as a second provider-state check;
- bind the verified token issuer and Firebase UID before bootstrap elevation;
  and
- keep upstream federation metadata such as `firebase.sign_in_provider` out of
  the account key. A password-to-Google sign-in-method change for the same
  Firebase issuer/UID is not provider drift, while the same email under a
  different UID or issuer is a different identity and must not claim the
  account.

`IDENTITY_PLATFORM_ISSUER` is the browser-visible TOTP display/QR issuer string,
not the ID-token issuer. It must not be repurposed for identity binding. The
token issuer is project-derived and verified by Firebase Admin using the
existing `IDENTITY_PLATFORM_PROJECT_ID` configuration.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail for #1521 |
| --- | --- | --- |
| OIDC protocol flow | `config.oidc.ShifterOIDCBackend`, `mozilla_django_oidc`, `config._oidc_settings` | Extend verification/account resolution without replacing the code-flow, callback, state, nonce, JWKS, or session machinery. |
| Identity Platform flow | `config.identity_platform.verify_identity_token`, `_assert_account_can_create_app_session`, `IdentityPlatformBackend`, `config.views.identity_platform_session` | Preserve revoked-token, domain, verified-account, MFA, POST/CSRF, and fixed-error behavior. |
| Normalized identity evidence | `config.identity_platform.IdentityUserClaims` | Generalize the existing immutable shape into the dependency-neutral shared contract; do not create a sibling OIDC DTO or reuse raw mappings after validation. |
| Bootstrap policy | `config.bootstrap_admin.apply_bootstrap_admin_flags` | Make verified identity evidence mandatory; keep the runtime email lists as selectors, not identity keys. |
| User/profile persistence | `management.models.UserProfile`, `management.services.get_user_profile`, current subject persistence | Evolve this service boundary to resolve and bind immutable issuer/subject state; do not write profile fields directly from both providers. |
| Role synchronization | `config.user_type_sync`, `config.cognito_groups`, `config.organizer_authority` | Invoke only after identity verification/binding; do not merge their CTF/organizer policies into bootstrap admin. |
| Audit | `risk_register.services.audit_log`, `audit_role_sync`, `audit_auth_event`, `AuthPrincipal`; `AuditLog.Action.ROLE_SYNC` | Reuse the durable audit model and strict-write mode for binding/elevation. Do not create another audit table or free-form event taxonomy. |
| Errors | OIDC `SuspiciousOperation`/existing callback failure; `IdentityPlatformAuthError` codes; `shared.errors.classify_user_message` | Translate internal binding conflicts at provider boundaries and preserve generic client responses. Do not expose whether an email, issuer, subject, or privileged account matched. |
| Logging | module loggers, `shared.log_sanitize.safe_log_value` / `safe_log_fingerprint` | Log bounded outcome categories or fingerprints, never tokens, authorization codes, full claim mappings, provider bodies, or raw issuer/subject pairs. |
| Runtime configuration | `config._oidc_settings`, `config._runtime_env`, `config._env_manifest`, committed `env-manifest.json` | Reuse `OIDC_ISSUER_URL`, `OIDC_RP_CLIENT_ID`, and `IDENTITY_PLATFORM_PROJECT_ID`; no new allowed-issuer knob is needed. |
| Deployment binding | `entrypoint.sh`, AWS SSM/user-data and `scripts/portal-deploy`, GCP `render_runtime_env.py` and runtime inventory | No new secret or env value should be introduced. Existing bootstrap-list validators and issuer/project bindings stay authoritative. |
| Import boundaries | `.importlinter`, `shared` contracts, `management.services` | `shared` must stay dependency-neutral; `management` must not reach into provider/config or CTF layers. |

`risk_register.services.AuthPrincipal.cognito_sub` is another legacy
provider-specific name already populated by Identity Platform. Do not add an
Identity-Platform-specific audit principal beside it. If binding evidence is
added to auth audit state, evolve the existing facade toward provider-neutral
issuer/subject vocabulary while preserving any durable audit-key compatibility.
The same caveat applies to `audit_auth_event`'s default
`ActorType.COGNITO`: Identity Platform currently inherits that label. It is not
proof of provider identity. If #1521 needs provider-distinct audit attribution,
extend the bounded incumbent vocabulary once and keep both callers on the same
facade; do not encode provider identity in free-form context text.

## Cross-cutting security layers

1. **Browser/request shape.** OIDC stays on the library callback with state and
   nonce. Identity Platform stays a CSRF-protected POST and must require a JSON
   object containing a non-empty string ID token; do not coerce lists, objects,
   or other values with `str(...)`.
2. **Token/protocol validation.** Cognito adds exact issuer and audience checks
   to the existing JWS/nonce flow and checks ID-token/UserInfo subject parity.
   Identity Platform retains Firebase Admin project/signature/revocation checks.
3. **Claim shape/policy.** Both paths require non-empty issuer/subject/email and
   literal-true verification before any ORM lookup. Identity Platform also keeps
   the provider account, allowlist, and MFA gates.
4. **Account resolution/persistence.** The management service resolves the
   issuer/subject tuple first and performs immutable, collision-safe binding
   under a row lock. Email is only the constrained unbound-account seam.
5. **Privilege/authorization mutation.** Bootstrap flags, CTF claim sync, and
   provider organizer reconciliation run only after the identity gate. Their
   existing separate policies remain intact.
6. **Audit/observability.** Security state changes use strict existing audit
   writes in the transaction. Rejections use bounded reason categories. Raw
   provider artifacts never enter logs or audit JSON.
7. **Error envelope.** OIDC retains the generic callback failure path; Identity
   Platform retains fixed `IdentityPlatformAuthError.code` values and classified
   messages. Tuple mismatch details stay server-side and sanitized.
8. **Configuration and secret handling.** Expected Cognito issuer/client data
   already comes from the OIDC Secret Manager bundle via `entrypoint.sh`; the GCP
   project ID and bootstrap lists already flow through the validated runtime env
   renderer/inventory. No new secret shape, Terraform output, ConfigMap key, or
   environment binding is required.
9. **OS/runtime exposure.** Identity/access tokens remain request-memory values
   passed to provider APIs in HTTP bodies/headers. They must never be written to
   process argv, environment variables, generated env files, database columns,
   exception messages, or command output. The only new durable value is the
   non-secret issuer paired with the existing opaque subject.

Provider infrastructure is upstream defense in depth: Cognito
`auto_verified_attributes`, its pre-signup allowlist, Identity Platform's
`allow_duplicate_emails = false`, and the optional `beforeCreate` function all
reduce risk but do not replace the application gate. No Terraform, blocking
function, password, MFA, or bootstrap-operator provisioning change is required
to satisfy this issue.

## Persistence and migration boundary

- Add new migration state only under `management/migrations`; do not edit the
  historical `mission_control` / `ctf` migrations or duplicate their frozen
  models.
- Legacy rows must remain deployable. A row with an existing subject and no
  issuer may acquire the configured, verified issuer only when the next login
  presents that same subject. A row with neither value may bind once after all
  gates. A row with a different value is denied; login must never "repair" it by
  overwriting evidence.
- Do not infer or backfill a subject from email. Do not silently choose among
  duplicate email users. Database uniqueness/integrity failures are auth
  failures, not permission to retry with another account.
- Validate model/migration agreement with Django's migration checks and test the
  historical unbound/subject-only states. Persistence tests should drive the real
  management service and database, mocking only the external provider boundary.

## Extensibility seam

The next reasonable variation is another verified provider behind the existing
single `AUTH_PROVIDER` runtime selection. It should need only an adapter that
produces the same verified-identity contract and provider-specific protocol
tests; the management binding service, bootstrap policy, audit mutation, and
provider-conformance tests must remain unchanged. The seam parameter is the
validated `issuer`/`subject`/`email`/`email_verified` evidence value, not a new
allowed-provider list or an `if provider == ...` branch in persistence.

Explicit multi-provider account linking, automatic account recovery after an
issuer migration, or multiple identities per Django user is a different product
contract. Do not pre-authorize those behaviors by accepting multiple tuples or
silently rebinding during login.

## Whole-repository surfaces

The implementation is bounded by these existing surfaces:

- provider and HTTP boundaries: `config/oidc.py`,
  `config/identity_platform.py`, `config/views.py`, and
  `config/_oidc_settings.py`;
- shared policy/persistence: `config/bootstrap_admin.py`, a dependency-neutral
  shared verified-identity contract, `management/models.py`,
  `management/services.py`, and a new management migration;
- cross-cutting mutation and observability incumbents:
  `config/user_type_sync.py`, `config/cognito_groups.py`,
  `config/organizer_authority.py`, `risk_register/services.py`, and the existing
  `AuditLog` model;
- regression surfaces: `tests/mission_control/test_oidc.py`,
  `tests/config/test_identity_platform.py`, management-service/migration tests,
  settings/env-manifest checks, and one provider-parameterized invariant suite;
- inspected runtime layers expected to remain unchanged: `entrypoint.sh`,
  AWS portal user-data/deploy scripts and Cognito Terraform, GCP runtime-env
  rendering/inventory and Identity Platform Terraform/function code.

If no new environment binding is added, `config/env-manifest.json`, GCP runtime
inventory, Terraform, Kubernetes, and deployment scripts must remain unchanged.
If implementation nevertheless changes one of those shapes, it must update and
pass that surface's existing generator/validator rather than hand-maintaining a
second copy.

## Gotchas and anti-patterns

- Do not use `bool(email_verified)`, truthiness, or a default that turns a
  missing claim into acceptance. Only the literal boolean true passes.
- Do not validate after `filter_users_by_claims`, `get_or_create`,
  `apply_bootstrap_admin_flags`, profile/group writes, or session login.
- Do not treat a configured Cognito pool, provider email allowlist,
  `auto_verified_attributes`, or Identity Platform `beforeCreate` hook as proof
  carried by this login.
- Do not use email, subject alone, issuer alone, username, provider group,
  `firebase.sign_in_provider`, or the TOTP display issuer as the account key.
- Do not overwrite a stored binding when the same email arrives from another
  issuer/subject, including a federated identity. Do not "heal" drift by changing
  the database or by creating a second privileged user.
- Do not duplicate raw-claim schemas, validation helpers, bootstrap workflows,
  exception hierarchies, audit models, or provider-specific profile fields.
- Do not fold organizer authority, self-service CTF roles, or local Django-admin
  assignment into the bootstrap-email policy.
- Do not return or log raw exception text when it may contain provider response
  bodies, tokens, authorization codes, client IDs, claims, or identity tuple
  details. Do not log the existing subject with the current unsanitized
  `management.services.update_cognito_sub` pattern.
- Do not mock `apply_bootstrap_admin_flags`, the binding service, or audit facade
  in the acceptance tests. Patch Firebase/network or the mozilla provider
  boundary, then assert committed user/profile/audit state and absence of writes
  on rejection.
- Do not edit old migrations, weaken `.importlinter`/ADR guard, add a migration
  exception, or introduce a new env knob to make tests easier.

Negative coverage must include both providers and prove no write/elevation for:
missing verification, false verification, malformed non-boolean verification,
issuer drift, subject drift with the same verified email, and a federated
same-email/different-subject identity. Also preserve positive coverage for the
same bound tuple and for a federation method change that retains the same
verified issuer/subject.

## Non-goals

- No implementation in this preflight.
- No formal Ground Control requirement or traceability work.
- No replacement of Cognito, Identity Platform, `mozilla-django-oidc`, Firebase
  Admin, Django sessions, or the provider-selection model.
- No new password handling, MFA policy, domain allowlist, bootstrap-email input,
  provider group semantics, CTF role mapping, or organizer-authority policy.
- No multi-provider account-linking UI, automatic issuer migration, account
  recovery workflow, or bulk email-based identity backfill.
- No physical rename/removal of the legacy subject column unless separately
  scoped with all database/MCP consumers migrated.
- No Terraform, Kubernetes, Secret Manager, SSM, runtime-env, or OS topology
  change unless the implementation introduces an otherwise-unnecessary config
  shape.

## Validation obligation for the later implementation

Changes under `shifter/shifter_platform` must pass the repository's targeted
provider, management/migration, and audit tests; Ruff format/lint; mypy where
configured; Django migration drift checks; import-linter; and the full ADR guard.
The provider-parameterized invariant tests must assert persisted state and query
ordering, not merely helper return values.

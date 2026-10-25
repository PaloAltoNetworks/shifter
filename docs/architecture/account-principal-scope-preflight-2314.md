# Account, principal, and resource-scope preflight (#2314)

Status: architecture guidance for the authorized S1 source integration;
production authority cutover remains S8

Date: 2026-09-20

Contract: active Ground Control requirement PLAT-2011 and GitHub issue #2314,
under the #2308 redesign; PLAT-232 and PLAT-233 are adjacent requirements

This note records the minimum repository-wide boundaries for S1. It is not an
implementation plan and adds no runtime model, migration, endpoint, policy, or
authentication behavior.

The issue names `docs/design/identity-authorization-2308-proposal.md`, but that
file is absent from this checkout. ADR-066 records only the binding decisions
needed by S1. Later slices must restore or otherwise reconcile the accepted
parent design before using this note as authority for policy, token, cloud-IAM,
or cutover work.

## Readiness decision

S1 is architecture-ready only with ADR-066's explicit supersession. Without
that supersession, the repository would retain two incompatible historical
assumptions:

- ADR-046 and ADR-048 require a personal organization and workspace for every
  user; and
- ADR-054 requires one customer per deployment.

Issue #2314 requires individual accounts without subdivisions and shared B2C and
B2B hosting. Editing models while leaving those older rules authoritative would
make both the migration and authorization behavior internally contradictory.
ADR-066 keeps the existing bounded domains and cross-cutting controls while
replacing those two assumptions. The current PLAT-2011, PLAT-232, and PLAT-233
wording is aligned with ADR-066; implementation traceability must remain aligned
as artifacts change.

## Fixed domain and contract boundaries

### Account hierarchy

`workspaces` remains the sole persistence and policy owner for customer scope.
Extend it with `Account`; do not create a tenancy app, account repository, or
account copy under `management`, `shared`, CMS, Engine, CTF, frontend state,
provider labels, or OpenFGA.

| Account type | Required hierarchy | Forbidden default |
| --- | --- | --- |
| individual | account only | organization, workspace, or membership inferred from the person |
| team | one default organization; one default workspace per organization; optional additional organizations/workspaces | creator-derived owner/admin grant |
| enterprise | one default organization; one default workspace per organization; optional additional organizations/workspaces | creator-derived owner/admin grant |

`Account`, `Organization`, and `Workspace` keep immutable public UUIDs and local
database primary keys. `Organization.account` and `Workspace.organization` are
real intra-domain relationships. Existing organization/workspace IDs are
preserved; rebuilding rows to obtain a cleaner hierarchy is prohibited.

Type and default vocabularies are closed. Named database constraints enforce
closed values, unique public UUIDs, and at most one default organization per
account and default workspace per organization. The domain service creates the
required default graph atomically and idempotently and verifies the at-least-one
invariant. A Django `CheckConstraint` cannot prove a cross-table rule such as
“individual has no organizations”; the locked service and mapping validation
must prove it. Do not denormalize `default_organization_id` and `is_default` as
two writable truths.

### Principal identity

`management` remains the identity boundary. One stable `Principal` has a closed
human/service kind. A human principal has exactly one existing Django user; a
service principal has none. Provider bindings are separate immutable rows keyed
by exact `(issuer, subject)` and point to the principal. This preserves Django
sessions, lifecycle, staff/superuser behavior, and local CTF users without
turning `UserProfile` into the new customer account.

The current `UserProfile.cognito_sub unique=True` is a legacy global-subject
constraint. The durable key is already specified by ADR-009 as the tuple. Move
canonical uniqueness only after every complete legacy tuple is mapped; do not
relax the old constraint first and leave two writable binding stores. A
subject-only legacy row is unresolved until an exact issuer is established by
trusted mapping evidence. Email is never that evidence.

A service principal's creator and responsible contact are attribution and
operations relationships. They are not identity or ownership aliases. Use
non-cascading lifecycle semantics so changing or deleting a contact cannot
delete, re-key, transfer, disable, or reauthorize the service. `ApiToken`, GCP
service accounts, Workload Identity subjects, `shared.audit.AuthPrincipal`, and
`shared.api.principals.active_actor_user` are existing credential, cloud, audit,
or request concepts; none is the new durable principal record.

Temporary CTF users map to human principals by user ID even when email and
provider binding are absent. Keep `UserProfile.is_ctf_account`, the first-login
password gate, event participation, provider-login denial, token denial, and
middleware checks. Do not generate an email, issuer, provider subject, account
membership, or personal workspace for them.

### Membership and authorization

Membership rows target the stable principal. Because `Principal` is owned by
`management`, `workspaces` stores its validated scalar identity and must not add
a cross-layer foreign key. The `management.services` public facade resolves
authenticated Django users to principal references; `management.principals` may
hold same-domain implementation but is not a cross-domain import surface.
Workspaces services resolve and authorize customer membership. Consumers
receive frozen scalar results through `workspaces.services`. If a consumer needs
a new principal operation, re-export the narrow operation from
`management.services` and update the existing facade allowlist rather than
importing the implementation module.

Keep account, organization, and workspace membership distinct. Current
`OrganizationMembership` and `WorkspaceMembership` role vocabularies and
`workspaces.roles` are incumbents to evolve, not schemas to duplicate. Default
hierarchy creation writes no membership. An explicitly requested account or
workspace creation operation may compose a separately authorized membership
mutation, but “creator” alone is never the grant.

OpenFGA is not present in the current dependency or configuration inventory.
S1 establishes stable object and principal identities that a later policy slice
can project. It does not add a local tuple table, an authorization cache, a
custom policy evaluator, or an OpenFGA availability fallback. Until the S8 hard
cut, current workspaces service checks remain the runtime authority and the new
model is not a second live policy source.

### Shared `PrincipalRef` and `ResourceScope`

Use one dependency-neutral shared module for the frozen principal reference and
closed scope contract. Follow `shared.verified_identity`'s single-constructor
validation pattern and the repository's closed Pydantic/wire-contract patterns
where serialization is required. Do not define one shape in each domain, in
OpenAPI, and in OpenFGA.

`PrincipalRef` contains only the principal's stable opaque UUID and closed
human/service kind. It never embeds a Django user ID, provider tuple, email,
credential, account, membership, role, or policy. Only the management facade
resolves persisted identity into this reference; a composition boundary obtains
it before calling the workspaces facade, so neither domain imports the other's
models.

Principal identity and resource scope remain orthogonal. `ResourceScope` never
contains an owner or actor, and account membership never implies resource
ownership. When an owning domain records or maps an owner, it keeps the stable
principal UUID as a separate validated scalar fact while preserving any legacy
user/request identity required before S8. It must not derive the owner from the
account, the default hierarchy, the caller, or the first membership row.

The valid scope shapes are:

| `kind` | account | organization | workspace |
| --- | --- | --- | --- |
| `installation` | absent | absent | absent |
| `account` | required | optional | optional only when organization is present |

`ResourceScope` is an internal service value. HTTP and other untrusted inputs
name customer objects by public UUID and the workspaces facade resolves them
once; owning-domain persistence retains the validated internal scalar IDs,
including compatible existing integer workspace IDs. Internal IDs never enter a
public response.

The shared validator rejects unknown fields/kinds, non-canonical or invalid IDs,
installation scope with customer IDs, account scope without account, and a
workspace without organization. `workspaces.services` performs the database
validation the shared layer cannot: account type, organization-to-account and
workspace-to-organization ancestry, current lifecycle, and operation policy.
Every consumer uses that result. `account_id IS NULL`, missing workspace, an
empty mapping, or a caller flag can never mean installation scope.

Owning domains keep scalar scope columns and their own transaction/lifecycle
truth. The initial inventory in scope is the already workspace-bound chain:

- CMS `Request.workspace_id` and `RangeInstance.workspace_id`;
- Engine `Range.workspace_id`;
- CTF `CTFEvent.workspace_id` and `CommunicationCampaign.workspace_id`; and
- service projections, launch/replay digests, queries, and migration checks that
  consume those fields.

The owning rows need an explicit scope discriminator and account identity so an
individual can be account-scoped. Organization/workspace components may be
optional only under the shared contract. Keep the existing scalar
workspace IDs where present and valid. Do not replace them with a JSON scope,
infer ancestry on read, or add cross-layer foreign keys. Other user-owned
assets, tokens, catalog objects, model-access accounting, CTF participation,
and cloud resources do not acquire account scope merely because they contain a
user field; each owning slice must name that decision.

## Deterministic mapping boundary

The one-time mapping is a security migration, not a best-effort cleanup.
Historical migrations remain untouched. New migrations use historical Django
models, preserve IDs, and fail before S8 activation when evidence is incomplete
or contradictory.

Canonical mapping keys and stop conditions are:

| Current fact | Deterministic target | Fail-closed condition |
| --- | --- | --- |
| Django user ID | one human principal | duplicate/missing principal mapping |
| complete `UserProfile` issuer + subject | provider binding for that human principal | tuple already bound elsewhere or tuple disagreement |
| no provider fields, including temporary CTF user | human principal with no provider binding | fabricated email/issuer/subject |
| organization/workspace membership user ID | the mapped principal at the same durable scope and role | missing principal or duplicate/conflicting role |
| resource owner/request user projections | the mapped principal while preserving current owner facts | CMS/Engine/CTF owner or scope disagreement |
| valid shared organization/workspace | same organization/workspace IDs under an explicitly typed account | account type or ancestry cannot be proved |
| synthetic personal hierarchy | individual account-level scope when every ownership and membership fact agrees | extra members, non-synthetic data, conflicting owner, or foreign resource scope |

Do not classify rows by the display name `Personal`, email, username, first/last
row, group, or nullability. Team versus enterprise is not encoded in the current
schema and cannot be inferred. Any required mapping input must be explicit,
bounded, keyed by durable public identity, validated before writes, and kept out
of logs and process arguments; it is data-migration input, not a new product
approval workflow or customer-specific branch.

An ambiguous row remains unchanged and blocks activation with internal row IDs
and bounded reason codes. It is not deleted, attached to an arbitrary account,
converted to a team account to preserve a personal workspace, or repaired by a
runtime read. S1 tests the new fixtures and mappings; production authority does
not partially switch before S8.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Layer ownership | ADR-001; `.importlinter`; `scripts/check_layer_imports/layer_imports.yaml`; `management/management/commands/check_model_fks.py` | Keep Account in `workspaces`, Principal/bindings in `management`, contracts in `shared`, and scalar cross-domain references. Extend public service facades only. |
| Customer persistence/policy | `workspaces.models`; `workspaces.roles`; `workspaces.services._authorization`, `_memberships`, `_organization`, `_lifecycle`, `_personal` | Reuse public UUIDs, frozen projections, opaque denials, central role policy, row locks, idempotence, and strict audit. Retire the personal resolver as a default at cutover; do not copy its workflow. |
| Identity persistence | `management.models.UserProfile`; public `management.services`; same-domain `management.principals`; `management.services.resolve_user_by_provider_identity` and `bind_provider_identity`; user-profile creation signal; `management.lifecycle` | Preserve Django users and lifecycle, converge providers through one management service, and map bindings atomically. Cross-domain callers use only `management.services`; do not add provider-specific principal tables or import `management.principals` directly. |
| Provider verification | `shared.verified_identity`; `config.oidc.ShifterOIDCBackend`; `config.identity_platform.IdentityPlatformBackend`; `config.bootstrap_admin` | Keep issuer/audience/authorized-party/subject/verified-email and MFA/allowlist gates before lookup or mutation. Email remains a selector only. |
| Temporary CTF access | `UserProfile.is_ctf_account`; `management.services.configure_temporary_ctf_account`; CTF participant auth/middleware tests | Preserve provider-free, email-free local access and every deny-authoritative origin check. |
| HTTP admission | `config._drf_settings`; bearer-first `ApiTokenAuthentication`; `SessionAuthentication`; `shared.api.principals.active_actor_user`; exact token scopes | Invalid bearer credentials fail closed; unsafe session requests keep CSRF; credential admission remains separate from customer policy. S1 adds no auth scheme. |
| Validation/API | explicit DRF serializers; `ClosedSerializer`; `shared.api.strict_json`; `shared.api.errors`; generated OpenAPI/client types | Validate HTTP shape at the edge and domain invariants in the owning service. Return one sanitized request-ID envelope. Do not hand-copy DTOs or reflect exception text. |
| Persistence/concurrency | Django migrations, `transaction.atomic`, `select_for_update`, named unique/check constraints, real PostgreSQL lane | Serialize default creation, membership, binding, and mapping; let uniqueness arbitrate races; test the actual migration graph and PostgreSQL constraints. |
| Audit | `shared.audit` event/attribution/policy/vocabulary and immutable store | Add vocabulary members only to the canonical enum; strict-audit security mutations in their transaction using bounded IDs/codes. Do not revive `ActivityLog` or create an identity audit table. |
| Logging | `shared.log_sanitize`; request IDs; existing bounded auth logging | Log internal IDs and reason codes where needed; fingerprint provider/email values. Never log tuples, emails, tokens, rosters, mapping payloads, SQL, or raw provider errors. |
| Runtime configuration | `config/env-manifest.json` and `config/_env_manifest.py`; settings validators; `shifter/installation/schema.py`, `loader.py`, `render.py`, and `runtime_inventory*.py`; `platform/k8s/**`; `platform/terraform/**` | S1 needs no new env, secret, workload identity, service account, or cloud setting. Any later integration must extend the canonical inventories instead of reading ad hoc environment variables. |
| Tests/workflow | identity binding invariant tests; workspaces model/service/API tests; `MigrationExecutor` patterns; `make test-platform-postgres`; OpenAPI drift; ADR guard | Extend real service and migration tests, including collisions and ambiguity. Mock provider/network boundaries, not first-party services (ADR-019). |

## Cross-cutting security and runtime layers

1. **Provider proof.** Cognito/OIDC still verifies signature, issuer, audience,
   authorized party, subject, nonce/state, and verified email. Identity Platform
   still verifies a non-revoked token, exact issuer/subject, server-side email
   admission, account email verification, and MFA. Both construct the same
   `VerifiedIdentity` before principal lookup or binding. No account ID,
   organization, workspace, email, or group from claims is customer authority.
2. **Django and credential admission.** Existing Django users, inactive/deleted
   checks, session authentication/CSRF, fail-closed bearer parsing, exact token
   scopes, and CTF origin checks remain in front of domain policy. Future Knox
   credentials attach to a principal through its owning slice; `ApiToken` is not
   silently relabeled as a service principal.
3. **Shared shape validation.** `PrincipalRef` and `ResourceScope` are closed,
   immutable, dependency-neutral values. The constructor rejects malformed
   combinations before a domain receives them. This is the only shape validator;
   serializers and persistence adapters call it instead of reimplementing its
   truth table.
4. **Customer ancestry and policy.** `workspaces.services` resolves the stable
   IDs, proves Account -> Organization -> Workspace ancestry, rejects a
   subdivision for an individual account, and applies the exact live membership
   operation. Cross-account IDs fail with the same opaque denial as missing or
   unauthorized scope. Cached frontend context and future OpenFGA data are not a
   fallback authority.
5. **Owning-domain validation.** CMS, Engine, and CTF keep their lifecycle,
   owner, event, participant, range-access, replay, and generation checks. A
   valid `ResourceScope` is additive and grants none of those authorities. Scope
   and owner-principal facts are validated separately. Scope changes update every
   owning projection atomically or fail; no reader repairs drift and no
   membership lookup manufactures an owner.
6. **Database enforcement.** Unique and check constraints protect account type,
   public identity, default uniqueness, principal kind/user shape, exact provider
   tuple uniqueness, and membership/scope cardinality. Cross-row ancestry and
   exactly-one defaults are service/migration invariants under locks. Model
   `clean()` or `save()` alone is insufficient because bulk writes bypass it.
   Provider identity fields have no ordinary update path; database-level
   immutability protection should follow the repository's existing audit/cutover
   trigger pattern if updates cannot otherwise be excluded.
7. **Errors and enumeration resistance.** Domain-specific errors stay under the
   existing management/workspaces/CMS hierarchies and map once through
   `shared.api.errors`. Provider collision is a generic authentication failure;
   customer scope absence, cross-account ancestry, and missing membership are
   indistinguishable externally. Migration diagnostics contain bounded reason
   codes and internal row IDs only.
8. **Audit and observability.** Principal/binding, account, default, and explicit
   membership mutations use `shared.audit` with trusted request attribution and
   strict writes when authority changes. Audit state contains IDs, kinds,
   changed field names, and outcomes, never provider tuples, emails, tokens,
   claims, policy bodies, or mapping payloads. Metrics use low-cardinality kinds
   and outcomes, never principal or tenant identifiers.
9. **Secrets and configuration.** Provider subjects and customer IDs are not
   credentials, but remain sensitive identifiers. No new secret is needed for
   S1. Token values, provider payloads, and future OpenFGA/Knox/GCP credentials
   continue through their canonical secret/config owners and never enter model
   defaults, fixtures, Terraform values, ConfigMaps, or audit state.
10. **OS, worker, and cloud exposure.** Principal bindings, memberships, scope
    objects, and mapping input do not enter shell text, process argv, environment
    dumps, provisioner commands, Job specs, guest metadata, provider labels, or
    static bundles. Existing operation envelopes may carry only the validated
    non-secret scalar scope projection when an owning contract explicitly needs
    it. GCP service accounts and Workload Identity remain cloud principals, not
    application Principal rows.
11. **Repository gates.** Architecture and platform changes must pass ADR guard,
    layer imports, cross-layer FK checks, Ruff/format/mypy, missing-migration
    detection, focused SQLite tests, the PostgreSQL semantics lane, and any
    generated API compatibility checks for touched routes. Mapping tests must
    start from the real historical schema and prove both successful and blocked
    cases.

## Extensibility seams

The stable seam between authentication and policy is `PrincipalRef`. Adding a
second verified provider binding, a Knox credential, or another native
credential type attaches it to the same principal and does not change account
memberships or resource ownership. Provider adapters continue to emit
`VerifiedIdentity`; only the management binding service knows persistence.

The stable seam between customer policy and owning domains is `ResourceScope`
plus one `workspaces.services` ancestry/authorization resolver. A later scoped
policy or resource kind consumes the same explicit discriminator and optional
ancestry without adding nullable-ID inference or another role matrix.

The account-default seam is one service operation parameterized by the closed
`AccountType`. A future accepted account type adds its hierarchy policy there
and to the database vocabulary; it does not add type branches across CMS,
Engine, CTF, auth adapters, or frontend code.

## Gotchas and anti-patterns

- Do not reuse `management.lifecycle.AccountLifecycleState` for customer
  Account lifecycle. It currently describes Django-user authentication state.
- Do not treat Account, User, UserProfile, Principal, provider identity,
  ApiToken, audit `AuthPrincipal`, CTF participant, Django Group, GCP service
  account, organization, or workspace as aliases.
- Do not make a service principal a Django user, copy its creator's memberships,
  cascade-delete it with a contact, or transfer it when responsibility changes.
- Do not bind or merge by email, username, provider group, subject alone, or a
  first match. Do not overwrite a tuple, relax uniqueness before canonical
  mapping, or keep `UserProfile` and provider-binding rows as dual authorities.
- Do not infer installation scope from null account/org/workspace fields. Do not
  accept a client-supplied internal ID, scope kind, ancestry, role, or authority
  source as trusted.
- Do not embed an owner or actor in `ResourceScope`, infer a resource owner from
  account membership/defaults, or use account scope as proof that the caller may
  act. Preserve owner principal identity as a separate scalar fact.
- Do not attach an organization to an individual account to preserve a legacy
  personal workspace. Do not classify a shared organization as team or
  enterprise without explicit evidence.
- Do not call the current personal-workspace resolver as the fallback for a
  missing scope. Do not let a read create Account, Organization, Workspace,
  Principal, binding, membership, or policy state.
- Do not let default organization/workspace creation grant owner/admin/member,
  reuse `create_workspace` in a way that inherits its creator-owner side effect,
  or infer privilege from account type.
- Do not duplicate account/principal/scope schemas in JSON fields, serializers,
  OpenFGA tuples, frontend types, task payloads, or provider tags. Runtime
  serializers and generated contracts project the canonical domain/shared
  values.
- Do not add a generic repository, policy engine, exception tree, audit store,
  mapping runner, bootstrap script, background repair loop, or feature flag.
  Django migrations and existing services own schema and mapping.
- Do not silently repair mismatched CMS/Engine/CTF scopes, delete personal rows,
  rewrite ownership, or hide unresolved data behind an “unknown account.”
- Do not claim multi-customer isolation from UUIDs, filters, tests against
  SQLite, provider project names, or ADR text. Authorization, migration,
  PostgreSQL, secret, IAM, and network evidence remain separate obligations.

## Non-goals and implementation boundaries

- No source implementation, migration, API, fixture, or production data change
  is made by this preflight.
- No S8 production cutover, compatibility window, staged authority switch,
  rollback path, or deployment-specific customer fork.
- No OpenFGA model/evaluator/client, django-rest-knox integration, GCP IAM or
  renewal change, authentication protocol, token format, JIT/Vault product, or
  new approval workflow.
- No account/organization/workspace management API or SPA, invitation redesign,
  group lifecycle, scoped-policy authoring, principal credential lifecycle, or
  service-principal UI.
- No change to Django staff/superuser semantics, temporary CTF password access,
  CTF event/team/participant authority, API-token scopes, remote access,
  provisioning, cloud placement, secrets, network, catalog, or audit-reading
  policy.
- No automatic scoping of every user-owned table. S1 covers the named
  account/principal contracts and the existing workspace-bound ownership chain;
  another domain needs an explicit ownership decision before gaining scope.
- No deletion or transfer lifecycle for Account or Principal and no automatic
  cleanup of legacy ambiguous data.

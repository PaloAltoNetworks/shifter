# Workspace lifecycle preflight (PLAT-233, #1940)

Status: pre-implementation guidance reconciled with ADR-066 and #2314;
production authority cutover remains the coordinated S8 change

Date: 2026-09-20

Requirements: PLAT-233 (implements), PLAT-241 (constrains)

This note fixes the repository-wide boundaries for workspace create,
list/search, rename, archive/restore, and ownership transfer. It adds no
application behavior and is not an implementation plan.

## Readiness decision

PLAT-233 is architecture-ready under ADR-066, but the current lifecycle paths
encode the superseded personal-workspace model and cannot simply be extended:

- `workspaces.services._lifecycle.create_workspace` implicitly grants its
  creator `owner`, while ADR-066 requires hierarchy creation without an inferred
  grant;
- `workspaces.services._account.create_account_workspace` creates the same row
  without that grant, so the two paths currently have divergent validation,
  audit, authorization, and concurrency behavior;
- workspace and organization roles still target Django users, while ADR-066's
  durable membership identity is a principal;
- the SPA lives below a staff-only `/administer` route even though the API
  admits any active session and then applies organization/workspace authority;
  and
- the SPA workspace layout resolves detail from the caller's membership context,
  which cannot resolve a newly created workspace when creation grants no
  membership.

The implementation must converge these paths at the existing
`workspaces.services` boundary. It must not activate account/principal authority
alongside the legacy user/personal authority. Schema and mapping may land before
S8, but runtime authority changes together at S8 after mapping validation passes.

## Fixed domain and lifecycle boundaries

`workspaces` remains the sole persistence and policy owner for Account,
Organization, Workspace, their memberships, and workspace lifecycle. Public
surfaces use immutable UUIDs; internal joins and cross-domain scalar bindings
keep their existing integer IDs. No generic repository, tenancy app, JSON scope
bag, cross-layer foreign key, model signal, or frontend-owned lifecycle state is
introduced.

The lifecycle surface admits only an organization with a non-null Account whose
closed kind is `team` or `enterprise`. An individual account has no organization
or workspace. A legacy row with `Organization.account_id IS NULL` and a personal
compatibility workspace remain S8 mapping input and storage; neither is a
business-account default or eligible for the account lifecycle API.

Every eligible organization has exactly one default workspace and may have
additional workspaces:

- the partial database uniqueness constraint enforces at most one default;
- the account-locked domain service creates and verifies at least one default
  atomically and idempotently;
- `is_default` is the single structural designation and is included in the
  service/API projection so clients never infer it from name or order; and
- until a separately accepted set-default operation exists, the default cannot
  be archived. Otherwise an organization could retain one nominal but unusable
  default, because archived workspaces are inadmissible for new resource scope.

Workspace creation never infers owner, admin, member, policy, or cloud authority
from the caller, creator, account type, organization role, provider claims, or
Django staff state. An optional explicitly named initial membership may be
composed as a distinct authorized mutation; omission is valid and creates an
ownerless workspace. The account-aware creation transaction is the one creation
path for defaults and additional workspaces, parameterized by the structural
default designation and explicit grant input. The two current direct
`Workspace.objects.create` workflows must not remain independent policy paths.

An ownerless workspace is valid structural state. The existing "last owner"
rule applies once an owner exists; it cannot be used to fabricate an owner at
creation. Initial owner assignment needs an explicit organization-authorized
membership command. Ownership transfer remains a workspace owner command: the
target is an existing explicit workspace member, the target is promoted before
the actor is demoted, and the operation is atomic under the workspace lock.
After the principal cutover, membership and transfer target the stable principal
UUID rather than a Django user ID, email, provider subject, or creator relation.

Name uniqueness stays scoped to the organization and is enforced by the
database. The service owns normalization and the same length/nonblank validation
for HTTP, migration, admin, and composition callers. Database races translate
to one bounded classified conflict; raw `IntegrityError` text never crosses the
boundary.

## Authority boundary

Credential admission and customer policy remain separate:

- browser endpoints keep bearer-first `ApiTokenAuthentication`, then
  `SessionAuthentication`, with `IsAuthenticatedSession`; a valid platform token
  is still refused and unsafe session requests remain CSRF protected;
- the composition boundary resolves the authenticated Django user to ADR-066's
  `PrincipalRef` through the public `management.services` facade before calling
  principal-based workspace policy; `workspaces` must not import `management`;
- organization collection discovery, creation, and explicit first-owner setup
  use the existing persisted organization-admin seam and its audited superuser
  override;
- operations on an existing owned workspace use an explicit
  `WorkspaceOperation` and the single role matrix in `workspaces.roles`; and
- cached capabilities, SPA navigation, AccountMembership association, account
  kind, provider groups, Django groups/staff, token scopes, and cloud IAM are not
  workspace authority.

Organization authority does not silently become a workspace role. The explicit
initial-owner command is the bootstrap seam for a workspace created with no
grant. It must not be implemented by copying an organization admin into every
workspace, falling back to the creator, or adding an `owner_user` field.

Every lookup uses account and organization containment in the query or locked
service operation. A malformed UUID, missing row, wrong account ancestry,
legacy/ineligible organization, and unauthorized row produce the same opaque
tenant denial where their distinction would disclose existence.

## Archive boundary

Archive is the existing reversible `archived_at` marker. It is not deletion and
not a range lifecycle operation. It never deletes, rehomes, or mutates CMS or
Engine range bindings, provider resources, credentials, CTF state, membership,
quota evidence, or audit history. Restore only clears the marker.

Archive policy is operation-specific in `workspaces.services`. Do not add a
blanket archived check to every workspace authorization path: historical range
access, cleanup, audit, and restore need their separately accepted behavior.
List/search is active-only by default with an explicit archived-state filter,
and restore remains reachable without relying on a hidden row. A default
workspace archive is a classified conflict until default reassignment exists.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Domain ownership and imports | ADR-001, ADR-046 as superseded by ADR-066, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `check_model_fks` | Keep persistence/policy in `workspaces`; expose frozen scalar projections from `workspaces.services`; keep cross-domain references scalar. |
| Account hierarchy | `workspaces.models.Account`, `Organization`, `Workspace`; `workspaces.services._account`; `shared.identity_scope.ResourceScope` | Prove closed account kind and exact ancestry; use one locked, idempotent default/additional creation path; never infer installation or individual subdivisions. |
| Workspace authorization | `workspaces.services._authorization`, `_organization`, `_memberships`, `_lifecycle`; `workspaces.roles` | Reuse opaque denials, public UUID lookup, live grant checks, workspace mutex, central operation matrix, and conditional last-owner rule. |
| Principal identity | `management.services`; `management.principals`; `shared.identity_scope.PrincipalRef` | Resolve identity at the composition boundary; membership stores the validated scalar principal UUID and never imports management models. |
| HTTP validation | `shared.api.closed_serializer.ClosedSerializer`; typed DRF serializers; bounded query serializers | Reject unknown and repeated parameters, bound search/paging, validate primitive shape at HTTP, and repeat domain invariants in the service. |
| Errors | existing workspace classified outcomes; `shared.api.errors`; `shared.api.schema.ApiErrorSerializer` | Map once to the sanitized request-ID envelope; extend the existing mapper rather than create another exception hierarchy or return exception text. |
| Audit and logs | `shared.audit` vocabulary/attribution/strict writer; `shared.log_sanitize`; request IDs | Strict-audit mutations in their transaction using bounded internal IDs, action, field names, and outcomes. Log low-cardinality reason codes; do not log names, principal UUIDs, searches, rosters, or request bodies. |
| Persistence | Django migrations and named constraints; `transaction.atomic`; `select_for_update`; PostgreSQL test lane | Preserve IDs, use locks plus uniqueness to arbitrate races, and validate at-least-one/default and owner transitions where a check constraint cannot. |
| SPA transport/state | `frontend/src/api/client.ts`, `queryClient.ts`, `api/workspaces.ts`, generated `schema.d.ts`, TanStack Query | Reuse same-origin cookies, CSRF and request IDs; no component fetch; no mutation retry; invalidate lifecycle, organization, and membership context according to actual explicit grants. |
| SPA routing | `frontend/src/router.tsx`, `features/administer/routes.ts`, organization workspace layouts | Keep UUID route state and server-derived reachability. Do not grant staff merely to expose this UI or use membership context as the existence source for an ownerless workspace. |
| API publication | `config._drf_settings`, `shared.api.contract`, `openapi/v1.json`, `npm run gen:api` | Runtime serializers author the contract. Regenerate artifacts; do not hand-copy DTOs or make an ordinary breaking v1 change. |
| Runtime configuration | `config/env-manifest.json`, settings validators, installation schema/renderers, Kubernetes/Terraform inventories | This lifecycle needs no new env, secret, feature flag, cloud identity, provider setting, command, or worker payload. |

## Cross-cutting security and runtime layers

1. **Provider and session validation.** Existing OIDC/Identity Platform adapters
   continue to validate provider evidence and bind a Django session. PLAT-233
   consumes that authenticated actor only; it does not parse claims or infer
   customer authority from email, issuer, subject, or groups.
2. **DRF authentication and CSRF.** The bearer-first chain fails closed, the
   session-only permission rejects token principals, and Django
   `CsrfViewMiddleware` plus `SessionAuthentication` protects mutations. The SPA
   uses the canonical same-origin client. No `csrf_exempt`, alternate token, or
   direct `fetch` path is allowed.
3. **Transport shape.** Closed body/query serializers reject unknown or repeated
   keys, malformed UUIDs and booleans, overlong search/name input, and invalid
   paging before service invocation. Query bounds must match OpenAPI and the
   frontend instead of keeping the current free-form `_query_flag` behavior.
4. **Principal and ancestry validation.** `PrincipalRef` validates stable identity
   shape. `workspaces.services` then proves account kind, Account -> Organization
   -> Workspace ancestry, lifecycle admissibility, and the exact live operation.
   No null identifier or missing membership broadens scope.
5. **Persistence and concurrency.** The account/workspace mutex, atomic command,
   named unique/check constraints, and under-lock reauthorization cover default
   creation, name races, archive/restore, explicit membership bootstrap, and
   transfer. Model `clean()`, UI state, and preflight `exists()` checks alone are
   insufficient.
6. **Owning-domain policy.** Archive preserves scalar range bindings. CMS, Engine,
   CTF, remote access, quota, egress, model access, and range lifecycle keep
   their own existing gates. Workspace membership or lifecycle state grants none
   of their resource authority unless their accepted service seam explicitly
   composes it.
7. **Error envelope and enumeration resistance.** Domain outcomes map through the
   current workspace API mapper and `shared.api.errors`. External responses do
   not expose SQL, account kind/ancestry mismatch, target membership existence,
   provider data, or traceback text; the request ID remains the correlation
   handle.
8. **Audit and observability.** Trusted request attribution comes from
   `shared.audit` helpers. Successful security mutations are strict-audited in
   the transaction; denials/logs use bounded reason codes and metrics use only
   low-cardinality operation/outcome labels. Display names, emails, public UUID
   probes, principal UUIDs, tokens, headers, cookies, and bodies stay out.
9. **Secrets, configuration, OS and cloud exposure.** The feature introduces no
   secret or environment/config shape. Tenant/principal data never enters env,
   process argv, shell text, Kubernetes Job specs, guest metadata, provider
   labels, static bundles, Terraform values, or CI output. Browser responses keep
   the repository's SecurityMiddleware, CSP, Referrer-Policy, Permissions-Policy,
   secure-cookie, HTTPS, and HSTS controls.
10. **Published contract and workflow gates.** The runtime/OpenAPI/generated
    TypeScript chain remains one contract. Replacing the current v1 array list
    with a paginated envelope or replacing transfer `user_id` with a required
    `principal_uuid` is breaking and must use ADR-040's parallel-major or accepted
    retirement process. Additive evolution still runs OpenAPI drift and breaking
    checks, architecture/import/FK guards, focused backend/frontend tests, and
    real PostgreSQL race/constraint tests.

## Extensibility seams

The lifecycle collection query needs explicit, bounded `archived`, `search`, and
pagination parameters at the service/API boundary. The existing v1 array shape
cannot grow unbounded and cannot be silently changed; the next major contract
should use the repository's `PageNumberPagination` envelope. Keep filtering and
ordering in the authorized database query so a later account-level organization
filter does not require client-side filtering or materializing all rows.

The creation seam is the existing account-aware workspaces service operation,
parameterized by organization identity, `is_default`, and optional explicit
initial membership. A later accepted account type, default reassignment, or
workspace lifecycle action extends that one service and the central closed
vocabularies rather than adding branches across API, frontend, CMS, Engine, or
providers.

The identity seam is `PrincipalRef`. Human and service principals use the same
membership/transfer policy after S8; provider or credential type does not change
the workspace schema. Wire migration from user IDs must obey API versioning,
while persistence cutover remains a single canonical principal authority.

## Gotchas and anti-patterns

- Do not conflate Account, Organization, Workspace, Principal, Django User,
  provider identity, membership, owner role, CTF event/team, Django Group,
  Terraform workspace, cloud account/project, deployment, or range network.
- Do not call the personal-workspace resolver as a missing-scope fallback or mark
  a personal compatibility row as an individual account default.
- Do not keep both `_account` and `_lifecycle` workspace creation as independent
  policy workflows, or let a read/GET ensure defaults or create memberships.
- Do not grant the creator, organization admin, account member, first listed
  member, or individual principal an implicit workspace role.
- Do not require every workspace to have an owner at creation. Do not weaken the
  last-owner rule after an owner exists, fabricate a transfer target, or transfer
  by email/user name/provider subject.
- Do not archive the default until an accepted atomic default-reassignment
  operation exists. Do not make archive cascade, rebind ranges, or become a
  global authorization check.
- Do not trust the SPA's staff gate, navigation, cached capabilities, selected
  organization, or disabled buttons. Do not set `is_staff` to make organization
  administration reachable.
- Do not expose internal account/workspace IDs or keep `user_id` as the durable
  owner identity after principal cutover. Do not break v1 silently to remove it.
- Do not duplicate DTOs, validators, role matrices, exception trees, audit
  stores, logging formats, API clients, routers, pagination, or query parsing.
- Do not add env/config/secret/provider/cloud branches or place tenant data in
  logs, metrics labels, audit state, commands, worker payloads, or frontend
  bundles.

## Non-goals and implementation boundaries

- This preflight makes no runtime, migration, API, SPA, fixture, or production
  data change.
- No S8 partial cutover, dual-write/read fallback, feature-flagged authority,
  automatic legacy repair, or customer-specific fork.
- No organization/account lifecycle API, account-type conversion, default
  reassignment, workspace deletion, membership/invitation redesign, group
  lifecycle, or principal credential UI.
- No change to range ownership/access/cleanup, provisioning, CTF authority,
  quotas, egress, model access, cloud placement, IAM, secrets, network policy,
  workers, or Django admin escape hatches.
- No new authentication protocol, API token scope, OpenFGA evaluator/cache,
  custom policy engine, generic repository, background reconciler, or approval
  workflow.

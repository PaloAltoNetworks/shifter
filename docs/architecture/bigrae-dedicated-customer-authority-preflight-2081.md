# BigRAE Dedicated-Customer Authority Preflight

Issue: GitHub #2081, "Adopt the dedicated-customer BigRAE scope and
authority contract."

Status: pre-implementation architecture guidance. This note does not adopt
ADR-054 or implement #2048. The issue is the authoritative contract for this
requirement-free run.

ADR-053 is accepted on the current branch, so #2075's ownership dependency is
satisfied. ADR-053 remains the authority for BigRAE's tenant/product and
development surfaces; #2081 must not reopen that ownership decision.

## Boundary Decision

The first GCP SaaS release has one customer security and administration
boundary per BigRAE deployment. A deployment may contain several organizations,
workspaces, events, teams, participants, and operators for that customer, but it
does not share its application control plane, PostgreSQL authority, runtime
secret authority, or product workload identities with an unrelated customer.
Organizations and workspaces are internal authorization scopes; neither is a
synonym for the customer or evidence of hard control-plane isolation.

The deployment boundary is established collectively by the validated root
installation config, selected GCP backend settings, rendered Terraform state
and outputs, workload identities, networks, runtime configuration, and
deployment evidence. Today `RootConfig` declares one deployment name, domain,
profile, backend, and secret-reference map, while `GcpBackendSettings` declares
the project and region. Do not claim that one current manifest already contains
all trust domains, limits, identities, and resources, and do not add a customer
label and call it isolation.

Dedicated deployment does not flatten internal authorization. The controlling
relationships remain separate:

- organization administration is a persisted `OrganizationMembership` rule;
- workspace operations are decided from a persisted `WorkspaceMembership` and
  a closed `WorkspaceOperation`;
- event administration is event ownership, a bounded live staff capability, or
  the audited platform-superuser fallback;
- participation is an event-scoped `CTFParticipant` relationship; and
- range and remote access continue to use the persisted range owner, event
  participant binding, current generation, lifecycle, and declared channel.

These are intersecting policy checks, not an inheriting role hierarchy. In
particular, organization administration, workspace membership, a selected SPA
workspace, an API-token scope, and cloud IAM grant no event participation or
event ownership.

## ADR-054 Disposition And Operative Rules

The implementation should adopt a revised ADR-054 after ADR-053. Keep ADR-053
and its #2075 evidence unchanged. ADR-054 should be `accepted`, scoped to the
repository, enforced by `agent-policy` and `ci`, and use the following rule
meanings. Leave each rule's `checks` empty until a named checker actually proves
it; runtime and migration claims are evidenced by tests, not a documentary
check name.

| Rule | Operative meaning |
| --- | --- |
| `ADR-054-R1` | One BigRAE deployment is one customer boundary. Unrelated customers do not share its product control plane, PostgreSQL authority, runtime secret authority, or product workload identities. A provider project, organization row, workspace, hostname, tag, or label alone is not proof of that boundary. |
| `ADR-054-R2` | Organization, workspace, event, participant, application-operator, cloud-operator, and external-client authority stay distinct and compose only at their owning service boundaries. No role, claim, scope, selected context, or external capability implies another. |
| `ADR-054-R3` | Before the #2048 migration, CTF events, teams, and participants use the deployment-global model governed by event-native authority. The migration point is the first deployed schema/application release that backfills every event to its creator's personal workspace, rejects an unresolved backfill, makes the binding required, and routes all new event creation through the workspace service. After that point each event carries one immutable internal `workspace_id`; the binding proves tenant confinement only and never grants event participation, ownership, delegation, range access, organization authority, or secret access. |
| `ADR-054-R4` | Deployment-local services remain authoritative for authentication admission, authorization, validation, persistence, lifecycle effects, secrets, and audit. External clients use the versioned public API and obtain only the intersection of live actor authority, exact token scope when applicable, object policy, and current lifecycle. They cannot submit an authority source, bypass local admission, write domain tables, receive product workload credentials, or become the owner of a cloud effect. |
| `ADR-054-R5` | GCP IAM, datastore, secret, network, and evidence ownership is explicit and least-privilege. Effective identities and denied paths, rather than names or labels, prove isolation. Product workloads, development runners, participant guests, external clients, and operators remain separate trust domains. |
| `ADR-054-R6` | Dependency loss never creates permission or asserts an unobserved effect. Each dependency has a fail-closed or explicitly degraded behavior; durable operation state and reconciliation distinguish accepted, running, failed, indeterminate, and completed work. |
| `ADR-054-R7` | Release evidence includes session/token parity, revoked authority, cross-event denial, event-binding migration, remote-access revocation, audited override, effective IAM, network denied-path, and dependency-failure tests against the real owning boundaries. |

The registry evidence should point to #2081, this note, ADR-046/051/052/053,
the root installation and GCP backend schemas, the CTF and workspace
authorization services, the #2048 migration/tests, the platform IAM/network/
secret modules, and `shared.audit`. Do not add a new guard script merely to
search for the words "single customer."

ADR-046-R7 and ADR-052's decision/R6 must stop presenting an unconditional
event model:

- **Before migration:** `CTFEvent` has no workspace binding. Events, teams, and
  participants are deployment-global records, with access still limited by
  event ownership, event staff, participant membership, and the audited
  platform-root override. A range's existing workspace binding is not an event
  binding and must not be used to infer one.
- **Migration point:** the #2048 migration graph adds the scalar, backfills each
  existing event from its protected `created_by` user's personal workspace,
  fails on an unresolved owner/workspace, and makes the field required before
  the application treats ADR-051's binding as operative. It preserves event
  owner, staff, team, participant, range, and audit identities.
- **After migration:** every event has exactly one immutable scalar
  `workspace_id`, resolved from a public workspace UUID through
  `workspaces.services` for new events. The scalar is a cross-layer soft
  reference, never a CTF-to-workspaces foreign key. Workspace membership is an
  additional check only for the operations ADR-051 names; event-native checks
  remain independently mandatory.

At preflight time, current `CTFEvent` has no `workspace_id`. The reviewed
`2048-ctf-scoped-communications` branch adds a nullable field and a backfill,
but the model still permits `NULL`, its later migration does not make the event
field non-null, and there is no `MigrationExecutor` test for the event backfill.
That branch therefore does not yet prove the `ADR-051-R2` statement that every
event is bound. ADR-054 must not declare the post-migration state shipped until
the schema, service, and real migration test agree. A permanent nullable legacy
escape hatch would require the ADR to describe a mixed model instead.

## Authority Matrix

| Boundary or actor | Authoritative relationship | What it may authorize | What it never implies | Canonical decision point |
| --- | --- | --- | --- | --- |
| Deployment/customer | One validated `RootConfig` plus one selected backend deployment and its effective GCP placement | Deployment lifecycle and customer-local product boundary | An in-app customer role, unrelated-customer multitenancy, or proof from a label alone | `installation.schema`, `installation.loader`, backend bundle validation, deployment Terraform roots |
| Organization | Persisted `OrganizationMembership.admin`, with the audited Django-superuser override | Closed organization profile operations | Workspace authority, event authority, participant status, cloud IAM, or secret access | `workspaces.services` under ADR-048 |
| Workspace | Persisted active membership plus a closed operation; owner/admin/member policy is service-owned | The named workspace operation and separately checked workspace-bound resource operation | Organization administration, CTF ownership/participation, another user's range access, or deployment administration | `workspaces.services.authorize_workspace`, `authorize_bound_workspace`, and locked launch authorization |
| CTF event | `CTFEvent.created_by`, live `CTFEventStaff` capability, then active non-temporary superuser fallback | The closed event operation; creation still requires its existing organizer admission and, after #2048, workspace tenancy proof | Workspace membership as event access, ownership transfer, automatic staff/participant creation, or access to another event | `ctf.services.authorization.resolve_event_authority` and event service facades |
| Participant | One live `CTFParticipant` under its parent event and the current actor/account checks | That participant's event-scoped read/play operations and separately bound range channels | Ambient access from the same user participating elsewhere, workspace membership, organizer status, or access to another participant | CTF participant services, parent-scoped queries, `CTFAccountBoundaryMiddleware`, and WebSocket boundary |
| Application operator | Active, non-temporary Django superuser only where an ADR expressly provides the fallback | Audited platform-root operations on existing application resources | Event creation by a pure superuser, event ownership/staff synthesis, cloud IAM, or bypass of validation/lifecycle | CTF/workspace service resolvers plus strict `shared.audit` attribution |
| Cloud/deployment operator | Out-of-band deployment identity with reviewed GCP IAM and bootstrap/deploy access | Infrastructure and recovery operations allowed by effective provider policy | Django superuser, organization/workspace/event authority, participant identity, or an API token | GCP IAM/Terraform and the deployment bootstrap boundary |
| External client | Same-origin session with CSRF on unsafe methods, or `shf_` token bound to a live user and exact scopes | Only the public operation admitted by actor, scope, object policy, and lifecycle | Cloud credentials, direct persistence, submitted authority flags, catalog/Hub authority, wildcard application authority, or ownership of asynchronous effects | `/api/v1`, bearer-first DRF authentication, service policy, shared OpenAPI/error contract |

One user can appear in several rows, but authority is recomputed from the live
relationship relevant to the operation. Cached SPA capabilities and persisted
source/origin labels are presentation or evidence, never authorization inputs.

## Service And Infrastructure Ownership

| Concern | Owner and canonical incumbent | Dependency-outage behavior |
| --- | --- | --- |
| Public API and application services | `config/api_urls.py`, DRF, `shared.api.schema`, then the public `ctf.services`, `workspaces.services`, `cms.services`, and `engine.services` facades | An unavailable service returns the existing bounded failure and performs no alternate direct table/provider write. Accepted asynchronous work remains in its canonical durable state for retry or reconciliation. |
| Identity and admission | OIDC/Identity Platform validators and session creation in `config`, bearer-first `ApiTokenAuthentication`, `active_actor_user`, session CSRF, and CTF account-origin middleware | IdP loss blocks new IdP-backed session establishment. Existing sessions still undergo live local user/object checks until their normal expiry or revocation. Invalid bearer credentials fail without falling through to a logged-in session. No cached or unverified claim creates authority. |
| Domain authority and persistence | PostgreSQL models and migrations owned by each Django domain; Cloud SQL is provisioned by `portal/cloud-sql` | Database loss makes readiness unavailable and blocks authorization-dependent reads and mutations. Redis, browser state, provider labels, and external clients never become fallback domain truth. |
| Cache, scheduling, and delivery | Configured Django cache/Redis, CTF scheduler, durable launch/operation/outbox records, and shared notification/email transports | Security rate limits fail closed where their contract requires it. Cache or fan-out loss does not invent authority or delivery. Durable database truth remains distinguishable from optional notification delivery. |
| GCP IAM | `platform/terraform/gcp/modules/portal/iam`, Kubernetes service accounts/RBAC, provisioner Job admission, and provider IAM tests | Token/IAM loss blocks the effect. There is no fallback shared admin identity or external-client credential. Retried work keeps its original operation/generation and must revalidate current policy. |
| Runtime and range secrets | `portal/secrets`, GCP Secret Manager runtime bundles, entrypoint hydration, `shared.field_encryption`, `shared.cloud` secret adapters, and `engine.secrets` | Secret unavailability blocks startup/readiness or the specific new connection/effect. It never falls back to plaintext config, request input, a different customer's secret, or a credential in logs/errors. Existing provider-token revocation windows must be measured rather than described as immediate. |
| Network boundary | `portal/vpc`, `range/vpc`, their peering/firewalls, GKE private control-plane posture, ingress/Cloud Armor, Kubernetes `NetworkPolicy`, and provisioner Job admission | Loss of the authorized path makes the operation unavailable; it does not open a public management path or broaden a CIDR. A participant network remains untrusted even inside the customer's deployment. |
| Pack registry and artifact resolution | Tenant-local `RaesPackageSource`/registry plus `shared.raes` validation, digest, object-source, and realizability boundaries | Source or registry loss blocks new acquisition/realization that needs it. Already admitted immutable local state may continue only when its existing contract has all required bytes and evidence; no substitute origin or entitlement is inferred. |
| Model/provider dependency | The selected range realization and its declared model/tool policy; cloud calls remain behind shared adapters and operation contracts | A model or provider outage cannot widen tools, models, destinations, budgets, or identity. Record failed/indeterminate truth and keep teardown/revocation independently available where possible; never report an unobserved success. |
| Audit and operational evidence | `shared.audit`, domain audit helpers, operation receipts/results, range-event outbox, provider audit logs, and external health/metrics | Strict security mutations fail with their transaction or record bounded intent before a non-rollbackable effect. Best-effort evidence loss is explicitly degraded and machine-visible. Provider logs supplement rather than replace application audit. |

The product authority is deployment-local even when an upstream Catalog, Hub,
email provider, identity provider, model provider, or GCP API participates. Such
a dependency supplies input or performs a bounded requested operation; it does
not select the actor, workspace, event, recipient, lifecycle transition, or
cloud effect.

## Canonical Incumbents To Reuse

| Concern | Reuse | Boundary to preserve |
| --- | --- | --- |
| Root deployment shape | `installation.schema.RootConfig`, `installation.loader`, `BackendBundle.validate_settings`, `GcpBackendSettings`, and the published backend contract | Extend one versioned closed config only if a real new operator input is needed. Do not introduce a second customer/deployment manifest or hand-maintained JSON schema. |
| Authentication | `shared.api_tokens.authentication`, `shared.api.principals`, DRF `SessionAuthentication`, OIDC/Identity Platform verification, and CTF account-origin gates | Preserve bearer-first fail-closed behavior, active-user checks, session CSRF, issuer/audience/authorized-party/subject/email verification, and temporary-account confinement. |
| Workspace authority | `workspaces.services` and the closed `WorkspaceRole`/`WorkspaceOperation` matrix | Add or use the one operation owned by workspaces; never import workspace models into CTF, compare role strings in a controller, or trust an internal ID from a client. |
| Event authority | `ctf.services.authorization`, `EventAuthoritySource`, `EventCapability`, event-staff policy, and service-level rechecks | Keep one operation-parameterized decision. Do not add workspace-owner, organization-admin, external-client, or cloud-role branches. |
| Participation and remote access | Parent-scoped CTF participant queries, `live_participant_for_user`, Engine range-owner/generation checks, `shared.remote_access`, and Guacamole bootstrap ownership | A participant relationship and the current range binding are required independently. Never mint from workspace membership or credential presence alone. |
| API shape and errors | Explicit DRF serializers, `shared.api.schema.PlatformAutoSchema`, committed OpenAPI/generated types, existing `CTFError` family, and `shared.api.errors` | Reject unknown/client-owned authority fields, preserve opaque denials and request IDs, and do not add writable `ModelSerializer`, a second envelope, or per-client exception hierarchy. |
| Persistence and migration | Django migrations, scalar cross-layer bindings, `transaction.atomic`, locks, constraints, `ImmutableFieldsMixin`, and real `MigrationExecutor` tests | Backfill deterministically, fail on ambiguity, make the shipped invariant a database/schema fact, and keep one writer. Do not dual-write or infer the binding on reads. |
| Secrets and logs | Secret Manager references, runtime hydration, `shared.field_encryption`, `shared.log_sanitize`, structured logging, and provisioner redaction | Keep secret values, tokens, signed URLs, participant data, provider bodies, and raw exceptions out of DTOs, env manifests, argv, audit state, metrics labels, and public errors. |
| Audit and recovery | `shared.audit`, domain audit adapters, launch/operation/outbox state, health checks, and provider-aware metrics | Reuse strict-versus-degraded policy and existing correlation/generation identities. Do not create an authority journal or external-client workflow store. |
| Cloud policy | GCP platform/range Terraform modules, Kubernetes RBAC/NetworkPolicy/admission, validation inventory, and existing IaC tests | Prove effective grants and denied paths. Do not duplicate policy in application config or treat workspace IDs/provider labels as network or IAM policy. |

## Cross-Cutting Layers The Intended Design Must Pass

1. **Installation shape:** all deployment input passes `RootConfig`, the selected
   backend bundle, secret-reference validation, GCP project/region validation,
   and the published-contract parity gates. #2081 needs no new runtime setting.
   If later work adds a stable deployment identifier or trust-domain input, that
   is one versioned field at this seam and is derived into provider artifacts;
   it is not copied into every domain schema.
2. **Identity and HTTP admission:** OIDC/Identity Platform token verification,
   bearer-first API-token authentication, active-user resolution, session CSRF,
   CTF account-origin middleware, and exact route admission run before domain
   policy. An external client cannot choose session fallback after presenting a
   bad bearer token.
3. **Transport shape:** public UUIDs and explicit serializers bound request
   shape; exact token scopes come from `shared.api_tokens`; OpenAPI is generated
   from the runtime permissions. Internal workspace IDs, role strings,
   `authority_source`, `is_admin`, customer IDs, and provider principals are not
   accepted as client assertions.
4. **Service authorization:** `workspaces.services` resolves live membership for
   the named workspace operation; CTF independently resolves event ownership or
   capability; participant and Engine services independently resolve event and
   range access. Authorization is repeated at the mutation/launch boundary and
   under the existing lock when concurrent revocation matters.
5. **Persistence and migration:** the event binding is a required immutable
   scalar after cutover, not a cross-layer foreign key or optional JSON field.
   Backfill uses protected creator identity and personal workspace only, fails
   on ambiguity, and preserves every event-native relationship. Model validation
   alone is not proof that a direct insert cannot produce an unbound event.
6. **Runtime configuration and admission:** Django env reads remain represented
   in `config/env-manifest.json`; renderers, Helm/Kustomize values, sensitive-env
   classification, Kubernetes RBAC/NetworkPolicy, and provisioner Job admission
   remain synchronized. A documentation boundary does not justify a new env key,
   feature flag, sidecar, or service account.
7. **Secret handling:** installation config contains references, runtime values
   come through Secret Manager/hydration, persisted sensitive fields use the
   existing encryption boundary, and remote access resolves a current reference
   only after authorization. No secret or bearer URL enters a request DTO,
   process argument, generated ConfigMap, Terraform variable value, log, audit
   payload, metric label, or client error.
8. **OS and effect boundary:** structured operation IDs/envelopes and admitted
   Jobs carry effects to workers. External-client payloads, event/workspace IDs,
   package data, provider responses, and credentials do not become shell text or
   process argv. Participant guests never receive control-plane, operator, or
   provisioner credentials.
9. **Errors and observability:** domain errors map once through the existing CTF/
   workspace adapters and `shared.api.errors`; missing and unauthorized tenant
   resources stay non-enumerating. Logs use bounded sanitized identifiers;
   strict override audit is request-attributed; raw database/provider/identity/
   secret errors never reach clients.
10. **Provider isolation:** Terraform validators, effective-IAM tests, firewall
    and network-policy tests, Kubernetes admission, and deployment smoke evidence
    prove the GCP boundary. Application workspace tests cannot substitute for
    provider isolation, and a GCP project or label cannot substitute for an
    authorization test.

## Negative Evidence Contract

The later implementation must extend the existing real-boundary suites rather
than create an ADR-only test harness:

- session and `shf_` token requests for the same actor/object produce the same
  object authorization result; unsafe sessions retain CSRF, tokens require the
  exact scope, revoked/inactive token owners fail, and an invalid bearer never
  falls through to an authenticated session;
- removing a workspace membership denies the operations that explicitly require
  that membership, including ADR-051 communication authoring/release, but does
  not itself create or erase event ownership or participation. A retained live
  `CTFParticipant` is still governed by event policy, proving that workspace
  membership is not event admission;
- an owner, staff member, participant, or token admitted in event A cannot read
  or mutate event B, address B's nested participants/teams, reuse B's range, or
  mint B's VPN/Guacamole/terminal access;
- participant revocation, disqualification, password-reset requirements,
  destroyed/stale range generation, undeclared channel, and ownership change
  deny new remote access. Active connection termination semantics must be stated
  and tested at the incumbent HTTP, WebSocket, Guacamole, and VPN boundaries;
  do not promise instantaneous revocation if only new-session admission is
  implemented;
- the platform-superuser fallback remains active/non-temporary, applies only
  where the closed operation permits it, never synthesizes owner/staff, resolves
  after lower authority, and strict-audits each actual override. Audit failure
  blocks a database-only mutation;
- a `MigrationExecutor` test starts before the event-scope migration, creates
  several events/users/participants/staff rows, migrates forward, proves the
  creator-personal-workspace mapping and relationship preservation, and proves
  an unresolved mapping fails loudly. The final schema rejects `NULL`, new
  service-created events are bound, and rebinding is rejected;
- external requests that submit an internal workspace ID, foreign public UUID,
  customer/organization claim, authority source, role, provider identity, or
  asynchronous result receive the existing bounded denial and cause no state or
  provider effect; and
- GCP evidence verifies effective workload IAM, Secret Manager isolation,
  platform/range network denied paths, participant-to-management denial, and
  failure behavior for IdP, database/cache, registry, secret, audit, model, and
  provider dependencies with a working positive control.

Canonical suites include `tests/ctf/test_drf_api_token_access.py`,
`test_platform_admin_authority.py`, `test_platform_admin_api.py`, participant
and VPN tests, Mission Control API-token/terminal/VPN tests, workspace authority
tests, and the real migration patterns in
`tests/workspaces/test_backfill_migration_schema.py`. The #2048 branch's
`test_event_workspace_scope.py` is useful service/model coverage but is not a
substitute for forward migration proof.

## Extensibility Seams

The event-tenancy seam is the immutable internal `workspace_id` resolved through
`workspaces.services`; the authority seam is the closed operation parameter to
the workspace and event resolvers. A future event-scoped capability or an
explicit event rehome adds one operation and one audited domain command without
changing controllers, role inheritance, or cross-layer model imports.

The external-client seam is the generated, versioned `/api/v1` contract. A new
client reuses the same authentication, scopes, serializers, service policy,
operation identity, and status projection; it does not receive a client-specific
controller, credential type, exception family, queue, or provider adapter.

The deployment seam remains `RootConfig.deployment` plus the selected backend's
closed settings and generated inventory. A future stable opaque deployment ID
or trust-domain declaration belongs once at that versioned seam. Supporting
unrelated customers in one control plane is not that parameter variation: it
requires a later ADR covering identity, row and cache partitioning, encryption
and secret authority, network/IAM isolation, migrations, evidence, recovery,
and incident ownership.

## Gotchas And Anti-Patterns

- Do not equate customer, organization, workspace, event, user, participant,
  range owner, application operator, cloud operator, or external client.
- Do not call the pre-#2048 model workspace-scoped. The current CTF event model
  is deployment-global even though ranges already carry workspace bindings.
- Do not call the post-#2048 model fully bound while `workspace_id` remains
  nullable or direct supported creation can omit it.
- Do not infer an event workspace from its creator on every read. The creator's
  later memberships may change; only the one-time migration/new-event decision
  establishes immutable scope.
- Do not infer event access from workspace owner/admin/member, organization
  admin, active UI context, email domain, IdP claims, API-token scopes, cloud
  IAM, a scenario, or a range binding.
- Do not add a CTF foreign key to `workspaces`, a duplicate workspace/event
  schema, a generic `tenant_id` JSON field, or a customer column across all
  models for a dedicated-deployment release.
- Do not turn the platform-superuser override into event ownership, event
  creation, participant status, staff membership, a token scope, or cloud IAM.
- Do not let Catalog, Hub, a model provider, an identity provider, or another
  external client call a worker/provider directly or write operation outcomes.
  External coordination remains input to deployment-local admission.
- Do not grant a broad shared service account to recover from IAM, Secret
  Manager, registry, or provider outages, and do not describe retry as success.
- Do not duplicate DRF schemas, role matrices, serializers, validation,
  exception hierarchies, error envelopes, audit tables, log redaction,
  operation state, health checks, or workflow logic for BigRAE-branded clients.
- Do not put tokens, secrets, signed Guacamole URLs, VPN profiles, participant
  data, provider responses, raw errors, or authority snapshots in env vars,
  argv, logs, audit free text, metrics labels, or public errors.
- Do not weaken internal authorization because all users belong to one customer.
  A dedicated customer boundary limits blast radius; it is not least privilege
  inside that boundary.
- Do not modify ADR-053's ownership split or absorb ADR-048/#1939 organization
  authority into this issue. ADR-053 remains #2075's work.

## Non-Goals And Implementation Boundary

- No issue implementation, ADR adoption, registry edit, runtime code, model,
  migration, API, OpenAPI, DTO, service, Terraform, IAM, secret, network,
  workflow, or test change in this preflight.
- No repository/product/symbol/resource rename from Shifter to BigRAE.
- No new control-plane service, modular-monolith split, customer service,
  authority broker, policy engine, or external-client gateway.
- No unrelated-customer multitenancy or claim that logical workspace isolation
  is equivalent to separate control planes, databases, secrets, or IAM.
- No new organization/workspace roles, event ownership-transfer policy,
  participant model, cloud operator role, or entitlement/distribution model.
- No change to deployment-global catalog, provider configuration, API-token
  scope registry, durable audit store, or feature flags except the explicit
  event transition wording required in ADR-046/052.
- No attempt to complete #2048 in #2081. The adoption must describe and test its
  migration point, but communication implementation remains owned by #2048.
- No live cloud mutation, deployment, identity change, secret read, workflow
  dispatch, issue edit, or external coordination from this architecture run.

## Validation Expectation

The architecture/documentation change that follows must run the full ADR guard.
If it edits only ADR and architecture prose, it needs no runtime config or cloud
mutation. The #2048 implementation independently needs its focused PostgreSQL
migration and authorization suites. Any later IAM, Terraform, Kubernetes, or
workflow change must also run the stack-native checks required by `AGENTS.md`;
documentation cannot waive them.

# ADR-054: Dedicated-customer deployment and internal authority

## Status

Accepted.

## Date

2026-09-05

## Context

ADR-053 defines BigRAE as the organizational and SaaS backend that consumes
RAES environment packs. The first GCP SaaS release needs a narrower customer
isolation claim than unrelated-customer multitenancy: one operated deployment
serves one customer. A deployment can still contain several organizations,
workspaces, events, teams, participants, and operators for that customer.

The application already has distinct organization, workspace, CTF, participant,
range, API-token, application-operator, and cloud-operator policies. Dedicated
deployment must not flatten those policies into a customer-wide role. It also
must not imply that an organization row, workspace, project name, hostname,
tag, or label proves infrastructure isolation.

ADR-046 and ADR-052 describe CTF events as deployment-global records. ADR-051
accepts an immutable event-to-workspace binding for scoped communications, but
that binding is not present on the current `dev` schema. The #2048 migration is
therefore an explicit activation point, not a consequence of accepting this
ADR.

## Decision

One BigRAE deployment is one customer security and administration boundary.
Unrelated customers do not share its product control plane, PostgreSQL
authority, runtime secret authority, or product workload identities under the
first GCP release claim. Supporting unrelated customers in one control plane
requires a separate isolation decision and migration.

The deployment boundary is established by the validated installation and
backend configuration together with effective identities, network policy,
data and secret placement, and observed deployment evidence. Internal
authorization is still evaluated independently at the service that owns each
resource. An upstream Catalog, Hub, identity provider, model provider, email
provider, or other client supplies input or performs a bounded requested
operation; it never becomes BigRAE's authorization or effect owner.

### Authority matrix

| Boundary or actor | Authoritative relationship | May authorize | Never implies | Decision point |
| --- | --- | --- | --- | --- |
| Deployment/customer | One validated root configuration, selected backend, and effective provider placement | Deployment lifecycle and the customer-local product boundary | An in-app customer role, unrelated-customer multitenancy, or isolation proved by a name or label | Installation schema and loader, backend validation, and deployment Terraform roots |
| Organization | Persisted `OrganizationMembership.admin`, with the accepted audited superuser override | Closed organization operations | Workspace, event, participant, cloud IAM, or secret authority | `workspaces.services` under ADR-048 |
| Workspace | Live `WorkspaceMembership` plus a closed `WorkspaceOperation` | The named workspace operation and a separately checked workspace-bound resource operation | Organization administration, CTF ownership or participation, another user's range access, or deployment administration | `workspaces.services` authorization and locked launch seams |
| CTF event | `CTFEvent.created_by`, an applicable live `CTFEventStaff` capability, then the accepted platform-root fallback | The named event operation | Access from workspace membership, ownership transfer, synthesized staff or participants, or another event | `ctf.services.authorization` and CTF service facades |
| Participant | One live `CTFParticipant` under its parent event plus current account checks | That participant's event-scoped operations and separately bound range channels | Ambient access from the same user in another event, a workspace role, organizer status, or another participant | Parent-scoped CTF queries and account/channel boundaries |
| Application operator | Active, non-temporary Django superuser only where an ADR expressly allows the fallback | Strict-audited platform-root operations on existing application resources | Event creation by a pure superuser, ownership or staff synthesis, cloud IAM, or a validation/lifecycle bypass | Domain service resolvers and `shared.audit` |
| Cloud/deployment operator | Out-of-band deployment identity with reviewed GCP IAM and bootstrap access | Infrastructure and recovery actions allowed by effective provider policy | Django, organization, workspace, event, participant, or API-token authority | GCP IAM/Terraform and bootstrap |
| External client | Same-origin session with CSRF for unsafe methods, or a live `shf_` token with exact scopes | Only the public operation admitted by the actor, scope, object policy, and lifecycle | Cloud credentials, direct persistence, client-supplied authority, wildcard application access, or ownership of asynchronous effects | Versioned `/api/v1`, bearer-first authentication, service policy, and generated OpenAPI |

One person can occupy several rows. Every request still recomputes the live
relationship relevant to the operation. Cached SPA capabilities and stored
source labels remain presentation or evidence, not authorization inputs.

### CTF event transition

Before #2048 is activated, `CTFEvent` has no workspace binding. Events, teams,
and participants are deployment-global records, while event ownership, live
staff capability, participant membership, exact token scope, and the audited
platform-root override restrict access. An existing range workspace binding is
not an event binding and cannot be used to infer one.

ADR-051 becomes operative only at the first deployed schema and application
release that satisfies all of these conditions:

- every existing event is deterministically backfilled to its protected
  creator's personal workspace;
- an unresolved creator-to-workspace mapping stops the migration;
- the final schema rejects an unbound event;
- supported new-event creation resolves one public workspace UUID through
  `workspaces.services` and always persists the internal scalar; and
- the binding is immutable after creation and covered by a real forward
  migration test.

After activation, every event carries exactly one immutable internal
`workspace_id`. It is a cross-layer soft reference, not a CTF foreign key to a
workspace model. The binding proves tenant confinement only. Workspace
membership does not grant event ownership, staff capability, participation,
range or remote access, organization authority, or secret access. ADR-051 can
require both a workspace operation and event-native authority for a named
communication operation without turning either check into the other.

### Service and infrastructure ownership

| Concern | Owner and incumbent | Dependency-outage behavior |
| --- | --- | --- |
| Public API and domain services | DRF and generated OpenAPI route to public `ctf.services`, `workspaces.services`, `cms.services`, and `engine.services` facades | An unavailable service returns a bounded failure and performs no alternate table or provider write. Accepted asynchronous work remains in its durable state for retry or reconciliation. |
| Identity and admission | OIDC/Identity Platform validation, bearer-first API-token authentication, active-actor resolution, session CSRF, and CTF account-origin checks | IdP loss blocks new IdP-backed sessions. Existing sessions and tokens still require live local user and object policy. An invalid bearer credential never falls through to a session. |
| Datastore | Each Django domain owns its PostgreSQL models and migrations; GCP Cloud SQL hosts deployment state | Database loss blocks readiness and state-dependent authorization or mutation. Cache, browser state, provider labels, and clients never become domain truth. |
| GCP IAM | Deployment Terraform, Kubernetes service accounts and RBAC, provisioner admission, and provider IAM tests | Token or IAM loss blocks the effect. No shared administrator identity or client credential is substituted; retry retains its operation and generation and revalidates policy. |
| Secrets | GCP Secret Manager runtime bundles, entrypoint hydration, field encryption, shared secret adapters, and Engine secret services | Missing secret material blocks startup/readiness or the specific connection or effect. It never falls back to plaintext request/config data, another deployment's secret, logs, or errors. |
| Network | Platform and range VPC modules, firewalls, GKE posture, ingress policy, Kubernetes `NetworkPolicy`, and provisioner admission | Loss of an authorized path makes the operation unavailable. It never opens public management access or broadens a CIDR. Participant networks remain untrusted. |
| Pack registry | Tenant-local registered package sources plus `shared.raes` validation, digest, object-source, and realizability checks | Source or registry loss blocks new acquisition or realization that needs it. Validated local immutable state can continue only when all required bytes and evidence already exist; no substitute source or entitlement is inferred. |
| Model/provider dependency | The selected realization plus its declared model/tool policy and shared cloud adapters | Outage cannot widen models, tools, destinations, budgets, or identity. Record failed or indeterminate truth and keep teardown or revocation independently available where possible. |
| Evidence | `shared.audit`, domain helpers, operation receipts/results, the range-event outbox, provider audit logs, and health/metrics | Strict security mutations fail with their transaction or record bounded intent before a non-rollbackable effect. Best-effort loss is visible as degraded state. Provider logs supplement rather than replace application audit. |

### External clients and effects

External clients use the same versioned public API, authentication chain,
explicit serializers, exact token scopes, domain services, operation identity,
and result projection as first-party clients. They cannot submit an authority
source, internal workspace ID, provider identity, or successful result as a
trusted fact. They cannot write domain tables, call workers or provider APIs
directly, receive product workload credentials, or become the owner of an
asynchronous cloud effect.

Dependency failure does not create an authority fallback or a success result.
Durable operation state distinguishes accepted, running, failed, indeterminate,
and completed work, and reconciliation remains owned by the deployment-local
service that admitted the operation.

## Verification contract

Release evidence must exercise real owning boundaries. It includes:

- session and `shf_` token parity for object authorization, while preserving
  CSRF for unsafe session requests and exact scopes for tokens;
- revoked or inactive authority, including invalid bearer credentials that
  cannot fall through to an authenticated session;
- cross-event denial for owners, staff, participants, nested resources, ranges,
  and remote-access channels;
- participant and remote-session revocation at the actual HTTP, WebSocket,
  Guacamole, and VPN admission boundaries;
- the audited platform-superuser fallback, including audit failure at strict
  database mutations;
- a forward `MigrationExecutor` test that proves deterministic event backfill,
  preservation of event-native relationships, fail-loud unresolved mappings,
  a required final field, bound new events, and immutable scope;
- effective GCP workload IAM, Secret Manager isolation, and platform/range
  network denied paths with working positive controls; and
- explicit IdP, datastore/cache, registry, secret, audit, model, and provider
  dependency failures without invented authority or completion.

At adoption, the current pre-migration CTF authorization baseline passes the
focused API-token, event-authority, revoked-staff, cross-event, and
platform-admin audit suites. The event-binding migration evidence is the
activation gate above; an unmerged or nullable schema does not satisfy it.

## Alternatives considered

- **Share one control plane between unrelated customers.** Rejected for the
  first release. It needs a complete identity, row/cache partitioning,
  encryption and secret, IAM/network, migration, recovery, evidence, and
  incident-ownership design.
- **Treat each organization or workspace as a customer boundary.** Rejected.
  Those are application authorization scopes and do not isolate the control
  plane, database, secrets, or workload identities.
- **Flatten internal authorization in a dedicated deployment.** Rejected. A
  smaller customer blast radius does not replace least privilege inside it.
- **Let external clients or upstream services own effects.** Rejected. They
  remain callers or input providers behind deployment-local admission,
  lifecycle, persistence, and result application.
- **Treat ADR-051 acceptance as the migration point.** Rejected. Only a
  required, immutable schema and proven forward migration make the event
  binding operational.

## Consequences

The first release makes a clear, supportable customer-isolation claim while
retaining existing internal policy and the modular-monolith service boundaries.
Dedicated deployments cost more per customer and require per-deployment
configuration, IAM, secrets, network, data, evidence, recovery, and incident
ownership. The narrower claim avoids presenting logical workspace isolation as
unrelated-customer multitenancy.

ADR-046-R7 and ADR-052-R6 now state both sides of the #2048 transition, and
ADR-051 states its activation prerequisites. ADR-053's two-surface ownership
decision and ADR-048's organization authority remain unchanged.

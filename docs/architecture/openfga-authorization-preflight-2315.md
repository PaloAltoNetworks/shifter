# OpenFGA authorization preflight (#2315)

Status: architecture guidance for the S2 authorization integration; production
authority cutover remains S8

Date: 2026-09-20

Contract: GitHub issue #2315 under the #2308 redesign and ADR-066. There is no
Ground Control requirement attached to this run.

This note restores the minimum policy and integration contract needed before
custom source work. The parent proposal named by #2308 is absent from this
checkout. This is not an implementation plan and adds no authorization model,
dependency, endpoint, UI, deployment, or runtime behavior.

## Readiness decision

The slice is architecture-ready only under these fixed boundaries:

- OpenFGA is the sole application-permission relationship authority after the
  S8 cutover. SQL owns principals, resource state and ancestry, policy/group
  display metadata, and durable operation/audit state. SQL does not hold a
  permission mirror or evaluate effective access.
- S2 may publish and exercise the new facade and policy model before S8, but it
  does not create mixed runtime authority. A protected surface uses exactly one
  authorization path. Legacy surfaces remain on their incumbent path until S8;
  a new OpenFGA denial is never rescued by a legacy role, Django permission, or
  local membership check.
- Authentication, credential admission, application authorization, cloud IAM,
  model-access authority, event participation, and resource lifecycle checks
  remain separate gates. Passing one never implies another.
- Every external policy mutation is a durable, serialized operation with intent
  recorded before the effect. An ambiguous external outcome remains unresolved
  and blocks conflicting edits until reconciliation establishes truth.
- The released OpenFGA server is a private authenticated dependency. Runtime
  application code exposes no store/model administration operation, and the
  design does not depend on OpenFGA's experimental API access-control feature or
  a custom proxy.

## One vocabulary and one authorization port

`shared` owns one closed action catalog, the authorization request/result
contracts, and a dependency-neutral provider port. `workspaces`, the incumbent
customer-scope policy owner, owns scoped group/policy display metadata and the
authorization durable-operation workflow, including the explicitly modeled
installation scope; `management` remains limited to principal/provider-binding
lifecycle. `config` is the composition root that binds the official OpenFGA SDK
adapter and hosts cross-domain administration presentation where it must resolve
both management principals and workspaces scopes. Owning services call the
shared port; they do not import SDK types, OpenFGA tuple syntax, or configuration.
Do not create a new authorization Django app or put policy persistence in
`shared` merely to avoid these existing boundaries.

Each action entry must carry enough static metadata to validate its use without
a second policy language: stable action code, supported target type and scope,
whether it is administrative, and whether it is delegable. Credential ceilings
refer to these same action codes. Predefined ApplicationAdministrator coverage
is set equality with every registered administrative action, not a wildcard or
name prefix. Human and service principals use the same principal object form
and action catalog; only authentication and lifecycle differ.

The request contract contains a validated `PrincipalRef`, one registered action,
one resolved target/scope projection, and a server-derived credential ceiling.
It never accepts an actor-supplied account, ancestry chain, role expansion,
provider claim, or contextual tuple. Unknown actions, invalid target/action
pairs, malformed scope, inactive principals, missing resources, and ancestry
mismatch fail closed before the provider call.

Use the incumbent `shared.identity_scope.ResourceScope` shape and
`workspaces.services.resolve_resource_scope` ancestry resolution. OpenFGA
object IDs use stable public UUIDs, never database integers, display names,
emails, usernames, issuer/subject pairs, or pack identities. Do not define a
second principal, scope, action, role, or error DTO in a domain or adapter.

The port returns a small typed decision: allowed, denied, or evaluator error.
Callers may expose allowed/denied only through the existing opaque HTTP error
contract. They retain evaluator-error classification for bounded metrics and
durable operation outcomes, without reflecting provider messages.

## Policy semantics and ownership

The model uses explicit installation, account, organization, workspace, and
resource relations. Parent relations project SQL-owned ancestry into OpenFGA;
they do not make OpenFGA the resource registry. A missing, stale, or conflicting
projection denies access and creates reconciliation work. It is never repaired
inside a permission check.

Predefined roles are named relations. Custom roles are role objects whose
permission relations are modeled in OpenFGA, and groups use the native userset
pattern (`group:<id>#member`). Direct assignments remain direct tuples. SQL may
store immutable IDs, names, descriptions, lifecycle state, and administration
display projections for roles/groups, but not expanded permissions or an
effective-access cache.

Ordinary deny is an explicit exclusion in the pinned model. Effective action
relations compose positive grants/inheritance minus the applicable deny
relation. Deny ancestry follows the same explicit resource hierarchy; absence
of a tuple is not overloaded as deny evidence. Installation-operator authority
is an explicit, separately assignable relation and never inferred from Django
staff/superuser, account administration, cloud IAM, or deployment access.

Credential admission is a ceiling, not another role evaluator. A request is
allowed only when the authenticated session/token/service credential permits
the registered action **and** the OpenFGA check permits it. Exact API-token
scopes remain fail-closed; no wildcard, provider group, Django group, or cached
UI capability can widen the result.

Delegation is checked on every direct assignment, group membership, group-role
binding, and custom-role/policy edit. The actor must hold the administration
action at the same or a broader valid scope, and every action the edit could
confer must fit both the actor's current delegable authority and credential
ceiling. Batch evaluation is all-or-nothing: one false, per-item error, timeout,
or incomplete result denies the mutation. Self-add, role editing followed by
assignment, nested group changes, cross-account object references, and
concurrent edits go through the same serialized boundary.

## Durable mutation and revocation contract

Policy writes reuse the repository's external-effect operation pattern, not its
domain-specific operation tables. The authorization owner persists its own
bounded operation record, immutable request digest, target scope/key, actor and
credential attribution, requested tuple delta, model ID, and outcome. Tuple
payloads, rosters, tokens, and provider error bodies do not enter audit or logs.

The required ordering is:

1. validate shape, ancestry, lifecycle, credential ceiling, and delegation;
2. serialize the canonical mutation scope and reject or join an equivalent
   request; record the operation and strict `requested` audit event atomically;
3. perform no network I/O while holding a database transaction or row lock;
4. submit one transactional OpenFGA write under the stable local operation ID;
5. record `confirmed`, `denied`, or `unresolved` with strict audit; and
6. reconcile `unresolved` state with primary-backed reads before any conflicting
   mutation can proceed.

The SDK's non-transactional split-write mode is forbidden. Hidden write retries
are disabled; the durable operation owns retries and idempotency. Duplicate
writes and missing deletes may use released conflict options only when the
requested final state and operation digest are identical.

Revocation is a monotonic security transition. The serialized revocation first
establishes the applicable deny/revocation fence, then removes positive
relationships, and is confirmed only after primary-backed readback proves the
fence and absence required by the operation. A later deliberate grant may
remove that fence only as part of a newly authorized, serialized operation.
Therefore a late result from an earlier grant cannot restore access after a
completed revocation. Timeout or connection loss after dispatch is unresolved,
never assumed failed or successful.

The canonical audit vocabulary is extended once to distinguish requested,
confirmed, denied, and unresolved policy results. Database-only mutations keep
their normal atomic strict-audit behavior. No second audit table, authorization
event bus, generic cross-store transaction framework, refresh daemon, or tuple
synchronization framework is introduced.

A rejected validation, authorization, ceiling, or delegation attempt emits the
strict `denied` audit outcome without claiming a requested external effect. An
accepted operation commits `requested` before dispatch and later commits exactly
one current `confirmed`, `denied`, or `unresolved` outcome; reconciliation may
advance unresolved to confirmed without erasing the earlier evidence.

## Supported SDK surface and failure semantics

The integration baseline is OpenFGA server v1.20.0 and Python SDK 0.10.4. Pin
the SDK exactly, resolve and record the immutable server image digest, pin the
authorization model ID, and retain this pair in a tested compatibility matrix;
do not silently float either version. Runtime code uses only the official SDK
operations below:

| Operation | Supported use | Required semantics |
| --- | --- | --- |
| `check` | one permission decision | `HIGHER_CONSISTENCY`; bounded deadline; false is denied; any error fails closed |
| `batch_check` | delegation and bounded coverage decisions | `HIGHER_CONSISTENCY`; correlate by request ID because response order is not contractual; any missing/per-item error denies the whole mutation |
| `write` | one authorized tuple delta | transactional mode only; durable operation owns retry/reconciliation |
| `read` | exact stored-tuple projection and uncertain-write reconciliation | `HIGHER_CONSISTENCY`; never used to compute effective access |
| `read_changes` | bounded diagnostics or reconciliation evidence | never sufficient by itself to prove an application operation or authorization decision |

`list_objects`/`list_users` may later support bounded advisory discovery but do
not authorize a mutation or replace `check`. Raw HTTP escape hatches, `expand`,
client-side batch fallbacks, contextual tuples for durable grants, conditional
writes that the released server does not provide, and non-transactional SDK
writes are outside the supported runtime surface.

An OpenFGA `allowed=false` is a normal denial. Invalid local input is denied
before dispatch. Authentication/authorization refusal by the server, timeout,
transport failure, rate limit, malformed response, unknown model/store, and
server error are evaluator failures and fail closed. For a write, an error that
can occur after dispatch (including timeout, connection reset, and server error)
is unresolved until readback; exception class alone never proves no effect.
Provider exception text, tuple data, credentials, endpoints, and stack traces
are not exposed through the API envelope.

## API, service, and UI boundaries

Administration endpoints use explicit DRF serializers and the existing closed
JSON/parser behavior. Public UUIDs identify principals, roles, groups, and
resources. Serializers validate transport shape; the owning service re-resolves
principal lifecycle, resource ancestry, actor authority, delegation ceiling,
and current operation state under serialization. HTTP views do not construct
tuples or implement policy.

The frontend consumes generated OpenAPI types through the shared API client and
TanStack Query modules. Unsafe session requests keep CSRF; mutations have no
automatic retry. Server-returned capabilities are presentation hints only, and
every endpoint reauthorizes. Do not hand-copy role/action DTOs, fetch directly
from components, expose raw tuples, or make the browser an OpenFGA client.

## Private deployment contract

OpenFGA runs as a private service with no public ingress. Use a released,
digest-pinned image, native TLS with hostname/CA verification, stable supported
client authentication, JSON logging, disabled Playground/profiling, bounded
database/client connection pools, resource limits, readiness, metrics, and
default-deny network policy. The baseline is OpenFGA's native preshared-key
authentication over TLS; unauthenticated mode is forbidden. A later native OIDC
client-credentials binding may replace it only through the typed deployment seam
with exact issuer/audience/claim validation. Permit only the
portal/authorization worker and a separate deployment administration job.
Disable unused listeners such as gRPC.

OpenFGA owns a dedicated PostgreSQL database/schema and least-privileged runtime
database identity. Its migration command runs as a deployment job before server
rollout. Django never imports its tables or queries that database. Store
creation, authorization-model publication, assertions, and migration are
deployment-only operations; the application runtime adapter exposes no
store/model administration method.

Stable OpenFGA authentication identifies clients but does not by itself enforce
fine-grained store/model administration. Runtime method allowlisting,
deployment-only credentials/workloads, private reachability, and network policy
are therefore required defense in depth. Do not depend on experimental OpenFGA
API access control and do not place a custom authorization proxy in front of it.

Database URLs, preshared/OIDC credentials, and TLS keys flow through the
canonical provider secret store and Kubernetes Secret/file bindings. Keep them
out of Terraform plan/state outputs where avoidable, ConfigMaps, generated
public manifests, environment diagnostics, audit, logs, shell history, and
process arguments. Prefer mounted configuration/secret files readable only by
the service identity. Application settings use the validated environment
manifest and bounded settings parsers; no module reads ad hoc environment
variables.

AWS Helm and GCP Kustomize/Terraform surfaces must express the same service,
secret, migration, network, health, and pinning contract. The seam is the
installation backend's typed runtime/service bundle: endpoint reference,
store/model IDs, credential/CA secret references, deadlines, and bounded pool
settings are parameters there. This permits the next deployment backend or
credential method without changing action, scope, policy, or domain contracts.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Layering/composition | ADR-001/ADR-066, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `management/management/commands/check_model_fks.py`, `config` | Contracts/port in `shared`; ancestry, policy metadata and durable policy commands in `workspaces`; identity in `management`; cross-domain administration presentation and SDK binding in `config`. Cross-domain calls use public service facades and scalar references. Do not create an authorization Django app merely to bypass these boundaries. |
| Principal/scope | `shared.identity_scope`, `management.services`, `workspaces.services.resolve_resource_scope`, `Account` hierarchy | Reuse the single human/service principal and scope shapes and re-resolve active identity plus ancestry at mutation time. |
| Current authorization | `shared.auth`, `shared.api.permissions`, `shared.api_tokens`, `workspaces.roles` and authorization services, `ctf.services.authorization`, `management.model_access_authority`, Engine preparation/sharing authorities | Inventory every protected surface and give it one catalog mapping/cutover disposition. Preserve distinct CTF, model-access, cloud and lifecycle gates; never OR a legacy check with OpenFGA. |
| HTTP contracts | `config._drf_settings`, `ClosedSerializer`, `shared.api.strict_json`, `shared.api.errors`, trusted audit attribution | Bearer-first authentication, CSRF, duplicate/unknown field rejection, bounded input, opaque denial, and request-ID error envelope remain mandatory. |
| Audit/logging | `shared.audit`, `shared.audit_adapter`, append-only `AuditLog`, `shared.audit.integrity`, `shared.log_sanitize`, ECS logging | Extend one vocabulary; strict audit security mutations; use stable IDs and bounded reason codes. Never log relationships, role contents, rosters, tokens, provider payloads, or exception text. |
| Durable external effect | Engine preparation/runtime-plugin/model-request operation, lease, immutable-digest, reconciliation, and fenced-apply patterns; `shared.operation_intent`/envelopes | Reuse the pattern and primitives, not Engine domain tables. Persist intent before I/O, keep I/O outside transactions, fence conflicts, and reconcile ambiguity. Do not make a generic transaction/synchronization framework. |
| API/client generation | DRF OpenAPI, schema drift checks, `frontend/src/api/client.ts`, generated `schema.d.ts`/`types.ts`, Query modules | Generate types, use the common client, preserve CSRF/request IDs, and keep mutations non-retrying. |
| Configuration/deployment | `config/env-manifest.json`, `_env_manifest.py`, settings validators, `shifter/installation` schema/loader/render/runtime inventories, AWS Helm and GCP Kustomize/Terraform, `config.health_checks` | Add typed, secret-aware configuration and parity across both supported clouds. Health responses remain coarse and secret-free. |
| Workflow/testing | ADR guard, import/layer checks, OpenAPI drift, PostgreSQL suite, actionlint, TFLint, kube-linter/kubeconform, first-party service test policy | Test the real released OpenFGA server and PostgreSQL concurrency; mock the external SDK boundary only in unit tests, not first-party services. |

## Cross-cutting security and runtime layers

1. **Authentication and principal lifecycle.** Existing Cognito/OIDC/Identity
   Platform verification, Django session state, service-credential validation,
   inactive-principal checks, and temporary-CTF origin gates run before policy.
   Claims, email, groups, and creator/contact relationships are never grants.
2. **Credential admission.** Bearer parsing remains first and fail-closed;
   session mutation retains CSRF; exact token/service ceilings are ANDed with
   policy. Credentials and ceilings are server-derived, never request fields.
3. **Transport shape.** Strict JSON and `ClosedSerializer` reject duplicates,
   unknown fields, invalid UUIDs/enums, excessive lists, and unsupported action
   or target shapes. OpenAPI and generated frontend types derive from this one
   surface rather than copy it.
4. **Shared contract validation.** `PrincipalRef`, `ResourceScope`, and the
   closed catalog reject malformed combinations. The SDK adapter cannot relax
   them or accept arbitrary relation/tuple strings.
5. **Identity, ancestry, and lifecycle.** Management resolves the active
   principal; workspaces proves account/organization/workspace ancestry and
   lifecycle; the owning resource service validates its own state. Cross-account
   and stale references fail with opaque denial.
6. **Authorization and delegation.** The facade applies credential ceiling,
   pinned model/store identity, `HIGHER_CONSISTENCY`, deny precedence, explicit
   installation authority, and all-or-nothing delegation. There is no fallback
   evaluator or authorization cache.
7. **Persistence/concurrency.** PostgreSQL constraints, transactions, row locks,
   immutable digests, operation fences, leases, and primary-backed OpenFGA
   readback serialize policy edits and preserve unresolved outcomes. Network I/O
   never occurs inside the SQL transaction.
8. **Secrets, configuration, and OS exposure.** Canonical typed installation and
   settings inventories carry secret references; provider secret stores and
   mounted files deliver values. Secrets do not appear in argv, environment
   diagnostics, Terraform outputs, ConfigMaps, logs, audit, API, or UI.
9. **Network/process boundary.** Private DNS/service exposure, native TLS/auth,
   default-deny policy, separate runtime/admin workloads, least-privileged
   PostgreSQL, and disabled unused endpoints contain the released server.
10. **Errors and observability.** `shared.api.errors` returns stable status/code,
    detail, and request ID without provider detail. Sanitized structured logs and
    low-cardinality metrics distinguish allowed, denied, evaluator error,
    requested, confirmed, and unresolved without relationship data.

## Required conformance and coverage evidence

- Catalog tests enumerate all protected API, HTML, service, scheduled, and
  worker entry points. Every surface maps to exactly one registered action or an
  explicit public/authenticated-only exemption. Unknown/unmapped surfaces fail
  the test; route name or HTTP verb inference is insufficient.
- ApplicationAdministrator equals the complete registered administrative set,
  and human/service fixture matrices prove equivalent action coverage.
- Shared conformance fixtures exercise hierarchy inheritance, ordinary deny,
  installation authority, direct/group/custom/predefined grants, credential
  ceilings, delegation, self-add, cross-account references, unknown actions,
  malformed context, timeout, and evaluator failure. Downstream slices reuse
  these fixtures rather than restating expected policy.
- Integration tests use the pinned released server and real PostgreSQL to cover
  transactional native tuple writes, concurrent grant/revoke/mutate, duplicate
  delivery, timeout after dispatch, restart/reconciliation, and the rule that a
  confirmed revocation survives a late earlier grant.
- Deployment tests cover model/store ID pinning, model assertions, private-only
  reachability, TLS/auth failure, secret redaction, migration-before-rollout,
  network-policy allow/deny paths, and runtime rejection of admin operations.

## Gotchas and prohibited anti-patterns

- Do not introduce a local role evaluator, effective-permission table, tuple
  mirror, authorization cache, generic sync daemon, custom policy language, or
  generic distributed-transaction framework.
- Do not treat SQL ancestry/display rows as permission truth, or OpenFGA tuples
  as identity/resource existence truth. A group definition and its membership
  relationship are different ownership facts.
- Do not infer installation scope from missing account IDs, authority from
  Django staff/superuser or cloud IAM, identity from email, or permission from
  account type, creator, provider group, cached UI state, token scope alone, or
  the ability to administer an OpenFGA deployment.
- Do not use read/list APIs as an authorization evaluator, compute permissions
  in the frontend, accept tuple/relation strings over HTTP, or put provider
  objects/errors in service contracts.
- Do not hide ambiguous writes with retries, clear an unresolved fence by age,
  hold SQL locks across network I/O, or let grant and revoke use different lock
  keys. Operation ordering must be defined by durable state, not arrival time.
- Do not use `latest`, an unpinned model, SDK default write retry, experimental
  API access control, public ingress, a custom proxy, shared database tables, or
  runtime store/model administration.
- Do not allow legacy permission checks to rescue OpenFGA denial. S8 is a hard
  authority cutover, not an OR, shadow-allow, feature-flag fork, or dual-write
  window.

## Non-goals and implementation boundaries

- This slice does not perform S8 production cutover, migrate legacy memberships,
  remove legacy role checks, or claim completed multi-account isolation.
- It does not redesign authentication, issue a new credential/token format,
  replace exact API-token scopes, or make a service principal a Django human.
- It does not make OpenFGA authoritative for identity, resource lifecycle or
  ancestry, cloud IAM, CTF event participation, model-access authority,
  provider installation, secrets, or deployment administration.
- It does not add organizational approval, just-in-time access, nested-group
  semantics beyond the pinned model, customer-authored executable policy, or a
  public/general policy query language.
- It does not make UI capability responses an authorization guarantee or expose
  raw tuples, store/model administration, audit internals, or reconciliation
  controls to ordinary clients.

## External protocol references

- [OpenFGA Python SDK](https://github.com/openfga/python-sdk)
- [Consistency](https://openfga.dev/docs/interacting/consistency)
- [Relationship queries](https://openfga.dev/docs/interacting/relationship-queries)
- [Tuple writes](https://openfga.dev/docs/getting-started/update-tuples)
- [Roles and permissions](https://openfga.dev/docs/modeling/roles-and-permissions)
- [Custom roles](https://openfga.dev/docs/modeling/custom-roles)
- [Blocklists and exclusions](https://openfga.dev/docs/modeling/blocklists)
- [Server configuration](https://openfga.dev/docs/getting-started/setup-openfga/configure-openfga)
- [API authentication and experimental access-control warning](https://openfga.dev/docs/getting-started/setup-openfga/access-control)
- [Production deployment guidance](https://openfga.dev/docs/best-practices/running-in-production)

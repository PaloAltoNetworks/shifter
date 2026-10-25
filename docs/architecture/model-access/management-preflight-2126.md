# Scoped model-access management preflight — #2126

Architecture guidance for M09 / PLAT-202, inspected at `26e03790266a` on
2026-09-20. This is neither an implementation plan nor authorization to claim a
provider, deployment or workflow as qualified. Apply
[ADR-059](../../adr/059-range-model-access-broker.md),
[ADR-060](../../adr/060-model-access-allocation-accounting.md) and
[ADR-061](../../adr/061-model-access-operations-qualification.md), together with
the [architecture](architecture.md), [security](security.md),
[sharing contract](sharing.md), [source-management preflight](source-management-preflight-2243.md)
and [broker preflight](broker-preflight-2122.md).

Platform paths below omit the `shifter/shifter_platform/` prefix; installation
paths omit the leading `shifter/`. Other paths are repository-relative.

## Decision and ownership

M09 is a management projection over existing owner domains, not a new policy
engine. Keep these authorities separate:

- The installation-owned v3 catalog and its mounted path/digest define the
  deployed, non-secret runtime envelope. They are validated by
  `installation/model_access.py`, `installation/model_broker_runtime.py`,
  `config/_model_access_settings.py` and `shared/model_access/runtime.py`.
- Engine publication, allocation, sharing, grants, budgets and request ledgers
  are the live durable authority. Immutable revisions and compare-and-set
  pointers belong there.
- A per-allocation v4 source overlay selects an approved tenant source. It does
  not replace the installed inventory or become a second deployment catalog.
- CTF owns event demand, event source sponsorship and organizer authority. CMS
  owns scenario needs, ordinary range launches and existing-range authority.
- The broker owns bounded execution only. It does not infer portal authority,
  publish policy, manage rosters or read application tables.

Consequently, do not expose one generic `policy` document, revision or status
that conflates catalog publication, source configuration, event intent, sharing
membership, allocation, credential delivery and accounting. A management
resource may compose their read projections, but each mutation must enter the
owning service and compare that owner's revision.

Catalog validate/publish/drain may activate only inventory that the installed
runtime, IAM, network and provider adapter already support. A web request must
not rewrite the mounted catalog, environment, Helm/Terraform state, ConfigMap or
process global. Onboarding a new shard, principal, provider or credential
mechanism remains a deployment change. Draining blocks new use; it never deletes
old revisions, rewrites allocations/prices, releases uncertain liabilities,
refunds spend or cancels a potentially billable provider request.

The existing ADRs already decide these boundaries; M09 needs no new authority
ADR. This note records the management-specific guardrails that were previously
spread across the architecture, security, sharing and source documents.

## Authority and visibility

Authentication, API-token scope and domain authority are cumulative. A scope is
never object authority, staff status is not platform-operator authority, and
workspace membership alone is not event authority.

| Principal | Canonical authority | Permitted projection or mutation |
| --- | --- | --- |
| Deployment operator | `management.services.is_platform_operator` | Validate/publish/drain the deployed catalog envelope; manage deployment ceilings; inspect operator-only coordinates and all-range aggregates. An active staff user who is not a platform operator does not qualify. |
| Tenant source administrator | `workspaces.services.resolve_administrable_organization` and source workspace authorization | Manage its tenant's source metadata and write-only credentials inside deployment maxima. It may see the coordinates of sources it administers, but gains no catalog, event or range authority. |
| Event owner or delegated organizer | `ctf.services.authorization` with the exact `EventCapability` | Declare bounded event demand, choose delegated sources/profiles and assess the event. It cannot expand deployment or tenant maxima, and participation is not organization administration. |
| Existing-range administrator | CMS/workspace range authorization | Inspect and tighten or change its range within current source-use authority and ceilings. It cannot infer authority from possession of a range identifier. |
| Scenario/range launcher | Existing CMS/mission-control launch authorization | Select only choices returned as permitted for that launch; admission remains server-side. |
| Participant | CTF participant authorization for the exact event/range | Read only its range's safe availability, limits, deadline and bounded denial/readiness state. It receives neither management mutation authority nor another member's contribution or usage. |

Use role-specific service DTOs. Do not serialize an operator object and redact it
in a view or component. Provider project/account identifiers, raw provider quota
and IAM/principal details remain operator-only, except that an authorized tenant
source administrator necessarily sees its own configured source coordinates.
Organizers may see approved display identity, logical assignments, ceilings and
effective balances, but not secret references or deployment coordinates.
Participant DTOs must be range-scoped and omit rosters, bindings, source
coordinates, account contributions and low-cardinality shared-pool details that
would reveal other users.

## Management semantics

### Revisions, preview and publication

Every mutation reauthorizes the active actor under the owning transaction and
uses optimistic comparison. Do not use timestamps or one unrelated counter as a
universal fence. In particular, `CTFEvent.model_source_revision` currently
fences source selection only; it cannot be advertised as fencing demand,
profiles, budgets or a wider event-policy aggregate unless the CTF owner service
supplies a revision covering that exact aggregate.

Sharing continues to use `shared/model_access/sharing_models.py`,
`engine/services/_sharing.py`, the sole compiler in
`shared/model_access/effective_policy.py`, owner resolvers and
`config/model_access_sharing.py`. Preview and publish must call the same
resolver/compiler path. Preview returns bounded matched/excluded counts and
reason codes, all applicable revisions, conflicts, balance/cap information and
active-range effects; it is not authority. Publication re-resolves membership,
checks full-collection authority and performs compare-and-set. The caller cannot
supply trusted publisher, actor, source, membership-revision or audit fields.
Operator-only all-ranges, snapshot/dynamic membership, independent facets and
pooled-plus-individual accounting retain the semantics in `sharing.md`; do not
add an API-only selector language or overlap evaluator.

Event assessment consumes the typed `EventModelDemand`, CTF-908 declarations,
PLAT-201 capacity assessment, current source sponsorship and Engine's allocation
and account projections. It must not reproduce admission or capacity arithmetic
in the browser. A best-effort capacity fallback is not a valid positive decision
for required model access. Weights influence existing allocation strategy; they
do not create quota, authority or exact participant counts.

### Range status, revoke and re-enroll

Range access status is a read model, not a new mutable status table. Compose it
from the immutable allocation and price snapshot, current grant/credential
authority, source-policy transition, budget accounts/postings and delivery
state. Count each distinct account once when reporting used/reserved amounts.
Expose explicit optional-unavailable, stale, pending, ready, revoking and denied
states using bounded authored reason codes; never derive them from provider or
exception strings.

Revoke must use `engine/services/_model_allocation_lifecycle.py` and the request
lifecycle to fence current grants and dispatch leases transactionally. Database
authorization can be fenced before transport closes, so success may remain
`revoking`; it does not prove provider cancellation or no billable effect.
Outstanding reservations and uncertain effects remain liabilities under their
original immutable price/account vector.

Re-enroll never returns a participant credential to the portal or browser and
never reactivates a terminally revoked grant. It may request only a fresh,
currently authorized successor for the same admitted allocation/policy epoch,
then reuse the operation-bound control/provisioner path and verified SSH-stdin
delivery into guest tmpfs. If the policy changed, fresh admission precedes
enrollment. If no bounded operation-owned delivery command exists for the range,
the action stays unavailable rather than tunnelling a token through the web
worker or replaying a launch/provider request. Lost responses are idempotent
conflicts/reconciliation cases, not permission to reveal or replay secrets.

## Cross-cutting passage requirements

These layers are cumulative; satisfying the local view or service style does
not establish the complete boundary.

| Layer and canonical incumbents | Required passage |
| --- | --- |
| HTTP authentication and authorization: `shared/api_tokens/authentication.py`, `shared/api/{permissions,principals}.py`, `shared/api_tokens/{permissions,scopes}.py`, `ctf/api/_base.py`, owner services | Browser requests use the existing session and CSRF path. Programmatic requests use bearer-first, fail-closed authentication, newly registered exact read/write scopes and the active token owner. A bad bearer never falls through to a session. Reauthorize current operator/event/workspace/range authority on every request and idempotent retry. The SPA never stores API tokens. |
| Routing and contracts: `/api/v1` in `config/api_urls.py`, domain URL modules, `shared/api/schema.py`, committed `openapi/v1.json` and generated frontend `schema.d.ts` | Publish resources through the owning DRF/service boundary; use the config composition root only for genuinely cross-domain commands. Preserve import contracts: Engine does not import CMS/CTF models and the broker imports no Django/application layer. Exact token scopes must appear in OpenAPI. Generated contract drift is a failure, not a hand-maintained client workaround. |
| Raw input and semantic validation: `shared/api/strict_json.py`, `shared/api/closed_serializer.py`, `core_models.ClosedModel`, `catalog.py`, source/admission/sharing models | Bound request bytes and collection sizes; reject duplicate JSON members, unknown fields, coercions and non-finite values. DRF shapes HTTP only; owner services revalidate shared closed models and canonical semantic/digest rules. Do not duplicate catalog, selector, demand, weight or accounting validation in serializers or React forms. |
| Persistence and concurrency: Engine models/services, owner-domain row locks, unique/check constraints and keyset range enumeration | Store immutable revisions plus a CAS publication pointer, preserve canonical lock order and perform no cloud/provider/secret I/O under locks. Reauthorize after external I/O. Redis, caches and previews are not policy, membership or financial authority. Retain historical price, source, account, cleanup and liability references with `PROTECT`/tombstone semantics. |
| Installed config and runtime shapes: installation model-access loaders/renderers, runtime digest validation, broker/control inventories and `.importlinter` | Management state can narrow or select only what the installed envelope realizes. Evolve all closed consumers together; do not bypass exact inventory, disabled defaults, catalog digest, provider binding, broker isolation or the `scripts/check_layer_imports` public-facade rules. A source's presence or successful connection does not establish publication, capacity or qualification. |
| Secrets and OS-level exposure: existing source credential API, `shared.cloud` secret stores, owned secret names, broker credential resolver, provisioner enrollment | M09 adds no readable credential DTO and no second secret store. Metadata and secret bytes stay separate; writes are TLS-only and write-only. No credential, enrollment token or secret reference leaks through URLs, query strings, process argv, environment literals, shell interpolation, manifests, ConfigMaps, Terraform state, operation JSON, browser storage, logs or support bundles. Keep broker retrieval ephemeral and enrollment on private control plus SSH stdin/tmpfs. |
| IAM, network and host consumers: broker/control Helm templates and network policies, GCP/AWS Terraform modules, GCP render/probe scripts, AWS bootstrap, deployment workflows | Management availability must reflect the actual adapter, identity, exact-target IAM, egress, TLS and image deployment. Same-project placement is allowed but does not merge broker, invocation or control identities. No API mutation broadens IAM/network policy or fabricates readiness; additive network policies must not reopen private services. |
| Accounting and lifecycle: `_model_request_accounting.py`, `_model_request_lifecycle.py`, allocation/grant/source-policy transition services | Limits are finite server-owned integers applied once per distinct account. Preserve shared and per-range facets, immutable prices and settlement against the original vector. Mutation fences old authority before replacement, retains uncertain outcomes and never automatically retries a potentially billed request on another source. |
| Errors: owner-domain exceptions and codes, `shared/api/errors.py`, broker/control envelopes | Return the standard bounded envelope and request ID. Use stable categories such as malformed input, unauthenticated, unauthorized/not visible, stale revision, in-progress and temporarily unavailable. Never serialize Pydantic paths/input, ORM details, membership lists, secret references, provider bodies, SDK exceptions or raw `str(exc)`. A safe API mapper cannot undo an earlier traceback/log leak. |
| Audit, logging and metrics: `shared.audit`, its central vocabulary, `RequestAudit`, `shared/log_sanitize.py` and existing model-access metrics | Config, budget, publish, drain, revoke and enrollment intent/outcome are strict audit events with server-derived real actor and request source. Thread trusted `RequestAudit` into the owning transaction; do not emit a second best-effort view audit. Existing sharing persistence currently records a system actor, so an authenticated M09 mutation must supply real attribution rather than preserve that placeholder. Add vocabulary/migrations only when no canonical action/entity exists. Audit/logs remain body-free and metric labels bounded. |
| SPA and accessibility: `frontend/src/api/{client,csrf,queryClient,errors,model-sources}.ts`, generated types, existing source picker/forms/dialogs and `frontend/e2e/a11y/matrix.ts` | Reuse the same-origin client, TanStack Query and components. Mutations do not auto-retry. Cache keys include owning tenant/event/range and relevant revision; a 409 visibly requires reload. Secret inputs never enter cache and clear after use/unmount. Empty, denied, stale, optional-unavailable, loading and partial-readiness states need semantic labels, focus/error handling and central browser/a11y coverage. |

The whole-repository consumers in scope are the shared model-access contracts and
schema vectors, Engine persistence/services/migrations, CMS/CTF/workspace and
management facades, the config composition root, DRF/OpenAPI and generated
frontend client, broker/control/provisioner enrollment, installation renderers,
Helm/NetworkPolicy, GCP/AWS Terraform and bootstrap/render/probe scripts, API
scope inventories, audit vocabulary, import contracts, ADR guard and canonical
deployment workflows. Do not add an operator script or a parallel manifest as a
management escape hatch.

## Extension seam and evidence

The extension seam is the existing owner projection plus the shared closed
contract, not a central management switch statement. A new provider extends the
provider registry, credential resolver, installed inventory and qualification
evidence. A new membership owner adds a bounded resolver at the config
composition root. A new management audience gets an explicit projection DTO and
visibility policy. A new assessment implementation may be asynchronous behind
the same resource/revision contract, but cannot weaken publication CAS or make a
job/cache authoritative.

Keep aliases, providers, hosting cloud, invocation account/project, credential
version, quota pool, financial account and sharing facet independently
parameterized. This permits the next expected changes—another qualified
provider, cross-cloud inference, a new selector owner or asynchronous capacity
assessment—without editing scenario policy or conflating identities. Capability
and readiness fields must be data-driven so planned support remains unavailable
until its installed/runtime evidence exists.

Reuse shared contract/vector tests; Engine sharing/allocation/accounting tests,
including PostgreSQL contention; CTF and CMS authorization tests; broker/control
boundary tests; installer/chart/render/IAM checks; OpenAPI scope/drift checks;
and frontend unit/browser/a11y suites. Evidence must cover cross-event and
cross-workspace negatives, revoked actors/tokens, stale preview and CAS races,
all six sharing examples, source-admin/organizer/participant redaction, real
audit attribution, safe error states, and secret sentinels absent from DTOs,
errors, logs, audit and rendered artifacts.

## Non-goals and prohibited shortcuts

M09 does not create a provider adapter, onboard IAM/egress, qualify a cloud,
replace source administration, redesign the event form, invent a range lifecycle
or add a generic gateway, vault, job framework, policy language, budget system,
roster API or prompt-capture facility. It does not add arbitrary provider URLs,
remote tool execution, executable pack adapters, new RAES fields, per-range
cloud accounts or automatic fair-share scheduling.

Do not add API-only schemas, validation, exception hierarchies, audit stores,
financial caches or authorization evaluators. Do not authorize by staff flag,
workspace membership, scope, source visibility, guessed identifier or stale
preview. Do not serialize-then-redact operator DTOs, expose provider diagnostics,
reactivate revoked epochs, mutate allocation snapshots, reset spend, erase
liabilities, promise provider cancellation or replay a possibly billed request.
Private pack details and PLAT-215 prompt/response capture remain out of scope.

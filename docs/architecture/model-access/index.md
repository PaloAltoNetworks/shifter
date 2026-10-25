# Per-range model and tool access design — #681

Current status: the broker is parked and unsupported under
[ADR-068](../../adr/068-model-access-broker-parked.md); ADR-064 keyless-direct is
the only supported guest model path. The broker design and implementation
guidance below are historical; they do not authorize activation or extension.
For the selected LiteLLM OSS replacement, deployment-owned rotation and
qualification plan, see the
[#2274 evaluation](gateway-replacement-evaluation-2274.md). For repository
boundaries, see the
[#2274 gateway preflight](gateway-preflight-2274.md).

Historical design: 2026-09-06, requirement **PLAT-202**;
baseline `6fd946352ec22c8bf373a04b52f738f9f6c6a9f4` on `dev`.
The source issue remains the canonical work tracker:
[#681](https://github.com/Brad-Edwards/shifter/issues/681).

The historical design gives each admitted range generation a revocable,
budgeted capability to a deployment-owned broker. Provider credentials stay
outside participant control. Scenario and event configuration selects logical
profiles; Engine allocates approved model/account/project shards and owns
accounting. GCP/Vertex is the first qualification target under #2080.
Provider identity, model assignments, capacity and budgets can be shared
independently across selected ranges, users, groups, CTF collections or all
deployment ranges. Shared resources do not require shared participant tokens.

| Document | Purpose |
| --- | --- |
| [Gateway replacement evaluation](gateway-replacement-evaluation-2274.md) | #2274 comparison, selected LiteLLM OSS integration, deployment-owned rotation and qualification plan. |
| [Gateway replacement preflight](gateway-preflight-2274.md) | #2274 clarified replacement scope, ADR-068 precedence and repository boundaries for future integration. |
| [Architecture and contracts](architecture.md) | Ownership, configuration, allocation, API, persistence, protocol, lifecycle, and user flows. |
| [Tenant source management](source-management.md) | Implemented source publication, credentials, provider routing and live range transitions. |
| [Tenant source-management preflight](source-management-preflight-2243.md) | #2243 tenant authority, provider/hosting separation, write-only credentials, live-edit accounting and whole-repository validation boundaries. |
| [Configurable sharing](sharing.md) | Which ranges share which resources, membership modes, overlapping policies, pooled accounting and management examples. |
| [Sharing authority preflight](sharing-authority-preflight-2140.md) | M20 owner-resolution, transactional fence, mutation-path, validation and security guardrails. |
| [Allocation preflight](allocation-preflight-2120.md) | M03 transaction, shared-quota locking, pending-grant, lifecycle and cross-cutting validation guardrails. |
| [Durable allocations](allocations.md) | M03 quota reservations, v2 provider-pool membership, pending grants and preparation authority. |
| [Request accounting preflight](request-accounting-preflight-2121.md) | M04 budget-account contract, atomic ledger, dispatch lease, idempotency, reconciliation and cross-cutting security guardrails. |
| [Private broker preflight](broker-preflight-2122.md) | M05 incumbent listeners, identity and credential boundaries, streaming fences, deployment validators and qualification gaps. |
| [Scoped management preflight](management-preflight-2126.md) | M09 authority, visibility, revision, lifecycle, API/UI and whole-repository boundaries for operator and organizer management. |
| [Private broker runtime](broker-runtime.md) | M05 closed routes, identity/credential enforcement, resource bounds, drain and local HTTP verification. |
| [Security design](security.md) | Threats, identities, network/IAM boundaries, credential lifecycle, privacy, and negative tests. |
| [GCP deployment package](gcp-packaging.md) | Disabled M06 identity, TLS, network, runtime and deployment-lane resources. |
| [GCP packaging preflight](gcp-packaging-preflight-2123.md) | M06 repository integration gates for runtime isolation, IAM, egress, TLS and deployment evidence. |
| [Vertex adapter preflight](vertex-adapter-preflight-2124.md) | M07 pinned-client compatibility, Vertex transport/identity, count-based accounting, usage/error and whole-repository validation guardrails. |
| [GCP operator probes](../../ops/model-access-gcp-probes.md) | Project onboarding, effective IAM, source-preservation and TLS qualification cases. |
| [Operations design](../../ops/model-access.md) | Deployment, sizing, objectives, migration, failure recovery, cost, and release evidence. |
| [Implementation issues and dependencies](delivery.md) | Coding-sized work, milestones, hard blockers, and completion criteria. |
| [Example v1 policy](example-policy.v1.json) | Complete disabled, non-secret catalog with its canonical digest. |
| [Canonical JSON vector](canonical-json-v1-vector.json) | Exact UTF-8 canonical bytes and SHA-256 digest vector. |
| [Allocation vectors](weighted-rendezvous-v1-vectors.json) | Cross-implementation weighted-rendezvous inputs, ranks, and affinity namespaces. |
| [ADR-059](../../adr/059-range-model-access-broker.md) | Broker and authority decision. |
| [ADR-060](../../adr/060-model-access-allocation-accounting.md) | Allocation and mandatory accounting decision. |
| [ADR-061](../../adr/061-model-access-operations-qualification.md) | Revocation, operation, and qualification decision. |
| [ADR-064](../../adr/064-default-range-model-access.md) | Direct keyless default, mutually exclusive with broker-enforced access per range. |
| [ADR-068](../../adr/068-model-access-broker-parked.md) | Current decision: broker parked, direct access supported, future controls optional. |
| [Tenant user guide](../../features/model-access.md) | What organizers, participants, and operators will see. |

## Scope and support claims

Issue #2118 supplies the shared policy/schema/allocation/provider contract and
the disabled installation/runtime configuration boundary. It does not supply a
model service, persistence, deployment, migration, new RAES field, provider
implementation, or live qualification result. Those delivery stages remain in
the linked backlog, and ADRs remain proposed until their runtime claims land.

First delivery: the selected GCE cohort, multiple approved Vertex projects
and model aliases, required or explicitly optional scenario model access,
configurable sharing and budgets, and retained existing lifecycle authority.
The catalog and adapter boundary also cover Bedrock, direct provider APIs,
and bounded external HTTPS tools; their releases require their own issues
and evidence. Local scenario tools remain inside the range. Privileged
operator MCP is never delegated by model access. Model permission does not
imply ADR-058 participant-control support.

PLAT-215's wider runtime/experiment metering and prompt capture remain a
separate requirement. This design supplies mandatory access-accounting
metadata only. It neither implements experimental capture nor authorizes
prompt retention; any future capture path needs its own consent, scope,
storage, retention and export policy outside this broker audit boundary.

## Baseline findings that affect implementation

- The former guest provider-key issuance and embedded scenario bootstrap paths
  have been removed from core. Legacy GCP key teardown remains for draining old
  ranges. New enrollment must use broker capabilities, with no fallback to
  provider credentials on participant-controlled machines.
- `ctf/services/range/capacity.py` already declares roster/spare demand and
  organizer hints, but catches declaration/assessment/admission failures.
  #668/#621 are not blank-slate implementation tasks despite remaining open.
- `shared/capacity`, `engine/models/_capacity_assessment.py`, and
  `engine/services/_capacity_*` implement ADR-047. Extend those seams;
  security admission cannot inherit their advisory fallback.
- ADR-043's operation projection, result inbox, and Engine applier provide
  generation fencing. Do not grant the standalone provisioner Django table
  ownership or introduce a second execution generation.
- #1586 already selects a dedicated dynamic-secret project in repository
  prose; #2083 owns effective implementation and migration. This design
  consumes that boundary for legacy cleanup and enrollment references.
- ADR-064 supersedes the no-service-account default for direct GCP access.
  Broker-mediated ranges remain identity-less; direct access cannot satisfy
  mandatory broker accounting or serve as its outage fallback. ADR-057's
  existing GKE boundary still applies.

Implementation must recheck these paths against its current `dev` and retain
the decisions even if modules have moved.

## Implemented contract foundation

`shared.model_access` owns the frozen v1 DTOs, strict raw-JSON parser,
normalization/digest helpers, profile intersection, sharing selectors and
pools, provider protocol/registry, and fixed/weighted-rendezvous allocation.
The generated schema at
`shifter/installation/published_contract/model-access-policy.v1.schema.json`
lets the independently packaged installer validate the same closed shape.

Installation renders the catalog as a dedicated artifact and emits only
`MODEL_ACCESS_ENABLED`, `MODEL_ACCESS_CATALOG_PATH`, and
`MODEL_ACCESS_CATALOG_DIGEST` into backend runtime configuration. Runtime
startup reparses the mounted artifact with the canonical shared parser. The
default is disabled with no catalog path; enabling delivery still depends on
the broker, persistence, infrastructure, and qualification work in
`delivery.md`.

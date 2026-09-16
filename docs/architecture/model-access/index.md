# Per-range model and tool access design — #681

Status: proposed implementation design, 2026-09-06. Requirement: **PLAT-202**.
Repository baseline: `6fd946352ec22c8bf373a04b52f738f9f6c6a9f4` on `dev`.
The source issue remains the canonical work tracker:
[#681](https://github.com/Brad-Edwards/shifter/issues/681).

The selected design gives each admitted range generation a revocable,
budgeted capability to a deployment-owned broker. Provider credentials stay
outside participant control. Scenario and event configuration selects logical
profiles; Engine allocates approved model/account/project shards and owns
accounting. GCP/Vertex is the first qualification target under #2080.
Provider identity, model assignments, capacity and budgets can be shared
independently across selected ranges, users, groups, CTF collections or all
deployment ranges. Shared resources do not require shared participant tokens.

| Document | Purpose |
| --- | --- |
| [Architecture and contracts](architecture.md) | Ownership, configuration, allocation, API, persistence, protocol, lifecycle, and user flows. |
| [Configurable sharing](sharing.md) | Which ranges share which resources, membership modes, overlapping policies, pooled accounting and management examples. |
| [Sharing authority preflight](sharing-authority-preflight-2140.md) | M20 owner-resolution, transactional fence, mutation-path, validation and security guardrails. |
| [Security design](security.md) | Threats, identities, network/IAM boundaries, credential lifecycle, privacy, and negative tests. |
| [GCP deployment package](gcp-packaging.md) | Disabled M06 identity, TLS, network, runtime and deployment-lane resources. |
| [GCP packaging preflight](gcp-packaging-preflight-2123.md) | M06 repository integration gates for runtime isolation, IAM, egress, TLS and deployment evidence. |
| [GCP operator probes](../../ops/model-access-gcp-probes.md) | Project onboarding, effective IAM, source-preservation and TLS qualification cases. |
| [Operations design](../../ops/model-access.md) | Deployment, sizing, objectives, migration, failure recovery, cost, and release evidence. |
| [Implementation issues and dependencies](delivery.md) | Coding-sized work, milestones, hard blockers, and completion criteria. |
| [Example v1 policy](example-policy.v1.json) | Complete disabled, non-secret catalog with its canonical digest. |
| [Canonical JSON vector](canonical-json-v1-vector.json) | Exact UTF-8 canonical bytes and SHA-256 digest vector. |
| [Allocation vectors](weighted-rendezvous-v1-vectors.json) | Cross-implementation weighted-rendezvous inputs, ranks, and affinity namespaces. |
| [ADR-059](../../adr/059-range-model-access-broker.md) | Broker and authority decision. |
| [ADR-060](../../adr/060-model-access-allocation-accounting.md) | Allocation and mandatory accounting decision. |
| [ADR-061](../../adr/061-model-access-operations-qualification.md) | Revocation, operation, and qualification decision. |
| [Planned user experience](../../features/model-access.md) | What organizers, participants, and operators will see. |

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

- `shifter/engine/provisioner/gcp_range_vertex_creds.py` creates keys on a
  preconfigured service account and supports copying a shared source key.
  Separate secret/key objects are not separate principals.
- `plans/polaris_range_bootstrap.py` and `plans/_polaris_scripts_gcp.py`
  implement scenario-specific Vertex setup; the AWS sibling uses the
  per-range role path from #1377. Neither is a general allocation service.
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
- ADR-056's no-service-account guest default and ADR-057's existing GKE
  boundary apply. Model delivery must work without attaching a provider
  service account to participant-controlled VMs.

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

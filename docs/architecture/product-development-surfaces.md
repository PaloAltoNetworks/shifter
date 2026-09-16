# ADR-053: BigRAE surfaces: tenant/product and development

## Status

Accepted. Supersedes ADR-033 ("Product, distribution, and development
surfaces"). ADR-033 remains in the registry as historical evidence with
`status: superseded` and `superseded_by: ADR-053`.

## Date

2026-09-04

## Naming

This repository still uses `Shifter` in code, settings, infrastructure names,
and historical records. Per OpenRAE/hub#3, Shifter's target identity is
**BigRAE**, the organizational and SaaS backend. This note says
"BigRAE (currently named Shifter in this repository)" once here, then uses
BigRAE for the target product boundary and Shifter only for concrete current
identifiers. This ADR is not the product or repository rename.

## Context

ADR-033 separated Shifter into three surfaces: tenant/product, distribution, and
development. That framing predated the OpenRAE ecosystem split. Under
OpenRAE/hub#3, Shifter becomes BigRAE, the organizational and SaaS backend that
*consumes* RAES environment packs. Distribution is not BigRAE's concern:

- **RAES** owns semantics, contracts, and conformance.
- **Catalog** owns pack and reusable-asset discovery.
- **Environment Packs** owns the packs and their publication profile.
- **Hub** owns journey definition and cross-repository sequencing.

ADR-033's distribution plane gave the platform curated channels, published
platform artifacts, blessed environment-pack releases, promotion, and
replication. Those responsibilities belong upstream. Keeping them in a BigRAE
surface invited a marketplace, a catalog client, a pack downloader, an
entitlement system, and a signing or release service that BigRAE should never
own. Issue #1582 (operate distribution channels) was closed as misconceived, and
this ADR completes the correction that #1867 began.

The original two-way problem ADR-033 solved remains real and is retained here:
the mechanism that develops BigRAE must not be coupled to the environments it
deploys, and capabilities a bare operator tenant needs must not live only in
maintainer CI.

## Decision

BigRAE recognizes exactly **two** surfaces, and every capability is assigned to
one by a single test: **"does a bare operator tenant need this to run *or
extend* BigRAE?"**

1. **Tenant / product surface.** Everything an operator needs to run and extend
   BigRAE in their own account with zero maintainer infrastructure: install and
   bootstrap, run the platform, provision and destroy ranges, ingest content,
   extend the tenant's local registered-pack registry, use supported
   artifact-preparation capabilities, upgrade, and observe. Content ingestion and
   operator-facing artifact preparation live here.

2. **Development / engineering surface.** Everything that only concerns evolving
   BigRAE's own code: CI build and test, PR gating, maintainer environments, and
   the self-hosted runner fleet. Never shipped to operators, never required by
   them.

There is no third distribution surface. The following principles are binding:

- **BigRAE has no distribution plane.** It does not curate, bless, publish,
  promote, replicate, or operate distribution channels or a discovery catalog
  for environment packs or artifacts. Consuming an upstream-published pack,
  recording its immutable identity, checking whether a backend can realize it,
  or staging its content for one tenant does not make BigRAE a distributor. Pack
  semantics and conformance, discovery, packaging and publication, and
  cross-repository journeys stay with RAES, Catalog, Environment Packs, and Hub.
  A tenant's local registered-pack registry (the content an operator registers
  and can launch, optionally seeded by an in-box bootstrap seed consumed through
  the same uniform ingestion path) is a tenant/product concept, not a
  distribution or discovery catalog. (ADR-053-R2)

- **Shared capabilities are tenant/product-surface when operators need them.** A
  capability an operator needs, such as content ingestion or a supported
  artifact-preparation path, is productized rather than hidden in maintainer CI.
  Maintainers reuse that capability when it satisfies the same contract and
  policy. Dogfooding is a reuse preference, not authority to change a RAES
  requirement or proof that every consumed artifact is reproducible.
  (ADR-053-R1)

- **The CI runner fleet is development-surface and must not live in a
  product/operator deploy-target account.** The mechanism that deploys or bakes
  for an environment must never be a resource whose lifecycle is coupled to that
  environment. Operator install/bake provisions its own ephemeral compute inside
  the operator tenant; the maintainer runner fleet lives in maintainer/CI
  infrastructure, isolated from the environments it acts on. (ADR-053-R3)

  **Dev-tenant amendment (#1546).** The only deployments that exist today are
  maintainer-owned *dev tenants* (there is no product deployment model yet), and
  the current bootstrap is itself a dev-tenant deploy mechanism. For those dev
  tenants the binding invariant is **cross-tenant containment**: a GCP dev tenant
  must run its own CI/deploy rather than borrowing the AWS fleet, and neither dev
  tenant may assume the other exists. A self-contained per-tenant runner MAY live
  in that tenant's own project provided (a) it is a dedicated, re-creatable
  Terraform execution root whose state prefix is separate from the platform root,
  so a platform destroy never removes it, and (b) the deploy mechanism itself
  remains the repo's bootstrap CLI (`scripts/bootstrap`, `deploy.py runners`),
  not tenant-resident state. This preserves R3's rationale, that teardown never
  removes the deploy mechanism, because the mechanism lives in the repo and the
  runner is re-creatable by it. The GCP runner network isolation is enforced by
  ADR-008-R8. When a real product deployment model lands, product/operator
  deploy-targets revert to the original "maintainer-isolated or ephemeral"
  requirement.

- **Ingestion is entitlement-blind (see ADR-034).** Whether and how an operator
  is entitled to a piece of content is resolved at *acquisition*, outside the
  platform. The platform never contains an entitlement system. (ADR-053-R4)

- **BigRAE still owns its own software releases and provenance.** Publishing
  BigRAE's own software, provenance attestations (ADR-037), backend capability
  manifests, or cloud runtime state, and the release process owned by ADR-042,
  are distinct from distributing RAES environment packs. Owning your own release
  pipeline is not a pack distribution surface.

This ADR defines and enforces the surface boundary. The existing execution
programs run *under* it: RAES Backend (ADR-024), Backend Bundles & Substrate
(ADR-011, and the substrate-interface work in issue #1322), and Workspaces &
Platform API. Program tracking issue: #1584.

## Consequences

- Content ingestion and supported operator artifact-preparation capabilities
  work in a bare operator tenant; an operator is not promised an image builder
  for requirements that are exact, non-buildable, or satisfied by another
  backend mechanism.
- The maintainer runner fleet is relocated out of deploy-target accounts
  (#1437), so environments can be wiped and rebuilt without touching CI, and CI
  never spans one environment's teardown into another's outage.
- Pack discovery, publication, availability, and provider/location bindings are
  upstream facts owned by RAES, Catalog, Environment Packs, and Hub, separate
  from portable requirement semantics and from anything BigRAE operates.
- Maintainers reuse product ingestion and preparation capabilities where the
  same inputs, policy, timing, and output contract apply.
- This is a framing/policy ADR; it introduces no CI check of its own beyond the
  ADR registry `superseded_by` field. Downstream issues under #1584
  operationalize the boundary.

## Alternatives considered

- **Keep ADR-033's three-surface model and only soften the wording.** Rejected:
  the distribution plane is an ownership error, not a wording problem. Any
  BigRAE-owned distribution surface, however named, pulls marketplace,
  downloader, and entitlement responsibilities back into the backend.
- **Rename the distribution plane to a delivery, supply, channel, marketplace,
  or in-box-catalog plane.** Rejected: renaming keeps the misplaced ownership.
  BigRAE consumes upstream outputs through existing pack identity and
  registration seams; it does not operate a plane for them.
- **Treat every artifact as either pre-published or built in-tenant.** Rejected:
  RAES author intent may be exact, constrained, open, or absent. Backends may
  satisfy permitted requirements through an existing artifact, dynamic
  composition, an explicit preparation step, or another declared capability;
  acquisition transport and materialization are separate axes.

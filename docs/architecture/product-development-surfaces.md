# ADR-033: Product, distribution, and development surfaces

## Status

Accepted.

## Date

2026-07-11

## Context

Shifter is moving to OSS. Today there is no architectural distinction between
the pipeline that *develops* Shifter and the pipeline that *stands up and runs*
a Shifter environment. The maintainer CI/CD deploy path (GitHub Actions
reusable workflows on a persistent fleet of self-hosted runners that live inside
the deploy-target account, using the maintainers' GitHub org, OIDC federation,
and secrets) is also the only way an environment comes up.

That conflation has concrete failure modes:

- The deploy mechanism is a resource *inside* the thing it deploys. Tearing down
  an environment destroys the runners that would redeploy it, and those same
  runners serve other environments (a GCP teardown can strip the fleet that
  deploys AWS, and vice versa).
- There is no path for an external operator who does not have the maintainers'
  GitHub org, runner fleet, OIDC, or secrets.
- Capabilities that an operator genuinely needs, most sharply **image baking**,
  are implemented as maintainer-only CI constructs. Baking is not a
  development-only concern: operators must bake to extend their own catalog, and
  some shipped scenarios can never ship a pullable public image (licensed base
  images, private scenario content, per-tenant secrets, size) and are therefore
  bake-required in the operator's tenant. Baking is load-bearing product
  surface, not a maintainer convenience.

A clean split by "pipeline" is wrong in shape, because the most important
capabilities are dual-use. The split has to be by **surface**, classifying each
capability by whether a bare operator tenant needs it, and dual-use
capabilities must be productized once and dogfooded, not reimplemented
internally.

## Decision

Shifter recognizes three surfaces (planes), and every capability is assigned to
one by a single test: **"does a bare operator tenant need this to run *or
extend* Shifter?"**

1. **Tenant / product plane.** Everything an operator needs to run and extend
   Shifter in their own account with zero maintainer infrastructure: install and
   bootstrap, run the platform, provision and destroy ranges, **bake images and
   extend the catalog**, upgrade, and observe. Content ingestion and bake live
   here.

2. **Distribution plane.** The maintainer-to-public bridge that publishes the
   consumable artifacts: platform container images, blessed scenario
   packs/images (where they can be published), scenario content, and the
   installer. Its governing principle is that **content is the source of truth
   and a published image is a cache** of a bake; anything published can be
   rebuilt from source.

3. **Development / engineering plane.** Everything that only concerns evolving
   Shifter's own code: CI build and test, PR gating, maintainer environments,
   and the self-hosted runner fleet. Never shipped to operators, never required
   by them.

The following principles are binding:

- **Dual-use capabilities are product-plane and maintainer-dogfooded.** A
  capability an operator needs (baking, content ingestion) is built once as a
  tenant-plane capability, and maintainers produce the shipped/blessed artifacts
  by consuming that same capability. A maintainer-bespoke implementation of a
  product capability is the anti-pattern this ADR exists to prevent; divergence
  between the two is what produced the dev == deploy conflation.

- **The CI runner fleet is development-plane and must not live in a
  product/operator deploy-target account.** The mechanism that deploys or bakes
  for an environment must never be a resource whose lifecycle is coupled to that
  environment. Operator install/bake provisions its own ephemeral compute inside
  the operator tenant; the maintainer runner fleet lives in maintainer/CI
  infrastructure, isolated from the environments it acts on.

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
  not tenant-resident state. This preserves R2's rationale — teardown never
  removes the deploy mechanism — because the mechanism lives in the repo and the
  runner is re-creatable by it. The GCP runner network isolation is enforced by
  ADR-008-R8. When a real product deployment model lands, product/operator
  deploy-targets revert to the original "maintainer-isolated or ephemeral"
  requirement.

- **Ingestion is entitlement-blind (see ADR-034).** Whether and how an operator
  is entitled to a piece of content is resolved at *acquisition*, outside the
  platform. The platform never contains an entitlement system.

This ADR defines and enforces the surface boundary. The existing execution
programs run *under* it: ACES Backend (ADR-024), Backend Bundles & Substrate
(ADR-011, and the substrate-interface work in issue #1322), and Workspaces &
Platform API. Program tracking issue: #1584.

## Consequences

- Baking and content ingestion are first-class product capabilities that must
  work in a bare operator tenant; they are not deferred to a maintainer path.
- The maintainer runner fleet is relocated out of deploy-target accounts
  (#1437), so environments can be wiped and rebuilt without touching CI, and CI
  never spans one environment's teardown into another's outage.
- Distribution gains explicit public and private tiers whose entitlement is
  handled out-of-band, and container-first distribution is preferred because VM
  images (AMIs/GCP images/qcow2) are region/project-scoped and lean toward
  bake-in-tenant for the long tail.
- Maintainers accept a dogfood obligation: the blessed catalog is produced
  through the product bake/ingestion path, not a separate internal one.
- This is a framing/policy ADR; it introduces no CI check of its own yet.
  Downstream issues under #1584 operationalize it and may add enforceable rules
  in later ADRs.

## Alternatives considered

- **Keep one pipeline, document an operator path on top.** Rejected: leaves the
  deploy mechanism coupled to the environment and provides no productized bake
  or ingestion, so operators still cannot extend a tenant.
- **Treat baking as development-only and pre-publish every image.** Rejected:
  some shipped scenarios can never ship a public image, and operators must be
  able to bake their own content, so in-tenant bake is unavoidable product
  surface.

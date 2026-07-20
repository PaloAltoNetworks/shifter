# Range Single-AZ Placement

Scope: #959 (review finding NET-8). This document records the *existing*
single-availability-zone placement of the range VPC and all concurrent ranges,
its blast-radius and capacity rationale, and the explicit decision on whether
multi-AZ placement is warranted. ADR-021 records the binding decision; this
document is its rationale and live-model reference. The preflight artifact is
[range-isolation-placement-preflight-959.md](range-isolation-placement-preflight-959.md).

This is documentation of the current posture. It changes no Terraform, IAM, or
runtime behavior.

## Current state: everything lands in one AZ

The range VPC and every range placed in it are pinned to a single availability
zone: the first AZ the account exposes in the region.

- **Stable range VPC infrastructure** picks the AZ once:
  `local.primary_az = data.aws_availability_zones.available.names[0]`
  (`platform/terraform/modules/range/vpc/nat.tf`). The NAT subnet, firewall
  subnet, persistent-NGFW subnet, and SSM/Bedrock-endpoint subnet are all placed
  in `local.primary_az` (`nat.tf`, `firewall.tf`, `ngfw.tf`,
  `ssm-endpoints.tf`). The chosen AZ is published as the module's
  `availability_zone` output (`outputs.tf`).
- **The provisioner is bound to that AZ.** The stable output flows into the
  engine-provisioner as `RANGE_AVAILABILITY_ZONE`
  (`platform/terraform/modules/engine-provisioner/task_definition.tf`), read by
  `get_range_availability_zone` (`shifter/engine/provisioner/config.py`) and
  passed to the runtime module as `availability_zone`
  (`shifter/engine/provisioner/terraform_vars.py`).
- **Runtime range subnets and instances** are placed in `var.availability_zone`
  (`shifter/engine/provisioner/terraform/modules/range/main.tf`
  `aws_subnet.range`), so every subnet of every concurrent range shares the one
  AZ.
- **IAM enforces the AZ.** `ec2:RunInstances` is constrained with a condition
  `ec2:AvailabilityZone = var.range_availability_zone`
  (`platform/terraform/modules/engine-provisioner/iam.tf`), so the provisioner
  cannot launch range instances outside the chosen AZ even by accident.

## Rationale for single-AZ

Single-AZ placement is a deliberate cost-and-simplicity choice for ephemeral
training/exercise ranges:

- **Cost.** One NAT Gateway and one Network Firewall endpoint serve all ranges.
  Per-AZ NAT and firewall endpoints would multiply two of the most expensive
  fixed line items by the AZ count. Keeping all range traffic in one AZ also
  avoids inter-AZ data-transfer charges between range hosts, the firewall, and
  NAT.
- **Simplicity.** Routing, firewall endpoint mapping, and S3/SSM endpoint
  placement are single-target. There is no per-AZ route-target selection, no
  per-AZ firewall endpoint, and no AZ-aware subnet allocation to maintain.
- **Workload nature.** Ranges are short-lived and individually reprovisionable.
  The durable state that must survive (catalog, portal, user data) lives in the
  portal/platform tiers, which are independently multi-AZ; a range is cattle, not
  a pet.

## Trade-off accepted (blast radius and capacity)

- **Concentrated failure domain.** A single-AZ impairment takes out *all*
  concurrent ranges at once, plus the shared NAT/firewall path. There is no
  in-AZ redundancy for active ranges; recovery is reprovisioning in a healthy AZ,
  which today requires changing the pinned AZ.
- **Capacity ceiling.** Total concurrent range capacity is bounded by one AZ's
  limits: instance-type capacity in that AZ, subnet IP space, and ENI / NAT
  port limits. Scaling out cannot borrow capacity from sibling AZs.

These are the costs NET-8 flags. For the current scale and the ephemeral nature
of ranges they are acceptable; the durable platform is unaffected.

## Decision: defer multi-AZ

**Multi-AZ range placement is not warranted now.** The cost and complexity of
per-AZ NAT, per-AZ firewall endpoints, and AZ-aware placement outweigh the
availability benefit for ephemeral ranges whose recovery path is
reprovisioning. The decision is revisited if any of these change: ranges gain
long-lived state that cannot be reprovisioned cheaply; an availability SLO is
placed on individual active ranges; or one AZ's capacity becomes the binding
constraint on concurrent ranges.

## The seam a future multi-AZ change must use

If multi-AZ is later warranted, it must be introduced as an explicit placement
contract, **not** as an ad-hoc `multi_az` boolean or a stray
`data.aws_availability_zones` lookup in the runtime module:

- An environment-owned **ordered zone list** replacing the implicit
  `names[0]` pick, so the set of usable AZs is configuration, not discovery
  order.
- A **per-range placement selector** that assigns each range to an AZ from that
  list and feeds both the stable infrastructure and the runtime range module.
- A deterministic **per-subnet route target** per AZ (either a Network Firewall
  endpoint per AZ or another explicit egress target) so the default-deny egress
  model (ADR-020) holds in every AZ rather than hairpinning cross-AZ to a single
  endpoint.
- Matching updates to the `ec2:AvailabilityZone` IAM condition, NAT placement,
  and S3/SSM endpoint placement.

A bare boolean would hide routing, endpoint, IAM, and capacity semantics behind
one overloaded knob; the placement contract keeps them explicit.

## Evidence

| Concern | File |
| --- | --- |
| Stable AZ pick + NAT subnet | `platform/terraform/modules/range/vpc/nat.tf` |
| Firewall / NGFW / SSM-endpoint subnet placement | `platform/terraform/modules/range/vpc/{firewall,ngfw,ssm-endpoints}.tf` |
| AZ output | `platform/terraform/modules/range/vpc/outputs.tf` |
| Env binding (`RANGE_AVAILABILITY_ZONE`) | `platform/terraform/modules/engine-provisioner/task_definition.tf`, `shifter/engine/provisioner/config.py`, `terraform_vars.py` |
| Runtime subnet/instance placement | `shifter/engine/provisioner/terraform/modules/range/main.tf` |
| IAM AZ constraint | `platform/terraform/modules/engine-provisioner/iam.tf` |

## Non-goals

- No multi-AZ implementation, no change to AZ selection, NAT/firewall/endpoint
  placement, or the `ec2:AvailabilityZone` IAM condition.
- No change to the portal/platform tiers' own (independent) AZ posture.
- This document records the placement decision only; the egress isolation model
  is ADR-020 / [range-isolation-model.md](range-isolation-model.md).

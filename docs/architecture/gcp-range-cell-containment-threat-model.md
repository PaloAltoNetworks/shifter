# GCE range-cell containment threat model

Consolidated threat model for a compromised in-range adversary on the GCP GCE
range-cell substrate. It unifies the boundary analysis previously spread across
the #1345 and #1347 preflights and the AWS `range-isolation-model.md`, and
records the disposition of each escape and lateral-movement path. It is the
durable companion to ADR-056; it defines no new mechanism.

## Adversary model

The adversary controls a live-fire range guest: the attacker box, the AI agent
driving it, or a deliberately vulnerable target inside a range. The strongest
assumed position is root on a range VM, including root on a Docker host whose
participant workload runs in a container. The goal is to distinguish two
outcomes that are often conflated:

- **Guest-root activity.** Full control inside the provider VM boundary. This is
  expected for a live-fire range and is not, by itself, a containment failure.
- **Crossing the provider VM boundary.** Reaching another range cell, the
  management VPC or project, the metadata credential surface with useful scope,
  or provisioner-owned cloud resources. This is the boundary the range plane
  must hold.

Containment is proven by the absence of a usable management or cross-range
credential and by effective-permission tests from the strongest
participant-controlled context, not by hiding an endpoint from a root guest.

## Boundary dispositions

| Adversarial path | Control | Disposition |
| --- | --- | --- |
| Cell to peer cell | Per-range subnet and unique target tags; subnet-ingress allows only declared peer sources; egress internal is limited to the range's own subnet CIDRs; the shared range NAT bridges only explicitly listed subnets and never every subnet. A participant identity holds no Compute permission to retag or rewrite firewalls. | Closed. Proven against two simultaneously live ranges by the escape suite and the static plan-leak checker. |
| Cell to metadata server | Ordinary participant containers are blocked from `169.254.169.254` as defense in depth. A root guest can still reach the endpoint; the enforceable boundary is that the attached identity carries no management or cross-range capability. | Accepted with rationale. A root guest reaching the endpoint does not cross the VM boundary because the range identity is participant-bounded (ADR-056-R3). Any retained narrow, range-only capability is recorded as an explicit acceptance. |
| Cell to management VPC or project | Higher-precedence deny of the complete deployment-owned management, range, and private-service inventory sits above any allow lane; egress defaults to deny; the public-web and operator allow lanes are validated against the denied-network inventory so neither can name an internal destination. | Closed. Proven by cell to platform pod/service/node, Cloud SQL, Redis, portal, API, and peer-range denial probes. Routing or peering is not authorization. |
| Cell to provisioner resources | No provisioner credential, database credential, task payload, or cloud-management secret is placed in guest metadata, environment, argv, disks, or logs; the provisioner identity is never attached to a guest; bootstrap uses exact-object signed delivery with a per-range credential lifecycle. | Closed. The range host and range-Vertex service accounts are least-privilege and fail the IAM resource-scope checker if a project Storage or Secret role is added. |
| Cell to internet, DNS, or Google APIs | The effective egress mode is the single policy vocabulary: `none` creates no NAT and no general Google-API lane. Sanctioned public-web egress targets the public-internet complement of the denied-network inventory; the Google private-API VIP is reachable only through the Private Google Access lane when enabled. | Closed for the configured mode. DNS is a separately tested transport and is not inferred from a name-resolution failure. |
| Internet or participant to cell | The dedicated access-workload source allows only SSH 22 and RDP 3389; management ingress is SSH-only from the provisioner or management range; the OpenVPN gateway keeps a closed ingress and egress envelope. | Closed. Platform peering and provisioner source CIDRs are never turned into participant ingress. |

## Protocol and address-family coverage

- **IPv4.** Fully covered. Boundary CIDRs are validated as IPv4 and the
  denied-network inventory is expressed as IPv4 space, which subsumes every
  RFC1918 deployment range plus link-local metadata.
- **IPv6.** Not supported for range-cell boundaries. The firewall compiler
  rejects an IPv6 boundary CIDR rather than accept one it cannot enforce
  consistently. Range cells run on IPv4-only VPC networking; an IPv6 range plane
  is out of scope until a separate design covers it end to end.
- **TCP and UDP.** Internal same-cell allow and the default egress deny cover all
  protocols. Sanctioned lanes are protocol-scoped: management and access ingress
  are TCP (22, 3389, and the host management SSH port), public-web egress is TCP
  80 and 443, the Private Google Access lane is TCP 443, and the OpenVPN gateway
  ingress is UDP 1194 with a TCP 1195 health port. Any protocol outside a
  sanctioned lane falls to the default deny.

## Verification

Each closed boundary is proven by the versioned escape report
(`shared.range_escape`) run from participant and root-capable host context, plus
static mutated-plan tests over the rendered firewall. A boundary that cannot be
observed is recorded as skipped or indeterminate rather than assumed closed, and
a narrowly retained capability is recorded as an explicit acceptance. See
`docs/ops/range-escape-validation.md` for the runbook.

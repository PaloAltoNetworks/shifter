# Range Network Isolation Model

Scope: #959 (review finding NET-7). This document records the AWS range network
isolation model and blast-radius rationale. ADR-020 records the binding
decision; this document is its rationale and live-model reference. DNS
split-horizon containment (#1172) is implemented in
`platform/terraform/modules/range/vpc/dns_resolver.tf` and documented below.

The preflight artifact is
[range-isolation-placement-preflight-959.md](range-isolation-placement-preflight-959.md).
The configurable egress allowlist layered on top of this base is ADR-017 /
[range-egress-ip-allowlist.md](range-egress-ip-allowlist.md); this document does
not duplicate that contract. The DNS egress hardening preflight for issue #1172
is
[range-dns-egress-resolver-preflight-1172.md](range-dns-egress-resolver-preflight-1172.md).
The commercial self-serve zero-egress posture preflight for issue #1171 is
[range-zero-egress-preflight-1171.md](range-zero-egress-preflight-1171.md).

## Topology in one paragraph

All concurrent per-user ranges share **one** stable range VPC
(`platform/terraform/modules/range/vpc/`). Each range gets its own ephemeral
subnets carved from the VPC CIDR by the runtime provisioner module
(`shifter/engine/provisioner/terraform/modules/range/main.tf`). Internet-bound
traffic in the existing event posture flows **user subnet → AWS Network Firewall
→ NAT Gateway → IGW**. The firewall runs a STRICT_ORDER stateful policy whose
last rule drops all unmatched egress (default-deny). The optional commercial
self-serve zero-egress posture is different: runtime range subnet route tables
receive **no** `0.0.0.0/0` route, so there is no default-route path to Network
Firewall, NAT, or the IGW. Two layers therefore do different jobs, and the split
is the whole point of the design:

| Layer | Owns | Where |
| --- | --- | --- |
| Per-subnet security group | Local L4 **reachability** (ingress) | `modules/range/main.tf` `aws_security_group.subnet` |
| Route table + Network Firewall | Internet **egress** containment | `modules/range/vpc/firewall.tf`, runtime `aws_route.firewall` |

## Egress postures

| Posture | Route fact | Intended use |
| --- | --- | --- |
| `allowlist` | Runtime subnet route table has `0.0.0.0/0` to the Network Firewall endpoint; firewall forwards allowed traffic to NAT/IGW and drops unmatched egress. | Trusted event attendees and the existing range model. |
| `none` | Runtime subnet route table has no `0.0.0.0/0` route and no NAT/IGW target. | Commercial self-serve ranges with untrusted users, after runtime dependencies have moved to bake time or in-range services. |

The `none` posture is not the same as ADR-017 `deny-all`: `deny-all` is still a
firewall-enforced policy with a default route and exception lanes, while `none`
removes the default-route egress path. Existing private service endpoints (SSM,
STS, S3 gateway association, Bedrock, Route 53 Resolver) must be classified
explicitly for the commercial shape; leaving one reachable from participant
subnets is a design decision, not an incidental implementation detail.

## Security groups gate ingress, not egress

Each range subnet gets exactly one security group
(`aws_security_group.subnet`, one per subnet). Its rules are:

- **Intra-subnet ingress:** allow all protocols from the subnet's own CIDR.
- **Connected-peer ingress:** for each `connected_to` entry in the scenario
  topology, allow all protocols from the peer subnet's CIDR
  (`aws_security_group_rule.connected_subnet`). The comment notes the NGFW does
  the actual filtering between connected subnets when present.
- **Portal management ingress:** TCP 22 (SSH) and TCP 3389 (RDP) from the
  portal VPC CIDR only (`aws_security_group_rule.portal_ssh` /
  `portal_rdp`), reachable over VPC peering.
- **All egress:** protocol `-1`, `0.0.0.0/0` ("Allow all outbound traffic").

So the security group is an **ingress** allowlist: a range subnet accepts L4
traffic only from its own range (its subnet plus declared `connected_to` peers)
and from the portal's management ports. It deliberately does **not** restrict
egress.

### Why egress is left wide open

Security groups are stateful L4 (protocol/port/CIDR) filters. They cannot
express the controls the range actually needs on egress: TLS-SNI / HTTP-Host
domain allowlists, direct-IP-as-SNI rejection, or a default-deny that also
covers non-HTTP protocols. Encoding a partial IP-based egress allowlist in the
security group would be **redundant with, and weaker than**, the firewall, and
would split the egress policy across two control planes. The design therefore
makes the AWS Network Firewall the single egress control plane and leaves the
security group egress open. **The all-egress security group is safe only
because** every range route table sends `0.0.0.0/0` to the firewall endpoint and
the firewall's final rule drops everything not explicitly allowlisted.

## The Network Firewall default-deny is the egress control plane

The stable range VPC pins user-subnet egress to the firewall and the firewall
enforces default-deny:

- **Routing:** the private route table sends user-subnet `0.0.0.0/0` to the
  firewall endpoint (`firewall.tf` `aws_route.private_to_firewall`); the runtime
  module attaches each range subnet to a route table whose `0.0.0.0/0` target is
  the firewall endpoint (`main.tf` `aws_route.firewall`, gated on
  `var.firewall_endpoint_id`). The firewall subnet routes onward to NAT, and NAT
  to the IGW.
- **Policy (STRICT_ORDER, lower priority evaluated first):** NGFW-subnet bypass
  (priority 1, only with persistent NGFW infrastructure); victim IP allowlist on
  TCP 443 to PANW/GCP CIDRs (chunked); victim domain SNI/Host allowlist; optional
  Kali domain allowlist; NTP (priority 98); and **`drop ip $HOME_NET any ->
  $EXTERNAL_NET any` at priority 100, dropping all unmatched egress** across
  all protocols and ports. There is **no** Network Firewall allow rule for
  UDP/TCP 53 to public recursive resolvers (the former `8.8.8.8:53` lane).
  A separate stateful rule rejects TLS connections whose SNI is a literal IP
  address, so the domain allowlist cannot be bypassed by dialing an IP directly.
- The default SG of the range VPC is adopted and stripped to deny-all
  (`modules/range/vpc/main.tf` `aws_default_security_group.this`) so no workload
  can fall back to a permissive default.

### DNS containment (split-horizon resolver)

Range hosts use **AmazonProvidedDNS** (the VPC CIDR base + 2 address), set via
VPC DHCP options (`modules/range/vpc/dns_resolver.tf`). Name resolution is
filtered by **Route 53 Resolver DNS Firewall** before any external recursive
lookup can succeed:

- **ALLOW** suffixes required for the exercise (`victim_allowed_domains`) and
  bootstrap/service names (`range_dns_allowed_domains`, default `.amazonaws.com`
  for SSM/VPCE).
- **BLOCK** all other names (`NODATA` response).

Direct UDP/TCP 53 egress to public resolvers is not allowlisted in the Network
Firewall policy, so a host cannot bypass the split-horizon resolver by dialing
`8.8.8.8:53` (or any other public resolver). Resolver query logs land in
CloudWatch with the same KMS/retention conventions as firewall logs.

Issue #1172 tracks this posture; the preflight rationale is in
[range-dns-egress-resolver-preflight-1172.md](range-dns-egress-resolver-preflight-1172.md).

## Cross-range and participant isolation

Because all ranges share one VPC, the VPC's implicit local route makes every
range subnet CIDR reachable at the IP layer. Isolation is the composition of the
two layers above:

- **Lateral (within the shared VPC):** a range subnet's security group admits
  ingress only from its own range (own CIDR + `connected_to` peers) and the
  portal's management ports. Another range's subnet CIDR is **not** in that
  ingress allowlist, so a host in range A cannot open L4 connections into range
  B. Security-group *ingress* is what segments ranges from each other locally.
- **Internet (egress / exfiltration / C2):** a compromised range host has open
  security-group egress, but the route-table-to-firewall path plus the
  default-deny means it can only reach the narrow allowlisted destinations
  (victim XDR/XSIAM endpoints, NTP). DNS queries use the in-VPC split-horizon
  resolver; unknown external names are blocked at the Route 53 Resolver DNS
  Firewall layer and direct public-recursive `*:53` egress is dropped. It cannot
  open arbitrary internet TCP or UDP connections. **This internet containment
  relies on the Network Firewall default-deny plus the split-horizon DNS policy,
  not on security groups.**

That division is the finding NET-7 documents: security groups own local
reachability; the firewall owns internet egress. Neither layer provides VPC-level
isolation between ranges, and the design does not claim it does: ranges are
co-tenant subnets in one VPC by deliberate choice (see the single-AZ placement
decision, ADR-021 / [range-single-az-placement.md](range-single-az-placement.md)).

## Blast radius

- A compromise contained to one range instance cannot reach another range's
  hosts (target security-group ingress denies it) and cannot reach the internet
  except through the firewall's allowlisted lanes (default-deny drops the rest).
- The failure mode that would widen the blast radius is loss of the firewall
  egress path, because the security groups would then impose no egress limit at
  all. That is exactly the NAT-bypass hazard below.

## The `enable_network_firewall = false` NAT-bypass hazard

When `enable_network_firewall = false`, the private route table's `0.0.0.0/0`
target becomes the NAT Gateway directly (`firewall.tf`
`aws_route.private_to_nat`) and the runtime module's firewall route is not
created (it is gated on a non-empty `firewall_endpoint_id`). In that mode there
is **no default-deny**: the all-egress security groups now allow unrestricted
outbound internet access from every range host. This is acceptable only as an
explicit, dev-only opt-out. Making the firewall optional in any production
profile is a security-posture change that requires its own ADR and guardrail; it
is out of scope for this documentation issue.

## Evidence

| Concern | File |
| --- | --- |
| Per-subnet SG (all egress, ingress allowlist) | `shifter/engine/provisioner/terraform/modules/range/main.tf` |
| Default SG lockdown | `platform/terraform/modules/range/vpc/main.tf` |
| Firewall policy, default-deny, IP-SNI reject, routing | `platform/terraform/modules/range/vpc/firewall.tf` |
| Split-horizon DNS, DHCP, resolver query logs | `platform/terraform/modules/range/vpc/dns_resolver.tf` |
| NAT path | `platform/terraform/modules/range/vpc/nat.tf` |
| Configurable egress allowlist (layered on this base) | ADR-017, `docs/architecture/range-egress-ip-allowlist.md` |

## Non-goals

- No change to security groups, firewall policy, routing, NAT, or the
  `enable_network_firewall` default.
- No claim that security groups enforce cross-range internet isolation, and no
  claim that all-egress security groups are safe independent of the route-table
  and default-deny dependency.
- No multi-VPC-per-range redesign; that is a placement question handled by
  ADR-021.
- This document does not restate the ADR-017 egress allowlist contract; it
  documents the base posture that contract configures.

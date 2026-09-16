# ADR-059: Range model and tool access crosses a deployment-owned broker

## Status

Proposed for [#681](https://github.com/Brad-Edwards/shifter/issues/681),
PLAT-202, 2026-09-06. This is an implementation decision for review; it does
not advertise an installed capability or qualified provider.

## Context

Participant root must be an assumed adversary under ADR-056. The existing
Polaris model setup selects provider scripts and can place Vertex service
account keys in the guest. Multiple keys on one service account authenticate
the same principal. That cannot enforce independent range authorization,
spend ceilings, or immediate application revocation. Direct short-lived
provider tokens also permit calls that bypass application budgets.

The deployment is one customer authority under ADR-054. CTF, CMS, Engine,
RAES integration, provisioner, and provider adapters already have owners;
model access must preserve them.

## Decision

Introduce a narrow, separately deployed model-access broker in the existing
Helm package. The broker is the only participant-facing inference/tool entry
point with provider identity. Engine owns policy resolution, allocation,
grant and request accounting through service boundaries and PostgreSQL.
Shared wire and policy types live in native `shared`; only `shared.raes`
interprets released scenario contracts. A scenario asks for a logical
capability; it cannot supply credentials, provider coordinates, code, URLs,
or control-plane authority.

Use deployment-local opaque capabilities bound to the immutable deployment,
range, existing execution generation, admitted subject, policy revision,
and deadline. Every invocation is authorized and reserved online. Participant
capabilities never authorize the portal API, enrollment of another range,
cloud APIs, or privileged operator MCP. Broker provider credentials never
enter participant-controlled memory, images, metadata, disks, or responses.

GCP/Vertex is the first qualification target. Use Workload Identity and
deployment-owned, invocation-only service accounts in approved model
projects. A bounded catalog can allocate across projects and models without
creating projects or service accounts per range. Separate model projects,
compute targets, dynamic-secret storage, and the platform project even where
some configured IDs coincide. The model broker does not replace #1586's
dedicated dynamic-secret project design.

The broker has a dedicated private TLS listener reachable through an exact
range egress capability. It has no public portal routes or generic forward
proxy. Its control API uses authenticated workload identity and narrow
Engine service operations. Provider destinations, methods, model IDs,
protocol versions, and approved billing features come from validated
deployment configuration. Model tool-use content is untrusted data, never
permission to execute a tool. External tools require their own catalog
entry and grant. The detailed contracts are in the
[architecture](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/architecture.md) and
[threat model](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/security.md).

## Alternatives

| Alternative | Disposition |
| --- | --- |
| Provider keys delivered directly to guests, including per-range keys on a shared principal | Reject direct guest authority: application enforcement is bypassable. Sharing a broker-held provider identity remains supported under ADR-060. |
| Per-range provider principal with direct tokens | Useful defense for legacy access, but insufficient for mandatory request/spend enforcement outside the broker. |
| A gateway product as the authority and billing database | Reject a second authority. A future transport library may be adopted after protocol, dependency, and security review; it cannot own grants or budgets. |
| In-process proxy on the public portal listener | Reject: streaming load and participant HTTP parsing enlarge the portal exposure and failure domain. |
| Mandatory service mesh | Not selected. Dedicated TLS and authenticated service calls satisfy this seam; ADR-057 remains in force. |

## Consequences and evidence

The broker becomes a trusted prompt-processing component and a new available
service to operate. Its compromise can consume its approved provider shards;
it cannot be made harmless by a range ID claim. Limit its IAM, network reach,
routes, software, and shard inventory; qualify the effective boundaries.
Provider retention and billing remain external constraints.

Existing direct credential paths remain cleanup compatibility paths during
migration. They cannot satisfy this ADR or be an outage fallback. AWS and
other adapters need independent qualification; a provider-neutral interface
is not parity evidence. Delivery and proof owners are listed in the
[implementation backlog](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/delivery.md).

Registry checks validate documentation structure and existing import rules.
They do not prove this proposed runtime boundary.

The [M06 GCP packaging preflight](../architecture/model-access/gcp-packaging-preflight-2123.md)
records the repository integration gates for broker-only runtime inventory,
effective NetworkPolicy isolation, exact-target IAM, explicit range egress
and the real deployment/provenance path. These apply this decision without
adopting its runtime status or claiming deployed enforcement.

The M06 range-spec and RAES plan builders consume an explicitly admitted broker
capability and bind it to the deployment VIP before rendering firewalls.
Their integration tests verify the exact exception and incompatible-posture
rejections. M08 owns production enrollment and operation projection; M05 owns
the listener call to the transport-peer binding contract. Installing the
package alone establishes neither enrollment nor peer authentication.

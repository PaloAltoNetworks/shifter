# ADR-059: Range model and tool access crosses a deployment-owned broker

## Status

**Superseded by [ADR-068](068-model-access-broker-parked.md) (2026-10-05):** the broker is parked and not supported for use; keyless-direct (ADR-064) is the only live model path. This record is kept as history of the parked implementation.

Proposed for [#681](https://github.com/Brad-Edwards/shifter/issues/681),
PLAT-202, 2026-09-06. This is an implementation decision for review; it does
not advertise an installed capability or qualified provider.

The "no-service-account guest default" for GCP (ADR-059-R3) is superseded by
[ADR-064](064-default-range-model-access.md): range guests receive a keyless,
predict-only Vertex model identity by default, or stay identity-less when the
broker is the guest model path. The rest of this ADR (the broker, its
ownership, allocation, accounting and enforcement) is unaffected.

## Context

Participant root must be an assumed adversary under ADR-056. The existing
The retired embedded model setup selected provider scripts and could place Vertex service
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

For #2243, the platform GCP project is an explicitly valid Vertex source;
another project/account is optional. Broker and invocation principals remain
distinct with exact-target permissions even when their project IDs coincide.
Authorized tenant administrators manage source and write-only credential
references within the deployment envelope. CMS composes live tenancy authority
through the Workspaces facade; Engine owns immutable source storage, revision
fences, allocation, and accounting. Tenant organization administrators may
administer range model policy without a workspace seat through the narrowly
scoped model-source authorization service; this confers no guest access or
other workspace operation. Organization and workspace authority revisions are
retained in sponsored grants. Source registration does not itself confer source-use or spending
authority. Provider/authentication selection is independent of compute hosting;
live edits require revision checks, grant fencing and retained accounting under
ADR-060. The [source-management preflight](../architecture/model-access/source-management-preflight-2243.md)
records the incumbent validators and integration gaps. This clarifies intended
architecture; current packaging restrictions remain until implementation and
qualification, and no provider parity is asserted.

The broker has a dedicated private TLS listener reachable through an exact
range egress capability. Broker and control listeners bind the explicit private
pod IPv4 address injected by the Kubernetes Downward API, rejecting missing,
wildcard, public, loopback and link-local addresses. TLS, workload authentication
and default-deny NetworkPolicies still enforce the service boundary.
It has no public portal routes or generic forward
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
| Per-range provider principal with direct tokens | Revived, keyless, as the default-on baseline under [ADR-064](064-default-range-model-access.md) (Workload Identity, no key material); still insufficient for mandatory request/spend enforcement, which is why the broker remains and is mutually exclusive with it per range. |
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

The [M05 broker preflight](../architecture/model-access/broker-preflight-2122.md)
applies this boundary to the existing listeners, shared contracts, Engine
credentials/accounting and deployment validators. It records gaps in bounded
stream cleanup, credential abuse controls, workload-identity claim binding,
safe startup diagnostics and drain/readiness evidence. It introduces no new
authority or implementation claim; ADR-064's direct posture is not a fallback
for a range requiring broker enforcement.

The [M05 runtime](../architecture/model-access/broker-runtime.md) applies these
findings through bounded headers/bodies, closed control replies, immutable GCP
subject IDs, locked credential rotation budgets, isolated synchronous control
capacity and database waits, immediate upstream cancellation and signal drain.
Transport diagnostics are suppressed at their namespace boundary; startup errors
never serialize rejected configuration. Real local TLS and PostgreSQL tests
exercise the boundary alongside import enforcement. These are local proofs, not
the live IAM/network/load evidence required to adopt this ADR's support claims.

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

GCP deployment activation is branch-owned: a reviewed per-environment model
overlay supplies non-secret policy and endpoint intent, while the workflow
establishes or verifies versioned TLS Secrets and seals the catalog against the
deployment project. The same overlay is used for Terraform and workload
rendering. The compatibility renderer must project the catalog reference into
the application runtime and mount that catalog in runtime consumers before
enabling access. Direct cluster patches or a render-only check are not
qualification evidence.

The [AWS packaging contract](../architecture/model-access/aws-packaging.md)
applies the same broker boundary to EKS: exact-subject IRSA, separate regional
invocation roles, direct range peering, private DNS and TLS passthrough with
preserved client IPs, and exact private STS/Bedrock endpoint egress. The shared
guest role loses direct Bedrock authority. Terraform/Helm and offline tests do
not establish live provider parity; AWS and GCP require separate qualification.

GCP deployment retirement also removes the legacy guest invocation service
account, its broad model role, provisioner key-admin/act-as grants, static shared
provider-key references and direct-model runtime configuration. Teardown retains
deletion of range-owned legacy Secret Manager copies without reading their
payloads or retaining provider IAM. Externally managed shared keys require
owner revocation during migration; deleting a stored copy does not revoke a key.

[ADR-064](064-default-range-model-access.md) later restores a default-on,
keyless range model identity (a predict-only Vertex role attached via Workload
Identity, with no key material and no key-admin grant). The key retirement above
therefore stands: reachability returns without reintroducing guest-held keys.

The runtime enrollment path carries the deployment-verified private broker VIP
through the provisioner environment allowlist into the RAES firewall capability.
A missing destination fails before guest mutation. Teardown and residual
inventory retain the optional firewall identity independently of current
enablement; disabling broker configuration cannot hide an existing rule.

## Tenant source publication and provider egress (#2243)

Tenant source management uses an immutable v4 allocation overlay over the verified
v3 deployment catalog, preserving incumbent sharing, budgets and provider-pool
authority. Credentials stay in owned cloud secret versions and ephemeral private
control replies. Source publication and retirement recheck tenant authority;
range policy changes retain execution identity, hard expiry and old liabilities.

The provider egress proxy has no workload identity or platform configuration.
It admits fixed HTTPS provider/identity origins, pins public DNS answers, and
permits only exact configured AWS private endpoint CIDRs as exceptions. Broker
and proxy remain excluded from additive generic private-service policies.
See [source management](../architecture/model-access/source-management.md) for
implementation and qualification limits.

The workload IAM guard accepts model-source credential reads only for the control
worker, in the platform project, under the exact `shifter-model-source-` secret
namespace condition. Changed principals, projects, roles or conditions remain
rejected; tenant source registration does not grant general secret access.

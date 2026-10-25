# Model-access security design

Proposed security contract for [#681](index.md), ADR-059 through ADR-061.
This document defines required tests; it does not assert that they have run.

## Assets, adversaries and trust boundaries

Protect provider invocation identity and budget, other ranges' capabilities,
control-plane authority, scenario/participant data, accounting integrity and
revocation evidence. Treat participant root, all client headers and payloads,
scenario text, model output, tool output and stolen participant credentials
as hostile. A root guest can bypass in-guest firewall and client settings.
Provider services, IAM propagation and network delivery can fail independently.

Trusted computing base: deployment bootstrap/IAM, Engine and PostgreSQL,
broker and its protocol libraries, private TLS configuration, provider
credential issuance and the existing provisioner bootstrap transport. A
compromised broker can use the provider identities it holds outside Engine's
accounting. Mandatory budgets protect against participant misuse through the
broker; they do not prove containment of that broker compromise. Limit that
residual blast radius with deployment isolation, shard inventory, narrow
IAM, provider caps, egress controls, monitoring and emergency identity disable.

Model and broker integrity are outside the scenario world under ADR-058.
An exercise may simulate a credential or cloud API inside a range, but that
does not authorize access to Shifter's real IAM, broker or control plane.
Prompt injection is not mitigated by believing a model's instructions; the
model never receives a management principal or permission to choose a tool
destination.

## Identity and IAM matrix

| Principal | Allowed | Required negative proof |
| --- | --- | --- |
| Participant/root guest | Its active broker grant and exact declared range capabilities; default no attached GCE service account. | No platform/peer secret reads, IAM/Compute/Kubernetes action, service-account token minting, foreign grant or direct platform-funded model invocation. |
| Provisioner | Existing operation-scoped bootstrap; issue enrollment only for its bound pending range/generation; generation-bound temporary secret lifecycle through #2083. | No model invocation role or provider-key creation on the broker path; no arbitrary grant/subject enrollment, budget change or direct Engine ORM. |
| Broker KSA/GSA | Invoke approved provider shards via explicit identity references; authenticate only narrow Engine control operations. | No deployment-wide secret read, project creation, IAM policy/key administration, range mutation, public operator API or arbitrary impersonation. |
| Model shard GSA | Approved invocation/count operations in one approved project; explicit additional permissions only when proven necessary. | No service-account key administration, IAM/Compute, platform secrets/storage, training, endpoint deployment or unrelated project authority. |
| Portal/Engine workload | Its incumbent database and application authority; grant/accounting services and restricted temporary enrollment issuance. | No new provider invocation or cross-project token-creator rights merely because the broker needs them. |
| Deployment operator | Catalog/ceiling/identity configuration, shard drain and emergency revoke under existing audited operator authority. | Organizer/workspace membership alone cannot obtain these permissions. |
| Event organizer | Native event authority, allowed profile selection, reduced delegated limits, access status and revoke within that event. | No foreign event data, new provider identity/model/region, ceiling expansion or platform MCP access. |

GCP uses Workload Identity Federation for GKE, with separate KSA/GSA identity
for the broker. Cross-project invocation either binds the exact broker
principal to a minimal invocation role or uses service-account impersonation
on a closed target list. Select impersonation for v1 so each shard has a
separate auditable GSA; token creation is granted on each exact target GSA,
not the project. Validate the supported Google permissions at implementation
time; start with `aiplatform.endpoints.predict` and add only operations the
chosen count/invocation API proves necessary. Do not default to
`roles/aiplatform.user` or assume publisher-model IAM conditions support
resource-level model filtering. Broker alias/route enforcement is mandatory
where IAM cannot constrain a specific publisher model.

Model projects/accounts have explicit tenant/deployment access and billing
ownership and are not dynamically created per range. Under
[#2243](source-management-preflight-2243.md), a dedicated model project is
optional: Vertex may use the platform project. Broker and invocation identities
remain distinct, and effective IAM must deny invocation principals access to
platform data and unrelated resources even when they reside in the same
project. Check inherited grants, not only the newly authored bindings. Quota
pools may be shared by approved shards without merging range grants. Tenant
source registration requires organization authority; source-use/spending
eligibility is separately enforced. One customer's broker never receives
another deployment's workload identity.

The #1586 dedicated range-secret project remains the boundary for ephemeral
guest/bootstrap material. Broker provider identity is keyless on GCP. It does
not need per-range Google keys or copied shared-key secrets. Follow-on direct
API credentials, if unavoidable, live in exact named broker-only secrets in
the deployment's runtime secret authority, with rotation and metadata-only
administrative verification; never in a range-readable secret family or browser
readback. Secret values are resolved only at the authorized broker boundary.
Do not conflate these projects.

Google documents that a service account has a limited number of keys and
that deleting a key does not invalidate tokens already issued from it.
This is why adding keys is neither an identity-sharding strategy nor an
immediate revoke mechanism. See
[Google service-account key lifecycle](https://docs.cloud.google.com/iam/docs/keys-create-delete).

## Sharing authority and isolation

Sharing a broker-held provider identity, model assignment or budget pool
does not merge range grants or give members authority over each other.
The [sharing contract](sharing.md) supports selected sets, events/cohorts,
users, typed groups, named collections and all ranges in one deployment.
Require canonical IDs and authority over the complete selected collection;
an organizer's authority cannot spill into another event. All-ranges access
is operator-only and never crosses the customer/deployment boundary.

Group membership controls applicability, not publishing authority or funded
eligibility by itself. Self-service groups require separate approved spending
eligibility. All matching hard restrictions/accounts apply; priority cannot
bypass a cap. Unknown membership denies. Owner/group changes synchronously
invalidate the checked membership revision, including for large collections;
background reassessment cannot leave stale grants usable. Snapshot inclusion
does not preserve access after authorization is lost.

The M20 implementation makes the checked revision a deployment-scoped Engine
row keyed by the complete owner-qualified authority reference. Owner mutation
transactions advance it synchronously; effective-policy resolution checks both
selector and exact subject fences, including for snapshots. Publisher evidence
is server-derived and publication verifies every atomic authority in a selected
set or named union. Every auth-group atom in a funded selector independently
requires managed-membership or approved-spending evidence; eligibility for one
group cannot authorize another. Real PostgreSQL tests exercise owner-lock versus
removal ordering, bounded bulk invalidation, owner transfer and failed publish/
retry rollback, plus projection-refresh overlap with publication and drain under
the canonical projection-before-fence lock order. Automatic range assessment is
keyset-paged and records the complete assessed population count, so deployment
growth cannot silently truncate an all-ranges, user or workspace selector.

Shared-only budgets deliberately allow a member to consume the remaining
pool; show that consequence and offer individual spend/rate/concurrency caps.
Do not claim fair allocation without such a policy. Limit roster and usage
views to authorized subjects; use suppressed small-cohort aggregates where
individual contributions could otherwise be inferred. Shared balances alone
must not authorize unrestricted per-member attribution.

## Participant credential and network binding

Opaque credentials identify an Engine-owned grant; request fields cannot
override deployment, range, subject, generation, policy or shard. Hash
credential bytes at rest and use constant-time verification with bounded
lookup. Reject duplicate or conflicting authentication headers; never log
the rejected bytes. Enrollment/access/refresh endpoints are rate limited
before and after authentication to protect the database from guessing and
enrollment floods.

Enrollment is a one-use, short-lived bootstrap capability, delivered only
through the already authenticated provisioner-to-guest path after the
immutable allocation exists. It cannot request a different binding.
Refresh rotates atomically, expires with the grant, and rechecks current
authority. The helper's files are private and memory-backed; root can read
them, so confidentiality from root is not a claimed control. Image baking,
snapshots, support bundles and crash dumps must exclude these runtime files.
Restored guest disks are never sufficient to renew a revoked grant.

The GCP ingress design selects a dedicated internal passthrough load balancer
with TLS terminated by the broker listener and source-preserving backend
routing (`externalTrafficPolicy: Local` or its supported equivalent). The
provider-observed source must fall within the exact admitted range subnet
bound to the grant. Deny source mismatch even for a valid token. Use the
transport peer, never client `X-Forwarded-For`, for this check. GCE source
spoofing/IP forwarding must be disabled on this path and tested from root.
If the deployed LB/CNI path cannot prove source preservation, it is not
qualified: choose and document an authenticated ingress binding before
cohort release, rather than trusting a supplied header.

This prevents accidental credential reuse and a stolen token used directly
from another range/network. It cannot prevent an authorized root guest from
relaying requests for a collaborator through its own admitted subnet. That
traffic consumes the original grant's budget and lifetime. Neither bearer
tokens nor client certificates prove which human wrote a prompt.

## Required network paths

| Source → destination | Realization and constraint |
| --- | --- |
| Admitted range → broker VIP:443 | Exact VIP/port capability and provider firewall rules ahead of the broader management deny; restricted to enrolled range subnets. Dedicated listener exposes only the routes in the architecture contract. No broad pod/node/management CIDR allow. |
| Broker → Engine private control listener | TLS, exact hostname/audience and workload identity; NetworkPolicy only between these workloads. No public ingress route to the private control API. |
| Broker → selected provider/credential APIs | Fixed adapter origins and routes, verified TLS, controlled DNS and explicit egress. Allow the exact IAM token-service dependency required by impersonation. |
| Broker → DNS, telemetry | Existing controlled resolver and metadata-only telemetry paths. No arbitrary destination in a prompt, tool argument or metric label. |
| Bootstrap → range | Existing provisioner guest transport and its firewall/IAM scope; no new inbound participant path to provisioner Jobs. |

The private broker VIP is a new explicit capability in the provider-neutral
egress vocabulary and GCE renderer. It is not a general exception to
ADR-056's management deny. Test rule priority, peering, routes, load balancer
health-check reachability, backend pod/node paths and other ranges.
Keep `canIpForward` off for participating model clients. A gateway/NGFW with
forwarding authority requires a separately qualified source-binding design.

A strict zero-egress profile cannot transmit prompts to an external model
through a broker and still claim no external effects. Reject required external
model access with that profile. A separately declared model-broker capability
can permit only this effect; label it accurately and test it alongside
#2041's negative probes. Do not add blanket Google API or public-internet
egress to guests to make model bootstrap succeed.

Outbound SSRF defense is layered: catalog-selected scheme/host/port/path,
closed methods and headers, DNS/address validation and deployment egress
policy. Reject redirects, userinfo, IP-literal destinations, alternate
schemes, encoded path traversal, duplicate authority/Host fields, CONNECT,
webhooks and remote content fetches. Provider paths are constructed from
validated configuration, never copied from a client URL. Validate every
resolved address at connection time, including IPv6/mapped forms; DNS
rebinding cannot turn an approved host into metadata, loopback, private
control or peer-range access. Designated private provider VIPs are explicit
deployment entries, not a general exemption for private addresses.

## Threat-to-control-to-test mapping

| Threat | Control | Required evidence |
| --- | --- | --- |
| Root extracts provider credential from metadata, env or bootstrap | No provider credential/SA in the guest; broker-only workload identity. | Root-context metadata, filesystem, process and cloud permission probes with a successful narrow broker call as positive control. |
| Cross-range/deployment token substitution | Server-side grant tuple, current epoch/authority and source-subnet check. | Two live ranges and a foreign deployment fixture; swap every identity field, token and source. |
| Group join or overlap widens access/spend | Canonical selectors, publisher and spending eligibility, intersected restrictions, distinct account set and explicit choice conflicts. | Self-service join, foreign-event/all-ranges publication, tied priorities and overlapping group/event bindings; no authority gain or double charge. |
| Membership change leaves shared access alive | Synchronous membership-revision fence, new admission/epoch, original liability references. | Race invoke/refresh against removal, owner transfer and bulk invalidation; old grants fail while unaffected members continue on the same shared provider identity. |
| Prompt injection requests admin MCP, cloud tool or arbitrary URL | Model output is data; independent tool grant and closed route adapter; network/IAM deny. | Adversarial prompt/tool fixtures and actual network probes; no privileged effect. |
| Unbounded subagents or duplicate billing | Atomic parent/range budget and rate/concurrency admission; no automatic ambiguous replay. | Real PostgreSQL contention and many independent broker processes; limits never exceeded. |
| Stream continues after pause/reset/revoke | Online leases, deadline and grant epoch; cancellation fence. | Revoke during stream across multiple replicas, drop control connectivity, measure last delivery and attempted provider dispatch. |
| Stale cleanup deletes successor credential | Original full references and generation/epoch compare; idempotent cleanup. | Old-generation destroy/result arrival after new enrollment; successor remains usable. |
| Quota amplification through aliases/accounts | Shared real quota-pool identity; durable allocation. | Two aliases/GSAs sharing a pool cannot reserve its capacity twice; independent projects can allocate independently. |
| Sharing creates duplicate commitments or erases spend | One shared commitment with child draws, deduplicated request-account vector and retained original liabilities. | Concurrent first use, same pool through multiple selectors, pool migration with unknown requests; no overcommit, duplicate charge or refund. |
| Cost evasion via caches, multimodal payload, tool charges or price drift | Closed billing feature set, conservative upper bounds, expiring price revisions. | Boundary/unsupported feature vectors, unknown usage, manipulated usage fields and expired prices. |
| Parser/smuggling/slow-stream denial of service | Bounded headers, compressed and decompressed bytes, JSON depth, connections, timeouts and buffers. | Malformed lengths, duplicate JSON keys, compression bombs, slow consumers and partial SSE. |
| Data leaks through provider errors or observability | Safe error mapping and allowlisted metadata-only audit/log/trace fields. | Synthetic sentinel in prompts, responses, headers, tool fields and provider failures; absent from every telemetry/support/evidence sink. |
| Broker identity reaches control-plane administration | Dedicated service identity, route allowlist, no broad IAM/DB rights. | Invoke control endpoints with participant/foreign workload identities; broker attempts forbidden API/IAM operations. |
| Backup resurrects grant or repeats dispatch | Admission disabled after restore; fresh epoch, reconciliation and no blind replay. | Restore with active/unknown requests and stolen pre-restore tokens; old tokens fail and no second provider call occurs. |

## Revocation, privacy and residual risk

Application revoke has two observable phases: the Engine transaction blocks
new admission immediately; transport fencing completes within the ten-second
qualification target. A caller receives `revoking` until all dispatch leases
are fenced or expired. Returning success for a database update is not proof
of transport cancellation. Already accepted provider execution may remain
billable; use conservative reservations and an explicit provider outcome.

For a legacy leaked Google key, deleting the range secret or key alone is
insufficient. Inventory every consumer of the shared GSA, drain the cohort,
disable the affected identity or remove its invocation authority, and measure
denial with a previously minted token. Preserve residual evidence and account
for propagation. New broker grants revoke independently without disabling
the shared shard principal; a broker/shard credential compromise still
requires provider-side action with a wider blast radius.

Prompts and tool content are processed transiently in broker and provider
memory. Disable HTTP body logging, request/response tracing, payload sampling,
prompt caches at the broker, diagnostic dumps and unbounded exception text.
Do not persist prompts for idempotency. The restricted, expiring keyed intent
fingerprint described in the architecture is the only content-derived retry
record. Audit includes authenticated subject references, allocation/policy
revision, safe alias/shard identifier, request correlation, units, outcomes
and reason codes. Untrusted client session/agent IDs are neither authority
nor unrestricted metric dimensions.

Provider-specific retention, abuse monitoring, region processing and data-use
terms are verified before a shard is enabled, with an operator-visible data
policy record. A global endpoint or cross-region fallback requires explicit
approval in that policy; regional intent cannot be widened under load.
No real scenario secrets are used in qualification prompts. Evidence exports
remain deployment-scoped, protected and body-free; application audit does
not claim zero provider retention or a billing invoice guarantee.

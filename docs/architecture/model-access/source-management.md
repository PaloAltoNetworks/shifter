# Tenant model-source management

PLAT-202 / #2243 extends the existing model broker, allocation and sharing seams.
See the [tenant guide](../../features/model-access.md) for the user flows and
[preflight](source-management-preflight-2243.md) for the boundary assessment.

## Ownership and publication

Engine owns `ModelSource`, immutable `ModelSourceRevision` records and a tenant
registry mutex. Workspaces owns membership and administrator authority; CMS
composes those authorities for standalone launches and range administration;
CTF owns event configuration and sponsor authority. Registration and source-use
permission are distinct. Public administration APIs require session authority,
closed bounded JSON, tenant authorization and revision comparison. Readback
contains metadata only. Ordinary source users do not receive other users' grants.

The installed v3 catalog remains the deployment policy baseline. Tenant selection
compiles a per-allocation v4 catalog containing that verified baseline and exact
source/price revisions. The validator verifies the baseline digest and preserves
profiles, account limits, sharing, pool membership, unchanged legacy shards and
prices. Profiles can only narrow capabilities; quota limits can only tighten.
Sharing continues to match the verified baseline digest. Reapplying deployment
configuration cannot overwrite tenant source rows or resurrect old grants.

Source mutation synchronously fences dependent grants. Admission pins source,
user, workspace, organization and applicable event authority revisions. The
allocator uses the actual selected shard's immutable price schedule. Each budget
account remains charged once, with original liabilities retained after edits.
Application ceilings are recorded as `application_cap` observations; they do not
certify live cloud health or actual purchased quota. Existing quota usage and
outstanding commitments remain deducted from available capacity.

For independently routed weighted CTF sources, the allocator apportions whole
participant slots by weight using deterministic largest-remainder rounding.
It reserves all account shares atomically before the first participant draw,
then falls through the weighted ranking when a share is full. Multiple sources
on the same physical quota contribute to one total commitment. Shared routing
that pins a whole affinity group to one source retains its whole-group capacity
requirement. Existing v1/v2/v3 allocation semantics remain unchanged.

## Credential lifecycle

Credential input is transient. Engine commits a pending revision with a
server-generated source/version UUID before external storage I/O. The owned
secret store derives a fixed namespace from these IDs; users cannot supply a
secret path or ARN. Publication reauthorizes and compares the revision after
storage. Failure leaves a durable failed record for reconciliation, including
a successful external write whose authority was subsequently revoked.

Portal has create/read/retire access to owned model-source secrets; Engine's
control worker has read access. The broker receives an authenticated, bounded,
ephemeral **secret-bearing** execution projection through its private control
channel. It has no database or general secret-store permission. Neither source
keys nor this projection cross guest enrollment, plugin execution, browser
readback, audit or manifest boundaries. Provider credential objects suppress
secret repr, and provider error bodies are never returned to participants.

Tenant cleanup retires only owned obsolete versions after ten minutes, and
conservatively retains every version of a source with active allocations or
unresolved usage. Current versions remain available for re-enable. Retired rows
without a completion timestamp are retryable obligations; provider deletion is
idempotent and occurs outside database locks. Cleanup never deletes an externally
owned provider account or its credentials at the provider.

## Existing range transitions

CMS commits desired policy plus old-grant revocation first. A second transaction
reauthorizes, prepares and admits the replacement. The policy revision is separate
from the immutable execution operation. Admission failure remains visible and
blocked; an interrupted pending transition can resume at its existing revision.
Guest refresh exchanges a revoked predecessor for its admitted successor once,
under the same network identity and original hard expiry. Old access credentials
remain invalid and old outstanding requests settle against their original price
and accounts. No source switch automatically replays a provider request.

CTF defaults carry explicit organizer sponsorship through cold, spare and warm
preparation. A participant need not receive direct source-use permission.
Sponsorship is revalidated against active sponsor, event and tenant authority.
Absent explicit event demand, the verified scenario envelope and participant
ceiling produce the admission demand. Explicit malformed demand still fails.

## Provider and egress seams

Provider IDs dispatch through `ProviderAdapterRegistry` and the closed
`ProviderTarget` / credential resolver contracts. A conforming integration must
supply explicit authentication, protocol capabilities, conservative billing
bounds, normalized usage and bounded transport. A new provider is a reviewed
broker integration, not a tenant-provided URL or Python module loaded into core.
The executable scenario plugin seam remains independent of inference transport.

Direct Anthropic uses Messages; OpenAI translates the supported text/local-tool
subset to Responses with storage and automatic truncation disabled. Count and
invoke receive the same prompt and local tools. Input includes cached tokens;
output includes reasoning tokens. A missing terminal usage record retains the
conservative liability. OpenRouter pins one upstream with fallback disabled and
has no token-count capability here. Its entire configured physical context is
the pre-dispatch input bound, so smaller admitted input limits reject it.
Direct API geography is `provider-managed` and requires explicit scenario and
deployment permission.

The broker uses the explicit `MODEL_PROVIDER_PROXY`, never ambient HTTP proxy
variables, for external HTTPS provider/identity traffic. The internal
`model-provider-egress` service accepts CONNECT only for compiled provider and
credential hosts on port 443. It pins a resolved public IPv4 address before
connecting and rejects private/metadata DNS answers. Exact configured AWS
endpoint CIDRs are the sole private exception for AWS hosts. Connection count,
headers, setup time, lifetime and relay buffers are bounded. TLS remains end to
end between the broker and provider; the proxy does not inspect prompts or hold
credentials, cloud workload identity, service-account tokens or Django settings.

Additive NetworkPolicies exclude the proxy and broker from generic platform
private-service access. Only broker pods may enter the proxy; its egress allows
DNS, approved public TLS destinations and exact AWS endpoint CIDRs. The proxy's
host allowlist and broker TLS verification supply the hostname restriction that
an IP-based NetworkPolicy cannot express. Guest egress is unchanged. The GCP compatibility renderer includes the proxy
resources, excludes it from incumbent additive egress policies, and removes its
workloads/services/policies on disable. Rollout and immutable image verification
include the proxy alongside both broker authorization components.

## Deployment and evidence

Vertex's platform and model project may be equal. Invocation, control, runtime
and dynamic-secret identities remain distinct and least privilege. Cross-cloud
stored credentials do not change the compute backend. Onboarding an external
identity still requires its owner to grant invocation access; a source form
cannot invent external IAM or provider quota.

Synthetic contract, authority, rotation, retained-accounting, live-policy,
provider transport, egress, Helm and tenant UI tests accompany the implementation.
Full suites and PostgreSQL contention run in CI. Current live acceptance is GCP;
other provider contract tests do not constitute live provider qualification.
A configured source or compatibility probe never proves a complete live range.

# External scenario runtime and author SDK

Status: implementation design. This document does not claim the extraction or
runtime support is complete.

## Current implementation boundary

The working implementation contains the independently buildable SDK, bounded
runtime wire protocol, isolated worker helper, tenant-scoped installation API and
UI, encrypted registry credentials, compatibility controller, and deployment
resources for restricted plugin Jobs. Tenant organization admins install their
own plugins without staff status or per-plugin operator approval. Synthetic local
tests cover installation authority, probe fencing, output ownership, admission
policy and independent wheel execution; live cloud isolation is not yet qualified.

Worker jobs also require the `gvisor` RuntimeClass and dedicated plugin nodes.
Admission rejects default runtimes and platform-node placement. The GCP deployment
declares a bounded GKE Sandbox pool with warm capacity; AWS declares a dedicated
EKS sandbox node pool with the same workload restrictions. Pool membership is the
`node-restriction.kubernetes.io/shifter-pool=runtime-plugin` label, which a
kubelet cannot set. GKE applies it through its control plane; on EKS a trusted
labeler applies it only to running nodes that AWS has tagged as members of the
pool's own Auto Scaling group, and admission confines that labeler to the one
label (#2526). An installation without the required runtime fails closed.
It cannot run tenant code in the default container runtime as a fallback.

Tenant admins can now assign installed versions to registered packs and select
compiled guest targets through the tenant UI. The API verifies pack bytes before
offering guest choices or saving an assignment. A changed pack digest requires
explicit rebinding; it cannot silently drop the previous adapter requirement.
Range creation retains immutable executable, pack, target and parameter pins,
and operation inputs carry those pins through retries and destruction.

Tenant admins can upload and update content archives from the same page. The
server validates archive containment, canonical identity and contract conformance
before registration. Organization ownership is independent of portable pack names;
identical names can coexist in different organizations. Staff status alone does
not disclose another organization's content. Updates require the displayed digest
and preserve existing immutable range inputs. Content upload never installs or
executes an adapter.

The host execution paths support RAES GCE and native EC2 ranges. Engine queues isolated
validate/configure/verify planning invocations in the launch transaction. Workers
receive only the declared node identities, OS families and non-secret parameters;
they cannot query guests or providers. The provisioner waits for every validated
plan before cloud mutation, then executes configure and verify against its own
realized guest map inside the existing apply/cleanup boundary. Each target must
resolve to exactly one guest. Warm-pool reuse is excluded for assigned packs.
Guest-only cleanup uses core range destruction and remains independent of the
plugin image's availability or registry enablement.

Guest actions can request typed references to a bound guest's private address or
verified participant SSH public key. Core resolves every reference before the
first action and supplies bounded JSON data to the guest only. Missing declared
participant access fails before cloud mutation; missing realized values fail
inside apply's cleanup boundary. Management keys, secret references, provider
credentials and arbitrary output fields are not exposed by this contract.

The embedded private content tree, dedicated image recipes, workshop tooling and
corresponding build/test jobs have been removed from core after hash-verified
preservation in the owning repository. Shared image checks remain in core.

Current documentation and requirement rationales use generic platform contracts.
Historical plans that mixed core instructions with private scenario operations
are retired as implementation guidance. Private release entries and traceability
targets are removed from the current public documents; Git history is unchanged.
Synthetic scenario fixtures are included in normal platform code scanning.

Embedded scenario bootstrap and repair commands, provider-role creation and its
assume-role grant, guest provider-key issuance, and private executable assets have
also been removed. Container escape probes now require an explicit container;
there is no private default. Legacy GCP key revocation remains teardown-only.
AWS ranges using the retired role issuer must be drained with the previous release
before the IAM cutover.

The SDK and external worker have been built and exercised independently with
synthetic local conformance tests using a locally built SDK wheel. Worker image
delivery and live cloud qualification remain outstanding. SDK distribution is
tracked separately in [#2241](https://github.com/Brad-Edwards/shifter/issues/2241)
and does not block this qualification. An installation's `ready` status means its
compatibility probe succeeded; it does not mean a pack is runnable or a range is
ready. This branch is not a completed cutover.

Both AWS and GCP are required acceptance targets. The native EC2 host now uses the
same guest composition and plugin sequence, with explicit provider admission,
retained resource ownership, private management transport and reconstructive
cleanup. Its implementation and supported network intent are described in
[native EC2 runtime](native-ec2-runtime.md). Broker enrollment supplies temporary
model capabilities; legacy guest provider credentials are not part of this path.

## Outcome

An administrator installs a content pack and its executable adapter independently,
without rebuilding Shifter. Any adapter implementing a supported version of the
public contract can be installed; core contains no list of private adapters and
does not branch on scenario, image, domain, container, or guest names.

Private content, guest setup scripts, image recipes, infrastructure extensions,
answer material, and operational evidence live in the pack owner's repository.
Public defects and tests use synthetic reproductions. Git history is unchanged.

## Existing boundaries

- RAES package ingestion already supports independently supplied, digest-verified
  packs. RAES owns portable authoring intent and artifact requirements.
- ADR-041 provides lazy, exact Python distribution selection and bounded execution
  for verification. It does not provide executable installation or range setup.
- Artifact preparation already has immutable adapter manifests, digest-pinned
  worker images, separate cloud grants, administrator permissions, audited
  registration, operation/attempt fencing, and disable/retire behavior. Its HTTP
  API has no corresponding administrator UI. Its contract applies to artifact
  preparation, not per-range guest configuration.
- The Engine owns immutable operation inputs and applies results. The provisioner
  owns cloud and guest realization. Neither the portal nor a pack may import or
  install private code as a side effect of content ingestion.

## Public SDK

`shifter-adapter-sdk` is independently buildable and versioned. Authors install its
wheel without a Shifter checkout, Django, ORM models, settings, or provisioner
modules. It exposes wire contracts, version negotiation, bounded worker transport,
verification contracts, and a synthetic conformance harness. Core and external
adapters consume the same contract definitions. SDK releases do not contain a
private adapter or scenario fixture.

Preparation, runtime configuration, and verification remain distinct protocols.
A conforming adapter advertises only capabilities it implements. SDK compatibility
does not grant deployment permissions or establish that a pack is runnable.
New protocol major versions fail closed until core explicitly supports them.
SDK publication requires reproducible wheel/sdist builds and installation tests
outside the repository, including an independently packaged synthetic adapter.

## Executable installation and authority

Executable identity is an
immutable manifest plus digest-pinned worker image, not a module path or a
mutable image tag. Registry credentials are encrypted in the tenant datastore
and projected only into per-invocation image-pull secrets, never worker mounts.
Installation validates protocol, identity and capabilities, then performs an
isolated compatibility probe before activation. There is no operator-maintained
image allowlist or per-plugin cloud grant. No `pip install` occurs
inside the portal or provisioner and no application search path is mutated.

Tenant administrators may install their own plugins, disable versions, and retire
them entirely through the tenant UI. They are not restricted to a platform-curated
catalog. Pack installation remains independent. A pack's declaration is a
compatibility requirement, never permission to acquire or execute code.

Untrusted plugin code runs in a separate restricted worker, with no portal or
provisioner imports, database credentials, cloud credentials, host mounts, or
service-account token. The worker receives a bounded operation input and produces
a versioned plan. Shifter validates that plan and executes only supported actions
against the exact operation's authorized bindings. Guest scripts remain private
plugin assets. Plugin code cannot select another range, namespace, cloud identity,
or deployment configuration through its response.

The normal tenant deployment provides the plugin execution infrastructure.
Installation and capability validation are tenant API operations. No admin step
requires a grant UUID, Terraform, kubectl, a management command, or a cloud console.
An unavailable capability is a visible installation/readiness failure with a
tenant-level recovery action; it must never silently elevate the portal's cloud
authority or report successful installation while requiring an undisclosed manual
setup step.

## Runtime lifecycle

The platform binds an installed version to an exact registered pack digest and
pins that identity into each admitted operation. Admission checks compatibility,
backend support, required bindings, and authorization before cloud mutation.
An uploaded pack may carry a closed `model-needs.json` declaration containing
only workload roles, capabilities, strategies, regions, and finite limits.
Shifter binds it to the verified installed digest; provider sources, credentials,
routing, and spending authority remain tenant administrator policy.
An administrator may bind an exact provider image profile to an adapter target.
The profile is organization-owned runtime data stored with the pack assignment,
then pinned with the adapter and pack digest for the range lifetime. GCP profiles
accept exact image resources with either standard or prepromoted-directory
bootstrap metadata, or the closed preconfigured-machine-host contract. AWS
profiles accept exact AMI IDs with the same three bootstrap contracts (#2527,
#2528): the native EC2 backend gates a preconfigured host on the same
participant readiness canary, and refuses, before any mutation, a prepromoted
image whose baked domain differs from the authored one. An authored portable artifact binding remains
authoritative when present, and the adapter worker never receives cloud image
selection authority.
Runtime hooks receive bounded, operation-scoped input and authorized guest or
resource bindings through the SDK. They do not receive ORM handles, deployment
configuration dumps, unrestricted credentials, or platform import access.

Configure and verify complete before a range becomes ready. Hook failure cannot
be interpreted as success or fall back to a scenario-specific branch in core.
Retries use the existing generation and operation identity. Cancellation and
cleanup retain ownership and the pinned executable; an adapter is responsible
for idempotent behavior within the resources it was granted.

Disable blocks new admission. Existing operations retain the exact adapter and
grant evidence needed for cleanup. Retire prevents reactivation. Referenced
versions cannot be removed while ranges or cleanup obligations still need them.
Changing a pack or upgrading an adapter affects new admissions only. Core guest
containment and credential protections must survive extraction.

## Administrator experience

The Administer workspace provides an Adapters page with:

1. Installed versions, lifecycle state, supported capabilities and compatibility.
2. Installation from an author-provided plugin package, including private registry
   authentication when needed; the server resolves execution prerequisites and
   validation errors identify the corrective action without private diagnostics.
3. Review of executable digest and requested capabilities before activation.
4. Disable and retire actions with dependent packs, ranges, and cleanup effects.
5. Links from pack management to binding and readiness, separating missing pack,
   missing adapter, incompatible protocol, unavailable execution, and failed verification.
6. Provider image selection per adapter target, including the bounded host and
   participant-readiness fields required by a preconfigured GCP machine host.

Permissions are enforced in the service and API as well as the UI. Rejected
installation has no execution side effects. Audit records retain actor and
immutable installation identity without copying manifests into public metadata.
Raw manifest editing alone is not the complete pack-adapter administration flow.

## Extraction and evidence

Preserve the existing source in the private repository before removal, without
overwriting maintained pack files. Move scenario-owned implementation and tests
there, then port imports to the SDK. Remove core bootstrap dispatch, credentials,
image recipes, deployment defaults, workflow jobs, copied packs, and private
documentation. Replace mixed core tests with synthetic contract cases; retain
security assertions independently of the private implementation.

Completion requires all of the following:

- Core builds and tests without the private repository or any installed adapter.
- An independently packaged synthetic adapter installs through the same admin
  path as an external adapter and exercises admission, configure, verify, failure,
  retry, cancellation, and cleanup.
- Incompatible, missing, disabled, ambiguous, or unauthorized adapters fail before
  resource creation. A stale result cannot satisfy a newer operation.
- The extracted private adapter builds and installs against the SDK alone, and
  its tests run in its own repository. Both pack and adapter install at runtime.
- Both AWS and GCP pass installation, admission, configuration, verification,
  retry, cancellation and owned-resource cleanup with the extracted adapter.
  Local provider-specific plan tests do not substitute for these live checks.
- The real admin UI covers installation, binding, readiness, disable, and upgrade;
  direct API calls cannot bypass authorization or immutable identity.
- Repository guardrails reject renewed private imports/content and scenario-based
  dispatch; public metadata uses synthetic reproduction evidence.
- Required architecture, Python, frontend, infrastructure, and workflow checks
  pass. Live cloud validation records deployed versions and cleanup observations
  privately; local tests must not be presented as a live qualification.

## Broker integration checkpoint

The extraction branch includes the request-accounting foundation, conservative
settlement fixes, one-use guest enrollment, the private Engine control API and a
separate broker process. Vertex and Bedrock wire adapters use approved targets,
bounded Messages requests, provider token counting and complete usage evidence.
Local tests cover malformed requests, workload identity, stolen-token subnet
rejection, rotation races, transport fencing, disconnects and incomplete usage.

Deployment projection, trusted guest-bootstrap delivery, provider inventory,
AWS sandbox-node provisioning and native EC2 realization are connected in this
branch. Local checks cover both provider paths and independent SDK/worker builds.
Publication and live acceptance still need to establish the deployed isolation,
tenant installation, participant access, model traffic and cleanup behavior.
Both cloud qualification targets remain pending the user's choice of deployment
and time.

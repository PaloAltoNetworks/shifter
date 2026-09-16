# In-tenant artifact preparation: implementation design

Issue: [#1583](https://github.com/Brad-Edwards/shifter/issues/1583).
Status: the issue owner directed implementation on 2026-09-13 after adding
post-setup private pack and adapter installation as essential acceptance criteria.
This document describes the agreed direction and its implementation boundaries.
The operator procedure is [artifact preparation](../ops/artifact-preparation.md);
observed tenant evidence is recorded in the
[qualification record](../../shifter/packer/preparation/QUALIFICATION.md).

The [repository-wide preflight](raes-in-tenant-artifact-preparation-preflight-1583.md)
qualifies this direction against the current code. In particular, deployment
and internal authority remain distinct (ADR-054), private registration must
reach runtime capability and Job admission without a platform rebuild, and the
existing image registry's supplied evidence references do not replace independent
verification. Its boundary findings apply to built-in and private adapters alike.

## Decision

Shifter should execute an explicitly permitted, supported materialization
profile inside the operator's tenant and admit its immutable result into
existing artifact inventory. Shifter must maintain the adapters and concrete
build definitions needed by the scenarios this repository supports. A missing
adapter is work for this repository; a missing image is not permission to build.

The extension point is a **backend adapter for an exact materialization profile**.
Scenario identity is not the extension point. A scenario selects a profile and
immutable specification through the upstream contract; an installed adapter
implements that profile. Several scenarios can use one profile. A scenario
requiring a materially different procedure needs another declared profile,
rather than an `if scenario_name == ...` branch in the range provisioner.

This is an explicit operator preparation operation completed before launch.
Ordinary launch keeps its existing artifact-resolution boundary and never starts
a build or waits for a preparation worker.

## Responsibility boundaries

| Owner | Responsibility | Boundary Shifter consumes |
| --- | --- | --- |
| RAE/RAES | Portable artifact requirements, author permission/posture, mechanism and materialization identities, validation and resolution semantics | Released public contracts and validators |
| Scenario/environment-pack author | The scenario's required artifact, reproducible inputs and associated materialization specification; permission to use the selected mechanism | Immutable, integrity-checked package references and the declared profile/specification identity |
| Shifter adapter maintainers | Required adapters and profiles, repository-owned build definitions, scenario-specific preparation code, output guarantees and qualification tests | Exact profile id, version and digest; a supported procedure rather than an arbitrary build endpoint |
| Catalog/Hub/distribution services | Publishing, discovery, access entitlement and distribution of packages/artifacts | Existing source and acquisition boundaries |
| Shifter CMS | Authorize the operator's preparation request, select the registered tenant/backend, validate source identity, and expose bounded progress | Preparation service commands and status |
| Shifter preparation service and adapter | Durable execution, tenant isolation, locked-input verification, retry/fencing, output verification and cleanup | A separate preparation operation and a closed worker contract |
| Existing Shifter inventory/resolver | Admit verified immutable availability; select a satisfying artifact using the existing upstream resolution rules | Existing inventory projection and launch satisfaction binding |
| Range provisioner | Realize a range from its already selected, immutable artifact bindings | Existing range operation input; no recipe or preparation job reference |

Shifter maintains the required profile implementations and backend-specific
build material. The portable specification may refer to that repository-owned
material; it need not contain a ready-made cloud-image recipe from upstream.
Shifter still must honor the scenario's declared requirements and permission.
Conversely, upstream
permission to materialize does not grant tenant credentials or authorize an
operator to mutate a tenant: both checks must succeed independently.

## Contract and adapter shape

The released RAES materialization specification is a reference carrying
`specification_id`, `profile`, `digest`, and `locked_input_ids`. It is not itself
a portable shell script, Dockerfile, or GCE image recipe. The profile defines the
meaning of the referenced specification and how its integrity is verified.

Admission joins the complete identity: mechanism, profile id/version/digest,
specification id/digest, declared acquisition/timing, requirement and permission,
and the complete locked-input set. Matching only a friendly profile name or
scenario name is insufficient. A changed profile digest requires qualification
and registration again.

The adapter consumes the validated upstream reference plus server-selected
tenant policy. It resolves specification material through the trusted package
boundary or the profile's contained repository-owned build context, validates
the exact profile-defined shape, verifies all locked inputs,
executes its fixed procedure, and returns a candidate immutable output with
provenance. A separate admission step verifies that result before inventory can
expose it as available. Shared owns the public upstream translation; application
services and workers do not import private RAE modules or parse CLI output.

The internal preparation record is Shifter-owned operational state. It must not
become a second portable materialization specification. The existing preflight's
prohibition on a Shifter materialization DTO is interpreted at that portable
semantic boundary; it does not prohibit the necessary internal operation id,
attempt, lease, authorization context and result references.

Profiles have validated inputs and repository-maintained procedures, including
scenario-specific build scripts where needed. Versioned, integrity-checked build
material runs inside the adapter's declared build environment. It is not an
arbitrary command supplied by a browser or an executable hook in the controller
or worker launcher. The profile documents what code executes and with which
authority; the worker's isolation is part of that implementation contract.

## Private extensions after tenant setup

Authorized operators can introduce private packs and administrators can install
private adapters into an already-running tenant without a Shifter release,
platform rebuild, or upstream publication. Shifter maintains the adapters needed
by this repository. Tenant extensions add proprietary scenarios and procedures
through the same contracts and execution lifecycle.

Private packs pass through the normal integrity, permission, validation and
ingestion boundary. An adapter registration binds a versioned manifest to an
immutable worker-image digest in a private registry. The manifest declares its
materialization profiles, supported backend, inputs, outputs and verification
contract. Registration is tenant-scoped and selects only explicitly granted
worker permissions and configured private-registry access. No private content,
registry credential or tenant secret becomes public metadata.

A pack can declare an adapter dependency. Installing a pack does not install
executable code or authorize tenant permissions. Tenant administration controls
adapter installation and activation independently. Preparation resolves only an
enabled adapter whose complete declared profile identity matches the requirement;
built-in and private adapters use the same admission checks.

Each operation binds the exact adapter manifest and worker-image digest.
Upgrades install a new immutable version. Disabling an adapter prevents new
preparation requests; retirement preserves the versions and execution authority
needed for in-flight completion and cleanup. Existing admitted artifacts retain
provenance and their own retention policy.

Acceptance includes installing a private pack and adapter after tenant standup,
preparing its artifact and launching through the normal resolver, without
rebuilding Shifter or publishing private material upstream. Test missing or
mismatched adapter dependencies, unauthorized installation, cross-tenant access,
mutable image references, disabled versions, upgrades and retirement during an
active operation.

## Lifecycle and launch interaction

1. The operator requests preparation for an immutable package requirement in an
   authorized tenant. Browser input identifies the request; it does not supply a
   cloud account, worker command, recipe body or claimed output identity.
2. The service validates the package, permission, exact registered profile and
   tenant policy. It consults the existing resolver. A suitable admitted artifact
   already available produces a reuse result and no worker.
3. If preparation is permitted and supported, the service persists an immutable
   input reference and deduplicated preparation intent, then dispatches a worker
   through its own closed task profile.
4. The worker verifies locked inputs, performs the profile's procedure, and
   records a candidate immutable artifact and bounded provenance. A build exit
   code alone cannot complete the operation.
5. Admission independently checks output existence/identity, tenant ownership,
   profile/specification/input bindings and profile-specific output guarantees.
   It atomically records admitted availability for the current operation attempt.
6. A later launch resolves inventory normally and persists its immutable
   satisfaction binding. Provisioning never consults mutable preparation state.

Internal states are `queued`, `running`, `verifying`, `available`,
`failed`, and `cancelled`. `available` means verification and inventory admission
committed, not merely that the worker uploaded something. The idempotency key
includes tenant/backend, package and requirement identity, exact profile/spec and
locked inputs, and relevant policy version. Concurrency must converge through
database uniqueness and fenced transitions, not a pre-insert existence check.

The preparation service reuses established transactional mutation, audit,
outbox, result-inbox, retry and lease conventions. It gets separate state and
worker identities; it does not overload `Range`, `ProvisionerLaunchIntent`,
`OperationInput`, package source records or image-map notes. Each result binds
the immutable input digest, operation and current attempt/lease. Stale, duplicate,
cancelled and cross-tenant completions cannot admit availability.

Cancellation fences admission before cleanup starts. The adapter cleans staging,
temporary credentials and intermediate resources; a reconciler handles worker
loss and retries bounded cleanup. Admission failures retain bounded failure
evidence and quarantine/delete candidates according to tenant policy. Admitted
artifacts have a separate retention policy and cannot be deleted by temporary
worker cleanup while referenced by a launch.

## Isolation and output trust

Use a dedicated ephemeral Job, pinned worker image, service account and admission
policy. Preserve non-root execution, read-only root filesystem, dropped
capabilities, bounded resources/deadline, controlled volumes and endpoint-specific
egress. Do not broaden the provisioner Job policy to admit build commands.

The worker command accepts only a preparation id. A least-privilege boundary
delivers its immutable input. Prefer short-lived workload identity; never pass
credentials, signed URLs, recipe bodies or provider payloads in argv, labels,
annotations, events or user-visible diagnostics. Any intermediate build guest has
its own constrained identity and network policy; it does not inherit controller
or range-provisioner authority.

Provenance binds the immutable output identity to the package, requirement,
profile/specification digests, actual locked inputs, worker/adapter version,
tenant/backend, attempt and verifier result. Keep protected evidence references
separate from the bounded public status projection. Provenance establishes what
was executed; profile-specific verification establishes the claimed output
properties. Neither proves permission to redistribute the artifact.

## APTL comparison and the first Shifter profile

[APTL](https://github.com/Brad-Edwards/aptl) provides a useful example in
`raes_artifact_mechanisms.py`: the `aptl-contained-component-build` profile joins
full profile identity, specification digest and locked inputs, uses a contained
component context, builds an image, and reads back the resulting Docker image
identity. Its build procedure is behind the profile seam, separate from dynamic
composition and artifact acquisition timing.

That is a precedent for ownership and identity matching, not a Shifter adapter to
copy verbatim. An OCI image produced by that profile is not a bootable GCE image.
The inspected env-packs 5.2.0 TechVault materialization references select this
APTL profile; its kit materialization ledger is not an executable GCE recipe.

The first Shifter implementation is `shifter-gce-contained-build` version 1,
with the repository-maintained `http-smoke` context and
`scenario-dev/preparation-http-smoke` pack. It locks a concrete Ubuntu base and
its independently measured raw-disk digest, installs a contained HTTP service,
scans the output independently and exercises a fresh functional boot probe.
The public pack contract expresses the full permission and input identity without
an upstream contract change. Its physical qualification precedes the complete
tenant preparation/launch acceptance recorded in the qualification document.

## Negative behavior and acceptance criteria

| Trigger | Required result |
| --- | --- |
| Artifact already satisfies the requirement and is admitted/available | Reuse; no build |
| No artifact requirement or no explicit materialization permission | No preparation request |
| Missing image mapping alone | Existing missing-availability result; no fallback build |
| Exact identity would be replaced with another identity | Reject substitution |
| Opaque, externally governed or non-buildable artifact | Use its proper permitted mechanism or fail; never synthesize a substitute |
| Unsupported profile/version/digest or incomplete input locks | Reject before dispatch |
| Build succeeds but output readback/provenance/admission fails | Fail preparation; no inventory availability |
| Stale/cancelled/foreign-tenant result | Record disposition; no authoritative transition |
| Worker dies after candidate creation | Reconcile/quarantine and bounded cleanup; no inferred success |

Acceptance requires a real tenant build using Shifter-maintained adapters and
build material, strict permission/profile/input admission, no substitution or
implicit missing-image builds, and reuse of existing admitted availability.
Independent verification, fenced inventory admission and a prepare-to-launch
walkthrough must prove the output usable. The qualification record supplies
observed evidence; this design alone establishes no runtime acceptance.

Implement and review in this order on #1583: profile/specimen
qualification; operation/service persistence; isolated worker and adapter;
independent verifier/inventory admission; operator API/status; failure/recovery
and tenant walkthrough. No scenario-specific branch belongs in the provisioner.

## Dependency upgrade and verification boundary

The branch selects `raes==3.5.0` and `raes-env-packs==5.2.0`. Compatibility
repairs cover public artifact imports, canonical `key` authentication, coupled
OS fields and explicit VM constraints, configuration-bound runtime target selection,
and the complete `raes-provisioning-plan-v2` transport. The standalone consumer
remains RAE-free. Old `v1` / `2.0.0` plans remain readable only for cleanup, with
stored resource and `account-publickey` secret identities preserved.

Native launch now returns an enqueue receipt. Completed realization requires
independent guest OS and provider VM observations, complete composition
verification, immutable plan and operation identity, and the current execution
generation. The engine applies the public RAE realization gate before READY.
Warm activation produces fresh evidence and verifies source content without
reinstalling it. Directory access uses the existing idempotent reconciliation
and readback path.

Tests exercise public-accessor parity, malformed presence, actual compiler
transport round trips, missing/mismatched observations, stale generations,
cleanup and warm activation. Shipped smoke, Polaris and validation SDL retain
their authored OS and VM requirements; associated-artifact digests are refreshed.

These local checks do not certify native cloud effects. The generic published
manifest withholds `realization-envelope-v1` because it has no selected scenario
from which to construct an honest witness. After a pack is loaded, Shifter
configures the target with a scenario-bound carrier and advertises that contract
for the selected runtime target. Publication requires a passing aggregate
upstream conformance report for that configured target, including its
realization-envelope contract. An unsupported qualification case blocks this
delivery; passing core protocol cases cannot substitute for that result.

The dependency and authority direction is `RAE -> env-pack -> specific pack ->
backend adapter -> backend core`. The RAE runtime is authoritative: it selects
the backend, admits the portable plan, controls its execution, and evaluates the
returned status, observations and evidence. The backend never becomes the
authority merely because evidence flows back to the runtime.

The configured realization-envelope witness binds the loaded scenario name and
one of that scenario's declared compute nodes. It deliberately leaves sizing,
network, image, operating system and provider materialization open. The selected
carrier and digest travel with the immutable plan so completion uses the same
runtime decision across processes. Shifter's GCE adapter, maintained in this
repository, assigns an omitted network selection to a backend-owned subnet and
then calls the existing range-cell core. It does not alter the authoritative
portable plan used for completion accounting. An explicitly empty network
selection is preserved and rejected rather than defaulted. In shared-VPC mode
the adapter uses the tenant subnet allocator; in per-range-VPC mode it selects a
private subnet that does not overlap the scenario or portal networks.
The allocator's Engine-owned PostgreSQL boundary recognizes the current
`raes-range` provision or destroy generation alongside the incumbent `range`
generation, while retaining the same verb checks, generation fence,
serialization and release policy.

That allocation is one closed backend lifecycle value. Provision reserves it;
warm activation reads the prepared generation's value before revoking prior
access; destroy reads it for reconstruction. If provision failed before a
reservation existed, destroy still reconstructs the deterministic resource
names and converges without pretending that an allocation was made.

The published backend limits a plan to 64 realized nodes and 128 provisioning
resources. Those admission limits match the bounded completion evidence
transport, so a plan cannot pass runtime admission, mutate provider state, and
then fail only because its required observations cannot be returned.

This is the same responsibility boundary illustrated by APTL's scenario-to-
backend realization adapter: portable intent remains in the pack, while the
repository-owned adapter decides how its backend can fulfill open intent. No RAE,
env-pack or TechVault change is required for the GCE realization choice. The
broader released-content cohort tracked by #2082 remains separate.

## Implementation boundary

Proceed with the agreed ownership, exact-profile adapter interface, explicit
preparation-before-launch operation and post-setup private extensions. Qualify
one concrete profile and specimen before generalizing the tenant lifecycle.
Keep #1583 open until its preparation and private-extension acceptance evidence
exists. The dependency upgrade alone does not satisfy those criteria.

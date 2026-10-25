# GCE profile qualification

The maintained GCE profile passed physical qualification and the private pack →
private adapter → prepare → ordinary launch demonstration for #1583 on
2026-09-13. Physical cloud checks and controller-owned inventory admission are
separate evidence, recorded below.

These completed runs used profile digest
`sha256:776db366bb1a6fb603690a3999466c1997748903a3ed3aada06449b9434f7e70`.
Review then made the required boot-probe entrypoint explicit in `PROFILE.md`
and moved missing-probe rejection ahead of cloud acquisition. That correction
has profile digest
`sha256:809f70f1512204f84658ec1550c8e13eddcb924d30a7c285d36c55fa378e2991`.
Specimen version 0.1.2 pins the corrected profile; its pack digest is
`sha256:5af87982851eb62a0d240573f882363583db0a08f45da8978c1efbfbf598dbad`.
It declares the required compute service while leaving network realization
open for the runtime-selected backend adapter.
The contained context and cloud execution sequence are unchanged. The recorded
operations below retain their original identities; they are not qualification
records for a newly installed worker image or profile digest.

The 2026-09-13 runs use `gcp-dev`, project `prod-h5k4z5`, zone `us-central1-a`.
The base and independent scanner are the concrete public Ubuntu image
`projects/ubuntu-os-cloud/global/images/ubuntu-2204-jammy-v20260906`, provider ID
`5614745040379220357`. Both guest roles have no service account or external IP.
The disposable preparation VPC has no peering to the platform, runner or range
networks. Its only ingress rule permits TCP 8080 between preparation-tagged
guests for the fresh functional probe.

Live checks exposed and corrected three transport assumptions:

- Standard E2 rejects `onHostMaintenance=TERMINATE`. Preparation uses `MIGRATE`
  with an independent maximum runtime and stop action.
- Cloned disks share partition/filesystem IDs. The scanner must boot before
  attaching the candidate read-only, so boot-time mounts cannot select it.
- The serial endpoint can become unavailable during poweroff. A previously read
  attempt-bound receipt is retained, and completion still requires successful
  provider readback of a stopped VM.

The default Google shutdown-script unit has an unlimited stop timeout. The
profile replaces its stop command in `/run` for these disposable guests. This
ephemeral override is not part of the produced image. Cached metadata scripts
are removed before image creation and checked independently for residue.

The full ninth run completed input measurement, candidate construction, independent
output verification, the fresh HTTP boot probe, and empty cleanup readback on
2026-09-13. Operation `948b09ca-1133-4176-8512-356764062d7a` ran from 19:58:23Z
to 20:24:19Z. It measured the 10 GiB base disk as
`sha256:93c8bc1df171ea912f0f0ab54701b505e2bf6339b91ba9e47ca3fb3e45015a7a`,
matching the earlier independent input scans. The contained context was
`sha256:a8380d02c9f850f2a0adaf3a75461b086b16b66ef2b2286160065dac3817911e`.
The candidate output measured
`sha256:e3487cee61ca4bce1c69975242238880c5699960425eb524051051d011c43e61`.
The independent probe observed the service responding to its fresh challenge.
The candidate and every operation-owned guest/disk were removed afterward.

Earlier output scans rejected cloud initialization cache and user SSH material.
The profile now waits for cloud-init completion, cleans its cached state, removes
SSH material in every guest home, and rejects redirected cleanup paths. The
[cloud-init status and clean commands](https://docs.cloud-init.io/en/latest/reference/cli.html)
provide those lifecycle operations. Independent inspection then accepted the
sanitized output; no failure was converted into an admission claim.

The eighth run was an output-only development diagnostic. It passed independent
output inspection before interruption. Its recovery could not establish the
boot result, so its resources were cleaned and the complete ninth run was used
for the evidence above.

These observations qualify the physical construction/inspection/probe sequence.
The tenant workflow below separately establishes worker admission, inventory
admission and ordinary launch.

## Tenant integration checks

The private specimen pack and digest-pinned adapter were installed after the
tenant was running. The pack was retrieved from private object storage,
validated through the ordinary conformance boundary, and submitted through the
authenticated preparation API. Anonymous administration and worker requests
were denied. The installed Job policy accepted each supported worker phase and
rejected an unapproved image. Actual cloud and Kubernetes readback activated
the grant; verified controller upgrades preserved the immutable worker grant.

The first complete controller run passed input verification, then failed because
GCE image creation separately requires `compute.images.setLabels` when ownership
labels are supplied. The builder's resource-scoped role now includes that
permission. Its failed-operation cleanup completed with no remaining resources;
the authenticated retry started fresh attempts and completed independent output
verification and inventory admission at 22:48:07Z. Cleanup completed before the
ordinary launch request at 22:52:01Z. Operation
`d9fe7264-df1c-448d-bb2e-1f7e50003120` admitted image
`projects/prod-h5k4z5/global/images/prep-223d8e0c91d84540b0603a1c80d80f15`,
numeric provider ID `7706690857114180579`, with raw-disk digest
`sha256:11793996685af915fc983198ef69cdb403203d5ef9816825500d5b8867b8d788`.
The authenticated reuse request returned `available`, `reused: true`, `id: null`,
and left the attempt count unchanged. The verifier and cleanup receipts report
the fresh boot observation, sanitized output and no remaining temporary resources.
Worker execution failures now retain their bounded failure code instead of
being reported as independent verification failures.

Ordinary Smoke validation also found a Secret Manager authorization failure.
The corrected Terraform conditions retain the closed Secret Manager roles and
fully qualified secret-name prefixes, without the resource-type predicate that
rejected live calls. Provisioner probes passed absent/present lookup, creation,
version publication, readback and deletion, while platform-secret access stayed
denied. Portal probes accepted both `latest` and numbered participant versions
and rejected host-management and directory credentials. All disposable secret
fixtures and probe pods were removed.

Failed ranges are hidden from active CMS views, but failure does not establish
that cloud cleanup succeeded. The destroy entrypoints now allow owners with
current workspace authority to retry cleanup of those failed records. Destroyed
history remains excluded. Live teardown of the failed Smoke launch used this
normal service path before a fresh ordinary launch was requested.
That Smoke launch reached READY at 22:45:31Z and completed ordinary destruction
at 22:49:31Z.

The private adapter administration API installed version 2, disabled and enabled
it, then retired it. Version 1 remained enabled and the completed preparation
retained its exact original adapter reference. The temporary API tokens were
revoked after the checks.

The specimen's first launch exposed an invalid 512 MiB GCE allocation. Pack
version 0.1.1 declares 1 GiB and retains the same materialization requirement,
fixed inputs and context. Its canonical digest is
`sha256:241140db0aa27a5d5520374cf5159b380508ff4476eec15fecddf28806869f3c`.
The update used ordinary registration with an expected predecessor digest and
renewed conformance. The pinned env-packs exporter also exposed a transport
compatibility gap: its archive contains pack-relative files, while the older
object resolver required a wrapper directory. Both layouts now use the same
bounded extraction and upstream name, inventory and digest checks.

Synchronization with `origin/dev` brought the participant-readiness enforcement
from #1910. The tenant's `kep-v2-cleanbuild` and `nested-ai-lab-host` profiles
lacked the required canary contract and manifest digest. They were removed from
active runtime configuration; their cloud images were retained. The remaining
External image entries retain their typed profile configuration.
An unqualified nested profile cannot bypass the new validation or prevent the
qualified ordinary GCE path from starting. CMS lease migration 0044 from #27
was applied through the platform migration entrypoint.

The corrected private pack launched through ordinary CMS/Engine resolution as
request `a7c827c3-3665-41b0-ad70-ea4b239aba8c`, Engine range 15, at 23:12:44Z.
It reached READY at 23:16:00Z. An independent provider read observed boot-disk
`sourceImageId=7706690857114180579`, matching the admitted image. At 23:16:09Z,
a separate probe connected with the provisioned management credential and
provider-pinned SSH host key, then obtained the HTTP service's response to a
fresh nonce. The probe printed only bounded verification facts. Ordinary
destruction completed at 23:20:17Z; the range VM was absent and the admitted
image remained READY with the same numeric identity.

The final launch used platform image
`sha256:1ac69d4d6233c78a080766b281f4419df736ad2663712d80e11626464b1e80b2`
and provisioner image
`sha256:7353a9178fb34269ef43e9c530c6357113cc2caeac4f612207e92dc098d2a232`.
Preparation used independently approved worker/verifier image
`sha256:a28736a987a1d3a1efb3a8e367b06ad6576ccfb37ae073296f051d9b1ee3248a`.
These were privately pushed working-tree qualification builds. This record
establishes observed tenant behavior; CI release provenance remains the release
pipeline's separate responsibility.

The final deployment check found the Guacamole-bootstrap and RAES-record
maintenance workers restarting before their first heartbeat. At a 250m CPU
limit, startup exceeded the existing liveness window. With the standard worker
allocation (100m CPU and 256 MiB requested; 500m CPU and 512 MiB limits), both
started at 23:48:47Z and wrote their first heartbeats at 23:50:39Z/23:50:40Z.
The Guacamole worker's cgroup reported no out-of-memory events and a peak near
220 MiB; these were startup/liveness failures, not observed OOM kills. Both
continued with zero restarts and all platform deployments were ready. The chart
now carries the qualified allocations while retaining the existing probes.

## Open-requirement and installation-upgrade qualification

The final 2026-09-14 qualification used the same `gcp-dev` tenant to prove the
intended authority direction. Specimen pack 0.1.2 declares a compute service and
the prepared artifact it requires. It does not declare a GCE network, subnet or
provider materialization recipe. The RAE runtime selected the maintained GCE
adapter, passed a scenario-bound realization envelope in the immutable plan and
remained authoritative over the backend operation. The adapter allocated
`10.50.2.0/28` as subnet `shifter-r-17-backend-default` in the tenant range
network and realized the service without changing the portable plan.

The worker runtime was upgraded in place as a tenant add-on. Because the worker
image pin changes grant-defining authority, the old and new installations
briefly coexisted while the old grant was checked for pending cleanup. The old
grant was then revoked, its Kubernetes resources removed and its Terraform
destroy-only plan removed all 35 cloud resources. Final readback found only the
current `shifter-preparation-1583-v2` namespace, preparation VPC and four worker
identities. This was one tenant with a bounded worker-runtime upgrade, not a
second tenant. The current installation digest is
`sha256:c2bc4506e9c9d8c3c4973aac9fc4442c69da899ae1305d2948f966b1f1463015`;
grant `21a82e13-5d2a-4ce6-a004-3f3bef874ac0` was reverified against live cloud
and Kubernetes state and remained active with immutable configuration digest
`sha256:c4c12ea0cfd49cbfc8402fa1ce602e3676995e3405177b63e9d70d70d5b1b6f8`.

Private adapter `private-http-smoke` version 3 was installed after tenant
stand-up and remained enabled with manifest digest
`sha256:fb3a14861294ba01bf0ba4d10ce49102515b9ebad6641333f810e80de6e8987a`.
Preparation operation `26f79031-896a-4cf6-9a7a-ec97ddbb6292` completed four
separately authenticated phases, reached `available` with no pending cleanup,
and admitted
`projects/prod-h5k4z5/global/images/prep-a2d09b4cc39347ffab9638ada80edc7a`
with provider image ID `6861396432327993052`. Repeating the identical request
returned `reused: true`, proving that an immutable input combination is prepared
once and reused rather than rebuilt per range.

The first ordinary launch exposed a PostgreSQL coordination boundary that
accepted only legacy `range` operation envelopes. Forward migration 0064 grants
the same reserve/read/release routines to the current `raes-range` generation
without restoring direct table access. After the migration, request
`d4b996bf-3d4a-44eb-9bdd-8c646e715caf` created Engine range 17 and reached
READY. An authenticated probe observed VM
`shifter-r-17-backend-default-web-0`, verified its boot disk source image ID as
`6861396432327993052`, enforced the provisioned SSH host key and received a
fresh HTTP nonce response. Ordinary destruction then removed the VM and subnet,
released the database subnet reservation and left the admitted prepared image
READY. The range record is `destroyed`, and final database readback found zero
reservations for the request.

The final platform rollout used image
`sha256:8348d3449d13dcaa4d1073e4649e053c9d7a9510f795b7f3ac1f15607f6b693c`.
All 14 platform deployments reached their desired, updated, ready and available
replica counts. The provisioner remained pinned to
`sha256:329af3111a7f387990ff803874b5134f5de087f919482904a29cbd6e9ed3431d`,
and the independently approved preparation worker and verifier remained pinned
to `sha256:eb6bded860bc95877b6475b30cb5644a7d42cfa9eb58b7f15d9ae5c9c85dcc7e`.

## Running the cloud checks

Use an explicitly authorized tenant and account. Provision an isolated custom
VPC/subnet and one TCP 8080 ingress rule with both source and target tag
`shifter-preparation`. Do not peer this qualification network with tenant
workload networks. The image checks need no internet access from guests.

From the repository root, use the existing locked platform dependencies:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=shifter/packer \
  uv run --frozen --project shifter/shifter_platform python -m preparation.qualify \
  --account '<operator-account>' --project '<tenant-project>' --zone '<zone>' \
  --subnetwork 'projects/<tenant-project>/regions/<region>/subnetworks/<subnet>' \
  --base-image 'projects/<publisher>/global/images/<concrete-image>' \
  --base-image-id '<immutable-provider-id>' \
  --scanner-image 'projects/<publisher>/global/images/<concrete-scanner>' \
  --scanner-image-id '<immutable-scanner-id>' \
  --context-digest '<verified-contained-context-digest>' \
  --record '<new-private-receipt-filename>'
```

The receipt filename is created exclusively in the current directory; paths and
existing files are rejected. The runner records actual input measurements, candidate lineage, independent
output measurements, a functional boot result and cleanup. It never overwrites
an earlier receipt. The final cleanup removes every resource bearing this
operation's ownership label, including the unadmitted candidate image, and
requires empty provider readback. It does not modify the tenant's image mapping
registry. Remove the isolated network and firewall after qualification if they
are not subsequently managed by an installed preparation grant.

Full profile qualification also requires validating the authored public
requirement, associated input manifests and trust policy, then exercising the
approved worker images, durable controller and inventory admission boundary.

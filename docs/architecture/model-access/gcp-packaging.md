# GCP model broker deployment package

M06 / #2123 supplies disabled deployment infrastructure for PLAT-202. M05
owns the executable broker and private Engine control server, M07 the Vertex
adapter, M08 admission/enrollment projection, and M10 independent deployed
proof. A configured endpoint or successful render is not a qualified model
service. Do not enable this package with an image missing those consumers.

The file-backed inventory restrictions below describe the current package.
[#2243's source-management boundary](source-management-preflight-2243.md)
permits platform-project Vertex with distinct invocation/broker identities and
tenant-managed source publication.

## One deployment configuration

`settings.model_broker` is a closed GCP installation block. Absence means
`enabled: false`; no new GSA, model role, VIP, DNS zone or workload is created.
Enabled configuration requires hostname, exact private IPv4 VIP, admitted
range subnets, separate versioned broker/control TLS Secret names, a CA
ConfigMap name, and a bounded map of model project IDs to stable
invocation GSA account IDs. `global_access` defaults false; explicitly enabling
it permits cross-region private LB clients, not global provider routing.
The platform project, dynamic-secret project, or another project may be selected
as a source. Broker and invocation identities remain distinct, and exact-target
IAM applies equally when projects coincide. Terraform also checks that admitted
subnets belong to the configured range network and the VIP belongs to the GKE
subnet. These are deployment-owned coordinates, not scenario fields or
alternative quota-pool identifiers.

`shifter-config render` supplies the typed Terraform bridge. Environment →
platform-core → portal/iam create the identities. Platform-core owns the
reserved internal VIP and private DNS zone visible to platform and range
VPCs. Existing peering carries the route. GKE owns the internal passthrough
load balancer and health-check/backend firewall realization for the Service.
The release must retain that controller authority and verify its actual rules.
No blanket range-to-node/pod/management allow is added by this package.

`project_model_broker` validates Terraform output and the real bounded catalog,
then creates Helm transport values. Local bootstrap and Actions share the
same readback check against current root settings, including platform project
and region, before invoking that projection.
The Actions Kustomize compatibility lane invokes `render_model_broker.py`:
it renders the actual chart and selects its broker/control resources and the
application egress policies that must exclude the broker. At the combined
manifest boundary, every incumbent platform egress policy receives the broker
exclusion, independent of chart, Kustomize or generated names. The dedicated
broker policy owns DNS as well as control/provider/identity transport. This
narrowing updates the existing policy objects before applying broker workloads.
The control deployment checksum binds the actual combined `platform-runtime`
ConfigMap data, so config-only releases also roll its pods. Control inherits
the applied Engine worker's runtime references (including the Actions Secret
reference), and the enabled control deployment participates in the existing
post-secret-sync restart. Broker runtime references remain isolated. It does not
copy manifests or alter provisioner admission. Disabling in Actions removes and waits for the
explicit broker/control resource set with foreground deletion and a bounded
wait for dependent pods before restoring application policies. The deployment's ordinary manifests
restore its normal application policies. Changes in the chart therefore
reach both deployment paths.

For a tenant with a checked-in GCP model overlay template, the branch-dispatched
workflow binds the deployment project and current public CA, seals the catalog
digest, and applies that overlay in both the Terraform preparation and workload
jobs. The environment variable overlay remains a fallback for deployments
without a checked-in template. The compatibility renderer projects the enabled
catalog path and digest into `platform-runtime` and mounts the catalog ConfigMap
in every deployment that consumes that runtime ConfigMap. This keeps the portal,
workers, and control service on the same catalog revision. The workflow also
retires explicitly inventoried qualification objects only after their generated
replacement policies are present.

## Process and credential inventory

| Process | Image/entry | Configuration and credential authority |
| --- | --- | --- |
| Broker | Attested platform digest; `python -m model_broker` supplied by M05, bypassing `entrypoint.sh` | Explicit `MODEL_BROKER_*` env keys in `BROKER_RUNTIME_ENV_KEYS`; mounted catalog/identity inventory, exact TLS Secret and CA ConfigMap; dedicated KSA/GSA. No `platform-runtime`, Django initialization, database, Redis, portal secrets or Kubernetes token/RBAC. |
| Engine control | Same platform digest; application entrypoint runs `python -m engine.model_access_control`, supplied by M05 | Existing worker application authority, separate control TLS Secret, exact broker subject and control audience. Dedicated private listener on 8444, no public Ingress. |

Both deployment adapters use `render_model_access_env` to project the root
activation flag, catalog path and digest into the control container's explicit
environment. These values override inherited runtime defaults only for control,
which mounts the catalog. The closed Helm contract rejects missing settings,
unmounted paths and digest mismatches; the process revalidates the artifact.

The broker catalog is mounted at `/etc/shifter/model-access/catalog.json` and
its identity inventory alongside it. `shared.model_access.runtime` is the
Django-free bounded loader reused by application settings; it reads at most
2 MiB plus one byte, rejects duplicate/invalid catalog JSON, compares the
canonical digest, and rejects enabling a disabled catalog. Kubernetes packaging
has a separate conservative 96 KiB UTF-8 budget for the catalog plus identity
inventory, enforced by both installer projection and Helm. This reserves room
for metadata and client-side apply annotations below Kubernetes object limits;
it does not change the shared 2 MiB runtime contract. Larger catalogs must be
rejected before deployment until another mounted-artifact transport is supplied. The identity
inventory is deployment-owned; M05/M07 must resolve only catalog-approved
references against that closed map, never request-supplied service accounts.
The published installation contract gives broker env outputs their own
`model-broker` process role. The image verifier includes both optional
components only on validated enablement and still requires exact image IDs.

The broker's only token-issuance grant is a custom role containing
`iam.serviceAccounts.getAccessToken`, attached to each exact target GSA.
Each target has only `aiplatform.endpoints.predict` in its selected project.
No key resource, delegation chain, project-wide token creator, `actAs`, key
admin, endpoint creation or broad `aiplatform.user` is part of this path.
Broker-to-Engine ID tokens use its own GKE metadata identity; they are not
provider access tokens. Legacy guest Vertex roles are neither reused nor
retired by M06; M11 owns that coordinated migration.

## Effective network boundary

All NetworkPolicy grants are additive. The broad provider-API
and database/Redis chart policies always exclude `model-broker`, including
while disabled replicas drain; a narrow policy alone
would not remove their access. Broker egress consists of controlled kube-dns,
private control pods on 8444, fixed Google private API VIP on 443, and the GKE
Dataplane V2 metadata endpoint on TCP 80/8080. Logs use container stdout and
the existing node collector; no additional telemetry network lane is opened.
M05/M07 still enforce fixed origins/methods, verified TLS, redirects/address
checks and metadata-only telemetry. IP policies cannot authorize hostnames
or make untrusted content safe.

The private Service exposes 443 → broker TLS on 8443, with
`externalTrafficPolicy: Local`, explicit source ranges and regional access by
default. Engine's trusted current subnet binding must be compared with the
socket peer using `peer_matches_binding`; forwarding headers never supply
source authority. GCE instance requests explicitly disable IP forwarding.
OpenVPN forwarding gateways are not qualified model clients.

`broker_egress_destination` defines `model-broker-egress/v1` with exact `vip`
and `port: 443`. The GCE firewall consumer delegates capability validation to
`gcp_range_cell_model_broker`. It requires that capability explicitly,
compares it with the deployment-configured VIP, and rejects strict `none`,
forwarding/SA-bearing clients, Private Google Access, VPN and preprovisioned
firewall bypass. It preserves default/peer/management denies and opens only
the exact /32 on 443. Both `render_range_cell_plan` and
`build_raes_range_cell_plan` accept a `GceEgressPolicy` containing the existing
egress mode and the explicit broker capability, then pass it to the firewall
consumer; integration tests inspect their resulting rules and reject
strict zero egress, a mismatched VIP and Private Google Access.

M06 did not enroll production ranges: its operation runners supplied no broker
capability, and its configuration loader supplied no broker VIP. M08 added those
admission and deployment bindings in its generation-owned projection (see
[Guest egress projection](#guest-egress-projection)). Global
deployment enablement alone grants no range access. Similarly,
`peer_matches_binding` is a tested transport contract for the M05 listener;
this package has no production listener calling it. These tests establish the
helper and plan-builder behavior, not active enrollment or peer authentication.

## TLS, drain and evidence

Both broker and control have two replicas, anti-affinity and a PDB requiring
one available replica. The broker uses a zero-unavailable rolling update to support
rotation. The 150-second termination grace includes ten seconds for endpoint
withdrawal and the design's 120-second maximum admitted request, with time
for settlement. M05 must stop admission on termination and fence continuation;
probes must be provider-independent and never send paid prompts.

The branch-dispatched prepare job owns the broker CA signer Secret, distinct
versioned broker/control TLS Secrets, and public CA ConfigMap. On first adoption
it replaces unmanaged preflight certificates. Later runs verify the existing
signer and leaf keys, CA signatures, DNS/IP SANs, and at least 14 days of leaf
validity; they fail rather than silently replacing a live certificate. The CA
must have at least 30 days remaining. Private keys never enter Terraform state,
chart values, ConfigMaps, or evidence; only the public CA enters the checked
runtime overlay and trust ConfigMap. Mounts omit `subPath`. Before expiry,
rotation requires reviewed versioned Secret names and root intent, a checked
rollout, and old/new CA overlap for existing guests. Verify both replicas after
rollout and retain the old Secret until old connections and pods drain. A failed
rotation leaves admission disabled; never disable certificate verification.

Use the [operator probes](../../ops/model-access-gcp-probes.md). Local tests
exercise render/schema, IAM guard negatives, policy union, catalog binding,
source comparison, exact egress and unsafe combinations. Live LB/CNI source
preservation, stolen-token rejection, effective provider permission/model
availability, TLS rotation with streams and revocation remain M10 evidence.

Primary references: [GKE internal load balancing](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/internal-load-balancing),
[GKE NetworkPolicy and identity transport](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/network-policy),
[exact-target access-token permission](https://docs.cloud.google.com/iam/docs/reference/credentials/rest/v1/projects.serviceAccounts/generateAccessToken).

## M06 acceptance mapping

PLAT-202's credential plumbing and endpoint-routing clauses are the M06
implementation slice. Policy/shard allocation is the shared foundation in
#2118; the delivery graph assigns runtime admission, accounting and provider
execution to their respective implementation milestones. M06 makes no claim
that the entire umbrella requirement is operational.

| Issue #2123 criterion | Artifact of record | Verification |
| --- | --- | --- |
| Dedicated isolated broker and canonical configuration | `installation/gcp_model_broker.py`, `bundle_gcp.py`, Helm `model-broker.yaml`, `render_model_broker.py` | Installation projection and catalog tests; real Helm render and combined-manifest tests; exact running-image inventory tests. |
| Exact model identity authority and onboarding | Terraform `portal/iam/model_broker.tf`, `probe_model_broker.py` | Existing IAM guard with escalation mutations; onboarding readback failures and positive controls. |
| Explicit broker egress with retained denies | `shared/model_access/network.py`, `gcp_range_cell_firewall.py` | Effective rules deny neighboring addresses/ports, reject strict none, unsafe clients and overlapping intra-range destinations. |
| Source-preserving private transport and trusted binding | Helm internal Service, existing GKE Dataplane V2, `gcp_range_cell_resources.py`, `peer_matches_binding` | Rendered Service/source ranges, foreign/header-shaped source tests, operator LB/CNI probe procedure. Live qualification is the M10 release gate. |
| Broker egress, private Engine TLS and rotation | Helm `model-broker-network.yaml`, `model-access-control.yaml`, versioned TLS references | Additive policy selection tests, Kubernetes schema/security checks, documented rotation and stream probes. |
| Guard and quality integration | Existing IAM guard, GCP quality job, chart-derived Actions lane, ADR-059/061 | Escalation tests, full repository policy/completion gates, configured reviews and CI; existing provisioner admission retained. |

### Guest egress projection

The applied broker VIP is forwarded as `MODEL_BROKER_GUEST_VIP` with public TLS
coordinates. Only an admitted guest enrollment projects it into the RAES
firewall capability; enabling the installation alone opens no range egress.
The realizer rejects missing or non-private VIPs, creates only TCP 443 to that
exact /32, and retains the fixed firewall name for teardown and residual
inventory even after broker configuration is disabled. The provisioner Job
environment allowlists carry this non-secret value through both GCP renderers.

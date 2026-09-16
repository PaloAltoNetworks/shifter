# Prepare artifacts in an existing GCP tenant

Artifact preparation is an explicit operation before range launch. It builds an
artifact only when the pack author permits the exact installed materialization
profile, specification and fixed inputs. A missing image does not start a build.
Ordinary launch resolves admitted inventory and never waits for a builder.

Shifter maintains the [contained GCE profile](../../shifter/packer/preparation/PROFILE.md),
its worker, build contexts and independent verification code. The maintained
[HTTP specimen](../../scenario-dev/preparation-http-smoke/) demonstrates a pack
that selects that profile. The [qualification record](../../shifter/packer/preparation/QUALIFICATION.md)
distinguishes physical image checks from tenant workflow evidence.

## Separate permissions

| Action | Required authority |
| --- | --- |
| Store and register a private pack | Bucket upload access, then normal CMS authoring permission |
| Provision the preparation installation | Cloud and Kubernetes operator access |
| Activate or revoke its application grant | `engine.manage_preparation_grants` plus actual cloud/Kubernetes readback access |
| Install, disable or retire an adapter | `engine.manage_preparation_adapters`; API scopes `cms:preparation-adapters:read` / `cms:preparation-adapters:write` |
| Request, inspect, cancel or retry preparation | `engine.prepare_artifacts`, access to the scenario, and API scopes `cms:preparation:read` / `cms:preparation:write` |

Token scopes restrict the caller's existing role. Staff/content authoring does
not confer adapter or cloud-grant administration. Pack upload, registry pull,
executable approval and cloud IAM are separate decisions. A private adapter is
trusted executable code under its approved role; the installation does not
promise a sandbox for arbitrary code with cloud credentials.

## Install the optional runtime

Use the platform management commands from the deployed software version in an
operator environment with tenant database access. Rendering needs no cloud
credentials. Activation needs the operator's Google Application Default
Credentials and Kubernetes access as well as the application actor. Do not give
the running controller broad IAM administration or cluster administration just
to run activation. Resolve runtime secrets through the deployment's existing
secret mechanism; never place their values in installation JSON or arguments.

The operator supplies an `installation.json` matching
[`PreparationInstallation`](../../shifter/shifter_platform/shared/cloud/preparation_installation.py).
Its nested `grant` matches
[`PreparationGrantConfiguration`](../../shifter/shifter_platform/shared/preparation_grant.py).
The principal fields are:

| Field | Meaning |
| --- | --- |
| `grant.protocol`, `grant.backend` | `shifter.preparation-grant/v1`, `gce` |
| `grant.project_id`, `grant.zone`, `grant.namespace` | Tenant cloud scope and dedicated `shifter-preparation-*` worker namespace |
| `grant.subnetwork` | Concrete `projects/PROJECT/regions/REGION/subnetworks/NAME`; the renderer creates a VPC with the same `NAME` |
| `grant.builder_service_account`, `verifier_service_account`, `cleanup_service_account` | Three distinct `preparation-*` Kubernetes identities |
| `grant.approved_worker_images`, `approved_verifier_images`, `cleanup_image` | Exact private `registry/repository/image@sha256:DIGEST` approvals for each role |
| `grant.registry_prefixes`, `image_pull_secrets` | Allowed private registry path prefixes ending in `/`, and existing pull-secret names; use an empty secret list when node registry access supplies pulls |
| `grant.permissions` | `gce-image-build` and `private-artifact-storage` for the maintained adapter |
| `grant.trusted_input_bindings` | Map from each authored `trust_policy_ref` to approved `BoundInput.digest` values; each digest binds the actual descriptor and associated input manifest |
| `grant.scanner_image`, `scanner_image_id` | Independently approved concrete scanner image and immutable numeric GCE image ID |
| `grant.worker_endpoint` | Tenant HTTPS endpoint ending `/api/v1/cms/artifact-preparation/workers/`; this installation's network policy requires reachable public HTTPS on port 443 |
| `grant.max_duration_seconds`, `max_concurrent_operations`, `max_disk_gb` | Per-phase deadline, concurrent operation limit, and individual disk size limit |
| `platform_namespace`, `controller_image` | Existing platform namespace and exact platform image digest containing the controller command |
| `service_accounts` | Four distinct GSA emails keyed by `builder`, `verifier`, `cleanup`, `controller`, all in the tenant project |
| `network_cidr`, `cluster_name`, `cluster_location` | Unused private subnet with a `/20` to `/28` prefix and existing GKE cluster identity |
| `input_images` | Additional concrete input images requiring cloud image-use access; private publisher IAM remains the publisher's responsibility |
| `controller_secret_ids` | Secret names for `DB_SECRET_ID`, `APP_SECRET_ID`, `REDIS_SECRET_ID`; optional startup secret references are explicitly controlled |

The controller name derives from the scope digest. The generated installation
has four separate Workload Identity bindings, role-specific Compute permissions,
a private VPC without internet routes, NAT or peering, one contained HTTP probe
firewall, restricted Pods, bounded Jobs, admission policy and network policies.
Build and scanner guests receive neither service accounts nor external IPs.
The controller reads provider state and three named platform secrets; workers
receive no database credentials or Secret Manager payload permission.

Render into a dedicated Terraform root and state prefix:

```sh
mkdir preparation-runtime
python manage.py render_preparation_runtime --configuration installation.json \
  --format terraform > preparation-runtime/main.tf.json
terraform -chdir=preparation-runtime init \
  -backend-config='bucket=EXISTING_TERRAFORM_STATE_BUCKET' \
  -backend-config='prefix=preparation/INSTALLATION_NAME'
terraform -chdir=preparation-runtime plan -out=installation.plan
terraform -chdir=preparation-runtime apply installation.plan

python manage.py render_preparation_runtime --configuration installation.json \
  --format kubernetes > preparation-runtime.json
kubectl apply -f preparation-runtime.json
python manage.py install_preparation_grant \
  --actor OPERATOR_USERNAME --configuration installation.json
```

Review the actual plan before applying it. When adopting an existing preparation
network through Terraform import, remove that network's default internet route
explicitly: `delete_default_routes_on_create` does not remove routes on imported
networks. Activation rejects remaining internet routes, peering or NAT. It also
checks installed custom permissions, conditional bindings, Workload Identity,
named secret grants, Kubernetes admission/RBAC/isolation, and controller rollout.
Rendering or applying a document alone never activates a grant. Organization
administrators retain their authority over inherited IAM and cluster policy.

A change to cloud or worker authority uses a new namespace and dedicated identities/network.
Retain the earlier installation while its operations require cleanup. This
includes changes to approved worker/verifier image sets; do not retarget a
running installation's identities. For a platform-controller release update,
change only `controller_image`, render/apply the Kubernetes resources, and rerun
grant activation. Readback verifies the actual rollout and refreshes the audited
installation proof while the worker grant and existing operation inputs remain
immutable. Controller upgrades cannot change IAM, network, worker pins or trust.
New adapter versions using already-approved images can share an installation.

## Add private content and executable adapters

Private packs can be installed after tenant setup. The optional Terraform module
[`raes-package-storage`](../../platform/terraform/gcp/modules/raes-package-storage/)
creates a bucket with uniform access, enforced public-access prevention,
versioning and a bucket-specific read grant for the existing portal GSA. The
module's `access_log_bucket_name` input must identify the tenant's terminal GCS
audit-log bucket; the uploader's write authority is managed separately. Set
`SHIFTER_RAES_PACKAGE_BUCKET` and optionally `SHIFTER_RAES_PACKAGE_PREFIX` in the
tenant's managed runtime configuration, then roll the platform processes.
This is a configuration change; subsequent uploads require no platform rebuild.

Upload one immutable archive, register its object key and canonical digest,
and run the normal conformance command described in
[content ingestion](content-ingestion.md). Set the existing scenario metadata's
`staff_only` flag when the pack should be restricted to staff. Private storage
does not by itself restrict catalog access inside the tenant.

The object resolver accepts the pinned env-packs `export_pack_archive` format
(pack-relative files) and archives with one containing pack directory. Flat
exports are staged under the registered scenario name before the same upstream
identity, inventory and digest checks; archive paths never choose that name.

An adapter manifest follows
[`AdapterManifest`](../../shifter/shifter_platform/shared/raes/preparation_contract.py).
It contains `protocol: shifter.artifact-preparation/v1`, a stable `adapter_id`,
immutable `version`, `backend: gce`, `worker_image`, `verifier_image`,
`verification_contract: shifter.gce-raw-disk/v1`, required permissions, and
`specifications`. Each specification carries the full public RAES reference,
complete locked inputs and the constraint kinds that its verifier supports.
Image tags, partial profile-name matches and unapproved executables are rejected.

For another contained procedure, derive a private image from the maintained
worker and copy its context into `/app/preparation/contexts/SPECIFICATION_ID`.
The profile document defines the context digest and input/verification contract.
Qualify the resulting procedure and independently approve its verifier image
before adding their exact digests to a new cloud installation. Publish those
images only to the operator's private registry. Neither the platform image nor
upstream packs need to change for another implementation of a supported contract.
A new backend or incompatible worker/verifier protocol requires platform support.

With the returned grant UUID, call:

```text
POST /api/v1/cms/preparation-adapters/
{"grant_id":"GRANT_UUID","manifest":{...complete immutable manifest...}}
```

The response returns the registration UUID and manifest digest. Installing the
same exact version is idempotent; changing its contents requires another version.
`GET` on the same path lists registrations only to authorized administrators.
No private manifest enters public discovery metadata.

## Prepare, inspect and launch

Request the public authored requirement address, not the compiled planner address:

```text
POST /api/v1/cms/artifact-preparation/
{
  "scenario_id":"preparation-http-smoke",
  "requirement_address":"provision.nodes.web.source.source-artifact",
  "adapter_id":"ADAPTER_UUID",
  "specification_id":"http-smoke"
}
```

The `202` response contains `id`, `state`, `failure_code`, `cleanup_pending` and
`reused`. Poll `GET /api/v1/cms/artifact-preparation/OPERATION_UUID/`. Identical
requests by the same operator converge on the existing operation. When ordinary
inventory already satisfies the requirement, the response is `available`,
`reused: true`, `id: null`; no operation or worker is created and no other
operator's private operation ID is disclosed.

The controller runs input verification, build, output verification and cleanup
as separately pinned Jobs. Output verification measures the raw disk,
independently checks the profile's guarantees, and boots a fresh guest for its
functional probe. The controller independently reads cloud ownership and image/
disk/instance lineage before committing availability. A worker receipt alone
cannot update inventory. Failed or stale evidence cannot mark the image ready.

`available` means inventory admission committed. Wait for
`cleanup_pending: false` to establish that temporary resources were removed and
the operation's capacity was released. The admitted image remains for ordinary
range launches. Its numeric image identity is persisted in the range binding
and checked again before creation and against the realized boot disk.

Then launch the registered scenario through the normal range API/UI. Launch
rechecks availability, exact authored constraints and the selected backend.
Preparation does not grant scenario access, workspace rights or range capacity.

## Cancellation, retries and retirement

`POST /api/v1/cms/artifact-preparation/OPERATION_UUID/cancel/` accepts `{}` and
fences admission immediately. Cleanup continues with the pinned cleanup image.
`POST .../retry/` also accepts `{}` and restarts only eligible cleaned terminal
work with the original immutable input; it cannot substitute another recipe,
image, cloud scope or grant. Cleanup retries retain capacity until provider
readback establishes that temporary resources are absent.

`POST /api/v1/cms/preparation-adapters/ADAPTER_UUID/state/` accepts
`{"state":"disabled"}`, `enabled`, or `retired`. Disabled versions block new
requests; retired versions cannot be enabled again. Existing attempts keep
their exact pinned registration and cleanup authority. Emergency cloud-grant
revocation fences ordinary work and admission:

```sh
python manage.py install_preparation_grant --actor OPERATOR_USERNAME \
  --revoke GRANT_UUID
```

Revocation preserves cleanup. Do not remove the old namespace, cloud roles,
private image access or network until its pending cleanup finishes. Admitted
images have a separate retention lifetime and must not be removed while live
range bindings rely on them. Preparation cleanup never deletes admitted images.

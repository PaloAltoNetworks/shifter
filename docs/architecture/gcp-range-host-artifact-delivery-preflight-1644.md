# GCP range-host artifact delivery preflight

Issue: GitHub #1644, "security: range-guest service account has project-wide
GCS read (cross-tenant exposure)".

This is requirement-free pre-implementation guidance. It does not implement the
issue or prescribe a new range lifecycle.

## Decision

Treat every service account attached to a participant-controllable GCE guest or
Docker host as a participant-reachable identity. `cloud-platform` is a required
OAuth transport scope for the existing host Secret Manager use; it is not an
authorization boundary. Metadata blocking inside a container is defense in
depth, not evidence that a root compromise of the VM host cannot use the token.

Remove project-level Cloud Storage access from `range_host`. Do not replace it
with bucket-level `objectViewer` on the shared assets bucket: that bucket
contains tenant artifacts, so a host compromise could still list or read other
tenants' objects. The current host-side GCS need is the Polaris smoketest
tarball. Deliver that exact object as a short-lived, provisioner-created signed
download capability, using the existing provisioner `ObjectStorage` protocol and
the GCP V4-signing implementation. The provisioner already has the scoped
assets-bucket read role and self-scoped `signBlob` grant needed to mint it.

The signed capability is a private bootstrap input, never a deployment setting,
Terraform input/output/state value, range-cell result, database field, event,
log field, metric label, error envelope, shell argv, or generated runtime-env
value. It may be available to the compromised host while valid, but authorizes
only the immutable object version selected for that range bootstrap. The host
retains logging/monitoring writes and its existing per-range Vertex-secret grant;
those are separate capabilities and must not regain broad storage access.

## Canonical incumbents and seam

- IAM/resource ownership: `platform/terraform/gcp/modules/portal/iam`,
  `platform/terraform/gcp/modules/portal/gcs`, and the existing
  `assets_bucket_name` output. Keep the workload/resource matrix authoritative;
  do not introduce an independently named host-artifact bucket or IAM module.
- Delivery: `provisioner.cloud.types.ObjectStorage`,
  `cloud.gcp.storage.GCPObjectStorage`, `PolarisRangeBootstrapPlan`, and the
  existing provisioner self-`signBlob` binding. Extend this delivery seam rather
  than adding a broker, service-account key, guest-side ADC flow, or a second
  signed-URL implementation.
- Runtime shape: `POLARIS_TESTS_BUCKET`/`POLARIS_TESTS_KEY`,
  `scripts/gcp/render_runtime_env.py`, `engine.ecs._GCP_PROVISIONER_ENV_KEYS`,
  and their inventory tests remain the non-secret object-selection contract.
  Validate their shell-template values with the existing config/rendering path;
  do not interpolate unvalidated bucket/key data into root-executed shell.
- Errors/logging: use `CloudStorageError`, provisioner `log_redact`/
  `safe_log_value`, and existing classified setup failures. Do not expose a
  signed URL, Google SDK error, bucket/key, metadata token, or IAM policy to a
  participant or API caller.

The extensibility seam is a typed private **exact object version + bounded
expiry** bootstrap-delivery value produced immediately before the host setup
step. A later host-required artifact can use the same producer only after it is
explicitly selected by trusted runtime configuration and has a distinct
authorization/test entry; it must not turn this into a general guest object
storage client or an unbounded prefix capability.

## Cross-cutting gates and verification

| Layer | Required outcome |
| --- | --- |
| Terraform/IAM | `range_host` has no project-level storage role. Extend the existing `check_tf_gcp_iam_resource_scope` checker and effective-permission fixtures to reject direct member, binding/policy, local-map, and equivalent custom-role object-read grants for `range_host` and any attachable range-host-pool identity, while allowing the existing logging/monitoring roles. |
| Config/rendering | Keep `POLARIS_TESTS_BUCKET` and key validation in the existing renderer/config path. The signed capability is generated at provision time and is not added to ConfigMaps, Helm values, runtime inventory, or a public schema. |
| Compute/metadata and OS | Test the realistic root-on-guest-host attacker, not only a blocked participant container: a metadata token must be unable to list/read any GCS bucket or arbitrary object, including a cross-tenant sentinel and Terraform state. Container metadata blocks remain tested as defense in depth. |
| Bootstrap delivery | Bind the URL to the trusted bucket/key and immutable GCS generation where supported, use a short bounded expiry, and fail the setup with a sanitized classified error when minting or download fails. Do not fall back to guest ADC, broad IAM, or an unsigned URL. |
| Observability/error envelope | Preserve only request/range correlation and bounded failure class. Redact URL query strings, object identifiers where tenant-sensitive, metadata tokens, and SDK/provider bodies from setup output, events, and API errors. |
| Readiness validation | Update the range-escape evidence contract so `metadata_server` means **no cross-tenant credential capability**, not merely that a participant container cannot reach metadata. A successful container-only probe cannot clear a root-on-host identity boundary. |

## Boundaries and anti-patterns

- No new service account per range, key distribution, GCS broker, storage
  schema, database persistence, public API/DTO, controller, workflow, or
  exception hierarchy.
- No change to the OAuth `cloud-platform` scope merely to hide the IAM defect;
  Secret Manager requires it for the existing Vertex-key path.
- Do not use a project role, broad custom role, shared-assets bucket viewer,
  `allUsers`, a metadata firewall claim, or an object-prefix condition that is
  broader than the trusted artifact contract as a shortcut.
- Do not expand the change into a redesign of GDC, Vertex credentials, artifact
  publication, range topology, or the generic object-storage protocol. The
  required boundary is guest access to platform storage, not all host cloud use.

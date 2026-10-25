# GHCR VM Guest Images Preflight (#2297)

Status: superseded by #2309

Date: 2026-09-19

> **Superseded (#2309).** This note scoped publishing Kali/Ubuntu **qcow2 VM
> disks** to GHCR for the GDC VM Runtime importer. #2309 retires that path: the
> supported GCE tenant bootstrap now consumes **GCE-native disk tarballs**
> (`shifter-gce-<role>`, artifact type `application/vnd.shifter.gce-image.v1`)
> imported as native GCE images. GDC is removed root-and-branch in #2311, and
> private-package credentials are tracked in #2312. The guidance below is
> retained for historical context only; see
> [`gcp-guest-images.md`](./gcp-guest-images.md) for the current contract.

This note fixes the boundary for publishing the existing basic Kali and Ubuntu
**VM disks** in GitHub Container Registry. It does not authorize changing a
tenant's selected boot source.

## Decision and boundary

Publish a versioned OCI **VM-disk artifact**, not an application container, for
each logical guest role:

| Role | Package |
| --- | --- |
| Kali | `ghcr.io/brad-edwards/shifter-vm-kali` |
| Ubuntu | `ghcr.io/brad-edwards/shifter-vm-ubuntu` |

The artifact payload must be the same bootable qcow2 output already exported
by `packer-gcp.yml`; a container root filesystem, Dockerfile, or a repackaged
GCE image is not an acceptable substitute. Publish a release/version tag for
operator discovery and record its immutable manifest digest. Runtime references
must use `oci://ghcr.io/brad-edwards/<package>@sha256:<digest>` (or the
equivalent `docker://` spelling accepted by the existing resolver), never a
mutable tag. The package documentation must state package name, version tag,
manifest digest, payload format, supported GDC VM Runtime version, visibility,
and required registry access.

`_resolve_image_source` already owns conversion of `oci://`, `registry://`,
and `docker://` to the GDC `source.registry` form. The implementation must
extend that canonical seam and its tests if stricter reference validation or
registry credentials are needed; it must not add a second image-source parser
or a parallel `GDC_GHCR_*` settings model.

Before making an OCI artifact consumable, prove with the deployed GDC VM
Runtime CRD that its registry importer accepts the selected OCI artifact layout
and qcow2 media type, preserves the digest-pinned reference, and boots both
guests. The repository has no checked-in CRD schema or registry-credential
field for `source.registry`. Therefore private-package support is blocked until
that CRD-supported credential shape is known and can be carried through the
existing Secret Manager reference → runtime environment → Kubernetes-secret
path. Do not place a PAT, `dockerconfigjson`, or registry credential in a
ConfigMap, Packer variable, workflow output, or artifact. A public, digest
pinned package may use the existing credential-free registry source only after
the importer proof succeeds.

## Existing contracts to preserve

- The GCP GDC path today builds a GCE image and exports `<role>.qcow2` to GCS;
  `GDC_<ROLE>_IMAGE_URL` is the sole tenant bootstrap selection seam. See
  `docs/architecture/gcp-guest-images.md`, `scripts/bootstrap/gcp_control_plane.py`,
  and `shifter/engine/provisioner/config/_gdc.py`.
- GCE range cells consume GCE image references, not GDC VM Runtime disk URLs.
  AWS consumes AMIs via `/shifter/ami/*`. Neither path consumes these GHCR VM
  artifacts.
- Packer build protection, GCP candidate validation/promotion, evidence labels,
  WIF, and the no-secret-on-argv rules in `.github/workflows/packer-gcp.yml`
  remain authoritative. GHCR publication must not turn a build tag into a
  qualification claim or advance an image family.
- Bootstrap remains optional: its current default is `GCP_RANGE_BACKEND=gce`;
  it must continue to render the existing GCS URLs unless an operator explicitly
  supplies the digest-pinned GDC role URL. Publication alone must not add a
  required image-qualification step or alter default tenant bootstrap.

## Required guards

- Keep publication in the existing protected-ref, least-privilege image-build
  workflow family; use `GITHUB_TOKEN` package write scope only in the publishing
  job and do not grant cloud identity or package-write permission to pull-request
  jobs. Keep actions SHA-pinned and retain actionlint, Packer tests, and ADR
  guard coverage.
- Validate the logical role (`kali` or `ubuntu`), package allowlist, OCI scheme,
  lower-case package path, and exact `sha256` digest once at the canonical GDC
  image-source/config boundary. Reject tags, arbitrary registry hosts, embedded
  credentials, query/fragment syntax, and unsupported media/layouts before a
  Kubernetes mutation. Error messages may identify role/package/digest but must
  never include credential material or a secret payload.
- Reuse `GDCVMRuntimeConfig`, the bootstrap renderer, static secret-reference
  model, `_resolve_image_source`, `safe_log_value`/`safe_log_fingerprint`, and
  the existing manifest/config tests. Do not introduce a registry repository,
  DTO, exception hierarchy, logger, or duplicate env parser.
- The extensibility seam is `(logical role, source URL, immutable digest,
  access reference)`. Role-to-package mapping belongs with the existing GDC
  role profiles; any future registry needs a data/config mapping, not workflow
  branches keyed by tenant, pack, image alias, or provider.

## Non-goals and anti-patterns

- No conversion of VM images into runnable containers; no change to AWS AMI,
  GCE-family, scenario-Pod, or control-plane container contracts.
- No automatic bootstrap cutover, default qualification gate, package-private
  credentials, mutable `latest` consumption, or registry-host free-for-all.
- No publication of private scenario images, recipes, evidence, or guest
  secrets. The two public base roles remain the only scope.
- No claim that upload, attestation, or a package tag proves a disk booted.
  Existing candidate validation and a targeted GDC registry-import/boot proof
  remain separate evidence surfaces.

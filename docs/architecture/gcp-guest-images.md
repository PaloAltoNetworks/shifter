# GCP Guest Images

How Shifter range guest VMs (Kali, Ubuntu, Windows, DC) are built and made
available on GCP, and how that differs from the AWS path. This is the GCP
parallel to the AWS AMI flow. The supported GCP range backend is GCE range
cells, which consume **native GCE images** directly.

## The two platforms, side by side

| Concern | AWS | GCP |
|---|---|---|
| Image build | `shifter/packer/` (`amazon-ebs`) | `shifter/packer/gcp/` (`googlecompute`) |
| Build trigger | `packer.yml` (self-hosted runner) | `packer-gcp.yml` (GitHub-hosted + Workload Identity) |
| Build artifact | AMI | GCE image in family `shifter-<type>` |
| Image discovery | `/shifter/ami/<type>` SSM parameter | newest non-deprecated image in the `shifter-<type>` family |
| Guest boot source | `aws_instance` AMI id | GCE instance `source_image` (a native GCE image) |
| Runtime wiring | per-OS AMI id Terraform vars | `GCP_RANGE_<TYPE>_IMAGE` runtime env |

GCE range cells consume a native GCE image directly (an instance
`source_image`), so the range provisioner resolves each logical guest role
through `GCP_RANGE_<TYPE>_IMAGE` (a family URL or an exact image). A fresh
tenant does not need to re-bake these images.

## Reusable GCE base images (GHCR)

The protected `packer-gcp.yml` workflow (`publish_target=ghcr`) exports each
built base image to a **GCE-native disk tarball** (`disk.raw` in a `.tar.gz`,
the default `gcloud compute images export` output) and publishes it to GHCR as
an OCI artifact. The reusable minimum base set is Kali, Ubuntu, and DC:

| Role | GHCR package |
|---|---|
| Kali | `ghcr.io/brad-edwards/shifter-gce-kali` |
| Ubuntu | `ghcr.io/brad-edwards/shifter-gce-ubuntu` |
| DC | `ghcr.io/brad-edwards/shifter-gce-dc` |

Each artifact uses artifact type `application/vnd.shifter.gce-image.v1`, a
single layer of media type `application/vnd.shifter.gce-image.tar.gz`, a
discovery tag (`gce-<image-id>`), and provenance annotations binding it to its
protected build (`org.opencontainers.image.revision`, `com.shifter.image.role`).
Tags are for discovery only; the immutable digest is the contract.

At bootstrap time `gdc-bootstrap --import-public-base-images` discovers the
complete base set, validates every artifact and its provenance before mutation,
pins each digest, and imports the disks as native GCE images in the target project with
`gcloud compute images create --source-uri` (no conversion). An unchanged
digest reuses the existing image when its runtime guest features also match; a
changed digest or missing required feature creates a traceably named compatible
image and moves the `shifter-<role>` family head. The importer uses a
private per-invocation bucket in the selected project and region with uniform
bucket access, public-access prevention, and soft delete disabled. It deletes
every transfer object and the bucket on success or failure. It then writes
`GCP_RANGE_{LINUX,KALI,DC}_IMAGE` into the deployment Environment and overlays
the exact same values for the first local platform bootstrap. The standalone
`gcp-images` command retains the same import/publication behavior for refreshes.

Publish the base packages **public** so the import pulls them credential-free;
private-package credentials are tracked in #2312. Raw disk export does not carry
GCE image-level guest features, so every base is re-imported with
`UEFI_COMPATIBLE` for the runtime Secure Boot posture. The DC image is also
marked with the `WINDOWS` guest OS feature; its boot and premium licensing are
verified in the #2309 proof tenant run. As an
alternative to GHCR, `packer-gcp.yml publish_target=tenant` leaves the built
native image in the target project's family with no registry copy.

## Pipeline stages

```
packer-gcp.yml ─┬─ build   → GCE image  shifter-<type>-<timestamp>  (family shifter-<type>)
                └─ export  → gs://<bucket>/<type>-<id>.tar.gz  (disk.raw)
                   publish → ghcr.io/brad-edwards/shifter-gce-<type>@sha256:<digest>
                                   │
bootstrap: gdc-bootstrap --import-public-base-images
                                → discover + validate + import into the tenant project
                                   → gcloud compute images create --source-uri gs://…/<type>.tar.gz
                                   → GCP_RANGE_<TYPE>_IMAGE = projects/<project>/global/images/<name>
                                   │
range provisioner → GCE instance source_image = GCP_RANGE_<TYPE>_IMAGE
```

1. **Build**—`packer-gcp.yml` builds one guest type on a GCE builder VM and
   publishes it into image family `shifter-<type>`. Builders run internal-IP
   only (reached over IAP) so they comply with the project's
   `compute.vmExternalIpAccess` org policy. See `shifter/packer/gcp/README.md`.
2. **Export + publish** (`publish_target=ghcr`)—the same workflow exports the
   built image to the staging bucket as a GCE-native `disk.raw` tarball
   (`gcloud compute images export`, a Cloud Build job pinned to the builder
   subnet) and publishes it to GHCR with ORAS. Both the Cloud Build identity
   (`--cloudbuild-service-account`) and the daisy worker VM
   (`--compute-service-account`) are pinned to the `…-packer` build SA—this
   project's builds otherwise default to the Compute Engine default SA, which
   the build SA cannot `actAs`.
3. **Import + wire**—the opted-in `gdc-bootstrap` path (or standalone
   `gcp-images` refresh) discovers the GHCR packages,
   validates each artifact and its provenance, pins the digest, and imports the
   disk as a native GCE image (`gcloud compute images create --source-uri`,
   reusing an unchanged `READY` digest), then writes exact
   `GCP_RANGE_<TYPE>_IMAGE` values into the deployment Environment. The fresh
   bootstrap overlays those same values before running platform preconditions.
4. **Launch**—the range provisioner creates each GCE guest with
   `source_image = GCP_RANGE_<TYPE>_IMAGE`.

## Build mechanism (Workload Identity, no SA keys)

`packer-gcp.yml` authenticates with GitHub → GCP Workload Identity Federation,
provisioned by `platform/terraform/gcp/modules/cicd-github-oidc` (the GCP analog
of the AWS `github-oidc` IAM role). The module creates a Workload Identity pool,
a repository-scoped OIDC provider, a least-privilege `…-packer` build service
account, the builder subnet + IAP firewall, and the reusable base-image staging bucket.

Configure these once (`docs/dev/deploy-secrets.md`):

| Name | Kind | Source |
|---|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | secret | module output `packer_workload_identity_provider` |
| `GCP_PACKER_BUILD_SERVICE_ACCOUNT` | secret | module output `packer_build_service_account_email` in `gcp-build-dev` / `gcp-build-proof` |
| `GCP_PACKER_VALIDATE_SERVICE_ACCOUNT` | secret | module output `packer_validate_service_account_email` in `gcp-validate-dev` / `gcp-validate-proof` |
| `GCP_PACKER_PROMOTE_SERVICE_ACCOUNT` | secret | module output `packer_promote_service_account_email` in `gcp-promote-prod` |
| `GCP_PROJECT_ID` | secret | the project |
| `GCP_PACKER_SUBNETWORK` | variable | module output `packer_builder_subnetwork` |
| `GCP_PACKER_USE_INTERNAL_IP` | variable | `true` (IAP builds) |
| `GCP_GCE_BASE_IMAGE_BUCKET` | variable | module output `gce_base_image_bucket` |

## Kali (built on the debian-12 GCE base, no import)

GCP has no first-party Kali image (the only Marketplace listings are third-party
repackages, not an Offensive-Security-published image; AWS keys off the official
Kali Marketplace product, which has no GCP equivalent). The obvious workaround—
importing Kali's official generic-cloud disk—does **not** work on GCE: that
disk ships no Google guest environment, so it never gets metadata-based SSH-key
injection or GCE network setup and packer can never connect to it.

Instead the kali builder starts from Google's GCE-native `debian-12` image and
converts it to Kali Rolling in place, in its first provisioning script
(`scripts/kali/gce-debian-to-kali.sh`): it adds Kali's official apt repo and
keyring, `full-upgrade`s the base onto kali-rolling (with `--force-overwrite` to
clear the 64-bit `time_t` library-transition file conflicts), and re-asserts
Google's guest-environment apt repo so `google-guest-agent` survives the
conversion (the Kali repos do not carry it). The remaining `scripts/kali/*`
steps then install the Kali toolset, Caldera and Claude Code on top. No imported
base image and no `GCP_KALI_SOURCE_IMAGE` secret are required.

## GCE range-cell images (build → validate → promote)

The GCE range-cell backend (the GCP range path) consumes native GCE images
**directly**. The GHCR export/publish above is a separate cross-tenant reuse
mechanism that lands the same native GCE images in a fresh project. The
provisioner resolves each logical guest role
through `GCP_RANGE_{LINUX,KALI,WINDOWS,DC}_IMAGE` (a family URL or exact image),
and `load_gce_range_cell_config` validates the reference shape, disk type, and a
per-role **policy** minimum boot-disk size (not the actual source-image size)
before any Compute Engine call so a malformed value fails fast instead of after
a create attempt.

Pack-owned images are built and qualified by their authors, then consumed through
explicit image profiles. Core's workflow choices contain only platform base
images; adding a pack never adds an image-name dispatch branch.

An **immutable candidate image is the unit of validation and promotion**; a GCE
image family is a mutable deployment channel, not evidence that a particular
image was tested. The pipeline is three stages:

```
packer-gcp.yml         build    → GCE image  shifter-<type>-<ts>   (family shifter-<type>)
packer-gcp-validate.yml validate → boot the EXACT candidate in a disposable,
                                    isolated VM; publish ID-bound evidence
packer-gcp-promote.yml  promote  → bind candidate ID to run/attempt/artifact,
                                    verify copy, commit family, deprecate old head
```

1. **Validate** (`packer-gcp-validate.yml`) boots the concrete candidate in a
   disposable VM with the runtime range-cell posture (**no external IP**, IAP
   subnet, Shielded VM, project SSH keys blocked) and reboots it once. Evidence
   is gathered **by the runner over an IAP tunnel**, not self-reported by the
   guest: for Linux the runner SSH-executes the guest-agent health check and gates on
   its exit code; for a pre-promoted DC the runner probes AD over LDAP (an
   anonymous rootDSE query proving AD DS is serving the **expected forest**, with
   **no first-boot promotion**). The candidate boots with **no service account
   and no OAuth scopes**, so guest code cannot read a cloud token and mutate its
   own image labels; the runner (WIF) holds all label authority. Passing again
   after the reset proves a clean boot with no manual input. On success the
   workflow uploads one versioned, bounded evidence artifact, then labels the
   exact candidate with its numeric image ID plus exact run, attempt, artifact,
   and revision locators; the VM is always deleted. Only image types with
   a matching validator are selectable (generic Linux,
   `dc-prebaked`); the sysprepped `windows` and first-boot-promotion `dc` images
   are excluded. Per-container runtime health and seeded AD content that depend
   on per-range credentials are a runtime/range-smoke concern, not part of this
   candidate-boot gate.
2. **Promote** (`packer-gcp-promote.yml`) takes the **exact** validated candidate
   image name and numeric ID, verifies the protected run attempt and exact
   unexpired artifact, then copies that image outside the prod family. It verifies
   the copy is `READY` and reports the validated `sourceImageId` before attaching
   the family (derived from the source image) and deprecating the previous head.
   It never re-resolves "newest in the dev family" at promotion time, and a
   failed copy cannot advance the family channel.

### Pre-promoted DC (`dc-prebaked`) vs. generic Windows/DC

The `windows` and `dc` images are **sysprepped** (GCESysprep), so their
build-time WinRM credential is discarded by sysprep. The pre-promoted
`dc-prebaked` image is captured **un-sysprepped** on purpose—GCESysprep cannot
generalize a promoted domain controller—so it needs deliberate credential
hygiene rather than relying on sysprep:

- The identical authored machine/domain identity across ranges is
  intentional (isolated, identical ranges) and is preserved.
- The DSRM secret is **generated per build** and injected as a sensitive Packer
  variable; there is no committed default DSRM password in the release contract.
- A pre-capture cleanup provisioner strips build transcripts, the DNS-forwarder
  handoff, and the staged AD-content seed (which carries baked passwords) so no
  secret-bearing artifact ships in the disk.
- The **live** domain Administrator credential is rotated **per range at
  runtime** by `plans/dc_setup.py` (`DC_DOMAIN_PASSWORD`), not baked.

### First live validation run (operator verification)

The candidate-boot validation subsystem (`packer-gcp-validate.yml` and
`shifter/packer/gcp/scripts/validate/*`) is exercised in CI only for template,
workflow, and script **shape** (`packer validate`, `actionlint`, `shellcheck`,
and the structural and behavioral unit tests). Its live behaviour is GCP-only
and is not exercised until an operator dispatches the workflow against a real
project: the IAP tunnel to the candidate VM, the runner's SSH session, and
the DC LDAP rootDSE probe.

Treat the **first `packer-gcp-validate.yml` run per environment** as the smoke
test for that live path, and confirm:

- `start-iap-tunnel` reaches the candidate on the SSH port (22 for generic
  Linux) and on 389 for a DC.
- The injected instance SSH key lets the runner reach the guest as the
  `validator` user (project SSH keys are blocked, so an instance key is used).
- `ldapsearch` on the runner returns the expected forest rootDSE for a
  `dc-prebaked` candidate.
- The disposable validation VM is deleted on both success and failure.

A failure on that first run is a wiring issue in the validation path, not a
candidate-image defect; fix it before treating its artifact as promotion
evidence. The #1699 implementation reconciles the code-path findings in #1621
and #1646: the build identity cannot federate as validate, validation runs only
from protected refs under a distinct Environment subject, and promotion checks
the exact successful run attempt, artifact ID, revision, project, image name,
numeric image ID, family, and validation phases. The mutable image labels are
only locators for that independently verified record; they cannot mint a pass.
The operator cutover/readback in `docs/dev/deploy-secrets.md` supplies the live
effective-policy evidence before those tracking issues are closed, and #2084
owns the exact-release security decision. #1622 remains the separate deeper
guest-content validation follow-up.

## Operating the pipeline

Build + publish the base set to GHCR (Actions → "Packer GCE Image Build", or). The
DC base is the pre-promoted `dc-prebaked` image (published under the `dc` role):

```bash
gh workflow run packer-gcp.yml -f image_type=kali        -f environment=gcp-dev -f publish_target=ghcr
gh workflow run packer-gcp.yml -f image_type=ubuntu      -f environment=gcp-dev -f publish_target=ghcr
gh workflow run packer-gcp.yml -f image_type=dc-prebaked -f dc_profile=<profile> -f environment=gcp-dev -f publish_target=ghcr
```

These run only from `dev`/`main` (the workflow rejects other refs). After all
three are published to GHCR, a fresh tenant imports, wires, and deploys them in
one invocation:

```bash
./scripts/bootstrap/deploy.py gdc-bootstrap \
  --project-id <project> --environment gcp-dev \
  --region <region> --zone <zone> \
  --shifter-config /path/to/shifter.yaml \
  --import-public-base-images --yes
```

For an existing platform, refresh only the imported set with
`./scripts/bootstrap/deploy.py gcp-images --project-id <project> --environment
gcp-dev --region <region>`.

For the GCE range-cell path, a dev image must pass the candidate-boot gate
before it can ship: run `packer-gcp-validate.yml` for the built image, then
`packer-gcp-promote.yml` with the exact validated image name. Promotion refuses
an image that is not labelled `validated=passed`.

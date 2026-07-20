# GCP Guest Images (GDC VM Runtime)

How Shifter range guest VMs (Kali, Ubuntu, Windows, DC) are built and made
available on GCP, and how that differs from the AWS path. This is the GCP
parallel to the AWS AMI flow.

> **Windows and DC guests use a different build path.** The GCE-packer-export
> flow described here works for the Linux guests (Kali, Ubuntu), whose images
> are hypervisor-portable. A GCE-built **Windows** image does **not** boot on
> GDC VM Runtime (firmware, drivers, and network differ). Windows/DC images are
> instead installed natively on GDC from an ISO—see
> [gdc-windows-dc-image-build.md](./gdc-windows-dc-image-build.md).

## The two platforms, side by side

| Concern | AWS | GCP |
|---|---|---|
| Image build | `shifter/packer/` (`amazon-ebs`) | `shifter/packer/gcp/` (`googlecompute`) |
| Build trigger | `packer.yml` (self-hosted runner) | `packer-gcp.yml` (GitHub-hosted + Workload Identity) |
| Build artifact | AMI | GCE image in family `shifter-<type>` |
| Image discovery | `/shifter/ami/<type>` SSM parameter | newest non-deprecated image in the `shifter-<type>` family |
| Guest boot source | `aws_instance` AMI id | GDC VM Runtime `VirtualMachineDisk` with a `gs://` source |
| Runtime wiring | per-OS AMI id Terraform vars | `GDC_<TYPE>_IMAGE_URL` runtime env |

The key GCP-specific wrinkle: a GCE image family is **not** something the GDC VM
Runtime can boot from directly. The VM Runtime imports a disk from a source URL
(`gs://`, `https://`, or a container registry—see
`_resolve_image_source`), so each built GCE image is **exported to GCS as a
qcow2** and the range provisioner references that `gs://` disk through
`GDC_<TYPE>_IMAGE_URL`.

## Pipeline stages

```
packer-gcp.yml ─┬─ build  → GCE image  shifter-<type>-<timestamp>  (family shifter-<type>)
                └─ export → gs://<project>-gcp-dev-gdc-vm-images/<type>.qcow2
                                   │
bootstrap runtime env: GDC_<TYPE>_IMAGE_URL = gs://…/<type>.qcow2
                                   │
range provisioner → VirtualMachineDisk { source.gcs.url = GDC_<TYPE>_IMAGE_URL }
                                   │
GDC VM Runtime imports the disk (auth: GDC_VM_IMAGE_GCS_SECRET_ID) and boots the guest
```

1. **Build**—`packer-gcp.yml` builds one guest type on a GCE builder VM and
   publishes it into image family `shifter-<type>`. Builders run internal-IP
   only (reached over IAP) so they comply with the project's
   `compute.vmExternalIpAccess` org policy. See `shifter/packer/gcp/README.md`.
2. **Export**—the same workflow exports the built image to the GDC VM image
   bucket as `<type>.qcow2` (`gcloud compute images export`, a Cloud Build job
   pinned to the builder subnet). Both the Cloud Build identity
   (`--cloudbuild-service-account`) and the daisy worker VM
   (`--compute-service-account`) are pinned to the `…-packer` build SA—this
   project's builds otherwise default to the Compute Engine default SA, which
   the build SA cannot `actAs`. The build SA therefore holds `compute.admin`
   plus `serviceAccountTokenCreator`/`serviceAccountUser` on itself (the export
   mints an access token for, and runs the worker as, that same SA). The bucket
   is read-granted to the bare-metal GCR identity the VM Runtime authenticates
   as.
3. **Wire**—set `GDC_<TYPE>_IMAGE_URL=gs://<bucket>/<type>.qcow2` in the
   bootstrap runtime contract (`scripts/bootstrap/deploy.py`) / the live
   `platform-runtime` ConfigMap. Sizing (`GDC_<TYPE>_VCPUS` / `MEMORY` /
   `DISK_SIZE_GIB`) is configured separately and already has defaults.
4. **Boot**—the range provisioner builds a `VirtualMachineDisk` whose
   `source.gcs.url` is the wired URL; the VM Runtime imports it using the
   `GDC_VM_IMAGE_GCS_SECRET_ID` secret and boots the guest.

## Build mechanism (Workload Identity, no SA keys)

`packer-gcp.yml` authenticates with GitHub → GCP Workload Identity Federation,
provisioned by `platform/terraform/gcp/modules/cicd-github-oidc` (the GCP analog
of the AWS `github-oidc` IAM role). The module creates a Workload Identity pool,
a repository-scoped OIDC provider, a least-privilege `…-packer` build service
account, the builder subnet + IAP firewall, and the GDC VM image bucket.

Configure these once (`docs/dev/deploy-secrets.md`):

| Name | Kind | Source |
|---|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | secret | module output `packer_workload_identity_provider` |
| `GCP_SERVICE_ACCOUNT` | secret | module output `packer_build_service_account_email` |
| `GCP_PROJECT_ID` | secret | the project |
| `GCP_PACKER_SUBNETWORK` | variable | module output `packer_builder_subnetwork` |
| `GCP_PACKER_USE_INTERNAL_IP` | variable | `true` (IAP builds) |
| `GCP_GDC_VM_IMAGE_BUCKET` | variable | module output `gdc_vm_image_bucket` |

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

The GCE range-cell backend (the default GCP range path) consumes the
`googlecompute` images **directly** as GCE images — it does not use the qcow2
export above (that is GDC-only). The provisioner resolves each logical guest role
through `GCP_RANGE_{LINUX,KALI,WINDOWS,DC}_IMAGE` (a family URL or exact image),
and `load_gce_range_cell_config` validates the reference shape, disk type, and a
per-role **policy** minimum boot-disk size (not the actual source-image size)
before any Compute Engine call so a malformed value fails fast instead of after
a create attempt.

An **immutable candidate image is the unit of validation and promotion**; a GCE
image family is a mutable deployment channel, not evidence that a particular
image was tested. The pipeline is three stages:

```
packer-gcp.yml         build    → GCE image  shifter-<type>-<ts>   (family shifter-<type>)
packer-gcp-validate.yml validate → boot the EXACT candidate in a disposable,
                                    isolated VM; label it validated=passed
packer-gcp-promote.yml  promote  → copy the EXACT validated candidate to the prod
                                    family; verify it, then deprecate the old head
```

1. **Validate** (`packer-gcp-validate.yml`) boots the concrete candidate in a
   disposable VM with the runtime range-cell posture (**no external IP**, IAP
   subnet, Shielded VM, project SSH keys blocked) and reboots it once. Evidence
   is gathered **by the runner over an IAP tunnel**, not self-reported by the
   guest: for Linux/polaris-vm the runner SSH-executes the check script (guest
   agent, host sshd management port, Docker, baked compose config/images, and
   that every declared compose service has a **running** container) and gates on
   its exit code; for a pre-promoted DC the runner probes AD over LDAP (an
   anonymous rootDSE query proving AD DS is serving the **expected forest**, with
   **no first-boot promotion**). The candidate boots with **no service account
   and no OAuth scopes**, so guest code cannot read a cloud token and mutate its
   own image labels; the runner (WIF) holds all label authority. Passing again
   after the reset proves a clean boot with no manual input. On success the
   workflow labels the exact candidate `validated=passed` and uploads a bounded,
   non-secret evidence artifact; the VM is always deleted. Only image types with
   a matching validator are selectable (generic Linux, `polaris-vm`,
   `dc-prebaked`); the sysprepped `windows` and first-boot-promotion `dc` images
   are excluded. Per-container runtime health and seeded AD content that depend
   on per-range credentials are a runtime/range-smoke concern, not part of this
   candidate-boot gate.
2. **Promote** (`packer-gcp-promote.yml`) takes the **exact** validated candidate
   image name, verifies it carries `validated=passed`, copies that image into the
   prod family (derived from the image's own family attribute, so `polaris-vm`
   and purpose-scoped `<purpose>-dc` families work with no per-name logic),
   verifies the new prod image is `READY`, and only then deprecates the previous
   prod head. It never re-resolves "newest in the dev family" at promotion time.

### polaris-vm range host (fail-closed compose stack)

The Polaris range host is a Debian Docker host image (`polaris-vm.pkr.hcl`)
running the polaris docker-compose stack. The stack lives outside this repo, so
`host-setup.sh` fetches it from GCS at bake time. For a promotable image the
stack is **mandatory** and verified: the build fails on a missing stack, a
`POLARIS_STACK_SHA256` checksum mismatch, an invalid compose config, a failed
build/pull, or a missing image. Set `GCP_POLARIS_STACK_SHA256` (and, optionally,
`GCP_POLARIS_STACK_GENERATION` to pin the immutable object version).

### Pre-promoted DC (`dc-prebaked`) vs. generic Windows/DC

The `windows` and `dc` images are **sysprepped** (GCESysprep), so their
build-time WinRM credential is discarded by sysprep. The pre-promoted
`dc-prebaked` image is captured **un-sysprepped** on purpose — GCESysprep cannot
generalize a promoted domain controller — so it needs deliberate credential
hygiene rather than relying on sysprep:

- The identical `BOREAS.LOCAL` machine/domain identity across ranges is
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
project: the IAP tunnel to the candidate VM, the runner's SSH to the polaris-vm
management port (2222), and the DC LDAP rootDSE probe.

Treat the **first `packer-gcp-validate.yml` run per environment** as the smoke
test for that live path, and confirm:

- `start-iap-tunnel` reaches the candidate on the SSH port (22 for generic
  Linux, the configured management port for polaris-vm) and on 389 for a DC.
- The injected instance SSH key lets the runner reach the guest as the
  `validator` user (project SSH keys are blocked, so an instance key is used).
- `ldapsearch` on the runner returns the expected forest rootDSE for a
  `dc-prebaked` candidate.
- The disposable validation VM is deleted on both success and failure.

A failure on that first run is a wiring issue in the validation path, not a
candidate-image defect; fix it before relying on the `validated=passed` label as
a promotion gate. Follow-up hardening of this subsystem is tracked in #1621
(attestation-bound evidence, dispatch-ref workflow trust) and #1622 (real
source-image disk check, deeper DC service/content probing).

## Operating the pipeline

Build + export one guest (Actions → "Packer GCE Image Build" → pick type/env, or):

```bash
gh workflow run packer-gcp.yml -f image_type=ubuntu -f environment=dev
```

After all four guests (`ubuntu`, `kali`, `windows`, `dc`) are built and
exported, wire each `GDC_<TYPE>_IMAGE_URL` and (re)deploy so the range
provisioner picks them up.

For the GCE range-cell path, a dev image must pass the candidate-boot gate
before it can ship: run `packer-gcp-validate.yml` for the built image, then
`packer-gcp-promote.yml` with the exact validated image name. Promotion refuses
an image that is not labelled `validated=passed`.

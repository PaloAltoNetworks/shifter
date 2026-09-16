# Packer GCE Image Builds

Reproducible Google Compute Engine guest-image builds for Shifter ranges
(issue #505, PLAT-001.10). These `googlecompute` templates are the GCP parallel
to the AWS `amazon-ebs` templates in the parent directory.

> **Provider separation.** This directory is a SEPARATE Packer configuration
> from `shifter/packer/`. `packer` reads only the directory it is invoked in
> (it does not recurse), so the AWS `packer build .` / `-only='*.<type>'` flow
> never sees a `googlecompute` source, and the AWS path is unaffected.

## The image-family contract

There is no GCP equivalent of the AWS `/shifter/ami/*` SSM parameter. Instead:

- Each build publishes image `shifter-<type>-<timestamp>` into **image family**
  `shifter-<type>` with labels (`project`, `managed-by`, `image-type`). The
  pre-promoted DC uses a purpose-scoped family `shifter-<purpose>-dc`.
- Consumers resolve the **newest non-deprecated image in the family**
  (`gcloud compute images describe-from-family shifter-<type>`).
- A dev image must pass the **candidate-boot validation gate**
  (`packer-gcp-validate.yml`) before it can ship: the workflow boots the exact
  candidate in a disposable, isolated VM and, on success, labels that image
  `validated=passed`.
- Promotion (`packer-gcp-promote.yml`) is **evidence-driven**: it copies the
  **exact validated candidate** (verified `validated=passed`) into the prod
  family, verifies the new prod image, then deprecates the previous head. It
  never re-resolves "newest in the dev family" at promotion time.

## Prerequisites

- [Packer](https://www.packer.io/downloads) 1.9+ (`packer init .` installs the
  `googlecompute` plugin)
- A GCP project with the Compute Engine API enabled and a build network/subnet
- A service account with image-build permissions (Compute Instance Admin,
  Service Account User, Storage)
- For `kali`: nothing extra; it converts the `debian-12` base to Kali (see below)

## Quick start

```bash
packer init .
# Validate (uses the committed placeholder var-file)
packer validate -var-file=dev.pkrvars.hcl .
# Build one image type. Real builds override the placeholder project/network/SA.
packer build -only='googlecompute.ubuntu' \
  -var="project_id=my-proj" -var="zone=us-central1-a" \
  -var="network=default" -var="subnetwork=default" \
  -var="service_account_email=packer-builder@my-proj.iam.gserviceaccount.com" \
  -var="image_prefix=shifter" -var="machine_type=e2-standard-2" \
  -var="use_internal_ip=false" .
```

In CI, variables are passed as `PKR_VAR_*` environment variables (never `-var`
CLI flags) so secrets cannot appear in a process list. See
`.github/workflows/packer-gcp.yml`.

## Image types

| Type | Source | Notes |
|------|--------|-------|
| `ubuntu` | `ubuntu-2204-lts` (ubuntu-os-cloud) | Reuses `../scripts/ubuntu` |
| `brokenbk` | `ubuntu-2204-lts` (ubuntu-os-cloud) | Reuses `../scripts/brokenbk` |
| `kali` | `debian-12` (debian-cloud), converted to Kali | No public Kali GCP image |
| `windows` | `windows-2022` (windows-cloud) | WinRM + GCESysprep |
| `dc` | `windows-2022` (windows-cloud) | AD DS via `PACKER_ROLE=dc`, GCESysprep, first-boot promotion |
| `polaris-vm` | `debian-12` (debian-cloud) | Docker host baking the polaris compose stack (fail-closed: requires the verified stack) |
| `dc-prebaked` | `windows-2022` (windows-cloud) | Pre-promoted DC baked from a `dc-profiles/<profile>` var-file; **un-sysprepped** |

### Kali (debian-12 base, converted to Kali Rolling)

GCP has no public Kali image (the AWS path uses an AWS Marketplace product
code; there is no Offensive-Security-published GCP image). Importing Kali's
official generic-cloud disk does **not** work on GCE: it has no Google guest
environment, so it never gets metadata-based SSH-key injection or GCE network
setup and packer can never connect to it.

Instead the kali builder starts from Google's GCE-native `debian-12` image and
its first provisioning script (`../scripts/kali/gce-debian-to-kali.sh`) converts
it to Kali Rolling in place: add Kali's official apt repo + keyring,
`full-upgrade` onto kali-rolling (`--force-overwrite` clears the 64-bit `time_t`
library-transition file conflicts), and re-assert Google's guest-environment apt
repo so `google-guest-agent` survives (the Kali repos omit it). No imported base
image and no `kali_source_image` / `GCP_KALI_SOURCE_IMAGE` are required:

```bash
packer build -only='googlecompute.kali' \
  -var="project_id=my-proj" -var="zone=us-central1-a" \
  -var="network=default" -var="subnetwork=default" \
  -var="service_account_email=packer-builder@my-proj.iam.gserviceaccount.com" \
  -var="image_prefix=shifter" -var="machine_type=e2-standard-2" \
  -var="use_internal_ip=false" .
```

See `docs/architecture/gcp-guest-images.md` for the full build → export → wire
pipeline.

### Windows / DC

The `googlecompute` builder has no auto-generated Windows password (unlike the
AWS path's `build.Password`). A throwaway local admin is created on the builder
VM from a per-build `winrm_bootstrap_password`, injected by CI via
`PKR_VAR_winrm_bootstrap_password` (never committed). The VM is generalized with
`GCESysprep` (`scripts/windows/sysprep.ps1`) and discarded, so the credential
never reaches the published image.

Packer connects over **WinRM-over-TLS only** (port 5986): the shared bootstrap
in `locals.pkr.hcl` stands up an HTTPS listener bound to a self-signed cert,
disables HTTP Basic and unencrypted transport, and opens only 5986. The
bootstrap password therefore never crosses the wire in cleartext. `winrm_insecure`
is set only to skip validation of the ephemeral builder's self-signed cert; the
channel is still encrypted.

#### Pre-promoted DC (`dc-prebaked`): un-sysprepped, so hygiene is explicit

The `windows` and `dc` images are sysprepped, so sysprep discards their
build-time credentials. `dc-prebaked` is captured **un-sysprepped** on purpose
(GCESysprep cannot generalize a promoted domain controller), so it performs the
equivalent hygiene by hand:

- The **DSRM** password is generated per build and injected as a sensitive
  Packer var (`PKR_VAR_dc_dsrm_password`); `promote-bake.ps1` refuses to promote
  without it. There is **no committed default DSRM secret**.
- A final `scripts/dc-prebaked/cleanup.ps1` provisioner strips the build
  transcripts, the DNS-forwarder handoff, and the staged AD-content seed
  (`C:\polaris\a2_setup.ps1`, which carries baked passwords) before capture.
- The identical `BOREAS.LOCAL` machine/domain identity is intentional and kept;
  the **live** domain Administrator credential is rotated **per range at
  runtime** by `plans/dc_setup.py` (`DC_DOMAIN_PASSWORD`), not baked.

#### polaris-vm: fail-closed compose stack

The `polaris-vm` host bakes the polaris docker-compose stack fetched from GCS.
For a promotable image the stack is mandatory and verified against
`POLARIS_STACK_SHA256` (optionally pinned to an immutable
`POLARIS_STACK_GENERATION`): a missing stack, checksum mismatch, invalid compose
config, failed build/pull, or missing image fails the build.
The bake also runs the full stack and requires every Compose-declared service
to be running before capture; candidate validation only observes that prebaked
state on first boot and after reset.
Pulled images must be digest-pinned. Before starting the stack, the bake rejects
privileged/host-namespace workloads and sensitive host binds, then blocks GCE
metadata access from host and Docker-forwarded traffic to protect the attached
builder identity.

> **Live validation.** `packer validate` and the `tests/test_packer_gcp.py`
> suite protect template/workflow shape; they do not prove a booted guest. The
> `packer-gcp-validate.yml` candidate-boot gate is the live-guest check. It
> boots the exact built image in a disposable isolated VM (no external IP, IAP,
> Shielded VM), reboots it, verifies guest/stack/AD health, and labels the image
> `validated=passed`. Run it against a real project after a build, then promote
> the validated image.

## Guest specialization

The Linux builders reuse the shared `../scripts/**` provisioning. Those scripts
carry AWS-specific guest tuning (the SSM agent; Claude Code's Bedrock binding).
Replacing that with GCP-native equivalents (OS-management agent; Vertex) is a
guest-runtime / range-provisioning concern tracked separately from this
image-build pipeline (per the #505 architecture preflight non-goals).

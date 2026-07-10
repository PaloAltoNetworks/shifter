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

## Operating the pipeline

Build + export one guest (Actions → "Packer GCE Image Build" → pick type/env, or):

```bash
gh workflow run packer-gcp.yml -f image_type=ubuntu -f environment=dev
```

After all four guests (`ubuntu`, `kali`, `windows`, `dc`) are built and
exported, wire each `GDC_<TYPE>_IMAGE_URL` and (re)deploy so the range
provisioner picks them up. Promotion of dev images to prod is handled by
`packer-gcp-promote.yml`.

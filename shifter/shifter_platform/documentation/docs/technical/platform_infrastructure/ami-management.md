# Machine Image Management

## AWS (AMIs)

AMI IDs stored in SSM Parameter Store, built via Packer workflows.

## SSM Parameters

| Parameter | Purpose |
|-----------|---------|
| `/shifter/ami/kali` | Kali attacker instance |
| `/shifter/ami/ubuntu` | Ubuntu victim instance |
| `/shifter/ami/windows` | Windows victim instance |
| `/shifter/ami/dc` | Domain Controller instance |

Provisioner fetches AMI IDs at runtime via `main.py:get_ami_from_ssm()`.

## AMI Types

### Packer-Built AMIs

Kali, Ubuntu, and Windows AMIs are built from base images using Packer.

| AMI | Base Image | Build Scripts |
|-----|------------|---------------|
| **kali** | Official Kali AMI | `shifter/packer/scripts/kali/` |
| **ubuntu** | Ubuntu 22.04 | `shifter/packer/scripts/linux/` |
| **windows** | Windows Server 2022 | `shifter/packer/scripts/windows/` |

Build configuration: `shifter/packer/*.pkr.hcl`

### Prebaked DC AMI

Domain Controller uses a manually-created AMI with AD DS already promoted.

| Property | Value |
|----------|-------|
| Domain | `internal.shifter` |
| NetBIOS | `INTSHIFTER` |
| Hostname | Fixed from AMI (typically `DC01`) |
| AMI IDs | `shifter/packer/dc-amis.json` |

**Critical:** The prebaked DC's Administrator password must match the
environment's domain password in AWS Secrets Manager (`shifter-{env}-portal-dc-domain`).
That secret is Terraform-managed — `terraform apply` for the portal stack
generates the value (`random_password.dc_domain_password` in the
engine-provisioner module) and seeds it — so the AMI build reads the value
from Secrets Manager rather than choosing one. Victims use the same password
for domain join. The value must never be committed to `terraform.tfvars`,
workflow YAML, or any other tracked file.

DC AMI is prebaked because runtime promotion adds 15-20 minutes to provisioning. Tradeoffs:
- Fixed domain name across all ranges
- Fixed hostname (no per-range DC naming)
- Password rotation must be coordinated between the AMI and the runtime secret

## Workflows

### Build (Dev)

Workflow: `.github/workflows/packer.yml`

| AMI Type | Action |
|----------|--------|
| kali, ubuntu, windows | Packer build, update dev SSM |
| dc | Read from `dc-amis.json`, update dev SSM |

### Promote (Prod)

Workflow: `.github/workflows/packer-promote.yml`

| AMI Type | Action |
|----------|--------|
| kali, ubuntu, windows | Copy AMI to prod account, update prod SSM |
| dc | Read from `dc-amis.json`, update prod SSM |

## Updating AMIs

### Packer-Built (kali, ubuntu, windows)

1. Modify scripts in `shifter/packer/scripts/`
2. Run "Packer AMI Build (Dev)" workflow
3. Test in dev
4. Run "Packer AMI Promote to Prod" workflow

### Domain Controller

1. Edit `shifter/packer/dc-amis.json` with new AMI ID
2. Run "Packer AMI Build (Dev)" workflow with `dc` type
3. Test in dev
4. Run "Packer AMI Promote to Prod" workflow with `dc` type

To create a new DC AMI:

1. Launch Windows Server 2022 base AMI
2. Install AD DS feature
3. Promote to DC with domain `internal.shifter`, NetBIOS `INTSHIFTER`
4. Set the domain Administrator password to the value already seeded in
   `shifter-{env}-portal-dc-domain` (Terraform-managed; read it from Secrets
   Manager, do not invent one) — see `dev/secrets.md`
5. Sysprep and create AMI
6. Update `dc-amis.json`

**Important:** The Administrator password set during promotion must match the
runtime secret referenced by the portal/engine Terraform stack for domain join
to work. Keep only non-secret identifiers in Terraform configuration; do not
store the password value in environment tfvars.

## Related Files (AWS)

| File | Purpose |
|------|---------|
| `shifter/packer/dc-amis.json` | DC AMI IDs (version controlled) |
| `shifter/engine/provisioner/main.py` | `get_ami_from_ssm()` function |
| `shifter/engine/provisioner/catalog/instances.py` | Instance type definitions |
| `shifter/engine/provisioner/plans/dc_setup.py` | DC verification (no promotion step) |

## GCP/GDC

GCP does not use AMIs or Packer. Guest images are managed differently per asset type:

- **GDC VM Runtime** - OS images stored in GCS, imported as `VirtualMachineDisk` CRDs. Image URLs configured in `GDCVMRuntimeConfig`.
- **Scenario Pods** - Standard container images from Artifact Registry.
- **VM-Series NGFW** - OVA image stored in GCS, bootstrapped via GCS bucket.

See [GDC Provisioning](gdc-provisioning) for details.

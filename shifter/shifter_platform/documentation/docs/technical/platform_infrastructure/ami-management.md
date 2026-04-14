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

**Critical:** The prebaked DC's Administrator password must match `dc_domain_password` in `terraform.tfvars`. Victims use this password for domain join.

DC AMI is prebaked because runtime promotion adds 15-20 minutes to provisioning. Tradeoffs:
- Fixed domain name across all ranges
- Fixed hostname (no per-range DC naming)
- Password must be coordinated between AMI and Terraform config

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
4. Set Administrator password to match `dc_domain_password` in terraform.tfvars
5. Sysprep and create AMI
6. Update `dc-amis.json`

**Important:** The Administrator password set during promotion must match the `dc_domain_password` value in `platform/terraform/environments/{env}/portal/terraform.tfvars` for domain join to work.

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

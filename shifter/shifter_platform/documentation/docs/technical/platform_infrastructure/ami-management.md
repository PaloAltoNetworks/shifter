# AMI Management

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

- Domain: `internal.shifter`
- NetBIOS: `INTSHIFTER`
- AMI IDs tracked in: `shifter/packer/dc-amis.json`

```json
{
  "dev": "ami-06c53b01bdb45f264",
  "prod": "ami-05ac9c21a6c0f8767"
}
```

DC AMI is prebaked because runtime promotion adds 15-20 minutes to provisioning. The tradeoff is a fixed domain name across all ranges.

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
3. Promote to DC with domain `internal.shifter`
4. Sysprep and create AMI
5. Update `dc-amis.json`

## Related Files

| File | Purpose |
|------|---------|
| `shifter/packer/dc-amis.json` | DC AMI IDs (version controlled) |
| `shifter/engine/provisioner/main.py` | `get_ami_from_ssm()` function |
| `shifter/engine/provisioner/catalog/instances.py` | Instance type definitions |
| `shifter/engine/provisioner/plans/dc_setup.py` | DC verification (no promotion step) |

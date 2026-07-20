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
| `/shifter/ami/brokenbk` | Broken Bank vulnerable training application |
| `/shifter/ami/polaris-dc` | Polaris scenario Domain Controller |
| `/shifter/ami/techvault` | TechVault scenario host |
| `/shifter/ami/polaris-vm` | Polaris scenario host |

The build workflow publishes each type to `/shifter/ami/<type>`; the provisioner resolves both the legacy known types and any custom key from that path.

Provisioner fetches AMI IDs at runtime via `shifter/engine/provisioner/provisioner_ami.py:get_ami_id()`.

## AMI Types

### Packer-Built AMIs

The kali, ubuntu, windows, brokenbk, and polaris-dc AMIs are built from base images using Packer (the `build` job in `packer.yml`).

| AMI | Base Image | Build Scripts |
|-----|------------|---------------|
| **kali** | Official Kali AMI | `shifter/packer/scripts/kali/` |
| **ubuntu** | Ubuntu 22.04 | `shifter/packer/scripts/ubuntu/` |
| **windows** | Windows Server 2022 | `shifter/packer/scripts/windows/` |
| **brokenbk** | Ubuntu 22.04 | `shifter/packer/scripts/brokenbk/` |
| **polaris-dc** | Windows Server 2022 | `shifter/packer/scripts/windows/` (shared, plus a scenario content script) |

Build configuration: `shifter/packer/*.pkr.hcl` (one file per type).

### Scenario-Baked AMIs

The techvault and polaris-vm scenario AMIs are baked by the separate `bake-scenario` job in `packer.yml`, which drives the guest over the no-inbound AWS Session Manager communicator rather than inbound SSH or WinRM.

| AMI | Base Image | Build Config |
|-----|------------|--------------|
| **techvault** | Ubuntu 24.04 | `shifter/packer/techvault.pkr.hcl` (`shifter/packer/scripts/techvault/`) |
| **polaris-vm** | Ubuntu 24.04 | `shifter/packer/polaris-vm.pkr.hcl` (`shifter/packer/scripts/polaris/`) |

### Prebaked DC AMI

Domain Controller uses a manually created AMI with AD DS already promoted.

| Property | Value |
|----------|-------|
| Domain | `internal.shifter` |
| NetBIOS | `INTSHIFTER` |
| Hostname | Fixed from AMI (typically `DC01`) |
| AMI IDs | `shifter/packer/dc-amis.json` |

**Critical:** The prebaked DC's Administrator password must match the
environment's domain password in AWS Secrets Manager (`shifter-{env}-portal-dc-domain`).
That secret is Terraform-managed—`terraform apply` for the portal stack
generates the value (`random_password.dc_domain_password` in the
engine-provisioner module) and seeds it—so the AMI build reads the value
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
| kali, ubuntu, windows | Packer build, fresh-boot SSM/DNS validation gate, then update dev SSM |
| brokenbk, polaris-dc | Packer build, then update dev SSM (no fresh-boot validation gate) |
| techvault, polaris-vm | Scenario bake over the no-inbound SSM communicator (`bake-scenario` job), then update dev SSM |
| dc | Read the id from `dc-amis.json` (trusted `dev` provenance, validated), update dev SSM |

The `kali`, `ubuntu`, and `windows` builds bake a deterministic AmazonProvidedDNS
upstream into the guest (issue #1633) so DNS is race-free from first boot. Before
the build overwrites `/shifter/ami/<type>`, a validation gate boots the exact
candidate AMI in a range-equivalent subnet and requires it to register with SSM
and resolve the regional SSM endpoint on a fresh boot and after a reboot. A
failed candidate leaves the previous known-good id in place. The gate reads its
subnet, security group, and instance profile from trusted repository Actions
variables (`PACKER_VERIFY_*_<ENV>`), not dispatch inputs; they are described in
the [AWS AMI seeding runbook](../../dev/aws-ami-seeding-runbook.md).

The base `build` job assumes a dedicated least-privilege image-pipeline IAM role
(`github_actions_image` in `platform/terraform/global/iam`, issue #1656), not the
broad deploy role. Its OIDC trust is pinned to the `dev`/`main` protected-branch
subjects, and its `iam:PassRole` is scoped to exactly the
`shifter-<env>-range-range-instance` role passed to EC2, so the verification
instance can receive only the range role. The role ARN is wired to the
`AWS_IMAGE_ROLE_ARN_<ENV>` secret (see the runbook cutover); the
`check_tf_iam_role_naming` guardrail (ADR-004-R22) pins the exact-subject and
exact-range-role invariants. `bake-scenario` keeps its own separate role.

### Promote (Prod)

Workflow: `.github/workflows/packer-promote.yml`

| AMI Type | Action |
|----------|--------|
| kali, ubuntu, windows, brokenbk | Copy AMI to prod account, update prod SSM |
| dc | Read the id from `dc-amis.json` (trusted `dev` provenance, validated), update prod SSM |

`packer-promote.yml` handles only kali, ubuntu, windows, dc, and brokenbk. The polaris-dc, techvault, and polaris-vm AMIs are built per environment (`dev` or `proof`) directly and are not promoted through this workflow.

Both DC publishers read `dc-amis.json` from a dedicated checkout of the protected
`dev` ref (never the dispatched/build ref or a runner leftover) and resolve it
through one shared validator, `shifter/packer/scripts/bake/resolve-dc-ami.sh`,
which fails closed unless the id exists, matches the AMI shape, and names an
image EC2 reports as `available` and owned by the target account. The prod
promote job also runs only from a protected ref (`dev`/`main`). See issue #1656.

## Updating AMIs

### Packer-Built and Scenario-Baked (kali, ubuntu, windows, brokenbk, polaris-dc, techvault, polaris-vm)

1. Modify scripts in `shifter/packer/scripts/`
2. Run "Packer AMI Build" workflow for the type
3. Test in dev
4. For promotable types (kali, ubuntu, windows, brokenbk), run "Packer AMI Promote to Prod"; polaris-dc, techvault, and polaris-vm are built per environment instead

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
   Manager, do not invent one), see `dev/secrets.md`
5. Set the DC's DNS forwarders to the link-local AmazonProvidedDNS so external
   names such as the regional SSM endpoint resolve deterministically (issue
   #1633): `Set-DnsServerForwarder -IPAddress 169.254.169.253 -PassThru`. This is
   the DC-role equivalent of the `FallbackDNS` baked into the Linux guests. Do
   not reset the DC's adapter to DHCP DNS: a promoted DC points its client at
   itself and forwards outbound queries, so a DHCP reset would break domain
   resolution.
6. Sysprep and create AMI
7. Update `dc-amis.json`

**Important:** The Administrator password set during promotion must match the
runtime secret referenced by the portal/engine Terraform stack for domain join
to work. Keep only non-secret identifiers in Terraform configuration; do not
store the password value in environment tfvars.

## Related Files (AWS)

| File | Purpose |
|------|---------|
| `shifter/packer/dc-amis.json` | DC AMI IDs (version controlled) |
| `shifter/engine/provisioner/provisioner_ami.py` | `get_ami_id()` function |
| `shifter/engine/provisioner/catalog/instances.py` | Instance type definitions |
| `shifter/engine/provisioner/plans/dc_setup.py` | DC verification (no promotion step) |

## GCP

GCP keeps four distinct image concepts separate (do not conflate them with AWS
AMIs):

### GCE guest images (Packer)

Compute Engine guest images are built with Packer, parallel to the AWS AMI flow
(issue #505, PLAT-001.10). They are **not** AMIs and their refs are **never**
stored in AWS SSM `/shifter/ami/*`.

- Templates: `shifter/packer/gcp/*.pkr.hcl` (`googlecompute` builders), a
  separate Packer configuration from the AWS `amazon-ebs` templates one
  directory up—`packer` invoked in either directory never sees the other.
- **Version pointer = image family.** Each build publishes image
  `shifter-<type>-<timestamp>` into image family `shifter-<type>`; consumers
  resolve the newest non-deprecated image in the family (the GCP-native analog
  of the AWS SSM parameter—there is no SSM equivalent).
- Build: `.github/workflows/packer-gcp.yml` (`workflow_dispatch`,
  `ubuntu-latest` + Workload Identity Federation). Promote dev→prod:
  `.github/workflows/packer-gcp-promote.yml` (copies the newest dev-family image
  into the prod project's family and deprecates the previous head).
- Image types: `ubuntu`, `brokenbk`, `kali`, `windows`, `dc`. **Kali** has no
  public GCP image and the official genericcloud disk is not GCE-bootable, so
  its builder converts Google's `debian-12` base into Kali Rolling in its first
  provisioning script; see `shifter/packer/gcp/README.md`.
- Agent triggers: the `build_gce_image` / `promote_gce_image` MCP ops tools
  (`infra_mutation`), parallel to `build_ami` / `promote_ami`.

> Guest specialization that is AWS-specific in the shared provisioning scripts
> (the SSM agent; Claude Code's Bedrock binding) is a guest-runtime / range
> concern tracked separately from this image-build pipeline.

### Other GCP image concepts (unchanged)

- **GDC VM Runtime** - OS images stored in GCS, imported as `VirtualMachineDisk` CRDs. Image URLs configured in `GDCVMRuntimeConfig` (`GDC_*_IMAGE_URL`).
- **Scenario Pods** - Standard container images from Artifact Registry.
- **VM-Series NGFW** - OVA image stored in GCS, bootstrapped via GCS bucket.
- **Control-plane containers** - Built and pushed to Artifact Registry by `_gcp-dev.yml`.

See [GDC Provisioning](gdc-provisioning) for details.

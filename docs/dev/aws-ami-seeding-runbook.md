# AWS range AMI seeding

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

The Portal Terraform stack reads the range base AMIs from SSM as data sources
(`/shifter/ami/kali`, `/shifter/ami/ubuntu`, `/shifter/ami/windows`,
`/shifter/ami/dc`). If any parameter is missing, `terraform plan` for the Portal
stack fails. On a fresh account you must build these four AMIs and seed the SSM
parameters before the first Portal apply. The runtime provisioner also resolves
guest AMIs from the same `/shifter/ami/*` parameters.

Packer sources live in `shifter/packer/` (`kali.pkr.hcl`, `ubuntu.pkr.hcl`,
`windows.pkr.hcl`, `dc.pkr.hcl`, shared `variables.pkr.hcl`, per-env
`dev.pkrvars.hcl` / `proof.pkrvars.hcl`). The deep reference is
[`shifter/packer/README.md`](https://github.com/Brad-Edwards/shifter/blob/dev/shifter/packer/README.md).

## Ordering: no circular dependency with the portal VPC

Packer needs a VPC and subnet to launch its builder instance, but it does **not**
need the portal VPC. `vpc_id` and `subnet_id` in `variables.pkr.hcl` have no
defaults; `dev.pkrvars.hcl` points them at the account default VPC and a public
subnet. So the build uses an existing general-purpose VPC/subnet, independent of
the portal Terraform that has not been applied yet. The Portal stack consumes the
AMIs only as SSM data sources, which is a soft, one-directional dependency.

The correct order on a fresh account is therefore:

1. Bootstrap the account.
2. Provision runners (for the CI build path).
3. Build the AMIs and seed `/shifter/ami/*` (this runbook).
4. Apply the Portal stack.

There is no chicken-and-egg between packer and the portal VPC. Do not try to
point packer at the portal VPC; use the account default VPC or an operator-owned
public subnet with outbound internet egress.

## Prerequisites

- **Kali Marketplace opt-in.** The Kali build sources an AWS Marketplace AMI
  (product code `7lgvy7mt78lgoi4lant0znp5h`). Accept the free subscription once
  per account at
  <https://aws.amazon.com/marketplace/pp/prodview-fznsw3f7mq7to>, or the Kali
  build fails with `OptInRequired`.
- **A builder VPC/subnet.** Set `vpc_id` / `subnet_id` in the environment
  pkrvars to an existing VPC and a public subnet with internet egress. Do not
  commit live IDs into a shared pkrvars; keep them in an operator override.
- **Runners** if you build through CI (the Packer workflow is `self-hosted`).
- **The base-image build IAM role and its secret** for the CI build path, one
  time per account (see the next section).

## Base-image build IAM role (one-time cutover)

Since issue #1656 the base `build` job in `packer.yml` assumes a dedicated
least-privilege image-pipeline role (`github_actions_image` in
`platform/terraform/global/iam`) instead of the broad deploy role. That role
trusts only the `dev`/`main` protected-branch OIDC subjects and can pass only the
exact `shifter-<env>-range-range-instance` role to EC2, so a base-image
verification instance can receive only the range role. The `check_tf_iam_role_naming`
guardrail (ADR-004-R22) pins those invariants.

The implementation PR ships the Terraform, workflow wiring, and guardrail but does
not apply IAM or set secrets. Complete the cutover once per AWS account (`dev`,
`proof`, and `prod` for promotions):

1. Apply the global-IAM stack so the role and its output exist:

   ```bash
   cd platform/terraform/global/iam
   terraform apply -var-file=<env>.tfvars
   ```

2. Set the `AWS_IMAGE_ROLE_ARN_<ENV>` GitHub secret from the output (prod is the
   unsuffixed `AWS_IMAGE_ROLE_ARN`; base builds target `dev`/`proof`):

   ```bash
   ROLE_ARN=$(terraform -chdir=platform/terraform/global/iam output -raw github_actions_image_role_arn)
   gh secret set AWS_IMAGE_ROLE_ARN_DEV --repo Brad-Edwards/shifter --body "$ROLE_ARN"
   ```

3. Confirm the repository still uses the default OIDC subject format so the pinned
   trust matches (a non-default subject would need the Terraform trust updated):

   ```bash
   gh api repos/Brad-Edwards/shifter/actions/oidc/customization/sub
   # expect use_default: true, use_immutable_subject: false
   ```

Until the secret is set the base `build` job fails closed with
`Required secret AWS_IMAGE_ROLE_ARN_<ENV> is not set`. The `bake-scenario` job
keeps its own deploy-role secret and is unaffected.

## Build path A: the Packer workflow (recommended)

The `Packer AMI Build` workflow (`.github/workflows/packer.yml`) is
`workflow_dispatch` on a `self-hosted` runner. It builds one AMI type per run,
extracts the AMI id from the build manifest, and writes
`/shifter/ami/<type>` with `aws ssm put-parameter --overwrite`. The build runs
only from a protected ref (`dev` or `main`); a dispatch from a feature branch is
rejected before AWS authentication, because the job executes checked-out code and
publishes SSM pointers. Since issue #1656 the base `build` job assumes a
dedicated least-privilege image-pipeline role, not the broad deploy role (see
[Base-image build IAM role](#base-image-build-iam-role-one-time-cutover)).

For `kali`, `ubuntu`, and `windows` the workflow first runs a fresh-boot
validation gate (issue #1633) before it seeds SSM. The gate boots the exact
built AMI in a runtime-equivalent range subnet with the range instance profile,
waits for the guest to register with SSM (registration requires the guest to
resolve the regional SSM endpoint, so a successful registration is the durable
proof that guest DNS works), resolves the endpoint through the guest system
resolver, reboots, and confirms both again. The SSM parameter is overwritten
only after the gate passes; a failed candidate leaves the previous known-good id
in place.

The gate reads its subnet, security group, and instance profile from **trusted
repository Actions variables**, not dispatch inputs, so the candidate's launch
identity cannot be chosen at dispatch time. Set these once per account (Settings
-> Secrets and variables -> Actions -> Variables), suffixed by environment
(`_DEV` / `_PROOF`):

| Variable | Value |
|----------|-------|
| `PACKER_VERIFY_SUBNET_ID_<ENV>` | A range-equivalent subnet that can reach SSM (private SSM endpoints or a NAT path), no inbound |
| `PACKER_VERIFY_SG_ID_<ENV>` | A no-inbound, egress-all security group |
| `PACKER_VERIFY_INSTANCE_PROFILE_<ENV>` | The SSM-enabled range instance profile (name ends in `-range-instance`), from `terraform -chdir=platform/terraform/environments/<env>/range output -raw range_instance_profile_name` |

Dispatch the three built base types (the gate reads the variables above):

```bash
for t in kali ubuntu windows; do
  gh workflow run "Packer AMI Build" -f ami_type="$t" -f environment=dev -f ref=dev
done
```

`dc` is not built by this workflow. `/shifter/ami/dc` is a pre-promoted
`internal.shifter` Domain Controller published from the checked-in
`dc-amis.json`; dispatching `ami_type=dc` reads the environment's id from that
file and seeds SSM without a build (see "Pre-promoted DC AMI" below):

```bash
gh workflow run "Packer AMI Build" -f ami_type=dc -f environment=dev -f ref=dev
```

`environment` accepts `dev` or `proof`. There is no `prod` build option: prod
AMIs are produced by promoting a validated dev AMI with `packer-promote.yml`, not
by building directly in prod. The workflow also builds the scenario AMI types
(`brokenbk`, `polaris-dc`, `techvault`, `polaris-vm`) on demand; the base types
above are the ones the portal plan requires.

## Build path B: local Packer

From a workstation with Packer and AWS credentials for the target account:

```bash
cd shifter/packer
packer init .
packer validate -var-file=dev.pkrvars.hcl -only='*.kali' .
packer build   -var-file=dev.pkrvars.hcl -only='*.kali' .

# Read the AMI id from the manifest and seed SSM:
AMI_ID=$(jq -r '.builds[-1].artifact_id | split(":")[1]' kali-manifest.json)
aws ssm put-parameter --name /shifter/ami/kali --type String \
  --value "$AMI_ID" --overwrite --region us-east-2
```

Repeat for `ubuntu` and `windows`. Do not build `dc` locally: `dc.pkr.hcl` is a
generalized Windows image with the AD DS feature installed but not promoted, and
publishing it to `/shifter/ami/dc` would corrupt the pre-promoted DC contract.
Seed `/shifter/ami/dc` from `dc-amis.json` instead:

```bash
AMI_ID=$(jq -r '.dev' shifter/packer/dc-amis.json)
aws ssm put-parameter --name /shifter/ami/dc --type String \
  --value "$AMI_ID" --overwrite --region us-east-2
```

## Pre-promoted DC AMI

`/shifter/ami/dc` points at a manually created, pre-promoted `internal.shifter`
Domain Controller (domain `internal.shifter`, NetBIOS `INTSHIFTER`). The AMI ids
live in `shifter/packer/dc-amis.json`; no Packer source rebuilds them. Both the
build workflow (`ami_type=dc`) and `packer-promote.yml` publish the checked-in id
rather than a fresh build. Each reads `dc-amis.json` from a dedicated checkout of
the protected `dev` ref and resolves it through the shared validator
`shifter/packer/scripts/bake/resolve-dc-ami.sh`, which fails closed unless the id
exists, is AMI-shaped, and names an image EC2 reports as `available` and owned by
the target account; the prod promote job additionally runs only from a protected
ref (`dev`/`main`). See issue #1656.

When you re-bake the pre-promoted DC (see
[AMI management](../technical/platform_infrastructure/ami-management.md)), set the
DC's DNS forwarders to the link-local AmazonProvidedDNS so external names such as
the regional SSM endpoint resolve deterministically:

```powershell
Set-DnsServerForwarder -IPAddress 169.254.169.253 -PassThru
```

This is the DC-role equivalent of the `FallbackDNS` baked into the Linux guests.
Do not apply the Linux or Windows-victim first-boot DNS reset to the DC: a
promoted DC owns its own DNS (its client points at itself and the DNS Server role
forwards outbound queries), so resetting the adapter to DHCP DNS would break
domain resolution.

## Verify

Confirm all four parameters exist before the Portal apply:

```bash
for t in kali ubuntu windows dc; do
  aws ssm get-parameter --name "/shifter/ami/$t" --region us-east-2 \
    --query 'Parameter.Value' --output text
done
```

Every command must print an `ami-...` id. A missing parameter fails the Portal
`terraform plan`.

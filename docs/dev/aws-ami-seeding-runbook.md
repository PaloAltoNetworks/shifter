# AWS range AMI seeding

The Portal Terraform stack reads the range base AMIs from SSM as data sources
(`/shifter/ami/kali`, `/shifter/ami/ubuntu`, `/shifter/ami/windows`,
`/shifter/ami/dc`). If any parameter is missing, `terraform plan` for the Portal
stack fails. On a fresh account you must build these four AMIs and seed the SSM
parameters before the first Portal apply. The runtime provisioner also resolves
guest AMIs from the same `/shifter/ami/*` parameters.

Packer sources live in `shifter/packer/` (`kali.pkr.hcl`, `ubuntu.pkr.hcl`,
`windows.pkr.hcl`, `dc.pkr.hcl`, shared `variables.pkr.hcl`, per-env
`dev.pkrvars.hcl` / `proof.pkrvars.hcl`). The deep reference is
[`shifter/packer/README.md`](../../shifter/packer/README.md).

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

## Build path A: the Packer workflow (recommended)

The `Packer AMI Build` workflow (`.github/workflows/packer.yml`) is
`workflow_dispatch` on a `self-hosted` runner. It builds one AMI type per run,
extracts the AMI id from the build manifest, and writes
`/shifter/ami/<type>` with `aws ssm put-parameter --overwrite`.

Dispatch it once for each of the four base types (`kali`, `ubuntu`, `windows`,
`dc`):

```bash
for t in kali ubuntu windows dc; do
  gh workflow run "Packer AMI Build" \
    -f ami_type="$t" -f environment=dev -f ref=dev
done
```

`environment` accepts `dev` or `proof`. There is no `prod` build option: prod
AMIs are produced by promoting a validated dev AMI with `packer-promote.yml`, not
by building directly in prod. The workflow also builds the CTF scenario images
(`ctf-*`, `brokenbk`) on demand; the four base types above are the ones the
portal plan requires.

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

Repeat for `ubuntu`, `windows`, and `dc`.

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

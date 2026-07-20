# AWS self-hosted runner provisioning

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

Every AWS deploy job (`_core.yml`, `_range.yml`, `_shifter-engine.yml`,
`_shifter-platform.yml`, `packer.yml`) runs on `runs-on: self-hosted`. A fresh
AWS account has no runners, so the AWS Deploy workflow cannot run until you
provision and register at least one. Bootstrap creates the shared state backend
the runner Terraform root reuses.

This runbook is the standup entry point. The authoritative reference for runner
architecture, health monitoring, removal, and gotchas is
[`platform/terraform/global/github-runner/README.md`](https://github.com/Brad-Edwards/shifter/blob/dev/platform/terraform/global/github-runner/README.md).

## Prerequisite

Run `scripts/bootstrap/deploy.py bootstrap --env <env>` first. It creates the S3
state bucket and rewrites `platform/terraform/global/github-runner/<env>.s3.tfbackend`
so the runner root uses the same backend.

## Automated path (recommended)

`scripts/bootstrap/deploy.py runners` provisions **and** registers the fleet
end-to-end (issue #1433):

```bash
./scripts/bootstrap/deploy.py runners --env dev --profile aws-dev
```

It provisions a dedicated, ADR-004-R20-compliant runner VPC by default
(`create_runner_network`), applies the runner root, mints a single-use token per
runner, registers each over SSM (token delivered inside one JSON `--parameters`
body so the operator-log redactor masks it; never written to Terraform state,
user data, a secret store, or logs), and verifies each runner online via the
GitHub API. Flags:

- `--use-existing-network`: reuse a configured `vpc_id`/`subnet_id` or the
  `allow_default_vpc` opt-in instead of creating a VPC (see step 1 below).
- `--runner-count N`: override `runner_count` for this apply.
- `--dry-run`: show the plan without minting a token or sending SSM commands.

Once every runner shows `status: online`, the AWS Deploy workflow can run. The
manual steps below remain available for one-off or debugging use.

## 1. Choose the runner network

The automated `runners` path provisions a dedicated runner VPC for you
(`create_runner_network = true`), which is the simplest ADR-004-R20-compliant
option. Skip the rest of this section unless you want to reuse an existing
network with `--use-existing-network`.

By default in the Terraform tfvars (ADR-004-R20) the runner stack fails closed on
the account default VPC: a range's private-DNS interface endpoints can hijack the
runner's AWS API resolution. Placement options are the dedicated runner VPC
above, an isolated network (portal VPC private tier) supplied via
`vpc_id`/`subnet_id`, or the `allow_default_vpc` opt-in. See the network
isolation preflight:
[`docs/architecture/github-runner-network-isolation-preflight-1222.md`](../architecture/github-runner-network-isolation-preflight-1222.md).

**aws-dev / aws-proof use the default VPC via the documented opt-in.** These
environments set `allow_default_vpc = true` in their tfvars, which accepts the
range private-DNS collision risk and auto-resolves the account default VPC plus
one of its subnets, so no live VPC/subnet IDs are committed (ADR-004-R14). The
durable placement design is being reassessed in issue #1437.

If instead you use an isolated network, leave `allow_default_vpc = false` and
supply `vpc_id`/`subnet_id`. For the portal VPC, read the IDs from its outputs:

```bash
cd platform/terraform/environments/<env>/portal
terraform output vpc_id
terraform output private_subnet_ids
```

Do not commit live VPC or subnet IDs to `dev.tfvars` / `proof.tfvars` (ADR-004-R14).
Keep them in a gitignored operator override or another approved deploy-time
binding. The subnet needs outbound egress for GitHub, ECR, SSM, and AWS APIs.

## 2. Terraform inputs

Defined in `platform/terraform/global/github-runner/variables.tf`:

| Variable | Required | Default | Notes |
|---|---|---|---|
| `create_runner_network` | no | `false` | Issue #1433. `true` provisions a dedicated non-default runner VPC (NAT-only egress, no private-DNS endpoints) and places the runner in it; takes precedence over `vpc_id`/`subnet_id`/`allow_default_vpc`. The `runners` automation path sets this by default. |
| `runner_network_cidr` | no | `10.20.0.0/24` | CIDR for the dedicated runner VPC when `create_runner_network = true`. |
| `allow_default_vpc` | no | `false` | ADR-004-R20 opt-in. `true` accepts default-VPC placement and auto-resolves the default VPC + a subnet. aws-dev/aws-proof set `true`. |
| `vpc_id` | conditional | `""` | Required for an isolated network (`allow_default_vpc = false`); leave empty to auto-resolve when opted in. Dedicated runner VPC or portal private tier. |
| `subnet_id` | conditional | `""` | As above; a non-default subnet with GitHub/ECR/SSM/AWS egress, or empty to auto-resolve. |
| `runner_count` | no | `2` | `dev.tfvars` / `proof.tfvars` set `3`. |
| `instance_type` | no | `t3.large` | Amazon Linux 2023, SSM access, no inbound. |
| `region` | no | `us-east-2` | |
| `github_org` / `github_repo` | no | `Brad-Edwards` / `shifter` | |
| `alarm_email` | no | empty | Subscribe an inbox to the runner-alerts SNS topic. |
| `enable_system_auto_recovery` | no | `true` | EC2 auto-recover on system status-check failure. |
| `cpu_alarm_threshold` | no | `95` | Sustained-CPU hang-proxy alarm. |

Sizing: start with `runner_count = 3` at `t3.large`. That covers the parallel
`Core` / `Range` / `Engine` / `Platform` jobs of one deploy with headroom; raise
`runner_count` if deploys queue on runner availability.

## 3. Apply the runner root

```bash
export AWS_PAGER=""
./scripts/runner-deploy.sh              # init + plan
./scripts/runner-deploy.sh --apply      # init + apply
```

The script reads `PANW_SHIFTER_DEV_PROFILE`. A fresh apply leaves each host
running the runner service but unregistered (`RunnerServiceActive = 0`) until
step 4.

## 4. Register each runner

Registration needs a single-use registration token from GitHub, exchanged once
for long-lived credentials on the instance. Mint one token per runner:

```bash
export AWS_PROFILE=aws-dev
export AWS_PAGER=""

INSTANCE=i-xxxxxxxxxxxxxxxxx
NAME=shifter-github-runner-N
TOKEN=$(gh api -X POST /repos/Brad-Edwards/shifter/actions/runners/registration-token --jq .token)

aws ssm send-command \
  --instance-ids "$INSTANCE" \
  --document-name AWS-RunShellScript \
  --region us-east-2 \
  --parameters "commands=[
    \"set -ex\",
    \"cd /home/ec2-user/actions-runner\",
    \"sudo -u ec2-user ./config.sh --url https://github.com/Brad-Edwards/shifter --token $TOKEN --labels self-hosted,linux,X64 --unattended --replace --name $NAME\",
    \"./svc.sh install ec2-user\",
    \"./svc.sh start\"
  ]"
```

Registration tokens are single-use and expire in about an hour; mint a fresh one
per runner. Verify the fleet is online:

```bash
gh api repos/Brad-Edwards/shifter/actions/runners --jq '.runners[] | {name, status}'
```

Once every runner shows `status: online`, the AWS Deploy workflow can run. To
remove or replace a runner, see the "Removing a runner" section of the
[github-runner README](https://github.com/Brad-Edwards/shifter/blob/dev/platform/terraform/global/github-runner/README.md).

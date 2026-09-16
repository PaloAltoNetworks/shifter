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

- `--use-existing-network`: place the runners in an existing compliant network
  supplied as `vpc_id`/`subnet_id` instead of the managed runner VPC (see step 1
  below).
- `--runner-count N`: override `runner_count` for this apply.
- `--dry-run`: show the plan without minting a token or sending SSM commands.

Once every runner shows `status: online`, the AWS Deploy workflow can run. The
manual steps below remain available for one-off or debugging use.

## 1. Choose the runner network

The standard placement (ADR-004-R20, issue #1437) is the dedicated runner VPC
from `modules/github-runner-network`: a private runner subnet with NAT-only
egress, no private-DNS interface endpoints, and encrypted flow logs. Both
`dev.tfvars` and `proof.tfvars` set `create_runner_network = true`, and the
`runners` path passes it, so a fresh account needs no network input and no live
IDs are committed (ADR-004-R14). Skip the rest of this section unless you need
an existing network.

The runner stack fails closed on the account default VPC: a range's private-DNS
interface endpoints can hijack the runner's AWS API resolution. The supported
alternative to the managed network is an existing compliant network, such as the
portal VPC private tier. For the portal VPC, read the IDs from its outputs:

```bash
cd platform/terraform/environments/<env>/portal
terraform output vpc_id
terraform output private_subnet_ids
```

Put `vpc_id` and `subnet_id` in a gitignored
`platform/terraform/global/github-runner/local.auto.tfvars`, never in the
committed tfvars, and run `deploy.py runners` with `--use-existing-network`. That
flag passes `-var=create_runner_network=false` after `-var-file=<env>.tfvars`.
Setting `create_runner_network = false` in `local.auto.tfvars` alone has no
effect, because `-var-file` values override `*.auto.tfvars`. The subnet needs
outbound egress for GitHub, ECR, SSM, and AWS APIs.

`allow_default_vpc` is a narrow exception, not a placement option. It requires a
documented risk acceptance in `docs/adr/exceptions.yaml` with owner, scope,
reason, and expiry. No tracked environment sets it, and it's never a recovery
fallback for a failed managed-network apply. See the placement preflight:
[`docs/architecture/github-runner-placement-preflight-1437.md`](../architecture/github-runner-placement-preflight-1437.md).

## 2. Terraform inputs

Defined in `platform/terraform/global/github-runner/variables.tf`:

| Variable | Required | Default | Notes |
|---|---|---|---|
| `create_runner_network` | no | `false` | Standard placement (#1433, #1437). `true` provisions a dedicated non-default runner VPC (NAT-only egress, no private-DNS endpoints) and places the runner in it; takes precedence over `vpc_id`/`subnet_id`/`allow_default_vpc`. `dev.tfvars` / `proof.tfvars` and the `runners` path set `true`. |
| `runner_network_cidr` | no | `10.20.0.0/24` | CIDR for the dedicated runner VPC when `create_runner_network = true`. |
| `allow_default_vpc` | no | `false` | ADR-004-R20 exception requiring a documented risk acceptance. `true` accepts default-VPC placement and auto-resolves the default VPC + a subnet. No tracked environment sets it; no effect when `create_runner_network = true`. |
| `vpc_id` | conditional | `""` | Existing compliant network (for example the portal private tier) when `create_runner_network = false`. Gitignored override only. |
| `subnet_id` | conditional | `""` | As above; a private subnet of `vpc_id` with GitHub/ECR/SSM/AWS egress. |
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

## Move an existing fleet onto the managed network

A runner applied on the account default VPC or another network moves when its
root is next applied with `create_runner_network = true`. The instance subnet
changes, so Terraform **replaces every runner instance**, and each environment
gains one NAT gateway, an Elastic IP, and flow-log storage. Treat the apply as a
migration:

1. Drain active self-hosted jobs, and don't dispatch deploys during the move.
   Don't run the apply from a job on the fleet it replaces.
2. Keep the current state and tfvars for rollback. Check NAT gateway and
   Elastic IP quotas in the target region.
   Re-registration mints real registration tokens. The current SSM transport
   carries the token in AWS CLI argv and retained Run Command input; see the
   secret-transport gap in the
   [placement preflight](../architecture/github-runner-placement-preflight-1437.md)
   before running the move.
3. Apply and re-register from outside the fleet:
   `./scripts/bootstrap/deploy.py runners --env <env> --profile <profile>`.
   Replacement runners register with `--replace`, which takes over stale
   registrations of the same name.
4. Verify each runner's effective placement and readiness separately. Check
   that each instance's subnet is the managed runner subnet, that GitHub shows
   the runner `online`, and that the `Shifter/RunnerHealth` alarms clear. Then
   run an ordinary deploy. A running service alone doesn't prove DNS, egress, or
   job readiness.

The managed network is single-AZ. A NAT gateway or AZ failure stops the fleet
until a re-apply restores it; that's recovery work, not high availability.

# GitHub Actions Self-Hosted Runners

EC2-based runners that pick up `runs-on: self-hosted` jobs from
`Brad-Edwards/shifter`. Lives in the dev account; cross-account roles
let it deploy to both dev and prod.

## Architecture

- `aws_instance.runner[count]`: Amazon Linux 2023, t3.large, no inbound
  rules (egress to GitHub/ECR/SSM). Access via SSM Session Manager.
- Placement is controlled by `var.create_runner_network`, `var.vpc_id` /
  `var.subnet_id`, and the `var.allow_default_vpc` opt-in (ADR-004-R20). By
  default the stack fails closed on the account default VPC, where a range's
  private-DNS interface endpoints can hijack the runner's AWS API resolution.
  Setting `create_runner_network = true` (issue #1433) provisions a dedicated,
  ADR-004-R20-compliant runner VPC (non-default, NAT-only egress, no private-DNS
  interface endpoints) via `modules/github-runner-network` and places the runner
  in it; its outputs take precedence over `vpc_id`/`subnet_id` and
  `allow_default_vpc`. Otherwise supply a non-default `vpc_id`/`subnet_id` (a
  dedicated runner VPC or the portal VPC private tier), or set
  `allow_default_vpc = true` to accept default-VPC placement and auto-resolve the
  default VPC plus a subnet (no committed IDs). aws-dev/aws-proof opt in today;
  the design is being reassessed in #1437.
- IAM instance profile with inline SSM Session Manager and ECR push/pull
  policies. Inline policies avoid `iam:AttachRolePolicy`, which may be
  denied by AWS Organizations SCPs in fresh managed accounts.
- Launch user data installs Docker, the build chain, the .NET runtime libs
  the Actions binary needs, and downloads the latest runner tarball.
  Registration is **automated** by the bootstrap `runners` path (see below);
  the manual `config.sh` recipe is kept only as a fallback.

State backend: `<env>.s3.tfbackend` (partial; bucket/key supplied at
`terraform init` time).

For a fresh AWS account, run `scripts/bootstrap/deploy.py bootstrap` before
this runner root. Bootstrap creates the shared S3 state bucket and rewrites
`dev.s3.tfbackend`; the runner root intentionally reuses that backend.

## Scheduling policy

GitHub Actions does not support a single `runs-on` target that uses
GitHub-hosted runners first, then self-hosted runners, then waits for
whichever runner frees up next. Standard GitHub-hosted labels such as
`ubuntu-latest` and self-hosted labels are separate scheduling targets.

Shifter splits work across both capacity pools instead:

- Portable quality jobs run on `ubuntu-latest`, using the repository's
  GitHub-hosted runner allotment. Pull-request events are hosted-only;
  `deploy.yml` must not route PR code into reusable jobs that target
  `runs-on: self-hosted`.
- Deployment, image build, Packer, and environment-mutating jobs remain
  on `self-hosted`, using the EC2 runner pool that has the expected
  long-lived tooling and account access patterns. Those jobs run only on
  trusted `push` / `workflow_dispatch` paths and bind a GitHub
  Environment such as `aws-dev`, `aws-prod`, or `gcp-dev` before assuming
  deploy credentials.

## Deploying

From repo root:

```bash
./scripts/runner-deploy.sh              # init + plan
./scripts/runner-deploy.sh --apply      # init + apply
./scripts/runner-deploy.sh --destroy
```

The script reads `PANW_SHIFTER_DEV_PROFILE` from `.env`. AWS pager
should be disabled (`export AWS_PAGER=""`) or `aws` calls will block on
`less`.

Before applying in a new account, choose a runner network that range
provisioning cannot deploy into. Valid choices are a dedicated runner VPC or
the portal VPC private tier. The runner subnet needs outbound egress for GitHub,
ECR, SSM, and AWS APIs through NAT, an approved proxy, or VPC endpoints plus
internet egress for GitHub. The account default VPC is not acceptable because
range-created private-DNS interface endpoints affect every workload in that VPC.

For the portal VPC option, use the portal Terraform outputs as the source for
`vpc_id` and `subnet_id`:

```bash
cd platform/terraform/environments/dev/portal
terraform output vpc_id
terraform output private_subnet_ids
```

Do not commit live VPC or subnet IDs to the placeholder tfvars files. Keep
deployment-specific IDs in a gitignored operator override or another approved
deploy-time binding. See the preflight note:
[`docs/architecture/github-runner-network-isolation-preflight-1222.md`](../../../../docs/architecture/github-runner-network-isolation-preflight-1222.md).

## Health monitoring

Each runner has CloudWatch alarms for EC2 instance/system status checks,
sustained CPU (hang proxy), and runner-service liveness. A systemd timer
(`shifter-runner-health.timer`, installed by `user_data`) publishes the
`actions.runner.*` service state as the `Shifter/RunnerHealth:RunnerServiceActive`
metric; its alarm treats missing data as breaching so a hung host that stops
reporting alarms instead of going silent. Alarms notify the
`shifter-github-runner-alerts` SNS topic
(`terraform output runner_alerts_topic_arn`); set `alarm_email` to subscribe an
inbox, or subscribe Slack/Teams to the topic. The system-status alarm can
EC2-auto-recover when `enable_system_auto_recovery` is set (default on).

A freshly applied host shows `RunnerServiceActive = 0` until you register the
runner below; the `service-inactive` alarm clears once `svc.sh start` runs.

The monitor installs via `user_data`, which runs only on first boot, so
`aws_instance.runner` sets `user_data_replace_on_change = true`. Applying this
change therefore **replaces** existing runners (re-running the install); a
replaced runner must be re-registered. Roll out one runner at a time
(`-target`) to avoid dropping all self-hosted capacity. See the runbook section
on rolling out the monitor to existing runners.

See the response runbook:
[`docs/ops/github-runner-health-alerts.md`](../../../../docs/ops/github-runner-health-alerts.md).

## Registering a runner

Each EC2 ships ready to register but not yet registered. `./config.sh`
needs a single-use **registration token** from GitHub. The token is
exchanged once for long-lived runner credentials stored in `.runner` /
`.credentials` on the instance. After that, the runner stays authenticated
indefinitely. You only mint a new token when adding,
re-registering, or replacing a runner.

### Automated (recommended)

The bootstrap `runners` subcommand applies this root and registers every runner
end-to-end (issue #1433). It provisions the dedicated runner VPC by default,
mints a single-use token **per runner**, delivers it inside one JSON SSM
`--parameters` body (so the operator log redactor masks the whole blob and no
token lands in Terraform state, user data, SSM Parameter Store, Secrets Manager,
or logs), and verifies each runner online via the GitHub API:

```bash
./scripts/bootstrap/deploy.py runners --env dev --profile aws-dev
# --use-existing-network   reuse an already-configured vpc_id/subnet_id / default-VPC opt-in
# --dry-run                show the plan without minting a token or sending SSM commands
```

### Manual (fallback)

For a one-off registration outside the bootstrap flow:

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

Verify:

```bash
gh api repos/Brad-Edwards/shifter/actions/runners --jq '.runners[] | {name, status}'
```

## Gotchas

### `./bin/installdependencies.sh` doesn't recognise Amazon Linux 2023

The bundled dependency installer matches on `/etc/os-release`'s `ID`
and aborts with `Can't detect current OS type` because AL2023 reports
`ID="amzn"` (and `ID_LIKE="fedora"` only, not real Fedora). The
runner binary still needs libicu / krb5-libs / zlib / lttng-ust /
openssl-libs at startup or `./config.sh` exits with
`Libicu's dependencies is missing for Dotnet Core 6.0`.

**Fix is baked in:** `user_data` installs those packages directly via
`dnf` so the runner is ready as soon as cloud-init finishes. If you
ever swap distros, drop the explicit `dnf install` line and let
`installdependencies.sh` handle it again.

### Registration tokens are single-use and short-lived (~1 hour)

You cannot re-use a token across multiple runners; mint one per
registration call. The runner itself does not need fresh tokens after
registration because long-lived `.credentials` handle ongoing auth.

### `runner-deploy.sh` clobbered the lockfile

Old behaviour was `rm -rf .terraform .terraform.lock.hcl` before init.
With `.terraform.lock.hcl` now tracked in git, that would delete the
pinned provider hashes on every run. Fixed to `rm -rf .terraform/`.

### Stale philips-labs auto-scaler artifacts

`webhook.zip`, `runners.zip`, `runner-binaries-syncer.zip` and a stale
`Prerequisites` block referencing `/shifter/github-runner/key-base64`
SSM params are leftovers from an abandoned attempt at the
philips-labs/terraform-aws-github-runner module. Current setup is
plain EC2; nothing in `main.tf` references them. Deleted in 3.95.3.

## Removing a runner

```bash
# From the EC2 (via SSM):
cd /home/ec2-user/actions-runner
TOKEN=$(gh api -X POST /repos/Brad-Edwards/shifter/actions/runners/remove-token --jq .token)
sudo ./svc.sh stop
sudo ./svc.sh uninstall
sudo -u ec2-user ./config.sh remove --token "$TOKEN"

# Then terraform destroy or scale down runner_count.
```

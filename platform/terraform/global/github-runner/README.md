# GitHub Actions Self-Hosted Runners

EC2-based runners that pick up `runs-on: self-hosted` jobs from
`Brad-Edwards/shifter`. Lives in the dev account; cross-account roles
let it deploy to both dev and prod.

## Architecture

- `aws_instance.runner[count]`: Amazon Linux 2023, t3.large, no inbound
  rules (egress to GitHub/ECR/SSM). Access via SSM Session Manager.
- IAM instance profile with inline SSM Session Manager and ECR push/pull
  policies. Inline policies avoid `iam:AttachRolePolicy`, which may be
  denied by AWS Organizations SCPs in fresh managed accounts.
- Launch user data installs Docker, the build chain, the .NET runtime libs
  the Actions binary needs, and downloads the latest runner tarball.
  **Registration is manual** -- see below.

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

Before applying in a new account, update `dev.tfvars` with the account-local
VPC and subnet. The runner instances need outbound internet access for GitHub,
ECR, and SSM; the default VPC public subnet is acceptable for dev bootstrap.

```bash
aws ec2 describe-vpcs \
  --profile "$PANW_SHIFTER_DEV_PROFILE" \
  --region us-east-2 \
  --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' \
  --output text

aws ec2 describe-subnets \
  --profile "$PANW_SHIFTER_DEV_PROFILE" \
  --region us-east-2 \
  --filters Name=default-for-az,Values=true \
  --query 'Subnets[?AvailabilityZone==`us-east-2a`].SubnetId | [0]' \
  --output text
```

## Registering a runner (one-time per instance)

Each EC2 ships ready to register but not yet registered. `./config.sh`
needs a single-use **registration token** from GitHub. The token is
exchanged once for long-lived runner credentials stored in `.runner` /
`.credentials` on the instance. After that, the runner stays authenticated
indefinitely. You only mint a new token when adding,
re-registering, or replacing a runner.

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

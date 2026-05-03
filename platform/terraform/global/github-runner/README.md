# GitHub Actions Self-Hosted Runners

EC2-based runners that pick up `runs-on: self-hosted` jobs from
`Brad-Edwards/shifter`. Lives in the dev account; cross-account roles
let it deploy to both dev and prod.

## Architecture

- `aws_instance.runner[count]` — Amazon Linux 2023, t3.large, no inbound
  rules (egress to GitHub/ECR/SSM). Access via SSM Session Manager.
- IAM instance profile with `AmazonSSMManagedInstanceCore` + an inline
  policy granting ECR push/pull on `shifter-*` repos.
- `user_data` installs Docker, the build chain, the .NET runtime libs
  the Actions binary needs, and downloads the latest runner tarball.
  **Registration is manual** — see below.

State backend: `<env>.s3.tfbackend` (partial; bucket/key supplied at
`terraform init` time).

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

## Registering a runner (one-time per instance)

Each EC2 ships ready to register but not yet registered. `./config.sh`
needs a single-use **registration token** from GitHub. The token is
exchanged once for long-lived runner credentials stored in `.runner` /
`.credentials` on the instance — after that, the runner stays
authenticated indefinitely. You only mint a new token when adding,
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
`ID="amzn"` (and `ID_LIKE="fedora"` only — not real fedora). The
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
registration — long-lived `.credentials` handle ongoing auth.

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

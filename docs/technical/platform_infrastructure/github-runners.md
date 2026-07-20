# GitHub Actions Self-Hosted Runners

Self-hosted runners for GitHub Actions workflows. The AWS fleet (below) serves
the shared `self-hosted` label; a GCP dev tenant runs its own runner under the
`gcp-dev` label so it does not borrow the AWS fleet (see
[GCP-native runners](#gcp-native-runners-dev-tenant-containment)).

## Scheduling policy

GitHub Actions does not provide native fallback from `ubuntu-latest` to
self-hosted runners or a priority order across those runner classes.
Workflow jobs must choose a concrete scheduling target.

Shifter splits workflow capacity by job type. Portable quality jobs run
on `ubuntu-latest` to use the GitHub-hosted runner allotment, while
deployment, image build, Packer, and environment-mutating jobs remain on
`self-hosted` custom runners.

## Infrastructure

| Parameter | Value |
|-----------|-------|
| **Terraform** | `platform/terraform/global/github-runner/` |
| **Instance type** | `t3.large` |
| **AMI** | Amazon Linux 2023 (latest) |
| **Count** | 2 |
| **Region** | `us-east-2` |
| **Access** | SSM Session Manager (no SSH) |

## Provisioning

Instances are created by Terraform with a user_data script that installs dependencies:

- Docker
- Git, jq, tar, unzip
- Python 3.12 + pip + devel headers
- Node.js + npm

The user_data script downloads the GitHub Actions runner binary but does **not** register it. Registration is manual.

## Post-Provision Setup

After Terraform creates the instance, connect via SSM and complete these steps:

### 1. Register the runner

```bash
sudo -u ec2-user bash
cd /home/ec2-user/actions-runner
./config.sh --url https://github.com/Brad-Edwards/shifter --token <TOKEN>
```

Generate the registration token at: Settings > Actions > Runners > New self-hosted runner.

### 2. Add the runner service user to the docker group

The user_data script adds `ec2-user` to the `docker` group, but `./config.sh` installs the runner service under its own user. The service user also needs docker access.

```bash
# Determine the runner service user (check the service file)
cat /home/ec2-user/actions-runner/.service | grep User=

# Add that user to the docker group
sudo usermod -aG docker <runner-user>
```

If the runner was installed to run as `ec2-user`, this step is already handled by user_data. If it runs as a different user (for example `runner`), the group add is required.

**Without this step, any workflow job that uses Docker (checkov, container builds, docker-compose) will fail with:**
```
permission denied while trying to connect to the Docker daemon socket
```

### 3. Install and start the service

```bash
cd /home/ec2-user/actions-runner
sudo ./svc.sh install
sudo ./svc.sh start
```

### 4. Verify

```bash
sudo ./svc.sh status
docker ps  # confirm docker access works for the service user
```

## Naming

Instances are tagged `shifter-github-runner-{N}` (1-indexed).

## IAM Permissions

The runner role (`shifter-github-runner`) has:

| Policy | Purpose |
|--------|---------|
| `AmazonSSMManagedInstanceCore` | SSM Session Manager access |
| ECR inline policy | Push/pull container images |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `permission denied` on Docker socket | Runner service user not in `docker` group | `sudo usermod -aG docker <user>` + restart service |
| Runner offline in GitHub | Service not started or crashed | `sudo ./svc.sh status`, then `sudo ./svc.sh start` |

## GCP-native runners (dev-tenant containment)

The runner story above is AWS-only. GCP-dev CI historically ran on the same AWS
fleet, so a GCP dev tenant could not stand up without an AWS one. Issue #1546
adds a GCP-native runner so each dev tenant is self-contained: a GCP dev tenant
runs its own CI/deploy, and neither dev tenant assumes the other exists. This is
the dev-tenant amendment to ADR-033-R2 (there is no product deployment model
yet; the current bootstrap is itself a dev-tenant deploy mechanism).

| Parameter | Value |
|-----------|-------|
| **Terraform root** | `platform/terraform/gcp/global/github-runner/` (dedicated GCS state prefix, separate from the gcp-dev platform root) |
| **Network module** | `platform/terraform/gcp/modules/github-runner-network/` |
| **Instance** | private-only Shielded VM (no external IP), OS Login, dedicated least-privilege service account |
| **Network** | dedicated custom VPC, private subnet with flow logs, Cloud NAT egress, SSH ingress from Google's IAP range (`35.235.240.0/20`) only |
| **Label** | `gcp-dev` (registered with `--no-default-labels`, so it never matches bare `runs-on: self-hosted`) |

### Provisioning + registration

Runners are provisioned and registered by the bootstrap CLI, using the
operator's default gcloud/ADC identity (no service account key):

```bash
./scripts/bootstrap/deploy.py runners --cloud gcp --env gcp-dev --project-id <gcp-project>
```

The flow applies the Terraform root, then for each runner mints a single-use
GitHub registration token (`gh api`, held in memory only) and delivers it to the
host over the `gcloud compute ssh --tunnel-through-iap` stdin stream into a
root-only `0600` temp file. The token is kept out of the operator's argv/logs, a
Terraform input/output/state value, instance metadata, and Secret Manager. The
runner's `config.sh` requires `--token` for non-interactive registration and has
no stdin/file/env channel (its `Console.ReadKey` prompt fails on redirected
stdin), so the token is referenced as `--token "$(cat "$TOKFILE")"`; it appears
only momentarily in the isolated runner VM's process args while `config.sh` runs,
then the temp file is removed and the single-use token expires. The command fails
closed unless every runner registers cleanly AND the GitHub API reports it online
with the `gcp-dev` label.

The GCE startup script installs a pinned, checksum-verified runner but never
registers it (no token on the host), so registration stays entirely on the
out-of-band IAP path.

### Isolation and scheduling

- The `gcp-dev` label keeps GCP CI off the AWS `self-hosted` pool and vice
  versa. `_gcp-dev.yml` (deploy) and `gcp-dev-destroy.yml` select `runs-on: gcp-dev`.
- The ADR-003-R5 exposure checker treats `gcp-dev` as self-hosted-class, so the
  cut-over jobs keep their pull-request-reachability gate (no fork-PR can reach a
  self-hosted runner). New self-hosted labels must be added to that checker.
- Network isolation is pinned by `check-tf-gcp-runner-network` (ADR-008-R8):
  a dedicated custom VPC (never the default network) with IAP-only SSH.

### Custom actionlint label

`gcp-dev` is declared in `.github/actionlint.yaml` so actionlint accepts it as a
self-hosted runner label. Add any future custom runner labels there too.
| ECR auth failures | IAM role missing ECR permissions | Check `aws_iam_role_policy.ecr` in Terraform |

# GitHub Actions Self-Hosted Runners

EC2-based self-hosted runners for GitHub Actions workflows.

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

If the runner was installed to run as `ec2-user`, this step is already handled by user_data. If it runs as a different user (e.g., `runner`), the group add is required.

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
| ECR auth failures | IAM role missing ECR permissions | Check `aws_iam_role_policy.ecr` in Terraform |

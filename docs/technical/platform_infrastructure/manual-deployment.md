# Manual Deployment

Infrastructure stacks that are deployed manually (not via CI/CD).

## Global Terraform Stacks

Located in `platform/terraform/global/`. These stacks manage cross-cutting infrastructure that must exist before CI/CD can run or that require careful manual control.

| Stack | Purpose |
|-------|---------|
| `iam/` | GitHub OIDC provider, CI/CD IAM roles |
| `github-runner/` | Self-hosted GitHub Actions runner infrastructure |
| `dev-box/` | Windows development workstation |

## IAM Stack

GitHub OIDC authentication and IAM roles for CI/CD pipelines live in `platform/terraform/global/iam`. This stack is now applied by the bootstrap CLI, not by a manual `terraform apply`.

**What it creates:**

- GitHub OIDC identity provider
- IAM roles for GitHub Actions (`github-actions-shifter-dev`, `github-actions-shifter-prod`)
- Scoped IAM policies for infrastructure management

**Deploy:**

`scripts/bootstrap/deploy.py bootstrap` creates the S3 state backend (with native locking) and applies the `global/iam` stack (OIDC provider plus CI/CD roles) in one step:

```bash
# Dev environment
./scripts/bootstrap/deploy.py bootstrap --env dev --profile <dev account profile>

# Prod environment
./scripts/bootstrap/deploy.py bootstrap --env prod --profile <prod account profile>
```

**After deployment:**

Add the role ARN to GitHub repository secrets. Read it with `terraform output -raw github_actions_role_arn` in `platform/terraform/global/iam`:

- `AWS_ROLE_ARN_DEV` - Output from the dev bootstrap
- `AWS_ROLE_ARN` - Output from the prod bootstrap

## GitHub Runner Stack

Self-hosted GitHub Actions runners. The current architecture is the `github-runner-network` module plus a persistent `aws_instance` runner fleet in `platform/terraform/global/github-runner`, provisioned and registered by the bootstrap CLI. The older `terraform-aws-github-runner` Lambda and webhook module is no longer used.

**What it creates:**

- A dedicated, isolated runner VPC (`github-runner-network` module)
- Persistent EC2 runner instances
- IAM roles and security groups

**Prerequisite:**

Run `scripts/bootstrap/deploy.py bootstrap --env <env>` first so the shared S3 state backend that the runner root reuses exists.

**Deploy:**

```bash
./scripts/bootstrap/deploy.py runners --env dev --profile <dev account profile>
```

This provisions the runner network and instances, mints a single-use registration token per runner, registers each runner over SSM, and verifies each one online through the GitHub API.

**Reference:**

The authoritative runbook for standup, network isolation, health monitoring, removal, and gotchas is [`aws-runner-provisioning-runbook.md`](../../dev/aws-runner-provisioning-runbook.md).

## Dev Box Stack

Windows Server 2022 development workstation for remote development work.

**What it creates:**

- EC2 spot instance (Windows Server 2022)
- IAM role with S3, ECR, and Secrets Manager access
- Security group for RDP access
- Scheduled shutdown at 11 PM Pacific (cost control)
- Admin password in Secrets Manager

**Deploy:**

```bash
cd platform/terraform/global/dev-box
AWS_PROFILE=<dev account profile> terraform init
AWS_PROFILE=<dev account profile> terraform apply
```

**Management:**

Use the helper script from repo root:

```bash
./scripts/dev-box.sh status    # Check instance status
./scripts/dev-box.sh start     # Start the instance
./scripts/dev-box.sh stop      # Stop (saves costs)
./scripts/dev-box.sh connect   # Open Fleet Manager RDP
./scripts/dev-box.sh password  # Get admin password
./scripts/dev-box.sh tunnel    # Start SSM port forwarding for local RDP client
```

**Pre-installed tools:** Git, Python 3.12, Node.js LTS, AWS CLI, Terraform, VS Code, Chrome, Claude Code.

See `platform/terraform/global/dev-box/README.md` for full documentation.

## Deployment Order

For a fresh environment:

1. **Bootstrap (IAM + state backend)** - Must be first. `deploy.py bootstrap` creates the OIDC provider, CI/CD roles, and shared S3 state backend.
2. **GitHub Runner** - Optional. Only needed for self-hosted runners (`deploy.py runners`).
3. **Dev Box** - Optional. Only needed for Windows development.

After bootstrap, CI/CD can manage all other infrastructure automatically.

## GCP

GCP manual setup is separate from the AWS stacks above:

1. **GCP project setup** - Create project, enable APIs, configure billing
2. **Workload Identity Federation** - Configure OIDC provider for GitHub Actions
3. **Secure bootstrap inputs** - Set `public_hostname`, `enable_managed_tls = true`, and leave `gke_master_authorized_cidrs = []` for Connect Gateway (or use connected RFC1918 networks only)
4. **Bootstrap operator credentials** - Provide `GCP_BOOTSTRAP_ADMIN_EMAIL` and `GCP_BOOTSTRAP_ADMIN_PASSWORD` in the local bootstrap env or GitHub environment secrets, or be ready to enter them interactively
5. **Optional bootstrap admin elevation** - Provide `PLATFORM_BOOTSTRAP_STAFF_EMAILS` / `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` if the first operator should come up with admin privileges on first login
6. **DNS** - Point the public hostname at the reserved ingress IP if DNS is managed outside Terraform

The authoritative manual bring-up path is:

```bash
./scripts/bootstrap/deploy.py gdc-bootstrap --project-id prod-rwctxzl6shxk --cluster-id cluster1
```

That bootstrap path now expects:

- private GDC hosts with IAP-based operator access
- a managed-TLS public hostname (`shifter.example.com` in the current `gcp-dev` tfvars)
- authorized CIDRs restricting the public GKE control-plane endpoint
- Cloud Armor on the public ingress backends
- Terraform-managed Identity Platform for corporate login, with browser-side Google auth and server-side verified-token exchange
- a bootstrap-seeded first operator account

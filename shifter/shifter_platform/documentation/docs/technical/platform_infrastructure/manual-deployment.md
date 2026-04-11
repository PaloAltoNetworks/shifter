# Manual Deployment

Infrastructure stacks that are deployed manually (not via CI/CD).

## Global Terraform Stacks

Located in `platform/terraform/global/`. These stacks manage cross-cutting infrastructure that must exist before CI/CD can run or that require careful manual control.

| Stack | Purpose |
|-------|---------|
| `iam/` | GitHub OIDC provider, CI/CD IAM roles, Cursor Bedrock access |
| `github-runner/` | Self-hosted GitHub Actions runner infrastructure |
| `dev-box/` | Windows development workstation |

## IAM Stack

GitHub OIDC authentication and IAM roles for CI/CD pipelines.

**What it creates:**

- GitHub OIDC identity provider
- IAM roles for GitHub Actions (`github-actions-shifter-dev`, `github-actions-shifter-prod`)
- Scoped IAM policies for infrastructure management
- Cursor Bedrock IAM user for IDE access

**Deploy:**

```bash
cd platform/terraform/global/iam

# Dev environment
AWS_PROFILE=<dev account profile> terraform init -backend-config=dev.s3.tfbackend
AWS_PROFILE=<dev account profile> terraform apply -var-file=dev.tfvars

# Prod environment
AWS_PROFILE=<prod account profile> terraform init -backend-config=prod.s3.tfbackend
AWS_PROFILE=<prod account profile> terraform apply -var-file=prod.tfvars
```

**After deployment:**

Add the role ARN to GitHub repository secrets:

- `AWS_ROLE_ARN_DEV` - Output from dev deployment
- `AWS_ROLE_ARN` - Output from prod deployment

Get Cursor Bedrock credentials:

```bash
terraform output cursor_bedrock_access_key_id
terraform output -raw cursor_bedrock_secret_access_key
```

## GitHub Runner Stack

Auto-scaling self-hosted GitHub Actions runners using the `terraform-aws-github-runner` module.

**What it creates:**

- Lambda functions for webhook handling and runner management
- API Gateway webhook endpoint
- EC2 spot instances (ephemeral, scale-from-zero)
- IAM roles and security groups

**Prerequisites:**

1. Create a GitHub App:
   - Set "Where can this GitHub App be installed?" to **Only on this account**
   - Repository permissions: Actions (read), Checks (read), Metadata (read)
   - Organization permissions: Self-hosted runners (read/write)
   - Disable webhook initially (configure after deploy)
2. Store secrets in AWS SSM Parameter Store:
   - `/shifter/github-runner/key-base64` - Base64-encoded private key
   - `/shifter/github-runner/webhook-secret` - Webhook secret

See `.env.example` for secret format:

```bash
# Generate base64 key
base64 -w 0 app.private-key.pem

# Store in SSM (do this manually in AWS Console or CLI)
aws ssm put-parameter --name "/shifter/github-runner/key-base64" --value "..." --type SecureString
aws ssm put-parameter --name "/shifter/github-runner/webhook-secret" --value "..." --type SecureString
```

**Deploy:**

```bash
cd platform/terraform/global/github-runner

# Dev environment
AWS_PROFILE=<dev account profile> terraform init -backend-config=dev.s3.tfbackend
AWS_PROFILE=<dev account profile> terraform apply -var-file=dev.tfvars
```

**After deployment:**

1. Go to your GitHub App settings → Webhook
2. Enable webhook and paste the URL from terraform output
3. Enter the webhook secret (same value stored in SSM)
4. Subscribe to events: check **Workflow Job** only
5. Install the app on your repository

## Dev Box Stack

Windows Server 2022 development workstation for remote development work.

**What it creates:**

- EC2 spot instance (Windows Server 2022)
- IAM role with S3, ECR, and Secrets Manager access
- Security group for RDP access
- Scheduled shutdown at 11pm Pacific (cost control)
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

1. **IAM** - Must be first. Creates OIDC provider and CI/CD roles.
2. **GitHub Runner** - Optional. Only needed for self-hosted runners.
3. **Dev Box** - Optional. Only needed for Windows development.

After IAM is deployed, CI/CD can manage all other infrastructure automatically.

## GCP

GCP manual setup is separate from the AWS stacks above:

1. **GCP project setup** - Create project, enable APIs, configure billing
2. **Workload Identity Federation** - Configure OIDC provider for GitHub Actions
3. **Secure bootstrap inputs** - Set `public_hostname`, `enable_managed_tls = true`, and `gke_master_authorized_cidrs` in `platform/terraform/gcp/environments/gcp-dev/terraform.tfvars`
4. **Bootstrap operator credentials** - Provide `GCP_BOOTSTRAP_ADMIN_EMAIL` and `GCP_BOOTSTRAP_ADMIN_PASSWORD` in the local bootstrap env or GitHub environment secrets, or be ready to enter them interactively
5. **Optional bootstrap admin elevation** - Provide `PLATFORM_BOOTSTRAP_STAFF_EMAILS` / `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` if the first operator should come up with admin privileges on first login
6. **DNS** - Point the public hostname at the reserved ingress IP if DNS is managed outside Terraform

The authoritative manual bring-up path is:

```bash
./scripts/bootstrap/deploy.py gdc-bootstrap --project-id prod-rwctxzl6shxk --cluster-id cluster1
```

That bootstrap path now expects:

- private GDC hosts with IAP-based operator access
- a managed-TLS public hostname (`shifter.keplerops.com` in the current `gcp-dev` tfvars)
- authorized CIDRs restricting the public GKE control-plane endpoint
- Cloud Armor on the public ingress backends
- Terraform-managed Identity Platform for corporate login
- a bootstrap-seeded first operator account

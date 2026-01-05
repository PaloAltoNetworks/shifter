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
AWS_PROFILE=panw-shifter-dev-workstation terraform init -backend-config=dev.s3.tfbackend
AWS_PROFILE=panw-shifter-dev-workstation terraform apply -var-file=dev.tfvars

# Prod environment
AWS_PROFILE=dev-workstation-user terraform init -backend-config=prod.s3.tfbackend
AWS_PROFILE=dev-workstation-user terraform apply -var-file=prod.tfvars
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
AWS_PROFILE=panw-shifter-dev-workstation terraform init -backend-config=dev.s3.tfbackend
AWS_PROFILE=panw-shifter-dev-workstation terraform apply -var-file=dev.tfvars
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
AWS_PROFILE=panw-shifter-dev-workstation terraform init
AWS_PROFILE=panw-shifter-dev-workstation terraform apply
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

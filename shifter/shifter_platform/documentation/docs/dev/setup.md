# Setup

Deploying Shifter from a bare AWS account to full production.

## Prerequisites

- Python 3.12+
- Terraform 1.7+
- AWS CLI v2 configured with SSO or IAM credentials
- GitHub CLI (`gh`) authenticated
- Docker

## Cold-Start Deployment (New AWS Account)

Use the deployment CLI which walks you through each step with confirmations:

```bash
# Preview what will happen (no changes made)
./scripts/deploy.py full --env prod --dry-run

# Run the full deployment
AWS_PROFILE=<your-prod-profile> ./scripts/deploy.py full --env prod
```

Or run phases separately:

```bash
# Phase 1: Bootstrap AWS account (S3, DynamoDB, IAM)
AWS_PROFILE=<your-prod-profile> ./scripts/deploy.py bootstrap --env prod

# Or use standalone bash scripts:
# AWS_PROFILE=<your-prod-profile> ./scripts/bootstrap/prod.sh

# Phase 2: Deploy Terraform (Core → Range → Portal)
AWS_PROFILE=<your-prod-profile> ./scripts/deploy.py terraform --env prod
```

### 1. Bootstrap AWS Account

The `bootstrap` command creates:
- S3 bucket for Terraform state
- DynamoDB table for state locking
- GitHub OIDC provider (keyless CI/CD auth)
- IAM role with all required permissions

It outputs:
- GitHub secret value (`AWS_ROLE_ARN`)
- Backend configuration for `backend.tf` files

### 2. Configure GitHub Secrets

Add these secrets in GitHub repository settings (Settings → Secrets and variables → Actions):

| Secret | Value |
|--------|-------|
| `AWS_ROLE_ARN` | Prod IAM role ARN from bootstrap output |
| `AWS_ROLE_ARN_DEV` | Dev IAM role ARN from bootstrap output |

### 3. Update Backend Configuration

Copy the backend config from bootstrap output to these files:

| File | State Key |
|------|-----------|
| `platform/terraform/environments/prod/backend.tf` | `shifter/prod/terraform.tfstate` |
| `platform/terraform/environments/prod/portal/backend.tf` | `shifter/prod/portal/terraform.tfstate` |
| `platform/terraform/environments/prod/range/backend.tf` | `shifter/prod/range/terraform.tfstate` |

### 4. Configure terraform.tfvars

Copy and fill in the example:

```bash
cp platform/terraform/environments/prod/portal/terraform.tfvars.example \
   platform/terraform/environments/prod/portal/terraform.tfvars
```

Edit `terraform.tfvars` with your values. Key settings:

```hcl
environment  = "prod"
aws_region   = "us-east-2"
domain_name  = "shifter.yourdomain.com"
```

Terraform variables are committed to the repo (they're config, not secrets).

### 5. Deploy Infrastructure

Deploy in this order (dependencies flow down):

```
┌─────────────────────────────────┐
│  1. Core (ECR repositories)    │
│  platform/terraform/environments/prod/
└───────────────┬─────────────────┘
                │
        ┌───────┴───────┐
        │               │
        ▼               ▼
┌───────────────┐ ┌─────────────────────────┐
│  2. Range VPC │ │  (wait for Range)       │
│  .../range/   │ │                         │
└───────┬───────┘ └─────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  3. Portal                      │
│  .../portal/                    │
│  (references Range outputs)     │
└─────────────────────────────────┘
```

**Using the CLI (recommended):**

```bash
AWS_PROFILE=<your-profile> ./scripts/deploy.py terraform --env prod
```

The CLI walks through each component, shows the plan, and asks for confirmation before applying.

**Via CI/CD:**

Push to `main` branch to trigger deployment (after bootstrap and backend.tf are configured).

**Manual deployment:**

```bash
# Step 1: Core (ECR)
cd platform/terraform/environments/prod
AWS_PROFILE=<your-profile> terraform init && terraform plan && terraform apply

# Step 2: Range VPC
cd range
AWS_PROFILE=<your-profile> terraform init && terraform plan && terraform apply

# Step 3: Portal
cd ../portal
AWS_PROFILE=<your-profile> terraform init && terraform plan && terraform apply
```

### 6. ACM Certificate Validation

On first deploy, Terraform pauses waiting for ACM certificate validation (up to 45 min timeout).

**Get the validation records:**

```bash
# While terraform apply is running (or after plan), get the CNAME records:
cd platform/terraform/environments/prod/portal
AWS_PROFILE=<your-profile> terraform output -json acm_validation_records
```

Output format:
```json
{
  "shifter.yourdomain.com": {
    "name": "_abc123.shifter.yourdomain.com.",
    "type": "CNAME",
    "value": "_xyz789.acm-validations.aws."
  }
}
```

**Add to your DNS provider:**

| Type | Name | Value |
|------|------|-------|
| CNAME | `_abc123.shifter.yourdomain.com` | `_xyz789.acm-validations.aws.` |

After DNS propagates (~5 min), Terraform continues automatically.

### 7. Point Domain to ALB

After deployment completes:

```bash
cd platform/terraform/environments/prod/portal
AWS_PROFILE=<your-profile> terraform output alb_dns_name
```

Create a CNAME record pointing your domain to the ALB DNS name.

### 8. Build and Push Container

The first deploy creates empty ECR repos. Push the portal container:

```bash
# Via CI/CD: push to main triggers build
# Or manually:
./scripts/build-and-push.sh prod
```

### 9. Cognito Configuration

Cognito is fully configured by Terraform. You only need to:

1. **Set `cognito_domain_prefix`** in `terraform.tfvars` (must be globally unique):
   ```hcl
   cognito_domain_prefix = "shifter-prod-yourorg"
   ```

2. **Create first user** (after Terraform apply):
   ```bash
   # Get user pool ID from terraform output
   USER_POOL_ID=$(terraform output -raw cognito_user_pool_id)
   
   # Create user
   aws cognito-idp admin-create-user \
     --user-pool-id $USER_POOL_ID \
     --username user@paloaltonetworks.com \
     --user-attributes Name=email,Value=user@paloaltonetworks.com \
     --profile <your-profile>
   ```

Callback URLs (`https://yourdomain.com/oidc/callback/`) are automatically configured from `domain_name`.

Email domain restrictions are controlled via `allowed_email_domains` in portal module.

## Existing Environment Setup

If deploying to an account with existing infrastructure:

### Initialize Terraform

```bash
cd platform/terraform/environments/prod/portal
AWS_PROFILE=<your-profile> terraform init
```

### Verify State

```bash
AWS_PROFILE=<your-profile> terraform plan
```

No changes means infrastructure matches state.

## Common Issues

### State Lock Error

Someone else is running Terraform, or a previous run crashed:

```bash
# Check who has the lock, then force unlock if needed
terraform force-unlock <LOCK_ID>
```

### Provider Cache Issues

```bash
rm -rf .terraform
terraform init
```

### ACM Validation Timeout

If Terraform times out waiting for ACM:

```bash
# 1. Get the validation records again
terraform output -json acm_validation_records

# 2. Check if DNS is propagated (replace with your actual record name)
dig CNAME _abc123.shifter.yourdomain.com

# 3. If DNS is correct, just re-run apply (it will resume)
terraform apply
```

Common issues:
- **Trailing dot**: Some DNS providers need the trailing `.` removed from the value
- **Wrong record type**: Must be CNAME, not TXT
- **Propagation delay**: Wait 5-10 minutes after adding records

### Container Pull Failures

Check ECR repo exists and has images:

```bash
aws ecr describe-images --repository-name shifter-prod-portal
```

If empty, push a container first.

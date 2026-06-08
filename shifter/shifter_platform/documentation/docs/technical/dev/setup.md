# Setup

Deploy Shifter from a cloud account to a running environment.

## Prerequisites

- Python 3.12+
- `uv`
- Terraform 1.7+
- GitHub CLI (`gh`) authenticated
- Docker
- **AWS**: AWS CLI v2 configured with SSO or IAM credentials
- **GCP**: `gcloud` CLI authenticated with appropriate project

## Root Installation Config

Create and validate `shifter.yaml` before deployment:

```bash
cp shifter/installation/examples/aws.yaml shifter.yaml
uv run --project shifter/installation shifter-config validate shifter.yaml
```

Use `shifter/installation/examples/gcp.yaml` for GCP. See
[Installation Config](installation-config) for the field reference.

## AWS Deployment

Use the deployment CLI which walks you through each step with confirmations:

```bash
# Preview what will happen (no changes made)
./scripts/bootstrap/deploy.py full --env prod --profile <your-prod-profile> --dry-run

# Run the full deployment
./scripts/bootstrap/deploy.py full --env prod --profile <your-prod-profile>
```

Or run phases separately:

```bash
# Phase 1: Bootstrap AWS account (S3 state backend, GitHub OIDC, IAM)
./scripts/bootstrap/deploy.py bootstrap --env prod --profile <your-prod-profile>

# Or use standalone bash scripts:
# AWS_PROFILE=<your-prod-profile> ./scripts/bootstrap/prod.sh

# Phase 2: Deploy Terraform (Core → Range → Portal)
./scripts/bootstrap/deploy.py terraform --env prod --profile <your-prod-profile>
```

### 1. Bootstrap AWS Account

The `bootstrap` command creates:
- S3 bucket for Terraform state with S3 native locking (`use_lockfile = true`)
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
| `platform/terraform/environments/prod/portal/backend.tf` | `prod/portal/terraform.tfstate` |
| `platform/terraform/environments/prod/range/backend.tf` | `prod/range/terraform.tfstate` |

### 4. Configure deployment-specific values

The committed `terraform.tfvars` files ship an `example.com` baseline.
Override per-deployment values with a `local.auto.tfvars` (gitignored)
alongside each baseline — Terraform auto-loads `*.auto.tfvars` and the
local overrides win:

```bash
cat > platform/terraform/environments/prod/portal/local.auto.tfvars <<EOF
domain_name           = "shifter.your-domain.example"
ses_domain            = "your-domain.example"
alarm_email           = "your-team@your-domain.example"
allowed_email_domains = ["your-domain.example"]
user_storage_bucket   = "shifter-user-storage-<your-account-id>"
EOF
```

`local.auto.tfvars` is gitignored — never commit one. The full list of
required values, plus the CI-deploy equivalent via GitHub secrets and
repository variables, is documented in
[`docs/dev/deploy-secrets.md`](../../../../../../docs/dev/deploy-secrets.md).

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
./scripts/bootstrap/deploy.py terraform --env prod --profile <your-profile>
```

The CLI walks through each component, shows the plan, and asks for confirmation before applying.

**Via CI/CD:**

Run `Deploy` with `workflow_dispatch` on `main` to deploy the AWS production
environment after bootstrap and backend configuration are complete. Pushing or
merging to `main` updates the production code branch only; it does not deploy.

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
# Via CI/CD: run Deploy with workflow_dispatch on main
# Or manually:
./scripts/build-and-push.sh prod
```

### 9. Cognito Configuration

Cognito is fully configured by Terraform. You only need to:

1. **Set `cognito_domain_prefix`** in `local.auto.tfvars` (must be globally unique):
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
     --username YOUR_EMAIL@example.com \
     --user-attributes Name=email,Value=YOUR_EMAIL@example.com \
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

## GCP Deployment

GCP uses a single Terraform module (`platform/terraform/gcp/modules/platform-core/`) plus a Helm-packaged control plane (`platform/charts/shifter/`).

### 1. GCP Project Setup

Create a GCP project and enable the APIs required by the bootstrap path.

### 2. Configure Workload Identity Federation

Set up OIDC federation for GitHub Actions:

1. Create a Workload Identity Pool and Provider
2. Create a service account with required roles
3. Add GitHub secrets:

| Secret | Value |
|--------|-------|
| `GCP_SERVICE_ACCOUNT` | Service account email |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name |

### 3. Configure deployment-specific values

The committed `terraform.tfvars` ships an `example.com` baseline; supply
the real values via a gitignored `local.auto.tfvars` (Terraform auto-loads
`*.auto.tfvars`):

```bash
cat > platform/terraform/gcp/environments/gcp-dev/local.auto.tfvars <<'EOF'
project_id                  = "<your-gcp-project-id>"
public_hostname             = "shifter.<your-domain>"
enable_managed_tls          = true
gke_master_authorized_cidrs = ["<your-operator-egress>/32"]
EOF
```

For CI deploys the equivalent values come from GitHub secrets — see
[`docs/dev/deploy-secrets.md`](../../../../../../docs/dev/deploy-secrets.md).

### 4. Deploy

GCP deployments run through CI/CD on `gcp-dev`. The bootstrap entrypoint is:

```bash
./scripts/bootstrap/deploy.py gdc-bootstrap --project-id <your-gcp-project-id> --cluster-id cluster1
```

That flow:

1. builds or reconciles the GDC substrate
2. applies GCP Terraform (GKE, Cloud SQL, Memorystore, Pub/Sub, etc.)
3. builds and pushes control-plane images
4. renders secure Helm values from Terraform outputs and Secret Manager
5. installs or upgrades the Shifter Helm release

### 5. DNS and TLS

The GCP path requires a real hostname and managed TLS. Point the configured
hostname to the reserved global ingress IP so the Google-managed certificate can
become active.

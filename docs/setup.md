# Setup

## Prerequisites

- Node.js 22.x
- Python 3.11+
- Terraform 1.14+
- AWS CLI configured with SSO
- GitHub CLI (`gh`) for secrets sync

## First-Time Setup (New Clone)

### 1. Bootstrap Terraform Backend

Create S3 bucket and DynamoDB table for Terraform state. Run once per AWS account:

```bash
aws sso login

aws s3 mb s3://shifter-infra-$(uuidgen | tr '[:upper:]' '[:lower:]') --region us-east-2

aws dynamodb create-table \
  --table-name shifter-terraform-$(uuidgen | tr '[:upper:]' '[:lower:]') \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-2
```

Update `terraform/environments/prod/*/backend.tf` with the bucket and table names.

### 2. Deploy Global IAM

The OIDC provider and IAM role must exist before GitHub Actions can deploy:

```bash
cd terraform/global/iam
terraform init
terraform apply
```

### 3. Configure GitHub Secrets

Add these secrets in GitHub repository settings (Settings → Secrets and variables → Actions):

| Secret | Value |
|--------|-------|
| `AWS_ROLE_ARN` | Copy from step 2 output: `github_actions_role_arn` |
| `AWS_REGION` | Your AWS region (e.g., `us-east-2`) |

### 4. Create and Sync tfvars

```bash
cp terraform/environments/prod/portal/terraform.tfvars.example \
   terraform/environments/prod/portal/terraform.tfvars
```

Fill in values, then sync to GitHub secrets:

```bash
./scripts/sync-tfvars.sh
```

This creates `TF_VARS_PROD_PORTAL` and `TF_VARS_PROD_FOUNDATION` secrets automatically.

### 5. Deploy Infrastructure

Push branch and create PR. GitHub Actions runs `terraform plan`. Merge to main for `terraform apply`.

## Manual Deployment

Via workflow dispatch in GitHub Actions, or locally:

```bash
cd terraform/environments/prod/portal
terraform init
terraform plan
terraform apply
```

## MCP Development

### aptl-mcp-common

```bash
cd mcp/aptl-mcp-common
npm install
npm run build
npm test -- --coverage
```

### mcp-red

```bash
cd mcp/mcp-red
npm install
npm run build
npx @modelcontextprotocol/inspector build/index.js
```

## Documentation

### Local Preview

```bash
pip install -r requirements-docs.txt
mkdocs serve
```

Browse to `http://127.0.0.1:8000`

### Deploy to GitHub Pages

Automatic via GitHub Actions on push to `main`.

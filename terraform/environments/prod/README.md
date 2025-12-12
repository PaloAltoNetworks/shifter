# Foundation Infrastructure

## Purpose

Foundation infrastructure provides shared resources required by all Shifter components:

- Container registry (ECR) for application images
- Terraform state backend (S3 + DynamoDB)

## Architecture

### Container Registry

ECR repository stores Docker images for the portal application. Images are scanned on push and lifecycle policies retain the last 30 images.

### State Management

Terraform state is stored in S3 with DynamoDB for locking. This enables:
- Concurrent apply prevention
- State versioning and backup
- Multi-component coordination

State bucket and lock table use UUIDs to avoid naming conflicts across AWS accounts.

## Components

| Resource | Purpose | Notes |
|----------|---------|-------|
| ECR Repository | Portal container images | Auto-scan enabled, 30 image retention |
| S3 Backend | Terraform state storage | Encryption at rest, versioning enabled |
| DynamoDB Table | State locking | Prevents concurrent modifications |

## Usage

### Prerequisites

- AWS credentials configured via GitHub OIDC (see terraform/global/iam/)
- Terraform >= 1.0
- S3 bucket and DynamoDB table already provisioned (one-time manual setup)

### Deploy

Foundation infrastructure deploys automatically on merge to main via GitHub Actions workflow `infra-foundation.yml`.

Manual deployment:

```bash
cd terraform/environments/prod
terraform init
terraform apply
```

### Configuration

Variables are managed via `terraform.tfvars` (gitignored) and synced to GitHub secrets using `scripts/sync-tfvars.sh`.

Required variables:
- `aws_region`: AWS region (default: us-east-2)
- `portal_repository_name`: ECR repository name (default: shifter-portal)

### Outputs

- `portal_ecr_url`: ECR repository URL for pushing images
- `portal_ecr_arn`: ECR repository ARN for IAM policies

## Workflow Integration

The `infra-foundation.yml` workflow:
- Runs on changes to foundation terraform files
- Plans on PR, applies on merge to main
- Uses OIDC authentication (no static credentials)
- Comments plan output on PRs

## Dependencies

Foundation infrastructure must be deployed before:
- Portal infrastructure (requires ECR repository)
- Application deployments (requires ECR for image storage)

No dependencies on other Shifter components.

## State Backend Setup

**One-time manual setup required:**

1. Create S3 bucket for state storage (encryption enabled, versioning enabled)
2. Create DynamoDB table for locking (partition key: LockID)
3. Update backend configuration in `backend.tf` with actual resource names

All subsequent terraform components reference the same backend.

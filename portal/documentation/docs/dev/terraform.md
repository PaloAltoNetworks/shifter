# Terraform Patterns

How we manage infrastructure.

## Directory Structure

```
terraform/
├── environments/
│   ├── dev/
│   │   ├── main.tf           # ECR repositories
│   │   ├── backend.tf        # S3 state config
│   │   ├── variables.tf
│   │   ├── terraform.tfvars  # Environment config (committed)
│   │   ├── portal/           # Portal infrastructure
│   │   │   ├── main.tf
│   │   │   ├── backend.tf
│   │   │   └── terraform.tfvars
│   │   └── range/            # Range VPC infrastructure
│   │       ├── main.tf
│   │       ├── backend.tf
│   │       └── terraform.tfvars
│   └── prod/                 # Same structure as dev
├── modules/                  # Reusable modules
│   ├── portal/
│   │   ├── vpc/
│   │   ├── rds/
│   │   ├── ec2/
│   │   ├── alb/
│   │   └── cognito/
│   ├── range/
│   │   └── vpc/
│   └── ecr/
└── global/                   # Cross-environment resources
    ├── iam/                  # GitHub OIDC, roles
    ├── github-runner/        # Self-hosted runner
    └── dev-box/              # Windows dev instance
```

## State Management

Each component has its own state file:

| Component | State Key |
|-----------|-----------|
| Core (ECR) | `shifter/{env}/terraform.tfstate` |
| Portal | `shifter/{env}/portal/terraform.tfstate` |
| Range | `shifter/{env}/range/terraform.tfstate` |
| Global | `global/{component}/terraform.tfstate` |

State is stored in S3 with DynamoDB locking:
- **Dev**: `shifter-dev-infra-*` bucket
- **Prod**: `shifter-infra-*` bucket

## Working Locally

### Initialize

```bash
cd terraform/environments/dev/portal
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform init
```

### Plan

```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform plan
```

### Apply (Dev Only)

```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform apply
```

**Never apply to prod locally** - use the CI/CD pipeline.

## Configuration vs Secrets

### In terraform.tfvars (Committed)

```hcl
# Environment config - not secrets
aws_region         = "us-east-2"
environment        = "dev"
instance_type      = "t3.large"
domain_name        = "dev.shifter.example.com"
enable_autoscaling = false
```

### In GitHub Secrets (Not Committed)

The same tfvars content is stored in GitHub Secrets for CI/CD, where workflows write it to disk before running Terraform.

### In AWS Secrets Manager (Runtime)

Database passwords, API keys, etc. are stored in Secrets Manager and accessed at runtime, not during Terraform apply.

## Module Patterns

### Input Validation

```hcl
variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "Environment must be dev or prod."
  }
}
```

### Consistent Tagging

```hcl
locals {
  common_tags = {
    Project     = "shifter"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_instance" "example" {
  # ...
  tags = merge(local.common_tags, {
    Name = "${var.environment}-example"
  })
}
```

### Resource Naming

Pattern: `shifter-{environment}-{component}`

Examples:
- `shifter-dev-portal-ec2`
- `shifter-prod-range-vpc`
- `shifter-dev-user-storage`

## Provider Configuration

```hcl
terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "shifter"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
```

## Common Operations

### Import Existing Resource

```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform import \
  aws_instance.example i-1234567890abcdef0
```

### Remove Resource from State

```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform state rm \
  aws_instance.example
```

### View Current State

```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform state list
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform state show aws_instance.example
```

### Format All Files

```bash
terraform fmt -recursive
```

## Adding New Infrastructure

1. Create module in `terraform/modules/` if reusable
2. Add to environment in `terraform/environments/{env}/`
3. Update tfvars with required variables
4. Update GitHub secret with same tfvars
5. Test in dev before prod

## Debugging

### Enable Logging

```bash
export TF_LOG=DEBUG
terraform plan
```

### Common Issues

**State Lock Error**
```bash
# Force unlock (use carefully)
terraform force-unlock LOCK_ID
```

**Provider Cache Issues**
```bash
rm -rf .terraform
terraform init
```

**Plan Drift**
- Someone made manual changes in console
- Run `terraform plan` to see differences
- Either import or recreate the resource

## Don'ts

- Don't use `terraform apply -auto-approve` locally
- Don't hardcode values that vary by environment
- Don't store state locally (always use S3 backend)
- Don't skip `terraform plan` review
- Don't apply prod changes without PR review

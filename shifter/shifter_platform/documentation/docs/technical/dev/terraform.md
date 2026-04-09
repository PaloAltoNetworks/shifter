# Terraform Patterns

How we manage infrastructure.

## Directory Structure

```
platform/terraform/
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
│   │   ├── alb/              # Application Load Balancer, WAF
│   │   ├── cognito/          # User pool, OIDC
│   │   ├── ec2/              # Portal instances
│   │   ├── messaging/        # SNS/SQS for events
│   │   ├── rds/              # PostgreSQL database
│   │   ├── redis/            # ElastiCache Redis
│   │   ├── s3/               # User storage bucket
│   │   ├── ssm/              # SSM parameters
│   │   └── vpc/              # Portal VPC, subnets
│   ├── range/
│   │   └── vpc/              # Range VPC, Network Firewall
│   ├── pulumi-provisioner/   # ECS task for Shifter Engine
│   ├── pulumi-state/         # S3 + DynamoDB for Pulumi
│   ├── guacamole/            # Browser-based RDP
│   ├── log-aggregation/      # Centralized logging
│   └── ecr/                  # Container registries
└── global/                   # Cross-environment resources
    ├── iam/                  # GitHub OIDC, roles
    ├── github-runner/        # Self-hosted runner
    └── dev-box/              # Windows dev instance
```

GCP work is staged in a parallel tree so it cannot collide with the current
AWS deploy path:

```
platform/terraform/gcp/
├── environments/
│   └── gcp-dev/             # GCP control-plane foundation for gcp-dev, including optional hostname and DNS settings
└── modules/
    └── platform-core/       # VPC, GKE, Cloud SQL, Memorystore, Artifact Registry, Pub/Sub, GCS, ingress IP, optional DNS, secrets
```

The staged GKE runtime manifests live alongside that Terraform tree:

```
platform/k8s/gcp/
├── base/                   # Shared GKE deployments, services, RBAC
└── overlays/
    └── gcp-dev/            # gcp-dev-specific config, images, generated runtime/edge artifacts, Workload Identity
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
cd platform/terraform/environments/dev/portal
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform init
```

For the staged GCP tree, local validation still runs without a remote backend:

```bash
cd platform/terraform/gcp/environments/gcp-dev
terraform init -backend=false
terraform validate
```

CI bootstraps a GCS backend bucket named `${project_id}-terraform-state` for
`gcp-dev` pushes before running `terraform init`.

The `gcp-dev` tfvars file also exposes the first hostname/DNS controls for the
GKE edge path:

```hcl
public_hostname         = ""
enable_managed_tls      = false
create_dns_managed_zone = false
dns_managed_zone_name   = ""
dns_zone_dns_name       = ""
dns_record_ttl          = 300
```

With the defaults, `gcp-dev` stays on the reserved ingress IP and the portal
remains in debug-auth mode. When a hostname is configured and managed TLS is
enabled, the deploy workflow can switch the portal runtime to the non-debug
OIDC path once the OIDC secret is populated and the GKE managed certificate is
active. The generated edge manifest now includes a GKE `FrontendConfig` that
redirects browser traffic to HTTPS during that secure mode.

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

Terraform variables are committed to the repo. CI/CD reads them directly after checkout.

### In Cloud Secret Managers (Runtime)

Database passwords, API keys, and runtime signing keys are stored in the cloud
secret manager and accessed at runtime. For the current `gcp-dev` slice,
Terraform seeds the app, DB, and Guacamole runtime bundles needed for first
boot. The OIDC secret remains separately managed so the deploy workflow can
gate the non-debug portal path on actual identity-provider readiness.

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

1. Create module in `platform/terraform/modules/` if reusable
2. Add to environment in `platform/terraform/environments/{env}/`
3. Update tfvars with required variables
4. Test in dev before prod

For GCP work:

1. Add reusable modules under `platform/terraform/gcp/modules/`
2. Wire them into `platform/terraform/gcp/environments/gcp-dev/`
3. Provision provider-native shared services there first: Pub/Sub, GCS, Secret Manager, Cloud SQL, Memorystore, ingress IPs
4. Stage matching runtime manifests under `platform/k8s/gcp/`, including separate edge resources when path routing depends on healthy workloads
5. Keep the remote backend, deploy credentials, and rendered runtime config aligned with the Terraform outputs
6. Do not weaken or replace the existing AWS environment trees while expanding GCP

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
- Don't store state locally (use the existing remote backend for the target environment)
- Don't skip `terraform plan` review
- Don't apply prod changes without PR review

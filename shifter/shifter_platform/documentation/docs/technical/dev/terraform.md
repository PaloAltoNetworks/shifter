# Terraform

Infrastructure layout and local Terraform commands.

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
│   ├── engine-provisioner/   # ECS task for Shifter Engine
│   ├── engine-state/         # Engine state bucket and DynamoDB runtime locks
│   ├── guacamole/            # Browser-based RDP
│   ├── log-aggregation/      # Centralized logging
│   └── ecr/                  # Container registries
└── global/                   # Cross-environment resources
    ├── iam/                  # GitHub OIDC, roles
    ├── github-runner/        # Self-hosted runner
    └── dev-box/              # Windows dev instance
```

GCP work lives in a parallel tree so it cannot collide with the AWS deploy path:

```
platform/terraform/gcp/
├── environments/
│   └── gcp-dev/             # GCP control-plane foundation for gcp-dev
└── modules/
    └── platform-core/       # VPC, GKE, Cloud SQL, Memorystore, Artifact Registry, Pub/Sub, GCS, ingress IP, Cloud Armor, optional DNS, secrets
```

The GCP control plane is packaged separately as a Helm chart:

```
platform/charts/shifter/
├── templates/              # Deployments, services, ingress, BackendConfig, RBAC
├── values.yaml             # Chart defaults
├── values-gcp-dev.yaml     # gcp-dev environment overrides
└── values-gcp-prod.yaml    # gcp-prod environment overrides
```

## State Management

Each component has its own state file:

| Component | State Key |
|-----------|-----------|
| Core (ECR) | `shifter/{env}/terraform.tfstate` |
| Portal | `shifter/{env}/portal/terraform.tfstate` |
| Range | `shifter/{env}/range/terraform.tfstate` |
| Global | `global/{component}/terraform.tfstate` |

AWS Terraform state is stored in S3 with S3 native locking
(`use_lockfile = true`):
- **Dev**: `shifter-dev-infra-*` bucket
- **Prod**: `shifter-infra-*` bucket

The `engine-state` module creates a DynamoDB table for provisioner runtime
locks. It is not the Terraform backend lock.

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

The `gcp-dev` tfvars file carries the public edge and operator-access settings:

```hcl
public_hostname             = "shifter.example.com"
enable_managed_tls          = true
gke_master_authorized_cidrs = ["173.181.31.170/32"]
create_dns_managed_zone = false
dns_managed_zone_name   = ""
dns_zone_dns_name       = ""
dns_record_ttl          = 300
```

`gdc-bootstrap` fails before Terraform apply if these inputs are missing.
Routine GCP applies happen through CI/CD on `gcp-dev`.

### Plan

```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform plan
```

### Apply (Dev Only)

```bash
AWS_PROFILE=$PANW_SHIFTER_DEV_PROFILE terraform apply
```

**Never apply to prod locally** - use the CI/CD pipeline.

### RDS Change Application

RDS changes that AWS can apply during a deploy — instance class, storage
size, engine version, and dynamic parameter-group fields — must not be
treated as complete until AWS reports no pending modifications for the
affected instance. For dev-only RDS resources, prefer explicit
`apply_immediately` module inputs that default to applying intended changes
during the current deploy. Production must keep change timing deliberate:
either pass an explicit maintenance-window choice through the same module
surface or use a separate reviewed change flow.

`apply_immediately` does NOT remediate every RDS change. Static
parameter-group fields and major version upgrades still require an instance
reboot to take effect, and modify-class operations can still leave
`PendingModifiedValues` populated until the underlying maintenance action
completes. The post-apply check will surface that residual state, but it does
not by itself drive a reboot. When you change one of those fields, plan a
follow-up reboot (or a maintenance-window-gated path) explicitly.

Post-apply checks belong at the Terraform workflow boundary, after
`terraform apply`, where the existing AWS credentials and environment context
are already present. Reuse Terraform outputs or module outputs to identify
the managed DB instances; do not hardcode names such as `dev-portal-db`
inside a generic checker. For dev portal deploys, a successful apply that
leaves non-empty `PendingModifiedValues` is treated as an incomplete deploy
and fails the job loudly. Prod intentionally skips the check because prod
relies on the maintenance-window path.

## Configuration vs Secrets

### In terraform.tfvars (committed baseline)

```hcl
# Non-deployment-specific environment config — committed.
aws_region         = "us-east-2"
environment        = "dev"
instance_type      = "t3.large"
domain_name        = "dev.shifter.example.com"  # example.com baseline
enable_autoscaling = false
```

### In local.auto.tfvars (gitignored, per-deployment override)

```hcl
# Deployment-specific identifiers — never committed.
domain_name           = "dev.shifter.your-domain.example"
ses_domain            = "your-domain.example"
alarm_email           = "your-team@your-domain.example"
allowed_email_domains = ["your-domain.example"]
user_storage_bucket   = "shifter-dev-user-storage-<account-id>"
```

Terraform auto-loads `*.auto.tfvars` files alongside `terraform.tfvars`
and the `.local`/`.auto.tfvars` values win. CI deploy workflows render
`local.auto.tfvars` from GitHub secrets and repository variables; see
[`docs/dev/deploy-secrets.md`](../../../../../../docs/dev/deploy-secrets.md).

### In Cloud Secret Managers (Runtime)

Database passwords, API keys, and runtime signing keys are stored in the cloud
secret manager and accessed at runtime. For the current `gcp-dev` slice,
Terraform seeds the app, DB, and Guacamole runtime bundles needed for first
boot. GCP no longer relies on a separately managed OIDC runtime secret; it
provisions Identity Platform directly and bootstrap seeds the first operator
account for the secure portal path. The secure portal flow uses browser-side
Google auth and app-side verified-token exchange rather than server-side
password handling in Django.

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
4. Stage matching chart or generated deployment assets under `platform/charts/shifter/` and `platform/k8s/gcp/` as appropriate
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

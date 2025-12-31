# Platform Infrastructure

AWS infrastructure and CI/CD for Shifter.

## Directory Structure

```
platform/
├── terraform/
│   ├── global/
│   │   ├── iam/              # GitHub OIDC, CI/CD IAM roles
│   │   ├── github-runner/    # Self-hosted runner infrastructure
│   │   └── dev-box/          # Developer workstation
│   ├── modules/
│   │   ├── ecr/              # Container registries
│   │   ├── portal/           # Shifter app infrastructure
│   │   ├── range/            # Range VPC and networking
│   │   ├── pulumi-provisioner/   # ECS Fargate for Engine
│   │   ├── pulumi-state/         # Pulumi backend (S3 + DynamoDB)
│   │   └── log-aggregation/      # Centralized logging
│   └── environments/
│       ├── dev/              # Dev environment configs
│       └── prod/             # Prod environment configs
└── cloudformation/
    ├── dev/                  # Cortex XDR connector templates (dev)
    └── prod/                 # Cortex XDR connector templates (prod)
```

## Components

| Component | Module | Purpose |
|-----------|--------|---------|
| **Global** | `platform/terraform/global/iam/` | GitHub OIDC provider, CI/CD IAM roles |
| **Core** | `platform/terraform/environments/{env}/` | ECR repositories, budget alerts |
| **Range** | `platform/terraform/modules/range/` | Range VPC, security groups, Network Firewall |
| **Portal*** | `platform/terraform/modules/portal/` | ALB, EC2/ASG, RDS, Redis, Cognito, S3 |
| **Pulumi Provisioner** | `platform/terraform/modules/pulumi-provisioner/` | ECS Fargate task for range provisioning |
| **CloudFormation** | `platform/cloudformation/{env}/` | Cortex XDR connector IAM roles (manually deployed) |

*Portal is a legacy name. Deploys Shifter Django infrastructure.

## State Management

Terraform state stored in S3 with DynamoDB locking:

| Environment | Bucket | Lock Table |
|-------------|--------|------------|
| dev | `shifter-dev-infra-*` | `shifter-dev-terraform-*` |
| prod | `shifter-prod-infra-*` | `shifter-prod-terraform-*` |

## Related Docs

- [CI/CD](cicd.md) - Deployment pipelines
- [Networking](networking.md) - VPC architecture and peering

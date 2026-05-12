# Platform Infrastructure

Cloud infrastructure and CI/CD for Shifter.

## AWS

### Directory Structure

```
platform/terraform/
├── global/
│   ├── iam/              # GitHub OIDC, CI/CD IAM roles
│   ├── github-runner/    # Self-hosted runner infrastructure
│   └── dev-box/          # Developer workstation
├── modules/
│   ├── ecr/              # Container registries
│   ├── portal/           # Shifter app infrastructure
│   ├── range/            # Range VPC and networking
│   ├── engine-provisioner/   # ECS Fargate for Engine
│   ├── engine-state/         # Engine state bucket and DynamoDB locks
│   ├── guacamole/            # Browser-based RDP (Guacamole)
│   └── log-aggregation/      # Centralized logging
├── environments/
│   ├── dev/              # Dev environment configs
│   └── prod/             # Prod environment configs
└── cloudformation/           # Cortex XDR connector templates
```

### Components

| Component | Module | Purpose |
|-----------|--------|---------|
| **Global** | `global/iam/` | GitHub OIDC provider, CI/CD IAM roles, github-runner, dev-box |
| **Core** | `environments/{env}/` | ECR repositories, budget alerts |
| **Range** | `modules/range/` | Range VPC, security groups, Network Firewall |
| **Portal*** | `modules/portal/` | ALB, EC2 (configurable ASG), RDS, Redis, Cognito, S3 |
| **Provisioner** | `modules/engine-provisioner/` | ECS Fargate task for range provisioning |
| **Guacamole** | `modules/guacamole/` | Browser-based RDP access to range instances |
| **CloudFormation** | `cloudformation/{env}/` | Cortex XDR connector IAM roles (manually deployed) |

*Portal is a legacy name. Deploys Shifter Django infrastructure.

### State Management

Terraform state is stored in S3 with S3 native locking (`use_lockfile = true`).
The engine state module also creates a DynamoDB table for provisioner runtime
locks; that table is not the Terraform backend lock.

## GCP

See [GCP Infrastructure](gcp-infrastructure) for full details.

### Directory Structure

```
platform/
├── terraform/gcp/
│   ├── modules/platform-core/    # All GCP infrastructure
│   └── environments/gcp-dev/     # Environment config
├── charts/shifter/               # Helm chart for the GCP control plane
└── k8s/gcp/                      # GCP base manifests and generated deployment assets
```

### Components

| Component | Service | Purpose |
|-----------|---------|---------|
| **GKE Cluster** | GKE | Private nodes with node pools (web, workers, provisioner) and public control-plane endpoint restricted by authorized CIDRs |
| **Cloud SQL** | Cloud SQL | PostgreSQL (platform + Guacamole databases) |
| **Memorystore** | Memorystore | Redis (channel layer, worker coordination) |
| **Pub/Sub** | Pub/Sub | Event topic with per-domain subscriptions |
| **Artifact Registry** | Artifact Registry | Container image repositories |
| **Secret Manager** | Secret Manager | Runtime secret bundles |
| **Cloud DNS** | Cloud DNS | Optional public hostname with managed TLS |
| **Cloud Armor** | Cloud Armor | Baseline WAF policy on the public portal and Guacamole backends |

### State Management

Terraform state is stored in a GCS bucket per environment.

## Related Docs

- [GCP Infrastructure](gcp-infrastructure) - GKE, Helm, Cloud Armor, and GCP services
- [GDC Provisioning](gdc-provisioning) - Range guest provisioning on GDC
- [AMI Management](ami-management) - Packer builds and SSM parameter management (AWS)
- [Manual Deployment](manual-deployment) - Infrastructure elements deployed without CI/CD
- [CI/CD](cicd) - Deployment pipelines
- [GitHub Runners](github-runners) - Self-hosted runner setup and maintenance
- [Networking](networking) - VPC architecture and peering
- [Guacamole](guacamole) - Browser-based RDP integration

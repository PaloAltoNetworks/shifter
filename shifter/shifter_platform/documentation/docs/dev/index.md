# Developer Guide

Getting started as a Shifter developer.

## Quick Start

1. [Local Setup](local-setup.md) - Clone, dependencies, run locally
2. [Setup](setup.md) - Deploy to AWS from scratch
3. [CI/CD](ci-cd.md) - How deployments work
4. [Secrets](secrets.md) - What secrets exist, where they live
5. [Terraform](terraform.md) - Infrastructure patterns
6. [Principles](principles.md) - Engineering philosophy

## Prerequisites

- Python 3.12
- Node.js LTS
- Terraform 1.7+
- AWS CLI v2
- Docker
- Git

## AWS Access

You need AWS credentials for both environments:

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc)
export PANW_SHIFTER_DEV_PROFILE="your-dev-profile-name"
export PANW_SHIFTER_PROD_PROFILE="your-prod-profile-name"
```

Configure these profiles in `~/.aws/credentials` with your SSO or IAM credentials.

## Repository Structure

```
shifter/
├── shifter/
│   ├── shifter_platform/       # Django web application
│   │   ├── mission_control/    # Main app (ranges, agents, terminal)
│   │   ├── cms/                # Content management (agents, scenarios)
│   │   ├── engine/             # Orchestration services
│   │   ├── documentation/      # In-app docs (you're reading this)
│   │   └── config/             # Django settings
│   └── engine/                 # Range provisioner (Pulumi + ECS)
│       └── provisioner/        # Pulumi components and plans
├── platform/
│   └── terraform/
│       ├── environments/       # dev/ and prod/ configs
│       │   ├── dev/
│       │   │   ├── portal/     # Portal infra (VPC, RDS, EC2, ALB)
│       │   │   └── range/      # Range VPC infra
│       │   └── prod/
│       ├── modules/            # Reusable Terraform modules
│       └── global/             # Cross-environment resources (IAM, OIDC)
├── scripts/                    # Bootstrap and utility scripts
└── .github/workflows/          # CI/CD pipelines
```

## Git Workflow

```
feature/* ──► dev ──► main
              │        │
              ▼        ▼
           dev env   prod env
```

- **feature/*** - Development work
- **dev** - Integration, deploys to dev environment
- **main** - Production, deploys to prod environment

All changes go through pull requests. Never commit directly to dev or main.

## Next Steps

Start with [Local Setup](local-setup.md) to get the portal running on your machine.

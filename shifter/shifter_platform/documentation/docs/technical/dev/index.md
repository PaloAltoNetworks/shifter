# Developer Guide

Getting started as a Shifter developer.

## Quick Start

1. [Local Setup](local-setup) - Clone, dependencies, run locally
2. [Setup](setup) - Deploy to AWS or GCP from scratch
3. [Installation Config](installation-config) - `shifter.yaml` schema and validation
4. [CI/CD](ci-cd) - How deployments work
5. [Secrets](secrets) - What secrets exist, where they live
6. [Terraform](terraform) - Infrastructure patterns
7. [Cloud Adapters](cloud-adapters) - Cloud abstraction layer
8. [Principles](principles) - Engineering philosophy
9. [ADR Enforcement](adr-enforcement) - Architecture guardrails and policy checks

## Prerequisites

- Python 3.12
- Node.js LTS
- Terraform 1.7+
- Docker
- Git
- **AWS**: AWS CLI v2 with SSO or IAM credentials
- **GCP**: `gcloud` CLI authenticated with target project

## Cloud Access

**AWS** - Configure named profiles for each environment:

```bash
export PANW_SHIFTER_DEV_PROFILE="your-dev-profile-name"
export PANW_SHIFTER_PROD_PROFILE="your-prod-profile-name"
```

**GCP** - Authenticate with `gcloud auth login` and set the target project.

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
│   └── engine/                 # Range provisioner
│       └── provisioner/        # Cloud-specific provisioning (AWS EC2, GDC VMs/pods)
├── platform/
│   ├── terraform/
│   │   ├── environments/       # AWS env configs (dev/, prod/)
│   │   ├── modules/            # AWS Terraform modules
│   │   ├── global/             # Cross-environment resources (IAM, OIDC, runners)
│   │   └── gcp/               # GCP Terraform (modules/, environments/)
│   ├── charts/shifter/        # Helm chart for the GCP control plane
│   └── k8s/gcp/               # GCP deployment assets and base manifests
├── scripts/                    # Bootstrap and utility scripts
├── shifter/installation/        # shifter.yaml parser, validator, backend registry
└── .github/workflows/          # CI/CD pipelines (AWS + GCP)
```

## Git Workflow

```
feature/* ──► dev ──► aws-dev ──► main
              │        │          │
              │        ▼          ▼
              └──────► gcp-dev   prod env
                       │
                       ▼
                    gcp dev env
```

- **feature/*** - Development work
- **dev** - Integration, validation only
- **aws-dev** - AWS dev deployment branch
- **gcp-dev** - GCP dev deployment branch
- **main** - Production, deploys to prod environment

All changes go through pull requests. Never commit directly to deploy branches.

## Next Steps

Start with [Local Setup](local-setup) to get the portal running on your machine.

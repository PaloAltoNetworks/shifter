# CI/CD Pipeline

How code gets from your branch to production.

## Overview

All CI/CD runs through GitHub Actions. The main orchestrator is `deploy.yml`, which coordinates:

1. **Quality** - Linting, tests, security scanning
2. **Core** - ECR repositories (foundation)
3. **Range** - Range VPC infrastructure
4. **Pulumi Provisioner** - Container build
5. **Portal** - Infrastructure, container, deployment

## Trigger Rules

| Event | What Runs |
|-------|-----------|
| PR to any branch | Quality + Plan (no apply) |
| Push to `dev` | Quality + Plan + Apply to dev |
| Push to `main` | Quality + Plan + Apply to prod |

PRs get Terraform plan comments. Merges trigger actual deployments.

## Workflow Files

```
.github/workflows/
├── deploy.yml              # Main orchestrator
├── _quality.yml            # Linting, tests, Checkov
├── _core.yml               # ECR repositories
├── _range.yml              # Range VPC
├── _pulumi-provisioner.yml # Provisioner container
└── _portal.yml             # Portal infra + deploy
```

Underscore prefix (`_*.yml`) indicates reusable workflows called by `deploy.yml`.

## Dependency Chain

```
Quality (must pass first)
    │
    ▼
  Core (ECR)
    │
    ├──────────────┬─────────────────┐
    ▼              ▼                 ▼
  Range    Pulumi Provisioner    Portal Plan
                   │                 │
                   └────────┬────────┘
                            ▼
                      Portal Deploy
```

## Change Detection

The orchestrator uses path filters to run only relevant jobs:

| Filter | Triggers When |
|--------|--------------|
| `core` | ECR module, environment root, deploy workflow |
| `range` | Range Terraform, pulumi-state module |
| `pulumi_provisioner` | Pulumi code, ECR module |
| `portal` | Portal Django code, portal Terraform |

## Quality Gate

Runs on every PR and push:

- **Python linting**: `ruff check`, `ruff format --check`
- **Tests**: `pytest` with PostgreSQL service container
- **IaC scanning**: Checkov (soft fail - warnings only)
- **Coverage**: Pulumi provisioner requires 80% minimum

## Terraform Flow

Each component follows the same pattern:

1. **Plan job**:
   - Write tfvars from GitHub secret
   - `terraform init`
   - `terraform validate`
   - `terraform plan -out=tfplan`
   - Comment plan on PR (if PR)

2. **Apply job** (if plan succeeds):
   - Skip on PRs to prod
   - `terraform apply -auto-approve`

## Portal Deployment

After Terraform apply, portal deployment:

1. Build Docker image
2. Push to ECR with tags: `latest`, `{git-sha}`
3. Find target EC2 instance(s) via tags
4. SSM send-command to pull and run new container

**Single Instance Mode**: Deploys to `{env}-portal-ec2` tagged instance.

**Auto Scaling Mode**: Deploys to all instances in `{env}-portal-asg`.

## Environment Detection

```
Branch/Target     → Environment
PR to dev         → dev
PR to main        → prod (plan only)
Push to dev       → dev (full deploy)
Push to main      → prod (full deploy)
```

## Self-Hosted Runner

All workflows run on `self-hosted` runners (not GitHub-hosted). The runner has:

- AWS CLI configured
- Docker + BuildX
- Terraform 1.7.1
- Python 3.12
- Network access to AWS APIs

## Viewing Logs

1. Go to Actions tab in GitHub
2. Select the workflow run
3. Expand the job you want to inspect
4. Each step shows its logs

Terraform plans are also posted as PR comments for easy review.

## Common Issues

### Workflow Doesn't Trigger
- Check branch protection rules
- Verify path filters match your changes
- Look for `paths-filter` in deploy.yml

### Terraform Plan Fails
- Check for formatting issues: `terraform fmt -recursive`
- Validate locally first: `terraform validate`
- Review the error in the Actions log

### Docker Build Fails
- Check Dockerfile syntax
- Verify base image availability
- Review build logs for dependency issues

### Deploy Fails
- Check EC2 instance is running
- Verify SSM agent is healthy
- Review SSM command output in AWS console

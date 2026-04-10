# CI/CD Pipeline

How code gets from your branch to production.

## Overview

All CI/CD runs through GitHub Actions. The main orchestrator is `deploy.yml`, which coordinates:

1. **Quality** - Linting, tests, security scanning
2. **Core** - ECR repositories (foundation)
3. **Range** - Range VPC infrastructure
4. **Shifter Engine** - Container build
5. **Portal** - Infrastructure, container, deployment

## Trigger Rules

| Event | What Runs |
|-------|-----------|
| PR to any branch | Quality + Plan (no apply) |
| Push to `dev` | Quality + Plan + Apply to dev |
| Push to `gcp-dev` | Quality + GCP Terraform apply + image push + GKE deploy |
| Push to `main` | Quality + Plan + Apply to prod |

PRs get Terraform plan comments. Merges trigger actual deployments.

## Workflow Files

```
.github/workflows/
├── deploy.yml              # Main orchestrator
├── _quality.yml            # Linting, tests, Checkov
├── _core.yml               # ECR repositories
├── _range.yml              # Range VPC
├── _gcp-dev.yml            # GCP control-plane validate/apply/build/deploy
├── _shifter-engine.yml     # Shifter Engine container
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
  Range    Shifter Engine    Portal Plan
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
| `shifter_engine` | Shifter Engine code, ECR module |
| `portal` | Portal Django code, portal Terraform |

## Quality Gate

Runs on every PR and push:

- **ADR conformance**: `python3 scripts/adr_guard/adr_guard.py --all --level ci`
  Includes `adr-registry`, `layer-imports`, `cross-layer-model-imports`, and
  `cloud-factory-seam` (ADR-005-R1 cloud adapter parity).
- **Workflow linting**: `actionlint`
- **Terraform linting**: `tflint` with `tflint-ruleset-google` plugin
  The repo currently runs a narrow TFLint profile that excludes existing
  version/provider and unused-declaration debt until that backlog is burned down.
  The Google plugin adds GCP-specific rules (invalid machine types, deprecated
  attributes, etc.).
- **Python import contracts**: `lint-imports --config ../../.importlinter`
- **Python linting**: `ruff check`, `ruff format --check`
- **K8s schema validation**: `kubeconform` validates Kubernetes manifests against
  official schemas, pinned to the target GKE version.
- **K8s security and best practices**: `kube-linter` enforces security contexts,
  resource limits, privilege escalation prevention, and other best practices
  via `.kube-linter.yaml`.
- **K8s security scanning**: Checkov with the `kubernetes` framework (soft fail
  while manifests are being hardened).
- **Tests**: `pytest` with PostgreSQL service container
- **IaC scanning**: Checkov for Terraform (soft fail - warnings only)
- **Secret scanning**: gitleaks on newly introduced commits
- **Coverage**: Shifter Engine requires 80% minimum

Architecture checks are not skipped by the normal test-skip path. `[skip tests]` may skip slow test jobs on `dev`, but it does not bypass ADR or architecture enforcement.

## Terraform Flow

Each component follows the same pattern:

1. **Plan job**:
   - Checkout repo (tfvars are committed)
   - `terraform init`
   - `terraform validate`
   - `terraform plan -out=tfplan`
   - Comment plan on PR (if PR)

2. **Apply job** (if plan succeeds):
   - Skip on PRs to prod
   - `terraform apply -auto-approve`

**Note**: Terraform variables are committed to the repo in `terraform.tfvars` files. CI/CD reads them directly after checkout - no secrets or environment variables needed for tfvars.

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
PR to gcp-dev     → gcp-dev
PR to main        → prod (plan only)
Push to dev       → dev (full deploy)
Push to gcp-dev   → gcp-dev (provider routed away from AWS jobs)
Push to main      → prod (full deploy)
```

## Provider Routing

`deploy.yml` now resolves both an environment and a cloud provider:

- `dev` and `main` remain on the AWS deployment chain
- `gcp-dev` is isolated so it cannot accidentally trigger the AWS `prod` path
- Pull requests to `gcp-dev` run the dedicated GCP validation workflow for the staged GKE, Pub/Sub, GCS, Secret Manager, Cloud SQL, Memorystore, optional DNS, and control-plane manifests
- Pushes to `gcp-dev` authenticate to GCP, bootstrap the GCS Terraform backend, apply the environment, push the portal, provisioner, `guacd`, and `guacamole-client` images to Artifact Registry, render the runtime env file and edge manifest from Terraform outputs, sync the Guacamole namespace Secret, roll the GKE deployments, and then apply the edge resources
- The portal only flips into the non-debug OIDC path when the Terraform outputs declare a hostname with managed TLS, the `shifter-gcp-dev-oidc` secret has a readable version, and the GKE `ManagedCertificate` becomes `Active`; until then the workflow preserves the IP/debug fallback
- When the certificate is already active from a prior deploy, the workflow starts directly in secure mode; on first secure cutover it uses a two-phase deployment and promotes the runtime after certificate activation
- New multi-cloud work should enter through the shared cloud adapter layers rather than adding provider-specific calls directly in domain services

## Self-Hosted Runner

All workflows run on `self-hosted` runners (not GitHub-hosted). The runner has:

- AWS CLI configured
- gcloud SDK support for GCP workflows
- Docker + BuildX
- Terraform 1.7.1
- Python 3.12
- Network access to AWS and GCP APIs

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

### GCP Deploy Fails
- Verify `GCP_SERVICE_ACCOUNT` and `GCP_WORKLOAD_IDENTITY_PROVIDER` repository secrets are set
- Check the GCS backend bucket bootstrap step for IAM or bucket-name conflicts
- Review `terraform output -json` and the generated `platform-runtime.generated.env` values in the workflow logs
- Review the generated `platform-edge.generated.yaml` output if hostname, DNS, or certificate behavior is wrong
- Review the `guacamole-runtime` Secret sync step if the Guacamole client pods stay in `CreateContainerConfigError`
- If the portal remains in debug mode unexpectedly, verify the Terraform outputs expose `public_hostname`, `managed_tls_enabled=true`, that the OIDC Secret Manager secret has a readable latest version, and that the `platform-managed-cert` resource reaches `Status.CertificateStatus=Active`
- Check `kubectl rollout status` output for the specific control-plane deployment that stalled

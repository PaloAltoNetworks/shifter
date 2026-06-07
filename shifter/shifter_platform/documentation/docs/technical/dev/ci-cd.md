# CI/CD Pipeline

How GitHub Actions validates and deploys Shifter.

## Overview

All CI/CD runs through GitHub Actions. The main orchestrator is `deploy.yml`,
which coordinates:

1. **Quality** - Linting, tests, security scanning
2. **Core** - ECR repositories (foundation)
3. **Range** - Range VPC infrastructure
4. **Shifter Engine** - Container build
5. **Shifter Platform** - Application infrastructure, containers, deployment

## Trigger Rules

| Event | What Runs |
|-------|-----------|
| PR to `dev` / `main` | Quality only; no deploy or Terraform plan jobs |
| PR to `aws-dev` | Quality + AWS plan (no apply) |
| PR to `gcp-dev` | Quality + GCP validate (no apply) |
| Push to `dev` | Quality only; no deploy or Terraform plan jobs |
| Push to `aws-dev` | Quality + AWS deploy to dev |
| Push to `gcp-dev` | Fast GCP validation + GCP deploy |
| Push to `main` | Code branch update only; no deploy or Terraform plan jobs |
| Manual dispatch on `main` | AWS prod deploy |

Deployment-branch PRs get Terraform plan comments. `dev` is the integration
branch for Quality only. Dev deployments happen only from `aws-dev` and
`gcp-dev`.

`gcp-dev` pushes skip the global quality fan-out. The fast path still runs the
provider-local guardrails in `_gcp-dev.yml`: Terraform fmt/init/validate plus
rendered-manifest schema validation before deploy. Broad lint/test/security
coverage runs on PRs and `dev`; production deployment is a deliberate manual
dispatch from `main`.

## Workflow Files

```
.github/workflows/
├── deploy.yml              # Main orchestrator
├── _quality.yml            # Linting, tests, Checkov
├── _core.yml               # ECR repositories
├── _range.yml              # Range VPC
├── _gcp-dev.yml            # GCP validate/deploy workflow
├── _shifter-engine.yml     # Shifter Engine container
└── _shifter-platform.yml   # Shifter Platform infra + deploy
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
| `range` | Range Terraform, engine state module |
| `shifter_engine` | Shifter Engine code, ECR module |
| `shifter_platform` | Shifter Django code, portal/Guacamole Terraform |
| `gcp` | GCP Terraform, GCP Kubernetes assets, GCP scripts, GCP cloud adapters |

## Quality Gate

Runs on every PR and direct push to `dev`:

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
- **K8s security scanning**: Checkov with the `kubernetes` framework. Current
  soft-fail is scoped to Kubernetes manifest hardening and does not justify
  Terraform soft-fail.
- **Tests**: `pytest` with PostgreSQL service container for `shifter_platform`
- **IaC scanning**: Checkov for Terraform is a **blocking gate** under
  ADR-004-R11. Pre-commit and CI share the same config at
  `platform/terraform/.checkov.yaml`; `--soft-fail` is off. Accepted-risk
  waivers (Checkov `skip-check` entries or inline `# checkov:skip=…`
  comments) require a matching entry in `docs/adr/exceptions.yaml` with
  owner, reason, expiry, affected paths, and the Checkov policy ID.
- **Secret scanning**: gitleaks on newly introduced commits
- **Coverage**: `shifter_platform` emits terminal and XML coverage reports

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

**Note**: The committed `terraform.tfvars` files ship an `example.com`
baseline. Deployment-specific values (domains, alarm emails, allow-list
domains, account-suffixed bucket names, GCP project id, etc.) come from
GitHub repository variables and secrets at deploy time; CI/CD renders
them into a gitignored `local.auto.tfvars` before `terraform apply`.
See [`docs/dev/deploy-secrets.md`](../../../../../../docs/dev/deploy-secrets.md)
for the required surface.

## AWS Platform Deployment

After Terraform apply, AWS platform deployment:

1. Build Docker image
2. Push to ECR with tags: `latest`, `{git-sha}`
3. Find target EC2 instance(s) via tags
4. SSM send-command to pull and run new container

**Single Instance Mode**: Deploys to `{env}-portal-ec2` tagged instance.

**Auto Scaling Mode**: Deploys to all instances in `{env}-portal-asg`.

## Environment Detection

```
Branch/Target     → Behavior
PR to dev         → Quality only
PR to aws-dev     → AWS dev plan
PR to gcp-dev     → GCP validate
PR to main        → Quality only
Push to dev       → Quality only
Push to aws-dev   → AWS dev deploy
Push to gcp-dev   → Fast GCP validate + GCP deploy
Push to main      → no deploy
Dispatch on main  → AWS prod deploy
```

## Provider Routing

`deploy.yml` resolves branch intent explicitly:

- `dev` is the shared integration branch. It runs the quality gate for shared code changes, but it must not plan/apply infrastructure or deploy workloads.
- `aws-dev` is the only branch that deploys the AWS dev environment.
- `gcp-dev` is the only branch that deploys the GCP dev environment, and it uses the narrow GCP fast path on branch pushes.
- `main` is the production code branch; production deploys run only through deliberate `workflow_dispatch`.
- Shared Shifter application changes run Quality on `dev`; provider-specific deployment validation runs on the deployment branches before apply.
- The GCP control plane is deployed through the Helm chart in `platform/charts/shifter`, with generated values layered on top of environment defaults.
- The GCP portal auth contract is FirebaseUI/browser-side Identity Platform auth plus server-side verified-token exchange. Do not add Django credential handling to recreate Cognito semantics.
- Multi-cloud work enters through the shared cloud adapter layers rather than provider-specific calls in domain services.

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

Terraform plans are also posted as PR comments.

## Common Issues

### Workflow Doesn't Trigger
- Check branch protection rules
- Verify path filters match your changes
- Look for `paths-filter` in deploy.yml
- Confirm you are pushing to the right branch for the intended behavior: `dev` runs Quality only, `aws-dev` deploys AWS dev, `gcp-dev` deploys GCP dev, and prod deploys require manual dispatch on `main`

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
- Review the generated Helm values, ingress resources, and `BackendConfig` resources if hostname, DNS, certificate, or Cloud Armor behavior is wrong
- Review the `guacamole-runtime` Secret sync step if the Guacamole client pods stay in `CreateContainerConfigError`
- If the portal auth path is wrong, verify the Terraform outputs expose `public_hostname`, `managed_tls_enabled=true`, that Identity Platform was provisioned successfully, that the blocking function and MFA configuration are present, that the bootstrap operator credentials were supplied, and that the managed certificate reaches `Active`
- Check `kubectl rollout status` output for the specific control-plane deployment that stalled

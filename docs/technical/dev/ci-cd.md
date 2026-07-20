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

Environment deploys are **manual**: run the Deploy workflow and pick the
`environment` input. Push and pull_request run validation only; no branch name
triggers a deploy (#730).

| Event | What Runs |
|-------|-----------|
| Pull request | Quality only; no deploy |
| Push to `dev` / `main` | Quality only; no deploy |
| Manual dispatch, `environment: aws-dev` | Quality, then AWS dev deploy |
| Manual dispatch, `environment: aws-proof` | Quality, then AWS proof deploy |
| Manual dispatch, `environment: gcp-dev` | Quality, then GCP dev deploy |

Run a deploy from the Actions UI (**Deploy → Run workflow**, pick the branch to
deploy and the `environment`) or the CLI:

```
gh workflow run deploy.yml --ref <branch> -f environment=aws-dev
```

The branch you run it from is the code that deploys; the `environment` input
picks where it goes. `dev` is the integration branch (Quality only).

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
    ├──────────────┐
    ▼              ▼
  Range    Shifter Engine
    │              │
    └──────────────┘
            │
            ▼
  Shifter Platform Plan/Deploy
```

Downstream AWS jobs use explicit `needs.<job>.result` gates. A skipped upstream
is acceptable when its path filter did not select it, but a failed or cancelled
upstream must stop dependent infrastructure work. In particular, Shifter Platform
must not plan or apply on top of a failed Shifter Engine deploy.

## Change Detection

The orchestrator uses path filters to run only relevant jobs:

| Filter | Triggers When |
|--------|--------------|
| `core` | ECR module, environment root, deploy workflow |
| `range` | Range Terraform, engine state module |
| `shifter_engine` | Shifter Engine code, ECR module |
| `shifter_platform` | Portal/Guacamole Terraform and platform deploy workflow |
| `quality_relevant` | Any non-docs change, plus guardrail docs; controls whether Quality runs without launching deploy or Terraform plan jobs |
| `portal_image` | Portal image build inputs (`shifter/shifter_platform/**`, `cyberscript`, `installation`, `.dockerignore`); triggers the portal image build/deploy on a deploy dispatch without running Terraform |
| `gcp` | GCP Terraform, GCP Kubernetes assets, GCP scripts, GCP cloud adapters |
| `mcp` | MCP package changes, routed to Quality only |
| `quality_only` | Non-deploy test-support and guardrail surfaces (`scripts/polaris-aws-range/**`, `scenario-dev/polaris/tests/**`, `_quality.yml`, ADR/guardrail checker paths), routed to Quality only |

## Quality Gate

Runs on every PR, direct push to `dev`/`main`, and every manual deploy dispatch
(the safety gate before an apply) unless the diff is ordinary docs-only.
Guardrail docs such as `.github/pull_request_template.md`,
`.github/copilot-instructions.md`, `docs/adr/**`, and the ADR enforcement
guide are quality-relevant and still run Quality.

The deploy workflow exposes one `quality_relevant` output for this decision:
non-docs changes make it true, ordinary docs-only changes make it false, and
guardrail docs make it true even though they are documentation. PR Gate accepts
a skipped Quality job only when `quality_relevant` is false.

Inside `_quality.yml`, the always-run path-detection job runs
`scripts/quality_ownership/classify_paths.py`, which reads the versioned
quality-ownership contract at `.github/quality-path-filters.yaml` and rejects
any unclassified changed path before it selects jobs. That contract also maps
every production path to its blocking lint, security, and test jobs; the
`quality-path-ownership` ADR guard (ADR-004-R24) enforces that ownership.
See `docs/technical/dev/adr-enforcement.md` for how to add a quality unit or
record a gap.

The Shifter Engine reusable workflow has an additional blocking provisioner
pytest gate before local Docker validation, credentialed image build, and ECS
deploy. This keeps a deploy dispatch from building or deploying the provisioner
image when the top-level Quality job is legitimately skipped.

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
- **Tests**: package-local Python, JavaScript, and harness suites, including
  `shifter_platform`, `cyberscript`, `shifter/engine/provisioner`, `packer`,
  `installation`, `scripts/bootstrap`, `scripts/gcp`, `scripts/polaris-aws-range`,
  `scenario-dev/polaris/tests`, the Postgres migration proof, and MCP package
  tests including `mcp/planner`.
- **IaC scanning**: Checkov for Terraform is a **blocking gate** under
  ADR-004-R11. Pre-commit and CI share the same config at
  `platform/terraform/.checkov.yaml`; `--soft-fail` is off. Accepted-risk
  waivers (Checkov `skip-check` entries or inline `# checkov:skip=…`
  comments) require a matching entry in `docs/adr/exceptions.yaml` with
  owner, reason, expiry, affected paths, and the Checkov policy ID.
- **Secret scanning**: gitleaks on newly introduced commits
- **Coverage**: `shifter_platform` and provisioner test jobs emit XML coverage
  reports

Commit-message or label-based test skips are not accepted by `deploy.yml`.

## Terraform Flow

Each component follows the same pattern:

1. **Plan job**:
   - Checkout repo (tfvars are committed)
   - `terraform init`
   - `terraform validate`
   - `terraform plan -lock-timeout=5m -out=tfplan`
   - Comment plan on PR (if PR)

2. **Apply job** (if plan succeeds):
   - Skip on PRs
   - Create a local saved `tfplan` with `terraform plan -lock-timeout=5m -out=tfplan`
   - `terraform apply -lock-timeout=5m tfplan`

Branch and manual deploy runs are queued by the Deploy workflow's concurrency
group so a newer push cannot cancel a Terraform process after it has started
mutating remote infrastructure or while it holds the backend lock. Pull request
runs may still be cancelled by newer commits because they do not execute apply
jobs.

The saved plan file created inside the apply job is the apply contract. If state
moves after that local plan, Terraform should fail the saved-plan apply instead
of silently executing a fresh unplanned apply. Raw binary plans are not uploaded
as workflow artifacts because they can include unredacted plan/state data. The
platform Service Discovery replacement check reads the same saved `tfplan` that
the apply step consumes.

**Note**: The committed `terraform.tfvars` files ship an `example.com`
baseline. Deployment-specific values (domains, alarm emails, allow-list
domains, account-suffixed bucket names, GCP project id, etc.) come from
GitHub repository variables and secrets at deploy time; CI/CD renders
them into a gitignored `local.auto.tfvars` before `terraform apply`.
See [`docs/dev/deploy-secrets.md`](../../dev/deploy-secrets.md)
for the required surface.

## AWS Platform Deployment

The `Core -> Range -> Engine -> Platform` chain above is the order between the
reusable workflows. This section documents the ordered sequence of jobs and
steps **inside** the platform reusable workflow (`_shifter-platform.yml`), which
is the portal (platform) stack. Jobs run in this order (each `needs` the
previous):

1. **`push-guacamole-images`**: build and push the `guacd` and
   `guacamole-client` images to ECR (only when the pinned tag is absent). Runs
   first because the portal plan and apply reference them.
2. **`plan`**: render `local.auto.tfvars` from `TF_VARS_<ENV>_PORTAL` (and the
   engine image digest into `zz-engine-image.auto.tfvars`), render the backend
   config, then `init` / `validate` / `plan`.
3. **`apply`** (branch/dispatch only), in order:
   - **Drain Service Discovery** registrations the plan will delete (scale
     affected ECS services to zero) so replacements do not collide.
   - `terraform apply` the saved plan.
   - **Restore ECS desired counts** after apply.
   - **Assert portal inspection** route and endpoint wiring (no-op when
     inspection is off; fails the deploy if the routed firewall path is
     unhealthy).
   - **Verify RDS pending modifications applied** (dev only): a successful apply
     that leaves non-empty `PendingModifiedValues` fails the job.
   - **Wait for Guacamole ECS services to stabilize** (bounded poll).
4. **`build`**: build and push the portal image
   (`shifter/shifter_platform/Dockerfile`) to `shifter-<env>-portal`. The image
   is tagged `<short-sha>-<run-id>-<run-attempt>` and the job outputs its
   digest; there is no `latest` tag.
5. **`deploy`**, in order:
   - **Resolve topology** from Terraform state (`enable_autoscaling`,
     `ec2_instance_id`, `asg_name`).
   - **Update Parameter Store** with the new image digest and tag.
   - **Update bootstrap admin parameters** (staff / superuser emails).
   - **Run database migrations** on one healthy instance (ASG mode; single
     instance mode migrates inside its deploy script).
   - **Deploy via SSM** (single instance) **or trigger an ASG instance
     refresh** (ASG mode).
   - **Verify ASG image digest** and **verify ASG worker health** (ASG mode).
6. **`verify`**: post-deploy health check.
7. **`post-deploy-smoke`** (dev applies only, `continue-on-error`): run
   `scripts/smoke-test.sh`. A failure opens a `[smoke-test]` bug issue and does
   not fail the deploy. Requires the `SMOKE_*` secrets (see
   [`docs/dev/deploy-secrets.md`](../../dev/deploy-secrets.md)).

**Single instance mode** targets the `{env}-portal-ec2` tagged instance.
**Auto Scaling mode** refreshes `{env}-portal-asg` and verifies the new digest
and worker health on every in-service instance.

**Refresh scope and timing (issue #1639).** The ASG instance refresh runs only when the
portal actually changed (the portal image or platform Terraform). An engine-provisioner-only
deploy no longer triggers a full portal refresh. Refresh readiness tracks the ALB target
group (`health_check_type = "ELB"`), so a refresh converges once the portal is actually
serving instead of waiting out the EC2 "insufficient data to evaluate its health" window.
The ASG timing is environment-owned Terraform (`health_check_type`,
`health_check_grace_period`, and `instance_refresh_instance_warmup` on the portal root),
so a dev or proof tenant can shorten the health-grace to speed up the deploy, test, fix
loop without changing prod.

### First-run DNS timing

On a fresh account the first Portal apply blocks while AWS validates ACM
certificates and SES identities. Publish the validation records in the
authoritative DNS zone while the apply is waiting, and publish the runtime
routing records (ALB CNAMEs, CTFd A record) once the apply creates those
endpoints. The exact records and commands are in
[`docs/dev/deploy-secrets.md`](../../dev/deploy-secrets.md)
under the first-run DNS validation and routing sections.

## Environment Detection

```
Event / input                  → Behavior
Pull request                   → Quality only
Push to dev / main             → Quality only
dispatch environment=aws-dev   → AWS dev deploy
dispatch environment=aws-proof → AWS proof deploy
dispatch environment=gcp-dev   → GCP dev deploy
```

## Provider Routing

- `dev`/`main` are integration branches: they run the quality gate but never plan/apply infrastructure or deploy workloads.
- A deploy is a manual `workflow_dispatch` that names the `environment`; the branch you run it from is the code that deploys. No branch name selects the target.
- The GCP control plane is deployed through the Helm chart in `platform/charts/shifter`, with generated values layered on top of environment defaults.
- The GCP portal auth contract is FirebaseUI/browser-side Identity Platform auth plus server-side verified-token exchange. Do not add Django credential handling to recreate Cognito semantics.
- Multi-cloud work enters through the shared cloud adapter layers rather than provider-specific calls in domain services.

## Manual Deploy Inputs

`deploy.yml` runs on `workflow_dispatch`. The `environment` input selects the deployment target; the bootstrap flags are strict by default.

- `environment`: which environment to deploy: `aws-dev`, `aws-proof`, or `gcp-dev`. A closed choice enum. The branch you run the workflow from is the code that deploys.
- `aws_first_deploy` (default `false`): allow the AWS engine deploy to skip the ECS task-family existence check. Set `true` only for the first-ever deploy to a fresh AWS environment, before the platform Terraform apply has created the provisioner task definition. On any normal deploy a missing or typo'd task family fails the run instead of skipping silently. Clear it (re-run without the flag) once the platform stack has been applied.
- `gcp_require_active_certificate` (default `true`): require the GKE ManagedCertificate to be Active for the public hostname. Set `false` only for first-time GCP bootstrap, before DNS for the hostname has been pointed at the ingress IP.

## Runner Policy

Workflows choose one runner class per job. Portable quality jobs run on
`ubuntu-latest`; trusted deployment, image-build, Packer, and
environment-mutating jobs run on `self-hosted` runners. GitHub Actions does not
provide native fallback between those runner classes.

The self-hosted runner has:

- AWS CLI configured
- gcloud SDK support for GCP workflows
- Docker + BuildX
- Terraform (deploy jobs pin `1.13.3`)
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
- A deploy is a manual dispatch: `gh workflow run deploy.yml --ref <branch> -f environment=<aws-dev|aws-proof|gcp-dev>`. Pushes and PRs run validation only; no branch push deploys.

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

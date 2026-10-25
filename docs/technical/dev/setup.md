# Setup

Deploy Shifter from a cloud account to a running environment.

## Before You Start

Work through this checklist before running any command below. A fresh tenant
standup fails partway if an item is missing, so confirm all of them first.

### Local tooling

- Python 3.12+
- `uv`
- Terraform 1.7+
- GitHub CLI (`gh`) authenticated
- Docker
- **AWS**: AWS CLI v2 configured with SSO or IAM credentials
- **GCP**: `gcloud` CLI authenticated with appropriate project

### Accounts and access

- A cloud account (AWS or GCP) with billing enabled and permissions to create
  IAM, networking, compute, database, and storage resources.
- Admin access to the GitHub repository to set Actions secrets and variables
  (Settings, then Secrets and variables, then Actions).
- A domain you control, plus access to its DNS provider. It is required for
  certificate validation (ACM on AWS, managed TLS on GCP) and to point the
  hostname at the load balancer.

### Must already exist before the first Terraform apply (AWS)

These are hard preconditions; the Portal stack plan fails without them. See
[`aws-terraform-apply-order.md`](../../dev/aws-terraform-apply-order.md)
for the authoritative order.

- **Bootstrap has run** for the environment (`scripts/bootstrap/deploy.py
  bootstrap`), creating the S3 state bucket, GitHub OIDC provider, and deploy
  IAM role. This doc walks through it under [AWS Deployment](#aws-deployment).
- **Self-hosted runners provisioned and registered**, if deploying through CI
  (all AWS deploy jobs use `runs-on: self-hosted`). See
  [`aws-runner-provisioning-runbook.md`](../../dev/aws-runner-provisioning-runbook.md).
- **Range AMIs built and the `/shifter/ami/{kali,ubuntu,windows,dc}` SSM
  parameters seeded.** The Portal stack reads these as data sources. See
  [`aws-ami-seeding-runbook.md`](../../dev/aws-ami-seeding-runbook.md).
- **Engine provisioner image built** (CI `_shifter-engine.yml`) so the Portal
  stack can resolve its image digest.

### Must already exist before deploy (GCP)

- A GCP project with the required APIs enabled.
- Workload Identity Federation configured for GitHub Actions (pool, provider,
  purpose service accounts), with the explicit `GCP_*_SERVICE_ACCOUNT` value
  and `GCP_WORKLOAD_IDENTITY_PROVIDER` set in each purpose Environment.
- Public Kali/Ubuntu/DC base packages available in GHCR. The first local
  `gdc-bootstrap --import-public-base-images` invocation imports them as native
  GCE images before platform preconditions run; no platform-owned transfer
  bucket must already exist. See
  [`gcp-range-cell-deploy.md`](../../dev/gcp-range-cell-deploy.md) and
  [`gcp-guest-images.md`](../../architecture/gcp-guest-images.md).

### Configuration values

- The single authoritative checklist of every secret and repository variable a
  fresh environment needs, and how each is populated, is in
  [`deploy-secrets.md`](../../dev/deploy-secrets.md). The deploy
  preflight enforces these.

## Root Installation Config

Scaffold, edit, then validate `shifter.yaml` before deployment. `init` copies the
checked example for your backend to `./shifter.yaml` (local-only: it writes no
secrets and calls no cloud API):

```bash
# Scaffold ./shifter.yaml (run `init` with no --backend to list the available backends).
uv run --project shifter/installation shifter-config init --backend aws

# Edit shifter.yaml for your deployment, then validate its shape.
uv run --project shifter/installation shifter-config validate shifter.yaml
```

Use `--backend gcp` for GCP. See [Installation Config](installation-config) for the
field reference.

## Doctor

Once `shifter.yaml` is filled in, run `doctor` to validate the *selected backend* (not
just the config shape) before applying infrastructure. It runs the checks the backend
bundle declares (required tools on PATH, secret references, generated outputs, owned
repository paths, and the bundle's credential-free validation checks) and labels each
check as local-only, cloud-read-only, or deployment-mutating. It is non-mutating by
default and its output is backend/profile based, so you never need to read the deploy
workflow's branch logic to understand a failure.

```bash
# Local-only checks (default): config, tools, secret references, non-mutating validation.
uv run --project shifter/installation shifter-config doctor shifter.yaml

# Additionally run read-only health probes of the deployment endpoint (post-deploy).
uv run --project shifter/installation shifter-config doctor shifter.yaml --checks cloud
```

`doctor` exits `1` when any blocking check fails. It is a pre-mutation readiness signal;
the deploy preflight below, Terraform, and runtime health gates remain authoritative for
their own layers.

## Preflight

The deploy preflight is the shared, fail-safe check that every prerequisite is in
place before any change is made. It runs the same checks locally and in CI, so a
missing secret, tool, or config fails up front with a consolidated report instead
of partway through a Terraform apply.

Run it on demand before deploying:

```bash
# Validate an AWS environment (add --component core|range|portal to scope overlays)
./scripts/bootstrap/deploy.py preflight --cloud aws --env dev

# Validate the GCP environment
./scripts/bootstrap/deploy.py preflight --cloud gcp --env gcp-dev
```

The `bootstrap`, `terraform`, and `full` commands run the preflight automatically
at the start. It is interactive by default: it prints the results and asks you to
confirm the manual prerequisites it cannot verify (cloud authentication, DNS
access). Pass `--headless` (or run without a TTY, as CI does) to skip the prompts
and fail on any missing required prerequisite instead.

The first Identity Platform operator credentials
(`GCP_BOOTSTRAP_ADMIN_EMAIL` / `GCP_BOOTSTRAP_ADMIN_PASSWORD`) are required. To
deliberately skip operator creation, set `SHIFTER_SKIP_OPERATOR_BOOTSTRAP=true`
(locally) or the matching repository variable (CI); the skip is logged, never
silent.

## Environments and Terraform Layout

Shifter currently uses one Terraform directory set and one deploy branch per
environment. Standing up a new tenant means adding both. This is the current
model, not a target architecture; it duplicates stack wiring across
environments, so treat an existing environment's directory set as the unit you
copy.

### Terraform directories

```
platform/terraform/
  environments/<env>/        AWS environment; the root is the Core (ECR) stack
    range/                   Range VPC stack (its own backend state)
    portal/                  Portal / application stack (its own backend state)
  gcp/environments/<env>/    GCP environment (core stack plus Helm control plane)
  global/                    Shared account-wide stacks (IAM, GitHub runners, ...)
  modules/                   Reusable AWS modules
  gcp/modules/               Reusable GCP modules
```

Existing environments: `dev`, `prod`, and `proof` under `environments/` (AWS),
and `gcp-dev` under `gcp/environments/` (GCP). Each AWS environment is three
stacks applied in order (Core, then Range, then Portal), each with its own
backend state key. See
[`aws-terraform-apply-order.md`](../../dev/aws-terraform-apply-order.md)
for the authoritative order and state keys.

### Deploy branches

Each environment deploys from its own long-lived branch, not from `dev`. The
branch name does not always match the environment directory name.

| Environment | Terraform directory | Deploy branch | Trigger |
|-------------|---------------------|---------------|---------|
| AWS dev | `environments/dev` | `aws-dev` | push deploys |
| AWS proof | `environments/proof` | `aws-proof` | `workflow_dispatch` |
| AWS prod | `environments/prod` | `main` | `workflow_dispatch` |
| GCP dev | `gcp/environments/gcp-dev` | `gcp-dev` | push deploys |

`dev` is the integration branch: it runs Quality only and never deploys. See
[CI/CD](ci-cd) for the full trigger matrix.

### Adding a new environment

1. Copy an existing environment's Terraform directory set (for example
   `environments/proof/` for AWS or `gcp/environments/gcp-dev/` for GCP), then
   update its backend state keys and `local.auto.tfvars` values for the new
   account and hostnames.
2. Create the environment's deploy branch and wire its per-environment secrets
   and repository variables. See
   [`deploy-secrets.md`](../../dev/deploy-secrets.md).
3. Bootstrap the account and follow the standup steps below.

## AWS Deployment

Use the deployment CLI which walks you through each step with confirmations:

```bash
# Preview what will happen (no changes made)
./scripts/bootstrap/deploy.py full --env prod --profile <your-prod-profile> --dry-run

# Run the full deployment
./scripts/bootstrap/deploy.py full --env prod --profile <your-prod-profile>
```

Or run phases separately:

```bash
# Phase 1: Bootstrap AWS account (S3 state backend, GitHub OIDC, IAM)
./scripts/bootstrap/deploy.py bootstrap --env prod --profile <your-prod-profile>

# Phase 2: Deploy Terraform (Core → Range → Portal)
./scripts/bootstrap/deploy.py terraform --env prod --profile <your-prod-profile>
```

### 1. Bootstrap AWS Account

The `bootstrap` command creates:
- S3 bucket for Terraform state with S3 native locking (`use_lockfile = true`)
- GitHub OIDC provider (keyless CI/CD auth)
- IAM role with all required permissions

It outputs:
- GitHub secret value (`AWS_ROLE_ARN`)
- Backend configuration for `backend.tf` files

### 2. Configure GitHub Secrets

Add these secrets in GitHub repository settings (Settings → Secrets and variables → Actions):

| Secret | Value |
|--------|-------|
| `AWS_ROLE_ARN` | Prod IAM role ARN from bootstrap output |
| `AWS_ROLE_ARN_DEV` | Dev IAM role ARN from bootstrap output |

### 3. Update Backend Configuration

Copy the backend config from bootstrap output to these files:

| File | State Key |
|------|-----------|
| `platform/terraform/environments/prod/backend.tf` | `shifter/prod/terraform.tfstate` |
| `platform/terraform/environments/prod/portal/backend.tf` | `prod/portal/terraform.tfstate` |
| `platform/terraform/environments/prod/range/backend.tf` | `prod/range/terraform.tfstate` |

### 4. Configure deployment-specific values

The committed `terraform.tfvars` files ship an `example.com` baseline.
Override per-deployment values with a `local.auto.tfvars` (gitignored)
alongside each baseline; Terraform auto-loads `*.auto.tfvars` and the
local overrides win:

```bash
cat > platform/terraform/environments/prod/portal/local.auto.tfvars <<EOF
domain_name           = "shifter.your-domain.example"
ses_domain            = "your-domain.example"
alarm_email           = "your-team@your-domain.example"
allowed_email_domains = ["your-domain.example"]
user_storage_bucket   = "shifter-user-storage-<your-account-id>"
EOF
```

`local.auto.tfvars` is gitignored; never commit one. The full list of
required values, plus the CI-deploy equivalent via GitHub secrets and
repository variables, is documented in
[`docs/dev/deploy-secrets.md`](../../dev/deploy-secrets.md).

### 5. Deploy Infrastructure

Deploy in this order (dependencies flow down):

```
┌─────────────────────────────────┐
│  1. Core (ECR repositories)    │
│  platform/terraform/environments/prod/
└───────────────┬─────────────────┘
                │
        ┌───────┴───────┐
        │               │
        ▼               ▼
┌───────────────┐ ┌─────────────────────────┐
│  2. Range VPC │ │  (wait for Range)       │
│  .../range/   │ │                         │
└───────┬───────┘ └─────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  3. Portal                      │
│  .../portal/                    │
│  (references Range outputs)     │
└─────────────────────────────────┘
```

**Using the CLI (recommended):**

```bash
./scripts/bootstrap/deploy.py terraform --env prod --profile <your-profile>
```

The CLI walks through each component, shows the plan, and asks for confirmation before applying.

**Via CI/CD:**

Run `Deploy` with `workflow_dispatch` on `main` to deploy the AWS production
environment after bootstrap and backend configuration are complete. Pushing or
merging to `main` updates the production code branch only; it does not deploy.

**Manual deployment:**

```bash
# Step 1: Core (ECR)
cd platform/terraform/environments/prod
AWS_PROFILE=<your-profile> terraform init && terraform plan && terraform apply

# Step 2: Range VPC
cd range
AWS_PROFILE=<your-profile> terraform init && terraform plan && terraform apply

# Step 3: Portal
cd ../portal
AWS_PROFILE=<your-profile> terraform init && terraform plan && terraform apply
```

### 6. ACM Certificate Validation

On first deploy, Terraform pauses waiting for ACM certificate validation (up to 45 min timeout).

**Get the validation records:**

```bash
# While terraform apply is running (or after plan), get the CNAME records:
cd platform/terraform/environments/prod/portal
AWS_PROFILE=<your-profile> terraform output -json acm_validation_records
```

Output format:
```json
{
  "shifter.yourdomain.com": {
    "name": "_abc123.shifter.yourdomain.com.",
    "type": "CNAME",
    "value": "_xyz789.acm-validations.aws."
  }
}
```

**Add to your DNS provider:**

| Type | Name | Value |
|------|------|-------|
| CNAME | `_abc123.shifter.yourdomain.com` | `_xyz789.acm-validations.aws.` |

After DNS propagates (~5 min), Terraform continues automatically.

### 7. Point Domain to ALB

After deployment completes:

```bash
cd platform/terraform/environments/prod/portal
AWS_PROFILE=<your-profile> terraform output alb_dns_name
```

Create a CNAME record pointing your domain to the ALB DNS name.

### 8. Build and Push Container

The first deploy creates empty ECR repos. The portal, Guacamole, and engine
provisioner images are built and pushed by the Deploy workflow itself, not by a
local script. Trigger the deploy to build and push them:

```bash
# Run the Deploy workflow with workflow_dispatch on the environment's deploy
# branch (aws-dev for dev, main for prod). The _shifter-platform.yml "build"
# job builds shifter/shifter_platform/Dockerfile and pushes to the
# shifter-<env>-portal ECR repo; the "push-guacamole-images" job builds and
# pushes guacd and guacamole-client.
gh workflow run Deploy --ref main
```

### 9. Cognito Configuration

Cognito is fully configured by Terraform. You only need to:

1. **Set `cognito_domain_prefix`** in `local.auto.tfvars` (must be globally unique):
   ```hcl
   cognito_domain_prefix = "shifter-prod-yourorg"
   ```

2. **Create first user** (after Terraform apply):
   ```bash
   # Get user pool ID from terraform output
   USER_POOL_ID=$(terraform output -raw cognito_user_pool_id)

   # Create user
   aws cognito-idp admin-create-user \
     --user-pool-id $USER_POOL_ID \
     --username YOUR_EMAIL@example.com \
     --user-attributes Name=email,Value=YOUR_EMAIL@example.com \
     --profile <your-profile>
   ```

Callback URLs (`https://yourdomain.com/oidc/callback/`) are automatically configured from `domain_name`.

Email domain restrictions are controlled via `allowed_email_domains` in portal module.

## Existing Environment Setup

If deploying to an account with existing infrastructure:

### Initialize Terraform

```bash
cd platform/terraform/environments/prod/portal
AWS_PROFILE=<your-profile> terraform init
```

### Verify State

```bash
AWS_PROFILE=<your-profile> terraform plan
```

No changes means infrastructure matches state.

## Common Issues

### State Lock Error

Someone else is running Terraform, or a previous run crashed:

```bash
# Check who has the lock, then force unlock if needed
terraform force-unlock <LOCK_ID>
```

### Provider Cache Issues

```bash
rm -rf .terraform
terraform init
```

### ACM Validation Timeout

If Terraform times out waiting for ACM:

```bash
# 1. Get the validation records again
terraform output -json acm_validation_records

# 2. Check if DNS is propagated (replace with your actual record name)
dig CNAME _abc123.shifter.yourdomain.com

# 3. If DNS is correct, just re-run apply (it will resume)
terraform apply
```

Common issues:
- **Trailing dot**: Some DNS providers need the trailing `.` removed from the value
- **Wrong record type**: Must be CNAME, not TXT
- **Propagation delay**: Wait 5-10 minutes after adding records

### Container Pull Failures

Check ECR repo exists and has images:

```bash
aws ecr describe-images --repository-name shifter-prod-portal
```

If empty, push a container first.

## GCP Deployment

GCP provisions with Terraform (`platform/terraform/gcp/`, rooted at `environments/gcp-dev`, whose main module is `modules/platform-core/`) and a control plane deployed either from the Helm chart `platform/charts/shifter/` (the local `gdc-bootstrap` path) or from the kustomize overlay `platform/k8s/gcp/overlays/gcp-dev/` (the CI `deploy.yml` path).

### 1. GCP Project Setup

Create a GCP project. Before starting bootstrap, enable every Google Cloud API
required by the selected Shifter configuration. If the configuration uses AI
models, also enable every configured model in Vertex AI Model Garden: an
authorized project administrator must open each model, accept any provider or
Marketplace terms, and confirm that it is available in the configured region.
Enabling the Vertex AI API does not enable individual models. Complete both API
and model enablement before bootstrap, pack installation, or range
qualification; otherwise deployment can succeed while participant model calls
fail with a misleading model-not-found response.

### 2. Configure Workload Identity Federation

On a new project, run `scripts/bootstrap/deploy.py gcp-foundation --inputs
/path/to/foundation.tfvars.json --yes` using the complete example and ordering
in `scripts/bootstrap/README.md`. This creates the backend before identity
Terraform initializes and can provision an isolated private image-build network
before the platform exists. It verifies project/repository numeric IDs and
requires explicit purpose Environment and workflow trust tuples.

Apply `platform/terraform/gcp/global/cicd-oidc` for each used identity profile
(`gcp-dev`, `proof`, and `prod`) and follow the staged cutover/readback in
`docs/dev/deploy-secrets.md`. Do not hand-create service accounts or broaden the
provider condition. The profiles create one provider per project and distinct
purpose identities:

1. Create and protect the purpose GitHub Environments.
2. Apply the purpose identities from an independent operator principal.
3. Add each output only to its matching Environment:

| Secret | Value |
|--------|-------|
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deploy service account email |
| `GCP_DESTROY_SERVICE_ACCOUNT` | Destroy service account email |
| `GCP_PACKER_BUILD_SERVICE_ACCOUNT` | Image build service account email |
| `GCP_PACKER_VALIDATE_SERVICE_ACCOUNT` | Image validation service account email |
| `GCP_PACKER_PROMOTE_SERVICE_ACCOUNT` | Image promotion service account email |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name |

### 3. Configure deployment-specific values

The committed `terraform.tfvars` ships an `example.com` baseline; supply
the real values via a gitignored `local.auto.tfvars` (Terraform auto-loads
`*.auto.tfvars`):

```bash
cat > platform/terraform/gcp/environments/gcp-dev/local.auto.tfvars <<'EOF'
project_id                  = "<your-gcp-project-id>"
dynamic_secret_project_id   = "<your-gcp-project-id>"
public_hostname             = "shifter.<your-domain>"
enable_managed_tls          = true
gke_master_authorized_cidrs = []
EOF
```

Treat an existing `local.auto.tfvars` as deployment state, not as a reusable
sample. Before bootstrap, replace every tenant-bound value left by an earlier
project, especially `project_id`, `dynamic_secret_project_id`, and
`public_hostname`. Terraform auto-loads this file and its values drive the
ingress and managed certificate; selecting a different `shifter.yaml` does not
override a stale hostname here. Confirm the hostname in both inputs agrees
before applying so bootstrap does not stop at DNS/TLS for the previous tenant.

For CI deploys the equivalent values come from GitHub secrets; see
[`docs/dev/deploy-secrets.md`](../../dev/deploy-secrets.md).

The CI deployment also reads the committed tenant overlay at
`platform/k8s/gcp/overlays/<environment>/`; GitHub Environment values do not
rewrite its image or Workload Identity references. Before the tenant's first CI
deploy, verify both account-bound surfaces in that overlay:

- every `images[].newName` in `kustomization.yaml` uses the tenant project and
  the Artifact Registry repositories created for that environment
- every `iam.gke.io/gcp-service-account` annotation in
  `patch-serviceaccounts.patch` uses the tenant project and the service-account
  localpart created by the platform Terraform naming contract

Render the overlay before pushing the tenant branch and inspect the resulting
image names and service-account annotations:

```bash
kubectl kustomize platform/k8s/gcp/overlays/<environment> > /tmp/<environment>-rendered.yaml
```

Do not copy an existing tenant overlay without replacing both surfaces. A stale
project in either file can leave Terraform and GitHub correctly configured while
the CI Kubernetes deploy still pulls from another project's registry or binds
pods to another project's identities.

#### Optional: model access broker

> **Not supported for use.** The broker is parked: keep `settings.model_broker`
> and `settings.model_access` disabled. Three known defects make it unfit to run:
> its TLS certificates are never renewed, so deploys fail 16 days after the first
> broker deploy and its certificate expires at day 30; a fresh tenant with a
> broker template fails its first deploy; and every model call requires finite
> spend, rate, and concurrency limits. Range guests reach models through the
> keyless default below. This section documents the settings for reference only.

The ADR-059 model access broker is off by default. Without it, range guests use
the keyless Vertex identity (ADR-064). Turning it on needs three
`shifter.yaml` settings blocks that must agree with each other, plus prerequisites
outside the repository. Validation rejects a partial broker configuration before
any cloud change.

- `settings.model_broker`: `enabled: true`, the broker `hostname`, a private IPv4
  `vip` inside the platform GKE subnet, and `admitted_subnets`. Each admitted
  subnet must sit inside `range_network_cidr` and be disjoint from the VIP and
  from the other subnets. The block also needs the TLS Secret, control TLS
  Secret, and CA ConfigMap names, and `model_projects`, which maps each model
  project ID to its invocation service-account ID. `global_access` stays `false`
  unless cross-region private clients need the VIP.
- `settings.model_access`: `enabled: true` and a versioned, priced catalog
  with its digest. Every account needs a positive spend, rate, and concurrency
  ceiling; the schema has no unlimited mode.
- `settings.model_broker_runtime`: the provider inventory, whose principals must
  equal the applied invocation service accounts, and the fingerprint Secret name
  and key version. It also takes `guest_trust_ca_pem`, the public broker CA
  certificate that guests trust. With an empty CA, no guest can enroll.

Supply the blocks one of two ways:

1. A reviewed template at
   `platform/deploy/gcp/<environment>/model-broker-overlay.template.json`, the
   recommended path. It must contain exactly the three blocks above and the
   placeholders `__GCP_PROJECT_ID__`, `__GUEST_CA_PEM__`, and
   `__CATALOG_DIGEST__`. It must also use the fixed names
   `model-broker-tls-v1`, `model-control-tls-v1`, `model-access-ca-v1`, and
   `broker-fingerprint-v1`. On each CI deploy,
   `scripts/gcp/prepare_model_broker_overlay.py` creates or verifies the broker
   CA, both TLS Secrets, the CA ConfigMap, and the fingerprint Secret in
   `shifter-platform`. It also fills in the CA and the catalog digest. The
   reference shape is
   `scripts/gcp/tests/fixtures/model-broker-overlay.template.json`.
2. The `SHIFTER_CONFIG_OVERLAY_JSON` variable, or the blocks written directly into
   `shifter.yaml`. Neither path creates the trust objects or computes the catalog
   digest: create the Kubernetes Secrets and ConfigMap first, and set the digest
   and CA yourself. The local `gdc-bootstrap` path supports only this form. The
   chart mounts the trust objects by name, so a missing object makes the Helm
   upgrade fail.

Before enabling:

- Run the first deploy without the template. The template step connects to the
  GKE cluster before Terraform runs, so on a fresh tenant it fails because the
  cluster does not exist yet. Add the template once the cluster exists.
- Prepare every model project. Each one needs billing enabled, the label
  `shifter-deployment=<deployment.name>`, and the Vertex models enabled. Terraform
  enables the APIs and creates the invocation service account and its roles
  there. The CI deploy identity holds roles only in the platform project, so
  grant it equivalent authority in each other model project first.
- Set `GCP_RANGE_PRIVATE_GOOGLE_ACCESS=false`. Broker clients require
  source-preserving isolated egress, and a broker-enrolled range with Private
  Google Access on fails to provision.
- Plan certificate renewal. The template path issues 30-day TLS certificates
  and a 365-day CA, and refuses to deploy when a certificate has less than 14
  days left or the CA less than 30. It does not renew either automatically yet.

See [GCP packaging](../../architecture/model-access/gcp-packaging.md) and the
[model access GCP probes](../../ops/model-access-gcp-probes.md) for the full
contract and post-deploy checks.

### 4. Deploy

The first clean install runs locally under your own credentials (Workload Identity
Federation is only needed for CI). Subsequent deploys run through CI with
`gh workflow run deploy.yml --ref gcp-dev -f environment=gcp-dev`. The local
bootstrap entrypoint is below. GitHub Environment variables are not imported into
the operator's shell, so export the range-plane values locally even when CI is
already configured. Refresh both the `gcloud` user credential and Application
Default Credentials before a long bootstrap, and verify the Artifact Registry
Docker credential helper is on `PATH`:

```bash
gcloud auth print-access-token >/dev/null
gcloud auth application-default print-access-token >/dev/null
command -v docker-credential-gcloud >/dev/null

export RANGE_NETWORK_ZONE=<zone>
export GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL=<range-host-service-account>
```

Use the exact Terraform identity, not a hand-normalized variant of the
environment name. The standard module removes hyphens from the
`shifter-<environment>` account-id prefix (for example, `gcp-dev` becomes the
prefix `shiftergcpdev`). After the first platform apply, read back the canonical
value:

```bash
terraform -chdir=platform/terraform/gcp/environments/<environment> \
  output -raw range_host_service_account_email
```

Publish that exact value to the GitHub Environment and reuse it for local
retries.

If `gcloud` is installed under `~/google-cloud-sdk` but the credential-helper
check fails, load the SDK's standard path initializer and add the same guarded
source line to the operator's shell startup file before running bootstrap:

```bash
if [ -f "$HOME/google-cloud-sdk/path.bash.inc" ]; then
  . "$HOME/google-cloud-sdk/path.bash.inc"
fi
command -v docker-credential-gcloud >/dev/null
```

Do not work around a missing helper with a one-off registry login. Bootstrap
builds and pushes several images, and the persistent SDK path initialization
keeps the documented credential-helper flow available on later deploys.

When exact first-operator credentials are supplied in the process environment,
set `SHIFTER_BOOTSTRAP_ENV_SOURCE=process` with
`GCP_BOOTSTRAP_ADMIN_EMAIL` and `GCP_BOOTSTRAP_ADMIN_PASSWORD`. This prevents a
file-backed value from taking precedence unexpectedly. Do not set
`SHIFTER_SKIP_OPERATOR_BOOTSTRAP` unless omitting the first human operator is an
explicit deployment decision.

The public DC artifact can require substantially more temporary space than a
memory-backed `/tmp`. Set `TMPDIR` to a filesystem with enough free space for the
largest compressed and expanded image before using `--import-public-base-images`.

Then run:

```bash
./scripts/bootstrap/deploy.py gdc-bootstrap \
  --project-id <your-gcp-project-id> --environment <environment> \
  --region <region> --zone <zone> \
  --shifter-config /path/to/shifter.yaml \
  --import-public-base-images --yes
```

Keep the kubeconfig current context pinned to this tenant for the entire local
bootstrap, including the DNS/TLS wait. The bootstrap obtains the target Connect
Gateway context itself, but subsequent `kubectl` polls use the shared current
context. Do not run another cluster's `get-credentials` or `use-context` against
the same kubeconfig concurrently; use a separate `KUBECONFIG` for parallel
cluster work.

Despite the command name, the default `--range-backend gce` deploys the GKE control
plane and the GCE range plane and skips the GDC/ABM VM Runtime substrate. That
substrate is built only with `--range-backend gdc`. With the default
`--terraform-identity operator-adc`, Terraform runs under your Application Default
Credentials, creating no service account or key. The flow:

1. validates GCP/GitHub authentication and all three public OCI manifests
2. imports or reuses exact digest-derived `READY` GCE images through a private,
   per-run transfer bucket that is removed on every exit
3. publishes the exact references to the selected GitHub Environment and binds
   those same values to the local platform bootstrap
4. applies GCP Terraform (GKE, Cloud SQL, Memorystore, Pub/Sub, and related resources)
5. seeds the first Identity Platform operator
6. builds and pushes control-plane images
7. renders secure Helm values from Terraform outputs and Secret Manager
8. installs or upgrades the Shifter Helm release

For an existing platform, refresh only the public base set with
`./scripts/bootstrap/deploy.py gcp-images --project-id <project> --environment
<environment> --region <region>`. Either command accepts `--dry-run`; discovery
and read-only validation still run, while payload download and GCP/GitHub
mutation do not.

With `--range-backend gdc`, the flow first builds or reconciles the GDC substrate.

### 5. DNS and TLS

The GCP path requires a real hostname and managed TLS. Point the configured
hostname to the reserved global ingress IP so the Google-managed certificate can
become active.

### 6. Optional: participant OpenVPN access

Participant OpenVPN (ADR-039-R10) is off by default. When it is on, every
deployment runs one shared, autoscaled OpenVPN server pool, and participants
download an `.ovpn` profile for their range. The local `gdc-bootstrap` path never
deploys the pool, so turn it on after bootstrap through the CI deploy:

1. Apply `platform/terraform/gcp/global/cicd-oidc` for the tenant's identity
   profile from a revision that includes the pool. The apply adds the deploy and
   destroy roles `<prefix>_deploy_vpn_pool` and `<prefix>_destroy_vpn_pool`. Each
   role covers the pool's instance templates, regional instance group, and
   autoscaler, and its VM, disk, and template permissions apply only to the
   pool's `shifter-<environment>-vpn-` names. Without these roles the deploy
   fails when it creates the pool's instance template. Confirm both bindings:

   ```bash
   gcloud projects get-iam-policy <project> --format=json \
     | jq -r '.bindings[] | select(.role | test("vpn_pool")) | .role'
   ```

2. Set the GitHub Environment variable `RANGE_OPENVPN_ENABLED=true` for the
   tenant.
3. Run the CI deploy:
   `gh workflow run deploy.yml --ref <branch> -f environment=<environment>`.
   It creates the pool, the tenant OpenVPN CA, and the pool server certificate.
   It also records the scanned image digest, starts the servers, and waits until
   every server is healthy behind the load balancer.
4. Plan quota for the pool: it adds `e2-standard-2` VMs (two vCPUs each) up to
   the capacity profile's maximum, plus one external address for the endpoint
   and one for the pool's NAT.

Do not set `openvpn_pool_enabled = true` in `local.auto.tfvars` for a local
bootstrap. The local path does not build the server image or write the PKI and
release record, so those servers never start. Launches stay safe either way: the
runtime switch is off unless the CI deploy renders `RANGE_OPENVPN_ENABLED=true`,
and that render fails if no pool exists. See "Participant OpenVPN access" in
[`docs/dev/gcp-range-cell-deploy.md`](../../dev/gcp-range-cell-deploy.md) for
the network design, sizing, and session rules.

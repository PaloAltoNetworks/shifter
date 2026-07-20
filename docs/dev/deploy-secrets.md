# Deploy secrets and repository variables

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

The committed `terraform.tfvars` files in `platform/terraform/environments/...`
and `platform/terraform/gcp/environments/...` ship account-neutral baselines
that are intentionally broken-on-deploy where real account values are
required. Each environment provides its real deployment values via GitHub
secrets, repository variables, or a local operator overlay; deploy workflows
write them into a gitignored `local.auto.tfvars` that Terraform auto-loads
alongside the baseline (the `.local`/`.auto` overrides win).

This file lists values that must be configured before a fresh deploy. Set values
under **Settings → Secrets and variables → Actions**, separated by:

- **Secrets**: sensitive (project IDs, public keys with identifying
  comments, alarm email addresses, allow-list domains for self-signup,
  CIDR blocks for operator access).
- **Variables**: non-sensitive deployment parameters (region selection,
  feature flags).

Required values are enforced by the shared deploy preflight
(`scripts/bootstrap/preflight.py`), which runs the same checks locally and in the
CI deploy workflows. It reports every missing prerequisite up front before any
Terraform apply, so a gap fails in seconds rather than mid-run. Validate an
environment at any time without making changes:

```bash
./scripts/bootstrap/deploy.py preflight --cloud aws --env dev
./scripts/bootstrap/deploy.py preflight --cloud gcp --env gcp-dev
```

The **Required** column in the tables below marks the secrets the preflight
enforces. The first Identity Platform operator credentials are required unless
`SHIFTER_SKIP_OPERATOR_BOOTSTRAP=true` is set (locally) or the matching
repository variable is set (CI); the skip is logged, never silent.

## Secrets required to stand up an AWS environment

This is the single authoritative checklist of every secret a fresh AWS
environment standup needs, and how each one is populated. `dev` names are shown;
substitute `_PROOF` / `_PROD` (or the unsuffixed prod name) for the other AWS
environments. `.github/workflows/deploy.yml` forwards all of these to the
reusable deploy workflows. The GCP (`gcp-dev`) secrets are separate and listed
under [GCP (gcp-dev)](#gcp-gcp-dev).

The **Required** column marks the secrets the deploy preflight
(`scripts/bootstrap/preflight.py`) enforces before any Terraform apply; a
missing required secret fails the deploy up front rather than mid-run.

| Secret | Populated by | Required | Notes |
|---|---|---|---|
| `AWS_ROLE_ARN_DEV` | `scripts/bootstrap/deploy.py bootstrap --env dev` | yes | OIDC role the deploy jobs assume. Prod is `AWS_ROLE_ARN`. |
| `TF_INFRA_STATE_BUCKET_DEV` | `scripts/bootstrap/deploy.py bootstrap --env dev` | yes | Terraform state bucket the backend render reads. Prod is the unsuffixed `TF_INFRA_STATE_BUCKET`. |
| `TF_VARS_DEV_CORE` | `scripts/sync-deploy-secrets.sh --env dev` | yes | Core stack `local.auto.tfvars` payload (`budget_alert_email`). |
| `TF_VARS_DEV_RANGE` | `scripts/sync-deploy-secrets.sh --env dev` | yes | Range stack `local.auto.tfvars` payload (`agent_s3_bucket`, `vm_series_ami_id`). |
| `TF_VARS_DEV_PORTAL` | `scripts/sync-deploy-secrets.sh --env dev` | yes | Portal stack `local.auto.tfvars` payload (domain, email, buckets, capacity). |
| `SHIFTER_CONFIG_DEV_RANGE` | `scripts/sync-deploy-secrets.sh --env dev --stack config --shifter-config ./shifter.yaml` | yes | Deployment `shifter.yaml`; its `settings.range_egress` renders the range egress allowlist. |
| `SMOKE_TEST_USER_EMAIL` | manual | no | Post-deploy smoke user. See [Post-deploy smoke secrets](#post-deploy-smoke-secrets-dev). |
| `PLATFORM_BOOTSTRAP_STAFF_EMAILS` | manual | no | Comma-separated emails elevated to Django `is_staff` on first sign-in. Shared across all environments including prod. |
| `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` | manual | no | Comma-separated emails elevated to `is_superuser`. Shared across all environments including prod. |
| `SONAR_TOKEN` | manual | no | SonarCloud analysis token for the PR quality gate. Repository-wide, not per-environment. |
| `AWS_IMAGE_ROLE_ARN_DEV` | manual (from global-IAM output) | no | OIDC role the `packer.yml` base-image `build` job assumes (issue #1656), separate from the deploy `AWS_ROLE_ARN_*`. Least-privilege: its trust is pinned to the `dev`/`main` subjects and its `iam:PassRole` is scoped to the exact range instance role. Not checked by the deploy preflight, but the base build fails closed without it. Prod is `AWS_IMAGE_ROLE_ARN` (base builds target dev/proof); proof is `AWS_IMAGE_ROLE_ARN_PROOF`. Set from `terraform output -raw github_actions_image_role_arn` in `platform/terraform/global/iam`. See the [AWS AMI seeding runbook](aws-ami-seeding-runbook.md). |

"Populated by bootstrap" secrets are set once per account. "Populated by
`sync-deploy-secrets.sh`" secrets are re-pushed whenever the matching local
overlay changes. "Manual" secrets are set once under **Settings → Secrets and
variables → Actions** and are not written by either script.

Proof range standup needs `TF_VARS_PROOF_RANGE` and `SHIFTER_CONFIG_PROOF_RANGE`
as well, but `sync-deploy-secrets.sh` has no proof-range record yet, so set those
two by hand (see [AWS range](#aws-range-dev--prod)).

## Populating and syncing the secrets

The `TF_VARS_<ENV>_PORTAL` / `_RANGE` / `_CORE` and `SHIFTER_CONFIG_<ENV>_RANGE`
/ `SHIFTER_CONFIG_GCP_DEV` entries are whole-file payloads. Operators keep the
same values as gitignored `local.auto.tfvars` overlays (also used for local
`terraform` and symlinked into worktrees by `scripts/setup-worktree.sh`) and a
deployment `shifter.yaml`. `scripts/sync-deploy-secrets.sh` pushes those local
files into the matching GitHub secrets with `gh secret set`, so the secret and
the local overlay stay in step instead of the secret being hand-edited in the
GitHub UI:

```sh
# Preview what would be set (no writes):
scripts/sync-deploy-secrets.sh --env dev --dry-run

# Sync the dev tfvars overlays (portal, range, core):
scripts/sync-deploy-secrets.sh --env dev

# Include the SHIFTER_CONFIG_* payloads rendered from a shifter.yaml:
scripts/sync-deploy-secrets.sh --env dev --stack config --shifter-config ./shifter.yaml
```

The script fails loud when a selected overlay file is missing and never prints
secret contents. `scripts/bootstrap` still owns the one-time IAM role secret
(`AWS_ROLE_ARN_*`) and the state-bucket secret; this script owns the recurring
per-env tfvars/config payloads. Run it after editing an overlay (for example,
after changing the ASG capacity in a portal overlay) so the next deploy picks up
the new values rather than a stale secret.

Both bootstrap-owned secret names are env-suffixed for every non-prod
environment and unsuffixed only for prod, matching what the deploy workflows
read: prod uses `AWS_ROLE_ARN` / `TF_INFRA_STATE_BUCKET`, while dev uses
`AWS_ROLE_ARN_DEV` / `TF_INFRA_STATE_BUCKET_DEV` and proof uses
`AWS_ROLE_ARN_PROOF` / `TF_INFRA_STATE_BUCKET_PROOF`. A fresh non-prod bootstrap
sets the suffixed names automatically; do not set the unsuffixed
`TF_INFRA_STATE_BUCKET` for a dev or proof standup.

## GCP (gcp-dev)

Consumed by `.github/workflows/_gcp-dev.yml`.

| Name | Kind | Required | Notes |
|---|---|---|---|
| `GCP_PROJECT_ID` | secret | yes | The Google Cloud project the platform deploys to. |
| `GCP_REGION` | variable | no | Default `us-central1`. |
| `GCP_PUBLIC_HOSTNAME` | secret | yes | DNS name the platform serves on (for example, `shifter.your-domain.example`). |
| `GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN` | secret | yes | Identity Platform beforeCreate allow-list; the bootstrap operator must end with `@<this>` for sign-in to succeed. |
| `GCP_MASTER_AUTHORIZED_CIDRS` | secret | no | HCL list literal, for example `["1.2.3.4/32"]`. Empty (`[]`) locks the GKE control-plane to private endpoints only. |
| `GCP_SERVICE_ACCOUNT` | secret | yes | Workload-identity-federation service account for deploy. |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | secret | yes | Workload identity provider resource id. |
| `GCP_BOOTSTRAP_ADMIN_EMAIL` | secret | yes | First Identity Platform operator, elevated in Django. Must match `GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN`. Required unless `SHIFTER_SKIP_OPERATOR_BOOTSTRAP=true` is set to deliberately skip operator creation (the skip is logged). |
| `GCP_BOOTSTRAP_ADMIN_PASSWORD` | secret | yes | Initial password for the bootstrap operator (rotated by TOTP enrollment on first sign-in). Required unless `SHIFTER_SKIP_OPERATOR_BOOTSTRAP=true`. |
| `PLATFORM_BOOTSTRAP_STAFF_EMAILS` | secret | no | Comma-separated list of emails elevated to Django `is_staff` on first sign-in. |
| `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` | secret | no | Comma-separated list of emails elevated to `is_superuser`. |

For local GCP bootstrap, `scripts/bootstrap/deploy.py` validates the bootstrap
operator email against the Terraform output `identity_allowed_email_domain`.
When Terraform outputs are not available yet, it uses
`SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN` from the process environment.

### GitHub Actions WIF trust cutover (ADR-004-R23, #1690)

The `cicd-github-oidc` module federates GitHub Actions into GCP with an
**exact-subject** trust: the Workload Identity provider `attribute_condition`
admits only this repository, an exact protected `assertion.ref`
(`refs/heads/dev` / `refs/heads/main`), and an allow-listed `assertion.sub`; the
build service account is bound to those exact `principal://.../subject/<sub>`
members (never a repository-wide `principalSet`). Applying the Terraform text is
not the whole cutover - the live activation is a **fail-closed operator step with
readback**:

1. **Verify the OIDC subject format first.** `gh api
   repos/Brad-Edwards/shifter/actions/oidc/customization/sub` must return
   `use_default: true`, `use_immutable_subject: false`. A different result means
   the subjects in `local.federated_subjects` and the provider condition must be
   redesigned before applying - do not change the customization to fit the code.
2. **Set GitHub Environment deployment-branch policies.** An `environment:`
   subject does not carry the source branch, so every trusted Environment
   (`gcp-dev`, `dev`, `proof`, `prod`) must restrict deployment branches to the
   protected branches. Environment approval is deployment authorization, not
   code provenance.
3. **Apply the `gcp-dev` root**, then read back: `gcloud iam
   workload-identity-pools providers describe` (confirm the exact
   `attributeCondition`) and the build SA's `get-iam-policy` (confirm the exact
   `principal://.../subject/<sub>` members, no `principalSet`).
4. **Smoke it.** A protected-ref dispatch (from `dev`/`main`) federates; a
   feature-branch or tag dispatch is denied at the pool. There is no repository
   wildcard rollback path - an unlisted subject fails closed.

Adding or removing a trusted subject is a single edit to
`local.federated_subjects` **and** the matching `assertion.sub ==` clause in the
provider `attribute_condition`; the `check-tf-gcp-wif-trust` guard fails the
build if the two diverge. Splitting the shared build SA into per-purpose
identities is tracked in #1699.

## GCP Packer image builds

Consumed by `.github/workflows/packer-gcp.yml` (build) and
`.github/workflows/packer-gcp-promote.yml` (promote). Builds run on
`ubuntu-latest` with Workload Identity Federation (no long-lived SA keys);
variables reach Packer as `PKR_VAR_*` environment values, never `-var` CLI
flags. Reuses the deploy secrets `GCP_PROJECT_ID`, `GCP_SERVICE_ACCOUNT`,
`GCP_WORKLOAD_IDENTITY_PROVIDER`, and the variable `GCP_REGION` from the table
above, plus the following:

| Name | Type | Required | Purpose |
|------|------|----------|---------|
| `GCP_PACKER_ZONE` | variable | no | Build zone. Defaults to `${GCP_REGION}-a`. |
| `GCP_PACKER_NETWORK` | variable | no | Builder VPC network. Default `default`. |
| `GCP_PACKER_SUBNETWORK` | variable | no | Builder subnetwork. Default `default`. |
| `GCP_PACKER_SERVICE_ACCOUNT` | variable | no | Service account the builder VM runs as. Falls back to `GCP_SERVICE_ACCOUNT`. |
| `GCP_PACKER_MACHINE_TYPE` | variable | no | Builder machine type. Default `e2-standard-2`. |
| `GCP_PACKER_USE_INTERNAL_IP` | variable | no | `true` builds without an external IP (requires IAP `35.235.240.0/20` to the builder). Default `false`. |
| `GCP_VALIDATE_MACHINE_TYPE` | variable | no | Machine type for the `packer-gcp-validate.yml` disposable validation VM. Default `e2-standard-4`. |
| `GCP_GDC_VM_IMAGE_BUCKET` | variable | for export | GCS bucket the built image is exported into as a `gs://` qcow2 for the GDC VM Runtime (Terraform output `gdc_vm_image_bucket`). The export step fails loud if unset. See `docs/architecture/gcp-guest-images.md`. |
| `GCP_POLARIS_STACK_BUCKET` | variable | polaris-vm | GCS bucket holding the Polaris compose-stack tarball (`<bucket>/polaris/stack/polaris-stack.tar.gz`). The `polaris-vm` build's `host-setup.sh` fetches it and `docker compose build`s the stack into the image. **Required for a promotable `polaris-vm`:** the build fails if the stack is absent. The packer builder SA needs `roles/storage.objectViewer` on the bucket. See "Baking the polaris-vm host image" in `docs/dev/gcp-range-cell-deploy.md`. |
| `GCP_POLARIS_STACK_SHA256` | variable | polaris-vm | Required sha256 digest of the compose-stack tarball; the `polaris-vm` build verifies the fetched tarball and fails on mismatch, so a mutable GCS key cannot change what is baked. |
| `GCP_POLARIS_STACK_GENERATION` | variable | no | Optional GCS object generation to pin the exact immutable tarball version (`gs://bucket/key#generation`). |
| `GCP_DEV_PROJECT_ID` | secret | for promote | Source (dev) project for `packer-gcp-promote.yml`; the prod project is the `prod` environment's `GCP_PROJECT_ID`. |

Images are published to the image family `shifter-<type>` (the version pointer;
there is no SSM equivalent). A built dev image must pass the
`packer-gcp-validate.yml` candidate-boot gate (which labels it
`validated=passed`) before `packer-gcp-promote.yml` will copy that exact image to
prod. For Windows/DC, the workflow generates a throwaway `winrm_bootstrap_password`
per run and injects it via `PKR_VAR_*`; the pre-promoted `dc-prebaked` build also
generates a per-run DSRM password (`PKR_VAR_dc_dsrm_password`). Nothing is
committed.

## AWS portal (`dev` / `prod`)

Consumed by `.github/workflows/_shifter-platform.yml`. The committed
`platform/terraform/environments/<env>/portal/terraform.tfvars` is an
`example.com` baseline. The workflow's `Render local.auto.tfvars from
deployment secret` step, present in both the `plan` and `apply` jobs,
writes the real per-deployment values into a gitignored
`local.auto.tfvars` before Terraform runs, so deploys never plan or apply
against the baseline. The step picks the secret by environment and fails
loud (`::error::`) when the active environment's secret is empty.

| Name | Kind | Required | Notes |
|---|---|---|---|
| `AWS_ROLE_ARN_DEV` / `AWS_ROLE_ARN` | secret | yes | OIDC role assumed by the deploy job. |
| `TF_VARS_DEV_PORTAL` | secret | yes (dev) | Whole-file `local.auto.tfvars` payload for the dev portal root, rendered verbatim over the committed baseline before `terraform plan` / `apply`. |
| `TF_VARS_PROD_PORTAL` | secret | yes (prod) | As above, for the prod portal root. |

The `TF_VARS_<ENV>_PORTAL` secret holds plain Terraform HCL, the same
content you would put in a `local.auto.tfvars`. At minimum it must set the
values the `example.com` baseline deliberately leaves non-operational:

- `domain_name`, `ses_domain`, `ctfd_domain`, `ctf_from_email`
- `alarm_email`
- `allowed_email_domains` (deliberately empty in the baseline, fails
  closed)
- `ctfd_ssh_public_key`, `ctfd_ssh_allowed_cidrs` (empty in baseline,
  CTFd SSH ingress closed)
- `user_storage_bucket` and any other AWS-account-suffixed bucket names
  that vary per environment

For AWS local deploys, write the same HCL to a gitignored
`local.auto.tfvars` next to the environment's `terraform.tfvars` and run
`terraform apply` from a workstation that has the target role (see
**Local development** below).

## AWS core (`dev` / `proof` / `prod`)

Consumed by `.github/workflows/_core.yml`. The committed
`platform/terraform/environments/<env>/main.tf` defines shared ECR repos and
S3 budget alerts. Budget notification recipients are deployment-owned: the
workflow's `Render local.auto.tfvars from deployment secret` step writes
`budget_alert_email` into a gitignored `local.auto.tfvars` before Terraform
runs. The step picks the secret by environment and fails loud (`::error::`) when
the active environment's secret is empty.

| Name | Kind | Required | Notes |
|---|---|---|---|
| `TF_VARS_DEV_CORE` | secret | yes (dev) | Whole-file `local.auto.tfvars` payload for the dev core root. Must set `budget_alert_email` to a real operations address. |
| `TF_VARS_PROOF_CORE` | secret | yes (proof) | As above, for the proof core root. |
| `TF_VARS_PROD_CORE` | secret | yes (prod) | As above, for the prod core root. |

See `platform/terraform/environments/<env>/local.auto.tfvars.example` for the
minimum HCL shape.

### Fresh AWS account bootstrap order

Standup runbooks for the phases referenced below:

- Runner provisioning: [`aws-runner-provisioning-runbook.md`](aws-runner-provisioning-runbook.md)
- Range AMI seeding: [`aws-ami-seeding-runbook.md`](aws-ami-seeding-runbook.md)
- Terraform apply order: [`aws-terraform-apply-order.md`](aws-terraform-apply-order.md)
- Tearing an environment down: [`aws-teardown-runbook.md`](aws-teardown-runbook.md)

For a new AWS account, bootstrap the backend and CI identity before trying
run an AWS dev deploy (`gh workflow run deploy.yml --ref <branch> -f environment=aws-dev`):

If the account was **re-used** (a prior Shifter tenant was torn down here), first run
`./scripts/bootstrap/deploy.py account-recovery --env dev --profile <profile>` to detect
orphaned control-plane leftovers that would otherwise fail `terraform apply` one
collision at a time, and add `--sweep` to delete the owned ones. It refuses on a live
tenant and never touches data-bearing resources. See `scripts/bootstrap/README.md` and
`aws-teardown-runbook.md`. Off a TTY (CI or an automation wrapper), pass `--yes` on the
bootstrap commands below so their confirmation prompts proceed without a terminal;
`--yes` does not authorize the recovery sweep, which always needs `--sweep`.

1. Run `./scripts/bootstrap/deploy.py bootstrap --env dev --profile <profile>`.
   This creates the shared S3 state bucket, creates the GitHub OIDC role,
   sets `AWS_ROLE_ARN_DEV` and `TF_INFRA_STATE_BUCKET_DEV` (the env-suffixed
   names the dev deploy workflows read), and writes per-instance Terraform
   backend configs under `~/.shifter/<env>-<bucket>/`.
2. Run `./scripts/bootstrap/deploy.py runners --env dev --profile <profile>` to
   provision **and** auto-register the self-hosted runners (issue #1433). It
   provisions a dedicated, ADR-004-R20-compliant runner VPC by default, applies
   the runner root, and registers each runner over SSM (per-runner single-use
   token, never persisted). Pass `--use-existing-network` to reuse a
   non-default `vpc_id`/`subnet_id` (a dedicated runner VPC or the portal VPC
   private tier) or the `allow_default_vpc` opt-in instead; do not use the
   account default VPC without that opt-in, and do not commit live VPC/subnet IDs
   to tracked placeholder tfvars. AWS deploy workflows use `runs-on: self-hosted`.
3. Ensure `/shifter/ami/{kali,ubuntu,windows,dc}` exists in SSM Parameter
   Store before portal Terraform plans/applies. The Packer workflow updates
   these parameters after AMI builds; in a moved account, verify the Packer
   `dev.pkrvars.hcl` VPC/subnet values first. The Kali build also requires
   the target account to accept the free AWS Marketplace terms for product
   code `7lgvy7mt78lgoi4lant0znp5h`.
4. Review `TF_VARS_DEV_PORTAL` for account-specific values such as domain
   names, alarm email, SSH allowlists, and bucket names. Review
   `TF_VARS_DEV_RANGE` for range deployment values such as the agent S3 bucket
   and the regional PAN-OS VM-Series AMI, and set `SHIFTER_CONFIG_DEV_RANGE` to
   the deployment's `shifter.yaml` (its `settings.range_egress` is rendered into
   the range egress allowlist). Bootstrap configures the AWS role secret and
   backend files; the deploy workflows fail loud when the active portal or range
   tfvars secret, or the range `shifter.yaml`, is missing.
5. For the first deploy in a moved or fresh account, run the `Deploy` workflow
   with `gh workflow run deploy.yml --ref <branch> -f environment=aws-dev`
   (add `-f aws_first_deploy=true` for the first-ever engine deploy, before the
   platform Terraform apply has created the provisioner task definition). The
   dispatch forces the full AWS chain (Core -> Range -> Engine -> Platform).
   Deployment is always a manual dispatch; pushing to a branch runs validation
   only.

### First-run DNS validation

The first platform apply in a fresh account creates DNS-validated ACM
certificates for the portal domains and SES identities for the configured
mail domain. Publish these records in the authoritative DNS zone while the
apply is running; Terraform will continue once AWS observes the ACM records.

- ACM portal and Guacamole URL validation records are exposed by the root
  Terraform output `acm_validation_records`. They are CNAME records.
- SES domain verification uses a TXT record named `_amazonses.<ses_domain>`.
  Fetch the value with:
  `aws ses get-identity-verification-attributes --identities <ses_domain> --region <region>`.
- SES DKIM uses three CNAME records. Fetch the tokens with:
  `aws ses get-identity-dkim-attributes --identities <ses_domain> --region <region>`.
  Each token maps `<token>._domainkey.<ses_domain>` to
  `<token>.dkim.amazonses.com`.
- In Cloudflare, create ACM and DKIM CNAMEs as DNS-only records. Do not proxy
  validation CNAMEs.

### First-run DNS routing

After the first platform apply creates the portal ALB and CTFd instance,
publish the runtime DNS records:

- `domain_name` and `chat.<domain_name>` point to the Terraform output
  `alb_dns_name` as CNAME records. In Cloudflare, keep them DNS-only unless
  the deployment explicitly validates proxied Cloudflare behavior.
- `ctfd_domain` points to the Terraform output `ctfd_elastic_ip` as an A
  record. In Cloudflare, publish the record as DNS-only until the CTFd host
  has completed certbot and `https://<ctfd_domain>/login` works against the
  origin. After that validation, the CTFd `A` record may be switched to
  proxied with SSL/TLS mode `Full (strict)`. The DNS target is the bare
  Elastic IP address, never an `http://` or `https://` URL. Cloudflare
  challenge actions must be disabled or explicitly skipped for the CTFd
  hostname before event smoke testing; the CTFd sync scripts and automated
  checks expect the CTFd app to answer directly instead of a Cloudflare
  `cf-mitigated: challenge` page.

ALB access logs use a dedicated S3 bucket with SSE-S3 because Elastic Load
Balancing does not support SSE-KMS for Application Load Balancer access-log
delivery. Central Firehose log archives continue to use the log-aggregation
customer-managed KMS key.

### First-run private AWS API reachability

The portal VPC creates private AWS service endpoints for the runtime services
that must be reachable before application containers can start: ECR, S3,
CloudWatch Logs, Secrets Manager, SSM, STS/KMS, ECS/EC2/ELB, SNS, SQS, and
DynamoDB. These endpoints are part of the expected fresh-account platform
shape. They keep EC2 user_data, Docker image pulls, ECS secret resolution, and
awslogs setup from depending on the portal inspection firewall/NAT egress path
during first deploy. The portal EC2 user_data also retries the AL2023 package
metadata/install step so a transient repository timeout does not permanently
strand cloud-init.

Range status propagation depends on the portal worker containers consuming the
encrypted portal messaging SQS queues. If range provisioner tasks exit 0 but
CMS or CTF rows remain `pending`, check `docker logs worker-cms` on the portal
EC2 instance. `KMS.AccessDeniedException` on the portal messaging CMK means the
portal EC2 role is missing the SQS KMS decrypt/data-key grant; the
`portal/ec2` module must receive `module.messaging.kms_key_arn` and attach its
`sqs-kms-access` policy.

When portal inspection is enabled, ALB health checks and user traffic route
through the inspection boundary before reaching the private portal and
Guacamole targets. The targets therefore allow ingress both from the ALB
security group and from the portal public subnet CIDRs; the CIDR rule is still
VPC-local and is required for the routed middlebox path.

`enable_portal_inspection` defaults to `false` in the committed
`platform/terraform/environments/<env>/portal/terraform.tfvars` (#932). A deploy
that wants inspection sets `enable_portal_inspection = true` in its
`TF_VARS_<ENV>_PORTAL` secret payload (rendered as `local.auto.tfvars`, which
overrides the committed baseline). Enabling it removes the direct private → NAT
default route, so the portal apply job runs
`scripts/assert_portal_inspection/assert_portal_inspection.py` after
`terraform apply`: it fails the deploy if the live route tables do not point at
healthy per-AZ Network Firewall endpoints, instead of silently blackholing
egress. The assertion is a no-op when inspection is off.

### Post-deploy smoke secrets (dev)

The dev `post-deploy-smoke` job in `.github/workflows/_shifter-platform.yml`
runs `scripts/smoke-test.sh`, which provisions a minimal range as a smoke user,
verifies guest connectivity, and tears it down. It runs only for dev applies and
is `continue-on-error`, so a smoke failure does not fail the deploy; instead the
job opens a `[smoke-test]` bug issue (labels `bug`, `smoke-test`).

The smoke validates the **platform**, not scenario content: its ranges are built
entirely from base range AMIs (`smoke_linux` = Kali + Ubuntu, `smoke_windows` =
Kali + plain Windows, all `xdr_agent: false`), so it requires **no XDR agent and
no `SMOKE_*_AGENT_ID` secrets** (#1422). XDR/agent install is scenario content
and is exercised by real scenarios, not the smoke. Only one secret is needed,
set manually (not written by bootstrap or `sync-deploy-secrets.sh`):

| Name | Kind | Required | Notes |
|---|---|---|---|
| `SMOKE_TEST_USER_EMAIL` | secret | yes (dev smoke) | Email of the portal user the smoke provisions as. If the user does not exist yet it is created on first run. When unset, the smoke step fails loud before doing any work. |

## AWS range (`dev` / `prod`)

Consumed by `.github/workflows/_range.yml`. The committed
`platform/terraform/environments/<env>/range/terraform.tfvars` is an
account-neutral baseline. The workflow's `Render local.auto.tfvars from
deployment secret` step is present in both the `plan` and `apply` jobs; it
selects the active environment strictly from `inputs.is_dev`, writes the
matching whole-file secret into `local.auto.tfvars`, and fails loud
(`::error::`) when the active secret is empty.

| Name | Kind | Required | Notes |
|---|---|---|---|
| `TF_VARS_DEV_RANGE` | secret | yes (dev) | Whole-file `local.auto.tfvars` payload for the dev range root, rendered verbatim over the committed baseline before `terraform plan` / `apply`. Carries only the non-egress overrides below, **not** `victim_allowed_cidrs`. |
| `TF_VARS_PROD_RANGE` | secret | yes (prod) | As above, for the prod range root. |
| `SHIFTER_CONFIG_DEV_RANGE` | secret | yes (dev) | Full deployment `shifter.yaml` (root installation config) for dev. The workflow renders its `settings.range_egress` into `victim_allowed_cidrs.auto.tfvars` before `terraform plan` / `apply`, so the egress allowlist is sourced once from `shifter.yaml` (#1015). |
| `SHIFTER_CONFIG_PROD_RANGE` | secret | yes (prod) | As above, for the prod range. |

`.github/workflows/deploy.yml` also forwards `TF_VARS_PROOF_RANGE` and
`SHIFTER_CONFIG_PROOF_RANGE` for a proof range deploy, but
`scripts/sync-deploy-secrets.sh` has no proof-range record in its
`KNOWN_RECORDS`, so a proof range standup must set those two secrets by hand (or
add the records to the script first). Dev and prod range secrets are covered by
the sync script.

At minimum, each `TF_VARS_<ENV>_RANGE` payload must set the deployment-specific
values stripped from the committed baseline:

- `agent_s3_bucket`: the account-specific user-storage bucket read by range
  instance roles
- `vm_series_ami_id`: the regional PAN-OS Marketplace AMI to use. This is
  deployment configuration, not a credential; keep it in the overlay so the
  shared repo does not prescribe a marketplace version/region for every
  deployment.

The range egress allowlist (`victim_allowed_cidrs`) is **not** part of
`TF_VARS_<ENV>_RANGE`. The workflow's `Render range egress allowlist from
shifter.yaml` step (in both the `plan` and `apply` jobs) writes
`SHIFTER_CONFIG_<ENV>_RANGE` to an ephemeral file and runs `shifter-config
render` to generate `victim_allowed_cidrs.auto.tfvars`, so the configured policy
and the deployed firewall cannot drift (#958 / #1015). Putting
`victim_allowed_cidrs` in `TF_VARS_<ENV>_RANGE` re-creates that drift; keep it
out of the whole-file secret.

Local operators use the same model: write those values to a gitignored
`local.auto.tfvars` alongside the range `terraform.tfvars`. In this repo's
worktree workflow, `scripts/setup-worktree.sh` symlinks existing
`local.auto.tfvars` overlays from the main checkout into worktrees so local
plans do not lose the per-account values when branches change.

The committed `terraform.tfvars` also ships an empty `victim_allowed_cidrs`
baseline so the repo never carries a deployment's allowlist (PLAT-220 / #775).
This completes the `_core.yml` / `_range.yml` deploy-tfvars audit from #784:
the AWS core tfvars remain generic repository-name defaults, while account-bound
and deployment-specific range values are supplied by secret or local overlay.

For the PLAT-220 range egress allowlist:

| File                                                                                  | Status                                                |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------- |
| `platform/terraform/environments/{dev,prod}/range/terraform.tfvars`                  | committed; empty `victim_allowed_cidrs` baseline      |
| `platform/terraform/environments/{dev,prod}/range/local.auto.tfvars.example`         | committed; shape reference                            |
| `platform/terraform/environments/{dev,prod}/range/local.auto.tfvars`                 | gitignored; operator's non-egress account overrides (NOT `victim_allowed_cidrs`) |
| `platform/terraform/environments/{dev,prod}/range/victim_allowed_cidrs.auto.tfvars`  | gitignored; rendered by `shifter-config render` (CI: from `SHIFTER_CONFIG_<ENV>_RANGE`; local: from your `shifter.yaml`) |

Source for the PANW Cortex XSIAM/XDR allowlist:
<https://docs-cortex.paloaltonetworks.com/r/Cortex-XSIAM/Cortex-XSIAM-Administrator-Guide/Resources-Required-to-Enable-Access>.

See `docs/architecture/range-egress-ip-allowlist.md` for the full mapping
between `shifter.yaml.settings.range_egress` and the Terraform inputs.

## GCP range (`gcp-dev`)

The GCP range network egress allowlist is rendered from the deployment's
`shifter.yaml` into a dedicated `range_egress.auto.tfvars`, separate from the
`gcp-dev` `local.auto.tfvars` (which carries project / hostname / identity /
control-plane inputs). Two Terraform variables expose the platform contract:

| Variable                       | Type           | Meaning                                                                          |
| ------------------------------ | -------------- | -------------------------------------------------------------------------------- |
| `range_egress_mode`            | `string`       | One of `status-quo` (default), `deny-all`, `allowlist`                           |
| `range_egress_allowed_cidrs`   | `list(string)` | CIDR allowlist when `range_egress_mode = "allowlist"`                            |

The committed `terraform.tfvars` baseline sets `range_egress_mode =
"status-quo"`. Deployments that want enforcement set
`settings.range_egress` in `shifter.yaml`; the deploy renders it into
`range_egress.auto.tfvars` (gitignored), which Terraform auto-loads alongside
the baseline.

| Name | Kind | Required | Notes |
|---|---|---|---|
| `SHIFTER_CONFIG_GCP_DEV` | secret | yes | Full deployment `shifter.yaml` (root installation config) for `gcp-dev`. The `_gcp-dev.yml` `Render range egress allowlist from shifter.yaml` step writes it to an ephemeral file and runs `shifter-config render` to generate `${TF_DIR}/range_egress.auto.tfvars` before `terraform apply`; the step fails loud when the secret is empty. |

- **CI (`_gcp-dev.yml`)** renders `range_egress.auto.tfvars` from
  `SHIFTER_CONFIG_GCP_DEV`.
- **`scripts/bootstrap/deploy.py gdc-bootstrap`** renders the same file from
  the resolved `shifter.yaml` (`--shifter-config` → `$SHIFTER_CONFIG` →
  repo-root `shifter.yaml`) before the control-plane apply, failing loud if no
  root config is found.
- **Local `terraform` runs** use the operator workflow in
  `docs/architecture/range-egress-ip-allowlist.md` (run `shifter-config render`
  by hand, then `terraform apply`).

`shifter.yaml` holds secret *references*, not values, but it is the
deployment's authoritative config; carry it as a GitHub secret so CI does not
read a second, drift-prone copy of the allowlist. Do **not** also set
`range_egress_mode` / `range_egress_allowed_cidrs` in `local.auto.tfvars`;
that re-introduces the drift this flow removes.

### GCE range-cell backend variables

The GCP range backend defaults to `gce` (GCE range cells). These non-secret
inputs are GitHub Actions repository or environment **variables** (`vars.*`),
exported by the `_gcp-dev.yml` `Render generated runtime env` step into the
generated runtime config. Each account sets its own values; unset variables
fall back to the code defaults in `config.py`. See
`docs/dev/gcp-range-cell-deploy.md` for the operator runbook.

| Variable | Required | Notes |
|---|---|---|
| `GCP_RANGE_BACKEND` | no | `gce` (default) or `gdc`. Set `gdc` to roll back to GDC VM Runtime. |
| `GCP_RANGE_CELL_PROJECT_ID` | no | Project the range cells provision into. Defaults to the project parsed from the range VPC self-link (`range_network_id`), so it is correct even while the control-plane `GCP_PROJECT_ID` is a deploy-overlay placeholder. |
| `RANGE_NETWORK_ZONE` | yes | Compute Engine zone for range guests, for example `us-central1-a`. |
| `GCP_RANGE_LINUX_IMAGE` | yes | Full image or family URL for the Linux/host profile. For a Polaris deployment this is the `shifter-polaris-vm` family (the Docker host). |
| `GCP_RANGE_DC_IMAGE` | yes | Windows domain-controller image, pre-promoted at bake time. Baked per-domain from `dc-prebaked.pkr.hcl` into family `shifter-<purpose>-dc` (see "Baking a new pre-promoted DC image" in `docs/dev/gcp-range-cell-deploy.md`). For Polaris this is `shifter-polaris-dc` (BOREAS.LOCAL). |
| `DC_DOMAIN_PASSWORD` | DC scenarios | **Sensitive.** Domain Administrator password the provisioner sets on the pre-promoted DC (`set_admin_password`). Must match the password baked into the DC image by `a2_setup.ps1` at bake time (its `-AdminPassword` default). Provide via the GCP deploy config secret so it is rendered into the runtime env and forwarded to the provisioner job (`_GCP_PROVISIONER_ENV_KEYS`); if unset, DC setup fails setting the admin password. |
| `GCP_RANGE_KALI_IMAGE` | scenario | Kali image for non-Polaris scenarios (Polaris runs Kali as a container inside the host). |
| `GCP_RANGE_WINDOWS_IMAGE` | scenario | Generic Windows guest image for non-Polaris scenarios. |
| `GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL` | yes | Service account attached to range guests. Minimal scope: logging and monitoring write. |
| `GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL` | Polaris | Service account whose per-range key the a14-kali agent uses for Vertex AI. Leave empty to disable per-range Vertex credentials. |
| `GCP_RANGE_VERTEX_PROJECT_ID` | no | Vertex project. Defaults to `GCP_RANGE_CELL_PROJECT_ID`, then the control-plane project. |
| `GCP_RANGE_PRIVATE_GOOGLE_ACCESS` | no | Set `true` so no-external-IP guests reach Vertex AI and Cloud Storage over Private Google Access. |

The host and Vertex service accounts are **independent** inputs. Accounts that
require it may point both at the same service account; the render and the
provisioner never assume they differ.

## Local development

For local `terraform plan` / `terraform apply` against your own cloud
account:

```sh
# AWS dev portal
cat > platform/terraform/environments/dev/portal/local.auto.tfvars <<EOF
domain_name           = "shifter.your-domain.example"
ses_domain            = "your-domain.example"
ctfd_domain           = "ctf.shifter.your-domain.example"
alarm_email           = "your-team-alerts@your-domain.example"
allowed_email_domains = ["your-domain.example"]
user_storage_bucket   = "shifter-dev-user-storage-<your-account-id>"
EOF

cd platform/terraform/environments/dev/portal
terraform init -backend-config=dev.s3.tfbackend
terraform plan
```

```sh
# AWS dev range
cat > platform/terraform/environments/dev/range/local.auto.tfvars <<EOF
agent_s3_bucket = "shifter-dev-user-storage-<your-account-id>"
vm_series_ami_id = "ami-xxxxxxxxxxxxxxxxx"
victim_allowed_cidrs = [
  "<your-required-egress-cidr>/32",
]
EOF

cd platform/terraform/environments/dev/range
terraform init -backend-config=dev.s3.tfbackend
terraform plan
```

For event-sized AWS dev runs, put the full capacity overlay in
`TF_VARS_DEV_PORTAL`. The deploy workflow reads `terraform output -json` from
the applied portal state and derives its single-instance vs. ASG path from the
Terraform `enable_autoscaling` output; there is no separate GitHub variable to
keep in sync. The committed `terraform.tfvars` is a modest OSS default, while
the secret payload below is the event-sized overlay for ASG, warm pool, Redis
channel layer, and larger Guacamole/Postgres capacity:

```hcl
enable_autoscaling     = true
asg_min_size           = 2
asg_max_size           = 8
asg_desired_capacity   = 2
asg_warm_pool_min_size = 2
asg_warm_pool_state    = "Stopped"
enable_redis           = true

db_instance_class        = "db.m6i.xlarge"
db_allocated_storage     = 100
db_max_allocated_storage = 500
db_backup_retention_days = 7

redis_node_type = "cache.m6g.xlarge"

guacd_cpu                      = 2048
guacd_memory                   = 4096
guacamole_client_cpu           = 2048
guacamole_client_memory        = 4096
guacd_desired_count            = 6
guacamole_client_desired_count = 4

guacamole_db_instance_class        = "db.m6i.xlarge"
guacamole_db_allocated_storage     = 100
guacamole_db_max_allocated_storage = 500
guacamole_db_multi_az              = true

guacamole_enable_autoscaling       = true
guacamole_autoscaling_min_capacity = 4
guacamole_autoscaling_max_capacity = 10
guacamole_autoscaling_cpu_target   = 60
```

> **Keep the dev overlay minimal unless an event needs it.**
> `TF_VARS_DEV_PORTAL` is the *only* place the running dev fleet size is set:
> the committed `terraform.tfvars` is a fail-loud baseline that this secret
> always overrides. Nothing reconciles it automatically; edit your local
> overlay and push it with `scripts/sync-deploy-secrets.sh` (see [Populating
> and syncing the secrets](#populating-and-syncing-the-secrets)). The overlay
> above is *event-sized*. Left in place between events it makes every
> deploy run a full multi-instance ASG instance refresh (desired + warm pool ≈
> a dozen instances, roughly an hour) and holds prod-class RDS/Redis/Guacamole
> capacity. For ordinary dev, keep the ASG at a single instance with a minimal
> warm pool and shrink the DB/Redis/Guacamole lines to match:
>
> ```hcl
> asg_min_size           = 1
> asg_max_size           = 2
> asg_desired_capacity   = 1
> asg_warm_pool_min_size = 1
> ```
>
> Apply the event-sized overlay only for the duration of an event, then revert.

```sh
# GCP gcp-dev
cat > platform/terraform/gcp/environments/gcp-dev/local.auto.tfvars <<EOF
project_id                    = "your-gcp-project-id"
public_hostname               = "shifter.your-domain.example"
identity_allowed_email_domain = "your-domain.example"
gke_master_authorized_cidrs   = ["<your-workstation-egress>/32"]
EOF

cd platform/terraform/gcp/environments/gcp-dev
terraform init -backend=false
terraform plan
```

`local.auto.tfvars` is gitignored; never commit one.

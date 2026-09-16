# AWS Terraform apply order

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

This is the authoritative order for applying the AWS Terraform stacks on a fresh
account, the backend state key each stack uses, and the values you must override
before the first apply. Follow it top to bottom. The CI Deploy workflow applies
the same stacks in the same order; this doc lets an operator reproduce a first
apply by hand and understand what CI does.

For the secrets and repository variables that back these values, see
[`deploy-secrets.md`](deploy-secrets.md). For range AMIs, see
[`aws-ami-seeding-runbook.md`](aws-ami-seeding-runbook.md). To tear an account
down, see [`aws-teardown-runbook.md`](aws-teardown-runbook.md).

## Prerequisites

Before any stack applies, these must already exist:

1. **Bootstrap has run** for the environment
   (`scripts/bootstrap/deploy.py bootstrap --env <env> --profile <profile>`),
   creating the S3 state bucket, the GitHub OIDC provider, the deploy IAM role,
   and the per-instance backend config files under `~/.shifter/<env>-<bucket>/`.
2. **Self-hosted runners are provisioned and registered** if you deploy through
   CI (all AWS deploy jobs use `runs-on: self-hosted`). Run
   `scripts/bootstrap/deploy.py runners --env <env> --profile <profile>` to
   provision + auto-register them (issue #1433). See
   [`aws-runner-provisioning-runbook.md`](aws-runner-provisioning-runbook.md).
3. **Range AMIs are built and the `/shifter/ami/{kali,ubuntu,windows,dc}` SSM
   parameters are seeded.** The Portal stack reads these as data sources and its
   plan fails if any is missing. See
   [`aws-ami-seeding-runbook.md`](aws-ami-seeding-runbook.md).
4. **The engine provisioner image is built** (CI `_shifter-engine.yml`) so the
   Portal stack can resolve its engine image digest. Locally, the digest comes
   from the same ECR repo the engine build pushes to.

Terraform version: the stacks require `>= 1.5.0` with the `hashicorp/aws`
provider `~> 6.0`; CI pins Terraform `1.13.3`.

## Stacks, order, and state keys

Apply in this order. Each stack initializes against the shared state bucket with
its own `-backend-config=<env>.s3.tfbackend` (all use `region = us-east-2`,
`encrypt = true`, `use_lockfile = true`). Replace the placeholder bucket in the
tfbackend with the bootstrap-created state bucket, or use the rendered config
under `~/.shifter/<env>-<bucket>/`.

| Order | Stack | Directory | State key |
|---|---|---|---|
| 1 | Core | `platform/terraform/environments/<env>/` | `shifter/<env>/terraform.tfstate` |
| 2 | Range | `platform/terraform/environments/<env>/range/` | `<env>/range/terraform.tfstate` |
| 3 | Engine image | (no Terraform stack) | built by `_shifter-engine.yml` into ECR |
| 4 | Portal | `platform/terraform/environments/<env>/portal/` | `<env>/portal/terraform.tfstate` |

Only the Core key carries the `shifter/` prefix. The Portal stack reads the Core
state (`shifter/<env>/terraform.tfstate`) and the Range state
(`<env>/range/terraform.tfstate`) as remote-state data sources, so these keys
must match exactly.

There is no separate `engine` Terraform stack: the engine provisioner is an ECS
task defined by the `engine-provisioner` module consumed inside the Portal
stack. Its container image is built and pushed by the `_shifter-engine.yml`
reusable workflow before the Portal deploy, which is why "Engine" appears in the
CI chain (`Core -> Range -> Engine -> Portal`) even though it applies no
Terraform of its own.

## Per-stack first-apply overrides

The committed `terraform.tfvars` files are an `example.com` baseline that is
intentionally non-operational where a real account value is required. Supply the
real values in a gitignored `local.auto.tfvars` next to each stack's
`terraform.tfvars` (local), or via the `TF_VARS_<ENV>_*` secrets that CI renders
into `local.auto.tfvars` (see [`deploy-secrets.md`](deploy-secrets.md)).

### Core (`environments/<env>/`)

- `budget_alert_email`: real operations address for the S3 budget alert. See
  `local.auto.tfvars.example` in the stack directory.

### Range (`environments/<env>/range/`)

- `agent_s3_bucket`: the account-specific user-storage bucket range instance
  roles read (baseline placeholder `REPLACE_AGENT_S3_BUCKET`).
- `vm_series_ami_id`: the regional PAN-OS VM-Series Marketplace AMI (baseline
  placeholder `REPLACE_VM_SERIES_AMI_ID`).
- `victim_allowed_cidrs`: not set here. It is rendered into
  `victim_allowed_cidrs.auto.tfvars` from the deployment's `shifter.yaml`
  (`settings.range_egress`) by `shifter-config render`. Keep it out of the
  whole-file range secret. See
  [`../architecture/range-egress-ip-allowlist.md`](../architecture/range-egress-ip-allowlist.md).

### Portal (`environments/<env>/portal/`)

- `domain_name`, `ses_domain`, `ctfd_domain`, `ctf_from_email`: real DNS and
  mail identities (baseline is `example.com`).
- `alarm_email`: real operations address.
- `allowed_email_domains`: sign-up allow-list. Empty in the baseline, which
  fails closed (no one can self-register).
- `cognito_domain_prefix`: must be globally unique across AWS Cognito.
- `user_storage_bucket`: account-suffixed bucket name (baseline placeholder
  `shifter-<env>-user-storage-REPLACE_WITH_ACCOUNT_ID`).
- `ctfd_ssh_public_key`, `ctfd_ssh_allowed_cidrs`: empty in the baseline, which
  leaves CTFd SSH ingress closed. Set both to enable it.
- `enable_portal_inspection`: `false` in the baseline. Set `true` to route ALB
  and portal traffic through the inspection firewall (the apply then asserts the
  routed path is healthy).

The Portal stack also depends on the `/shifter/ami/*` SSM parameters and the
engine image digest existing before plan; both come from the prerequisites
above.

> **First-boot image ordering (retained ASG path).** On a fresh account the
> portal `image-tag` parameter defaults to `latest`, but no `latest` image
> exists in ECR yet, so ASG instances that boot before a real portal image is
> published fail bootstrap (`manifest unknown`) and the instance refresh then
> stalls on never-healthy targets. Build and push a portal image, and set the
> `/shifter/<env>/portal/image-tag` (and `image-digest` for digest-pinned
> deploys) parameters to that real image before the fleet is expected to be
> healthy; if instances already bootstrap-failed, run
> `scripts/portal-deploy/deploy_portal.sh` against them (or replace them) once
> the image and pointers exist, before starting the instance refresh. The
> active EKS portal path is digest-first and unaffected. See
> [`../architecture/aws-portal-first-image-ordering-preflight-1030.md`](../architecture/aws-portal-first-image-ordering-preflight-1030.md).

## Applying

Local, per stack (repeat for Core, then Range, then Portal):

```bash
cd platform/terraform/environments/<env>/<stack>
terraform init -backend-config=<env>.s3.tfbackend
terraform plan
terraform apply
```

`scripts/bootstrap/deploy.py terraform --env <env> --profile <profile>` runs the
same `core -> range -> portal` order and captures the Portal remote-state
tfvars. Never apply prod locally; use the Deploy workflow.

The first Portal apply blocks on DNS-validated ACM certificates and SES
identities. Publish the validation records while the apply is waiting, as
described in the first-run DNS validation section of
[`deploy-secrets.md`](deploy-secrets.md).

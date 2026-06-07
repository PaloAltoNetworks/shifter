# Deploy secrets and repository variables

The committed `terraform.tfvars` files in `platform/terraform/.../portal/`
and `platform/terraform/gcp/environments/...` ship an `example.com`
baseline that's intentionally broken-on-deploy. Each environment provides
its real deployment values via GitHub secrets and repository variables;
the deploy workflows write them into a gitignored `local.auto.tfvars`
that Terraform auto-loads alongside the baseline (the `.local`/`.auto`
overrides win).

This file lists values that must be configured before a fresh deploy. Set values
under **Settings → Secrets and variables → Actions**, separated by:

- **Secrets** — sensitive (project IDs, public keys with identifying
  comments, alarm email addresses, allow-list domains for self-signup,
  CIDR blocks for operator access).
- **Variables** — non-sensitive deployment parameters (region selection,
  feature flags).

Required values are enforced by the workflow preflight step.

## GCP (gcp-dev)

Consumed by `.github/workflows/_gcp-dev.yml`.

| Name | Kind | Required | Notes |
|---|---|---|---|
| `GCP_PROJECT_ID` | secret | yes | The Google Cloud project the platform deploys to. |
| `GCP_REGION` | variable | no | Default `us-central1`. |
| `GCP_PUBLIC_HOSTNAME` | secret | yes | DNS name the platform serves on (e.g., `shifter.your-domain.example`). |
| `GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN` | secret | yes | Identity Platform beforeCreate allow-list; the bootstrap operator must end with `@<this>` for sign-in to succeed. |
| `GCP_MASTER_AUTHORIZED_CIDRS` | secret | no | HCL list literal — e.g. `["1.2.3.4/32"]`. Empty (`[]`) locks the GKE control-plane to private endpoints only. |
| `GCP_SERVICE_ACCOUNT` | secret | yes | Workload-identity-federation service account for deploy. |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | secret | yes | Workload identity provider resource id. |
| `GCP_BOOTSTRAP_ADMIN_EMAIL` | secret | no | If set, bootstrap creates this user as the first Identity Platform operator and elevates them in Django. Must match `GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN`. |
| `GCP_BOOTSTRAP_ADMIN_PASSWORD` | secret | no | Initial password for the bootstrap operator (rotated by TOTP enrollment on first sign-in). |
| `PLATFORM_BOOTSTRAP_STAFF_EMAILS` | secret | no | Comma-separated list of emails elevated to Django `is_staff` on first sign-in. |
| `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` | secret | no | Comma-separated list of emails elevated to `is_superuser`. |

For local GCP bootstrap, `scripts/bootstrap/deploy.py` validates the bootstrap
operator email against the Terraform output `identity_allowed_email_domain`.
When Terraform outputs are not available yet, it uses
`SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN` from the process environment.

## AWS portal (`dev` / `prod`)

Consumed by `.github/workflows/_shifter-platform.yml`. The committed
`platform/terraform/environments/<env>/portal/terraform.tfvars` is an
`example.com` baseline. The workflow's `Render local.auto.tfvars from
deployment secret` step — present in both the `plan` and `apply` jobs —
writes the real per-deployment values into a gitignored
`local.auto.tfvars` before Terraform runs, so deploys never plan or apply
against the baseline. The step picks the secret by environment and fails
loud (`::error::`) when the active environment's secret is empty.

| Name | Kind | Required | Notes |
|---|---|---|---|
| `AWS_ROLE_ARN_DEV` / `AWS_ROLE_ARN` | secret | yes | OIDC role assumed by the deploy job. |
| `TF_VARS_DEV_PORTAL` | secret | yes (dev) | Whole-file `local.auto.tfvars` payload for the dev portal root, rendered verbatim over the committed baseline before `terraform plan` / `apply`. |
| `TF_VARS_PROD_PORTAL` | secret | yes (prod) | As above, for the prod portal root. |
| `AWS_PORTAL_ENABLE_AUTOSCALING` | variable | no | Default `false`. Enables ASG scaling steps in the deploy job. |

The `TF_VARS_<ENV>_PORTAL` secret holds plain Terraform HCL — the same
content you would put in a `local.auto.tfvars`. At minimum it must set the
values the `example.com` baseline deliberately leaves non-operational:

- `domain_name`, `ses_domain`, `ctfd_domain`, `ctf_from_email`
- `alarm_email`
- `allowed_email_domains` (deliberately empty in the baseline — fails
  closed)
- `ctfd_ssh_public_key`, `ctfd_ssh_allowed_cidrs` (empty in baseline —
  CTFd SSH ingress closed)
- `user_storage_bucket` and any other AWS-account-suffixed bucket names
  that vary per environment

For AWS local deploys, write the same HCL to a gitignored
`local.auto.tfvars` next to the environment's `terraform.tfvars` and run
`terraform apply` from a workstation that has the target role (see
**Local development** below).

### Fresh AWS account bootstrap order

For a new AWS account, bootstrap the backend and CI identity before trying
to use the `aws-dev` deploy branch:

1. Run `./scripts/bootstrap/deploy.py bootstrap --env dev --profile <profile>`.
   This creates the shared S3 state bucket, creates the GitHub OIDC role,
   updates `AWS_ROLE_ARN_DEV`, and rewrites the dev `.s3.tfbackend` files.
2. Update `platform/terraform/global/github-runner/dev.tfvars` with the
   target account's VPC/subnet IDs, apply the runner root, and register each
   runner with GitHub. AWS deploy workflows use `runs-on: self-hosted`.
3. Ensure `/shifter/ami/{kali,ubuntu,windows,dc}` exists in SSM Parameter
   Store before portal Terraform plans/applies. The Packer workflow updates
   these parameters after AMI builds; in a moved account, verify the Packer
   `dev.pkrvars.hcl` VPC/subnet values first.
4. Review `TF_VARS_DEV_PORTAL` for account-specific values such as domain
   names, alarm email, SSH allowlists, and bucket names.
5. Run the local Terraform deploy or refresh/push `aws-dev` only after the
   backend files and runners are in place.

## AWS range (`dev` / `prod`)

Range Terraform (under `platform/terraform/environments/<env>/range/`) is
applied locally by operators today, not by GitHub Actions, so there is no
CI secret to render — the operator writes the deployment-specific values
into a gitignored `local.auto.tfvars` alongside `terraform.tfvars`. The
committed `terraform.tfvars` ships an empty `victim_allowed_cidrs` baseline
so the repo never carries a deployment's allowlist (PLAT-220 / #775).

For the PLAT-220 range egress allowlist:

| File                                                                                  | Status                                                |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------- |
| `platform/terraform/environments/{dev,prod}/range/terraform.tfvars`                  | committed; empty `victim_allowed_cidrs` baseline      |
| `platform/terraform/environments/{dev,prod}/range/local.auto.tfvars.example`         | committed; shape reference                            |
| `platform/terraform/environments/{dev,prod}/range/local.auto.tfvars`                 | gitignored; operator writes `victim_allowed_cidrs`    |

Source for the PANW Cortex XSIAM/XDR allowlist:
<https://docs-cortex.paloaltonetworks.com/r/Cortex-XSIAM/Cortex-XSIAM-Administrator-Guide/Resources-Required-to-Enable-Access>.

See `docs/architecture/range-egress-ip-allowlist.md` for the full mapping
between `shifter.yaml.settings.range_egress` and the Terraform inputs.

## GCP range (`gcp-dev`)

The GCP range network egress allowlist piggy-backs on the existing
`gcp-dev` `local.auto.tfvars` (rendered from secrets/variables by
`.github/workflows/_gcp-dev.yml` for CI deploys, or operator-authored for
local apply). Two new Terraform variables expose the platform contract:

| Variable                       | Type           | Meaning                                                                          |
| ------------------------------ | -------------- | -------------------------------------------------------------------------------- |
| `range_egress_mode`            | `string`       | One of `status-quo` (default), `deny-all`, `allowlist`                           |
| `range_egress_allowed_cidrs`   | `list(string)` | CIDR allowlist when `range_egress_mode = "allowlist"`                            |

The committed `terraform.tfvars` baseline sets `range_egress_mode =
"status-quo"`. Deployments that want enforcement add the matching block to
`local.auto.tfvars`:

```hcl
range_egress_mode          = "allowlist"
range_egress_allowed_cidrs = [
  "203.0.113.0/24",
]
```

No additional GitHub secret is required for PLAT-220 today — the existing
`_gcp-dev.yml` "Render local.auto.tfvars from secrets/variables" step can
emit these two keys when a future repository variable adds them. CIDRs are
operator configuration, not secrets, so they may live in repository
variables; declare a GitHub secret only if your deployment classifies the
allowlist as sensitive.

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

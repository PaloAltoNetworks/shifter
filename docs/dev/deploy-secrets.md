# Deploy secrets and repository variables

The committed `terraform.tfvars` files in `platform/terraform/.../portal/`
and `platform/terraform/gcp/environments/...` ship an `example.com`
baseline that's intentionally broken-on-deploy. Each environment provides
its real deployment values via GitHub secrets and repository variables;
the deploy workflows write them into a gitignored `local.auto.tfvars`
that Terraform auto-loads alongside the baseline (the `.local`/`.auto`
overrides win).

This file is the canonical inventory of what needs to be configured before
a fresh deploy. Set values under **Settings → Secrets and variables →
Actions**, separated by:

- **Secrets** — sensitive (project IDs, public keys with identifying
  comments, alarm email addresses, allow-list domains for self-signup,
  CIDR blocks for operator access).
- **Variables** — non-sensitive deployment parameters (region selection,
  feature flags).

Required values are flagged as required by the workflow's own preflight
step; missing-secret runs fail loud with a pointer to this doc rather
than silently deploying the placeholder baseline.

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

## AWS portal (`dev` / `prod`)

Consumed by `.github/workflows/_shifter-platform.yml`. The portal stack
binds many values via `terraform.tfvars`; only those that differ between
deployers need to be supplied as secrets/variables. The remainder live
in the committed baseline (instance types, capacity defaults, alarm
thresholds, etc.).

| Name | Kind | Required | Notes |
|---|---|---|---|
| `AWS_ROLE_ARN_DEV` / `AWS_ROLE_ARN` | secret | yes | OIDC role assumed by the deploy job. |
| `AWS_PORTAL_ENABLE_AUTOSCALING` | variable | no | Default `false`. Enables ASG scaling steps in the deploy job. |

Additional values currently live in the committed `terraform.tfvars`
baseline. To override them per-deployment, drop a `local.auto.tfvars`
next to the corresponding `terraform.tfvars` and Terraform will merge
the two automatically (the `.local`/`.auto` file is in `.gitignore`).
The minimum set to override before a real deploy:

- `domain_name`, `ses_domain`, `ctfd_domain`, `ctf_from_email`
- `alarm_email`
- `allowed_email_domains` (deliberately empty in the baseline — fails
  closed)
- `ctfd_ssh_public_key`, `ctfd_ssh_allowed_cidrs` (empty in baseline —
  CTFd SSH ingress closed)
- `user_storage_bucket`
- AWS-account-suffixed bucket names that vary per environment

Future iterations of this workflow will move these into GitHub secrets
the same way the GCP path does; for now, contributors run a local
`terraform apply` (with their own `local.auto.tfvars`) from a workstation
that has the right role.

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

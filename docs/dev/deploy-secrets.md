# Deploy secrets and repository variables

The committed `terraform.tfvars` files in `platform/terraform/environments/...`
and `platform/terraform/gcp/environments/...` ship account-neutral baselines
that are intentionally broken-on-deploy where real account values are
required. Each environment provides its real deployment values via GitHub
secrets, repository variables, or a local operator overlay; deploy workflows
write them into a gitignored `local.auto.tfvars` that Terraform auto-loads
alongside the baseline (the `.local`/`.auto` overrides win).

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
   runner with GitHub. AWS deploy workflows use `runs-on: self-hosted`, and
   bootstrap does not create the runners.
3. Ensure `/shifter/ami/{kali,ubuntu,windows,dc}` exists in SSM Parameter
   Store before portal Terraform plans/applies. The Packer workflow updates
   these parameters after AMI builds; in a moved account, verify the Packer
   `dev.pkrvars.hcl` VPC/subnet values first. The Kali build also requires
   the target account to accept the free AWS Marketplace terms for product
   code `7lgvy7mt78lgoi4lant0znp5h`.
4. Review `TF_VARS_DEV_PORTAL` for account-specific values such as domain
   names, alarm email, SSH allowlists, and bucket names. Review
   `TF_VARS_DEV_RANGE` for range deployment values such as the agent S3 bucket
   and the regional PAN-OS VM-Series AMI. Bootstrap configures the AWS role
   secret and backend files; the deploy workflows fail loud when the active
   portal or range tfvars secret is missing.
5. For the first deploy in a moved or fresh account, run the `Deploy`
   workflow manually with `workflow_dispatch` on `aws-dev`. Manual dispatch
   forces the full AWS chain (Core -> Range -> Engine -> Platform). A plain
   branch push still obeys path filters, so it can skip Core or image
   publishing if the pushed commit only touched bootstrap/backend files.
   After the first full run has created the shared state and images, normal
   `aws-dev` pushes can use the filtered path.

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
| `TF_VARS_DEV_RANGE` | secret | yes (dev) | Whole-file `local.auto.tfvars` payload for the dev range root, rendered verbatim over the committed baseline before `terraform plan` / `apply`. |
| `TF_VARS_PROD_RANGE` | secret | yes (prod) | As above, for the prod range root. |

At minimum, each `TF_VARS_<ENV>_RANGE` payload must set the deployment-specific
values stripped from the committed baseline:

- `agent_s3_bucket` — the account-specific user-storage bucket read by range
  instance roles
- `vm_series_ami_id` — the regional PAN-OS Marketplace AMI to use. This is
  deployment configuration, not a credential; keep it in the overlay so the
  shared repo does not prescribe a marketplace version/region for every
  deployment.

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
| `platform/terraform/environments/{dev,prod}/range/local.auto.tfvars`                 | gitignored; operator writes account values and `victim_allowed_cidrs` |

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

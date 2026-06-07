# Bootstrap Scripts

Bootstrap automation for Shifter infrastructure.

## Features

The `deploy.py` CLI provides an interactive walkthrough for bootstrapping a bare AWS account and deploying infrastructure with intelligent automation:

**Automated Steps (with confirmation):**
- GitHub secrets configuration (via `gh` CLI)
- Per-environment `.s3.tfbackend` file updates
- Git commit and push

**Manual Steps (external systems):**
- DNS record creation (ACM validation, ALB pointing)

**AWS Bootstrap Creates:**
- S3 bucket for Terraform state (with `use_lockfile = true` S3 native locking — no DynamoDB)
- GitHub OIDC provider for keyless CI/CD
- IAM role with all required permissions. The role uses an inline
  AdministratorAccess-equivalent policy so bootstrap works in AWS
  organizations that deny `iam:AttachRolePolicy` via SCP.
- Optionally deploys Terraform infrastructure

**GDC Bootstrap Creates:**
- required GDC/GKE/GCP APIs and IAM bindings
- the custom VPC/subnet/firewall substrate for the eval cluster
- the Compute Engine admin workstation and cluster nodes
- the rendered `bmctl` cluster config and bootstrap bundle
- the hybrid GDC cluster plus VM Runtime enablement
- the inotify hardening needed to keep `macvtap-deviceplugin` stable
- admin workstation helpers for repeatable kubeconfig access
- the `shifter-gcp-dev-gdc-access` Secret Manager bundle consumed by the provisioner for GDC range-plane access

## Interactive Prompts

When automated options are available, you'll see:
```
[y/n/m]:
  y = yes (run automatically)
  n = no (abort - all steps are required)
  m = manual (show instructions and wait)
```

**Note:** All steps are mandatory for a functioning deployment. Choosing 'n' will abort the script with an explanation of why that step is required.

## Commands

## Fresh AWS Account Order

For a new AWS account, run bootstrap-only first. Do not start with `full`.
The self-hosted runner Terraform root uses the same S3 backend that
bootstrap creates, and the AWS deploy workflows cannot run until the
runners are provisioned and registered.

1. Run `bootstrap --env dev --profile <profile>` to create the shared dev
   state bucket, GitHub OIDC provider, and deploy role. Let it update
   `AWS_ROLE_ARN_DEV` and the dev `.s3.tfbackend` files.
2. Update `platform/terraform/global/github-runner/dev.tfvars` with the
   target account's VPC and subnet IDs.
3. Apply `platform/terraform/global/github-runner` and register each EC2
   runner with GitHub.
4. Seed or build the `/shifter/ami/{kali,ubuntu,windows,dc}` SSM
   parameters required by portal Terraform. The Kali build requires the target
   account to accept the free AWS Marketplace terms for product code
   `7lgvy7mt78lgoi4lant0znp5h`.
5. For the first deploy in the moved account, run the `Deploy` GitHub Actions
   workflow manually with `workflow_dispatch` on `aws-dev`. Manual dispatch
   forces the full AWS chain (Core -> Range -> Engine -> Platform). A plain
   branch push still obeys path filters, so it can skip Core or image
   publishing when the pushed commit only touched bootstrap/backend files.
   After the first full run succeeds, normal filtered `aws-dev` pushes are
   appropriate.
6. During that first platform apply, publish DNS records for ACM and SES
   validation in the authoritative DNS zone. ACM records come from the root
   Terraform output `acm_validation_records`. SES records come from
   `aws ses get-identity-verification-attributes` for the `_amazonses` TXT
   value and `aws ses get-identity-dkim-attributes` for the three DKIM CNAME
   tokens. In Cloudflare, keep ACM and DKIM CNAMEs DNS-only.
7. After platform apply creates runtime endpoints, publish routing records:
   `domain_name` and `chat.<domain_name>` CNAME to the root Terraform output
   `alb_dns_name`; `ctfd_domain` A-records to `ctfd_elastic_ip`.

### Bootstrap Only
```bash
./scripts/bootstrap/deploy.py bootstrap --env prod --profile <your-prod-profile>
```

### Terraform Only (after bootstrap)
```bash
./scripts/bootstrap/deploy.py terraform --env prod --profile <your-prod-profile>
```

### Full Deployment (bootstrap + terraform)
```bash
./scripts/bootstrap/deploy.py full --env prod --profile <your-prod-profile>
```

### Dry Run (preview without changes)
```bash
./scripts/bootstrap/deploy.py full --env prod --profile <your-prod-profile> --dry-run
```

### Bootstrap a Repeatable GDC VM Runtime Cluster
```bash
./scripts/bootstrap/deploy.py gdc-bootstrap --project-id prod-rwctxzl6shxk --cluster-id cluster1
```

This follows the official Google Distributed Cloud on Compute Engine evaluation path, but bakes in the
repo-specific fixes from the live spike:
- custom VPC/subnet instead of relying on `default`
- `multipleNetworkInterfaces: true` in the cluster config
- a deterministic `vxlan0` underlay for later shared-L2 scenario networks
- the persistent inotify sysctl fix before VM Runtime workloads are enabled

## Options

- `--env` (required): `dev` or `prod`
- `--profile` (required): AWS CLI profile name
- `--dry-run` (optional): Show what would happen without making changes
- `--project-id` (GDC only): GCP project ID, defaults to `PANW_GCP_DEV` or repo-root `.env`
- `--cluster-id` (GDC only): Cluster name / asset prefix, defaults to `cluster1`
- `--google-account-email` (GDC only): Optional Google identity to grant cluster-admin in cluster YAML

## Help

```bash
./scripts/bootstrap/deploy.py --help
./scripts/bootstrap/deploy.py bootstrap --help
./scripts/bootstrap/deploy.py terraform --help
./scripts/bootstrap/deploy.py full --help
./scripts/bootstrap/deploy.py gdc-bootstrap --help
```

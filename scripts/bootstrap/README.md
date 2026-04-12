# Bootstrap Scripts

Bootstrap automation for Shifter infrastructure.

## Features

The `deploy.py` CLI provides an interactive walkthrough for bootstrapping a bare AWS account and deploying infrastructure with intelligent automation:

**Automated Steps (with confirmation):**
- GitHub secrets configuration (via `gh` CLI)
- Backend.tf file updates
- Git commit and push

**Manual Steps (external systems):**
- DNS record creation (ACM validation, ALB pointing)

**AWS Bootstrap Creates:**
- S3 bucket for Terraform state
- DynamoDB table for state locking
- GitHub OIDC provider for keyless CI/CD
- IAM role with all required permissions
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

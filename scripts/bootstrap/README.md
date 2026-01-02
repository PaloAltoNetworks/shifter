# Bootstrap Scripts

AWS account bootstrap automation for Shifter infrastructure.

## Usage

The `deploy.py` CLI provides an interactive walkthrough for bootstrapping a bare AWS account and deploying infrastructure.

It creates:
- S3 bucket for Terraform state
- DynamoDB table for state locking
- GitHub OIDC provider for keyless CI/CD
- IAM role with all required permissions
- Optionally deploys Terraform infrastructure

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

## Options

- `--env` (required): `dev` or `prod`
- `--profile` (required): AWS CLI profile name
- `--dry-run` (optional): Show what would happen without making changes

## Help

```bash
./scripts/bootstrap/deploy.py --help
./scripts/bootstrap/deploy.py bootstrap --help
./scripts/bootstrap/deploy.py terraform --help
./scripts/bootstrap/deploy.py full --help
```

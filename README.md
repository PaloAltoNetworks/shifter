<p align="center">
  <img src="assets/logo-wide-short.png" alt="Shifter">
</p>

[![Deploy](https://github.com/Brad-Edwards/shifter/actions/workflows/deploy.yml/badge.svg)](https://github.com/Brad-Edwards/shifter/actions/workflows/deploy.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=alert_status&token=5fd0e92594a03e3defe1c85a402c9258dbfe4681)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=vulnerabilities&token=5fd0e92594a03e3defe1c85a402c9258dbfe4681)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=sqale_rating&token=5fd0e92594a03e3defe1c85a402c9258dbfe4681)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter)

# Shifter

Self-service enterprise cyber range platform. Users provision isolated attack environments with to run purple, red, and blue team scenarios with telemetry from targets to showcase XDR/XSIAM capabilities.

*Shifter IS NOT a product*. It is an internal tool to showcase XDR/XSIAM capabilities to customers. Cortex UX is intended to make the platform more user friendly and accessible to customers.

*Shifter IS NOT intended for product/stress testing any PANW products or services. Speak to Product Engineering for any such requests*.

Shifter is a compliment to existing demo environments and tools. It is not intended to replace them.

## Quick Links

| Doc | Purpose |
|-----|---------|
| [Local Setup](portal/documentation/docs/dev/local-setup.md) | Get the portal running locally |
| [Architecture](portal/documentation/docs/architecture.md) | System design and components |
| [Portal](portal/documentation/docs/portal/index.md) | Django app structure |
| [Execution Plane](portal/documentation/docs/execution/index.md) | AMIs, ranges, provisioning |

## Repo Structure

```
shifter/
├── portal/              # Django app (auth, UI, range management)
├── shifter-engine/      # Pulumi-based range provisioner (ECS task)
├── terraform/           # Infrastructure (VPCs, IAM, runners)
│   ├── environments/    # dev/, prod/ configs
│   ├── modules/         # Reusable modules
│   └── global/          # IAM, OIDC, runners
├── packer/              # AMI builds (Kali, victims)
└── scripts/             # Dev utilities
```

## Key Commands

```bash
# Portal
cd portal && uv run python manage.py runserver

# Tests
cd portal && uv run pytest
cd shifter-engine && pytest

# AMI build (triggers GitHub workflow)
./scripts/ami.sh -b kali    # Build in dev
./scripts/ami.sh -p kali    # Promote to prod

# Terraform - environment infra (CI/CD managed)
cd terraform/environments/dev/portal && terraform plan

# Terraform - global infra (manual, not in CI/CD)
./scripts/iam-deploy.sh dev   # IAM, OIDC roles
cd terraform/global/github-runner && terraform apply -var-file=dev.tfvars
```

## Git Workflow

`feature/* → dev → main`

- `main` deploys to prod
- `dev` deploys to dev
- PRs required for all merges

## Ethics

AI-driven attack capabilities exist in the wild. Defenders need realistic exposure. [Read more](portal/documentation/docs/ops/ethics.md).

## Safety

- Ranges are network-isolated
- Human oversight required for all scenarios
- All AI actions logged
- MFA-enforced authentication
- Access restricted to authorized personnel

## Disclaimer

This software is provided "as is" without warranty. The authors disclaim all liability for damages or legal consequences from use or misuse. You are responsible for legal compliance.

## License

(c) 2025 Palo Alto Networks, Inc. All rights reserved.

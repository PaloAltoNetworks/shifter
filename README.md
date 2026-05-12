<p align="center">
  <img src="assets/logo-wide-short.png" alt="Shifter">
</p>

[![Deploy](https://github.com/Brad-Edwards/shifter/actions/workflows/deploy.yml/badge.svg)](https://github.com/Brad-Edwards/shifter/actions/workflows/deploy.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=Brad-Edwards_shifter&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=Brad-Edwards_shifter)

# Shifter

Self-service agentic cyber range platform. Users provision isolated attack
environments to run purple, red, and blue team scenarios with telemetry from
targets, including XDR/XSIAM integrations.

## Summary

- [Summary](#summary)
- [CyberScript](#cyberscript)
- [Getting Started](#getting-started)
- [Prerequisites](#prerequisites)
- [Installing](#installing)
- [Usage](#usage)
- [Support](#support)
- [Deployment](#deployment)
- [Running the tests](#running-the-tests)
- [Built With](#built-with)
- [Contributing](#contributing)
- [Versioning](#versioning)
- [Ethics](#ethics)
- [Safety](#safety)
- [Maintainers](#maintainers)
- [Acknowledgments](#acknowledgments)

## CyberScript

Shifter is powered by CyberScript — a language for defining cyber ranges. Write
what you want in CyberScript, then Shifter builds it.

```yaml
instances:
  - name: Domain Controller
    role: dc
    os_type: windows
    domain_controller: true
    xdr_agent: false

  - name: Workstation 1
    role: victim
    os_type: windows
    xdr_agent: true
    join_domain: true

subnets:
  - name: dc_network
    instances: [Domain Controller]
    connected_to: [workstation_network]
```

You describe attack scenarios, network topology, and victim configurations
without dealing with cloud primitives or infrastructure complexity.

See
[`cortex_byot.yaml`](shifter/shifter_platform/cms/scenarios/templates/cortex_byot.yaml)
for a complete example.

## Getting Started

These instructions get a copy of the project up and running on your local
machine. See [Deployment](#deployment) for notes on deploying to a live cloud
account.

## Prerequisites

- Python 3.12 with [uv](https://github.com/astral-sh/uv)
- Node 20+ and npm
- Terraform 1.7+, kubectl, helm 3.15+
- [pre-commit](https://pre-commit.com/)

## Installing

Each package root manages its own dependencies (uv per pyproject.toml,
npm per package.json):

```shell
# Per-package Python envs
cd shifter/shifter_platform && uv sync
cd ../installation && uv sync
cd ../cyberscript && uv sync
# ...repeat for any package root you'll touch

# Per-package MCP servers
cd mcp/ops && npm ci
# ...repeat for each mcp/* root

# Install pre-commit hooks once per clone
pre-commit install
```

Full setup with database, secrets, and bootstrap flow:
[`shifter/shifter_platform/documentation/docs/technical/dev/setup.md`](shifter/shifter_platform/documentation/docs/technical/dev/setup.md).

## Usage

Local dev runs the Django platform service against a local Postgres + Redis;
provisioner, MCP servers, and the GCP/AWS terraform paths are documented under
[`shifter/shifter_platform/documentation/docs/`](shifter/shifter_platform/documentation/docs/).

## Support

Please read [SUPPORT.md](SUPPORT.md) for details on how to get support for
this project.

## Deployment

Production deploys flow through `.github/workflows/deploy.yml` (a single
entry point that dispatches per-cloud child workflows). Deployment-specific
identifiers (DNS names, alarm emails, GCP project IDs, allow-list domains,
SSH keys, etc.) are supplied via gitignored `local.auto.tfvars` files for
local runs and via GitHub repository secrets/variables for CI. The complete
required surface is documented in
[`docs/dev/deploy-secrets.md`](docs/dev/deploy-secrets.md).

## Running the tests

Tests run per-package. Common invocations:

```shell
cd shifter/shifter_platform && uv run pytest
cd scripts/bootstrap && uv run pytest
cd scripts/gcp && uv run pytest
cd shifter/engine/provisioner && uv run pytest
cd mcp/<name> && npm test
```

The aggregate gate every PR must pass:

```shell
pre-commit run --all-files
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

## Built With

- [Django](https://www.djangoproject.com/) — platform service (portal, CMS,
  Mission Control)
- [Terraform](https://www.terraform.io/) — AWS and GCP infrastructure
- [Kustomize](https://kustomize.io/) + [Helm](https://helm.sh/) — Kubernetes
  workload deployment on GKE
- [Apache Guacamole](https://guacamole.apache.org/) — clientless remote access
  into provisioned range hosts
- [Packer](https://www.packer.io/) — golden VM image build

## Contributing

We value your contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md)
for details on how to contribute, and the process for submitting pull
requests.

## Versioning

We use [SemVer](http://semver.org/) for versioning and
[conventional commits](https://www.conventionalcommits.org/) for commit and
pull request titles. Release notes are collated from towncrier fragments
under [`changelog.d/`](changelog.d/) — see
[`changelog.d/README.md`](changelog.d/README.md).

## Ethics

AI-driven attack capabilities exist in the wild. Defenders need realistic
exposure. [Read more](shifter/shifter_platform/documentation/docs/ops/ethics.md).

## Safety

- Ranges are network-isolated.
- Human oversight required for all scenarios.
- All AI actions logged.
- MFA-enforced authentication.
- Access restricted to authorized personnel.

## Maintainers

- Brad Edwards — [Brad-Edwards-SecOps](https://github.com/Brad-Edwards-SecOps),
  [Brad-Edwards](https://github.com/Brad-Edwards)

Thank you to all the
[contributors](https://github.com/Brad-Edwards/shifter/graphs/contributors)
who participated in this project.

## Acknowledgments

- README structure adapted from the
  [Palo Alto Networks open-source README template](https://github.com/PaloAltoNetworks/.github/blob/master/docs/README.example.md).
- CyberScript range topology drew on the practical experience of operators
  running attack/defend exercises in the wild.

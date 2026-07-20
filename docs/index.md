# Shifter documentation

Shifter is a cyber-range platform for running XDR and NGFW demos and CTF events
on AWS and GCP. This site is the single home for using, deploying, operating,
and developing it. See the [product overview](product-overview.md) for what
Shifter does.

## Use Shifter

| Section | Read this when |
|---|---|
| [Getting started](getting-started/index.md) | You are new and want the quickstart and core concepts. |
| [How-to guides](how-to/index.md) | You want step-by-step guides such as running your first demo. |
| [Features](features/index.md) | You need details on agents, ranges, the terminal, credentials, NGFW, CTF, or the risk register. |
| [Scenarios](scenarios/index.md) | You are running a specific scenario such as the AD attack lab, an NGFW range, or TechVault. |
| [Reference](reference/index.md) | You need the FAQ or support pointers. |

## Deploy and operate

Read these when you stand up or run an environment. The
[deploy preflight](https://github.com/Brad-Edwards/shifter/blob/dev/scripts/bootstrap/preflight.py)
enforces the prerequisites documented here before any Terraform apply.

| Doc | Read this when |
|---|---|
| [Deploy secrets and variables](dev/deploy-secrets.md) | You are configuring the GitHub secrets and repository variables a fresh AWS or GCP standup needs. This is the authoritative checklist. |
| [AWS Terraform apply order](dev/aws-terraform-apply-order.md) | You need the order the AWS stacks apply in and the preconditions each one has. |
| [AWS AMI seeding](dev/aws-ami-seeding-runbook.md) | You are seeding the range guest AMIs the portal stack reads. |
| [AWS runner provisioning](dev/aws-runner-provisioning-runbook.md) | You are provisioning and registering the self-hosted CI runners. |
| [AWS environment teardown](dev/aws-teardown-runbook.md) | You are tearing an AWS environment down. |
| [GCP range-cell deploy](dev/gcp-range-cell-deploy.md) | You are deploying the GCP GCE range-cell backend. |
| [Polaris on the GCP range-cell](dev/polaris-gcp-range-cell.md) | You are running the Polaris scenario on the GCP range-cell backend. |
| [Secrets rotation](dev/secrets-rotation-runbook.md) | You are rotating deployment or runtime secrets. |
| [Service Discovery ForceNew](dev/service-discovery-forcenew.md) | You hit a Service Discovery replacement and need the operational rule. |
| [Disaster recovery](ops/disaster-recovery.md) | You are recovering the AWS portal stack after a failure. |
| [GitHub runner health alerts](ops/github-runner-health-alerts.md) | A runner-health alert fired and you need the response steps. |
| [TechVault golden AMI bake](ops/techvault-bake-runbook.md) | You are baking the TechVault golden AMI. |

## Develop and govern

| Section | Read this when |
|---|---|
| [Technical docs](technical/index.md) | You are developing the platform: setup, secrets, Terraform, CI/CD, architecture, and subsystem docs. |
| [ADR enforcement](adr/README.md) | You need how architecture decisions are recorded and enforced in CI. |

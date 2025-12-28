# Shifter

Self-service cyber range platform. Users provision isolated Kali + victim environments for XDR/XSIAM testing.

## Docs

- [Architecture](architecture.md) - System overview, components, data flow
- [Security](security.md) - Security controls and considerations
- [Ethics](ops/ethics.md) - Why this exists, responsible use

### Developer Guide

- [Getting Started](dev/index.md) - Onboarding overview
- [Local Setup](dev/local-setup.md) - Run portal locally
- [CI/CD](dev/ci-cd.md) - GitHub Actions, deployments
- [Secrets](dev/secrets.md) - Where secrets live
- [Terraform](dev/terraform.md) - Infrastructure patterns
- [Principles](dev/principles.md) - Engineering philosophy

### Portal

- [Overview](portal/index.md) - Django app, routes, auth, terminal
- [Design System](portal/design-system.md) - Cortex XDR theme

### Execution

- [Overview](execution/index.md) - Shifter Engine and range runtime
- [Shifter Engine](execution/engine.md) - Pulumi ECS task
- [Kali AMI](execution/kali-ami.md) - Pre-baked attacker
- [Victim AMI](execution/victim-ami.md) - Pre-baked victim

### Orchestration

- [Overview](orchestration/index.md) - Range lifecycle

### SCMS

- [Overview](scms/index.md) - Scenario content (goal-state, not implemented)

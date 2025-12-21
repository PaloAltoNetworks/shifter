# Shifter

Self-service cyber range platform. Users provision isolated Kali + victim environments for XDR/XSIAM testing.

## Docs

- [Architecture](architecture.md) - System overview, components, data flow
- [Ethics](ops/ethics.md) - Why this exists, responsible use

### Portal

- [Overview](portal/index.md) - Django app, routes, auth, terminal
- [Design System](portal/design-system.md) - Cortex XDR theme

### Execution

- [Overview](execution/index.md) - Provisioner and range runtime
- [Provisioner](execution/provisioner.md) - Pulumi ECS task
- [Kali AMI](execution/kali-ami.md) - Pre-baked attacker
- [Victim AMI](execution/victim-ami.md) - Pre-baked victim

### Orchestration

- [Overview](orchestration/index.md) - Range lifecycle

### SCMS

- [Overview](scms/index.md) - Scenario content (goal-state, not implemented)

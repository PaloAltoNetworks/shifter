# Architecture

## Components

### Django Portal
- Authentication (paloaltonetworks.com email)
- Agent config management (upload XDR/XSIAM installers to S3)
- Range lifecycle (launch, destroy)

### Kasm Workspaces
- Containerized Kali desktop
- Cursor IDE with MCP servers
- Config injection at container launch

### Terraform Backend
- Per-DC victim VPC provisioning
- EC2 instance with user's agent
- Orchestrated via Step Functions

### MCP Servers
- `victim_run_command` - Execute commands on victim
- `victim_interactive_session` - Persistent SSH sessions
- Session management tools

## Data Flow

```mermaid
graph TD
    A[DC Browser] -->|HTTPS| B[Django Portal]
    B -->|Trigger| C[Terraform Backend]
    C -->|Provision| D[Victim VPC]
    D -->|EC2 + Agent| E[Victim Instance]
    B -->|Launch| F[Kasm Workspace]
    F -->|MCP Config| G[Cursor IDE]
    G -->|SSH/MCP| E
    G -->|1. Setup Vuln| E
    G -->|2. Attack| E
    E -->|Telemetry| H[XDR/XSIAM]
```

## Two-Context Pattern

- **Chat 1**: Configure vulnerability (defender context)
- **Chat 2**: Exploit vulnerability (attacker context, no memory of setup)

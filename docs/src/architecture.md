# Architecture

## Infrastructure Overview

Three components, decoupled via RDS + SQS:

- **Portal**: Django app for auth, agent upload, range status UI. Pushes to SQS on launch.
- **Provisioning Service**: Consumes SQS, provisions infra, deploys LibreChat
- **Range**: Per-user VPC with LibreChat + MCPs and victim EC2

```mermaid
graph TB
    subgraph "Portal VPC"
        Portal[Django Portal]
        RDS[(PostgreSQL)]
        SQS[[SQS FIFO]]
        Provisioner[Provisioning Service]
        Portal --> RDS
        Portal -->|push| SQS
        SQS -->|consume| Provisioner
        Provisioner --> RDS
    end

    subgraph "Range VPC (per-user)"
        LibreChat[LibreChat + MCPs]
        Victim[Victim Instance]
        LibreChat -->|SSH/MCP| Victim
    end

    User((User)) -->|HTTPS| Portal
    User -->|HTTPS| LibreChat
    Provisioner -->|Terraform| Victim
    Victim -->|Telemetry| XDR[XDR/XSIAM]
```

Portal writes to RDS and pushes to SQS. Provisioner consumes queue and updates RDS when done.

## Portal Infrastructure

### Network

```mermaid
graph TB
    subgraph "Portal VPC (10.0.0.0/16)"
        subgraph "Public Subnets (2 AZs)"
            ALB[ALB]
            NAT[NAT Gateway]
        end
        subgraph "Private Subnets (2 AZs)"
            EC2[Django on EC2]
            RDS[(RDS PostgreSQL)]
        end
        ALB --> EC2
        EC2 --> RDS
        EC2 --> NAT
    end
    Internet((Internet)) --> ALB
    NAT --> Internet
```

Two AZs required for RDS subnet group. ALB in public subnets with ACM cert. EC2 in private subnet pulls container from ECR.

### Components

| Component | Purpose |
|-----------|---------|
| ALB | HTTPS termination, routes to EC2 |
| EC2 | Runs Django container, pulls from ECR |
| ECR | Container registry for Django image |
| VPC | Network isolation, public/private subnet separation |
| RDS | PostgreSQL 16, encrypted, credentials in Secrets Manager |
| Cognito | User authentication, MFA, email verification |

### Authentication

```mermaid
sequenceDiagram
    participant User
    participant Django
    participant Cognito

    User->>Django: GET /protected
    Django->>User: 302 → Cognito hosted UI
    User->>Cognito: Login + MFA
    Cognito->>User: 302 → /callback?code=xxx
    User->>Django: GET /callback?code=xxx
    Django->>Cognito: Exchange code for tokens
    Cognito->>Django: JWT (id_token, access_token)
    Django->>Django: Validate JWT, create session
    Django->>User: 302 → /protected (with session cookie)
```

Cognito user pool configured with:

- Email as username
- MFA required (TOTP)
- Pre-signup Lambda for domain restriction (`@paloaltonetworks.com`)
- Email verification required

Django stores minimal user data (email from token claims). No passwords in DB.

### Secrets Management

RDS credentials auto-generated at provision time, stored in Secrets Manager. Secret configured with `recovery_window_in_days = 0` to allow immediate deletion and avoid naming conflicts on destroy/recreate cycles.

## Range Infrastructure

Per-user ephemeral VPCs provisioned by the Provisioning Service.

### Provisioning Flow

1. Portal writes `Range(status='pending', agent_id=X)` to RDS
2. Portal pushes `{ range_id }` to SQS FIFO queue
3. Provisioning Service consumes message
4. Terraform apply:
   - VPC + subnet
   - Security group (SSH from LibreChat)
   - EC2 victim instance
   - User-data installs XDR agent from S3
5. Generate MCP config JSON with victim IP
6. Deploy LibreChat instance (ECS or EC2) with MCP servers
7. Update Range row: `status='ready'`, `victim_ip`, `chat_url`
8. Delete message from queue (success) or send to DLQ (failure)

### Components

| Component | Purpose |
|-----------|---------|
| LibreChat | Chat UI, agent loop, MCP tool use |
| MCP Servers | SSH to victim, command execution |
| Victim EC2 | Target for attacks, runs user's XDR agent |

### Isolation

- Each range is its own VPC (no peering to portal)
- MCP config hardcodes victim IP (agent can't escape)
- Cognito SSO ensures user identity across Portal and LibreChat

## Deployment Pipeline

### Infrastructure

GitHub Actions deploys infra via Terraform on merge to main.

```mermaid
graph LR
    Push[Push to main] --> GHA[GitHub Actions]
    GHA -->|OIDC| AWS[AWS]
    GHA -->|terraform apply| Infra[Infrastructure]
```

IAM via OIDC federation. No static credentials. Role permissions scoped to shifter-* resources.

**Foundation Infrastructure:** ECR registry and terraform state backend. See `terraform/environments/prod/README.md`.

**Global IAM:** GitHub Actions OIDC federation and permissions. See `terraform/global/iam/README.md`.

### Portal Application

Portal deploys on push to `portal/**`:

```mermaid
graph LR
    Push[Push portal/*] --> Build[Build Docker]
    Build --> ECR[Push to ECR]
    ECR --> SSM[SSM Run Command]
    SSM --> EC2[Pull + Restart]
```

EC2 user data bootstraps Docker and ECR auth. SSM pulls new image and restarts container.

### Secrets Sync

Terraform variables stored locally in `.tfvars` files (gitignored). Synced to GitHub secrets before PR using `scripts/sync-tfvars.sh`. Creates namespaced secrets for each environment and component.

## Two-Context Pattern

MCP enables AI-driven scenario setup via separate LibreChat conversations:

1. **Setup chat**: "Set up a PHP command injection on /cmd.php and a SUID privesc"
   - AI uses victim MCP to configure vulnerabilities
   - User can specify flags, locations, difficulty

2. **Attack chat**: "Hack the target at 10.0.1.50, get root, find the flag"
   - Fresh context (no memory of setup)
   - AI uses attack methodology: recon → exploit → privesc
   - XDR/XSIAM detects the attack chain

User demos detections to customer.

## MCP Configuration

MCPs are config-driven. Provisioning service generates per-range config with victim IP, SSH credentials, and network restrictions. Same MCP binary, different config per range. No code changes needed per deployment.

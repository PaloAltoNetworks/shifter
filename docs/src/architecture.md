# Architecture

## Infrastructure Overview

Three components, decoupled via RDS:

- **Portal**: Django app for auth, agent upload, range status UI. Triggers Step Functions on launch.
- **Provisioning Service**: Step Functions + Lambda, provisions range infra (subnet, Kali, Victim)
- **LibreChat**: Shared multi-tenant chat UI in Portal VPC
- **Range**: Per-user subnet in Range VPC with Kali + Victim EC2

```mermaid
graph TB
    subgraph "Portal VPC"
        Portal[Django Portal]
        RDS[(PostgreSQL)]
        StepFn[[Step Functions]]
        Lambda[Lambda Functions]
        LibreChat[LibreChat + MCPs]
        Portal --> RDS
        Portal -->|start execution| StepFn
        StepFn --> Lambda
        Lambda --> RDS
    end

    subgraph "Range VPC (10.1.0.0/16)"
        subgraph "User Subnet"
            Kali[Kali Instance]
            Victim[Victim Instance]
            Kali -->|attacks| Victim
        end
    end

    User((User)) -->|HTTPS| Portal
    User -->|HTTPS| LibreChat
    LibreChat -->|SSH/MCP| Kali
    Lambda -->|AWS API| Kali
    Lambda -->|AWS API| Victim
    Victim -->|Telemetry| XDR[XDR/XSIAM]
```

Portal writes to RDS and triggers Step Functions. Lambda functions create AWS resources and update RDS directly.

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

Per-user ephemeral subnets in Range VPC, provisioned by Step Functions + Lambda.

### Provisioning Flow

1. Portal writes `Range(status='provisioning', agent_id=X)` to RDS
2. Portal starts Step Functions execution with `{ range_id }`
3. Lambda functions execute sequentially:
   - `create_subnet`: Create /24 subnet in Range VPC
   - `create_kali`: Launch Kali EC2 from pre-baked AMI
   - `create_victim`: Launch Victim EC2, install XDR agent from S3
   - `mark_ready`: Update Range status to 'ready'
4. Each Lambda reads from RDS, creates AWS resources, writes back to RDS
5. On error: `cleanup` Lambda destroys any created resources

### Components

| Component | Location | Purpose |
|-----------|----------|---------|
| LibreChat | Portal VPC | Shared chat UI, agent loop, MCP tool use |
| Kali EC2 | Range VPC | Attack tools, MCP-controlled |
| Victim EC2 | Range VPC | Target with XDR agent |

### Isolation

- Each user gets a dedicated /24 subnet in Range VPC
- Security groups restrict traffic between subnets
- Range VPC has no route to Portal VPC (Lambda uses AWS APIs)
- Victim VMs have no IAM role (can't call AWS APIs)

## Deployment Pipeline

### Infrastructure

GitHub Actions deploys infra via Terraform on merge to main.

```mermaid
graph LR
    Push[Push to main] --> GHA[GitHub Actions]
    GHA -->|OIDC| AWS[AWS]
    GHA -->|terraform apply| Infra[Infrastructure]
```

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

IAM via OIDC federation. No static credentials. Role permissions scoped to shifter-* resources.

### Secrets Sync

Terraform variables stored locally in `.tfvars` files (gitignored). Synced to GitHub secrets before PR:

```bash
./scripts/sync-tfvars.sh
```

Creates namespaced secrets: `TF_VARS_{ENV}_{COMPONENT}` (e.g., `TF_VARS_PROD_PORTAL`).

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

MCPs connect LibreChat to range instances via SSH. Currently using hexstrike-ai MCP for Kali access.

**Current State:** MCPs are configured manually in LibreChat. Users SSH into their Kali instance from LibreChat.

**Future State:** Per-range MCP config will be auto-generated:

```json
{
  "server": {
    "name": "shifter-range-${range_id}",
    "toolPrefix": "kali"
  },
  "targets": {
    "kali": {
      "host": "${kali_private_ip}",
      "ssh_user": "kali",
      "ssh_port": 22
    },
    "victim": {
      "host": "${victim_private_ip}",
      "ssh_user": "ubuntu",
      "ssh_port": 22
    }
  }
}
```

Same MCP binary, different config per range. No code changes needed.

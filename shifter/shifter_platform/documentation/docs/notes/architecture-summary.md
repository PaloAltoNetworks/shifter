# Architecture Summary: Shifter Cyber Range Platform

## Infrastructure (AWS `us-east-2`)

**VPCs: 2 main VPCs**
- **Portal VPC** (`10.0.0.0/16`): Hosts the Django platform
  - 2 AZs with public/private subnets
  - NAT Gateway (single, cost-optimized)
  - VPC Flow Logs enabled
- **Range VPC** (`10.1.0.0/16`): Isolated attack environment
  - Dynamic per-user subnets (`10.1.{index}.0/24`, max 254 concurrent ranges)
  - AWS Network Firewall for domain-based egress filtering
  - Security groups: Kali, Victim, DC, NGFW

**VPC Peering**: Portal ↔ Range (for SSH terminal access from browser)

---

## Data Layer

| Service | Configuration |
|---------|---------------|
| **RDS PostgreSQL** | db.t3.large, v16, 20-100GB autoscaling, 7-day backups, log exports enabled |
| **Redis (ElastiCache)** | cache.t3.micro, v7.1, replication group enabled (2 nodes, multi-AZ, automatic failover) |
| **S3** | User storage bucket for agent uploads (5GB/user quota, 2GB/file limit) |
| **Secrets Manager** | Django secret key, field encryption key, SSH keys |

---

## Compute

| Component | Type | Purpose |
|-----------|------|---------|
| **Portal** | EC2 t3.xlarge | Django app (ASG ready but single instance for now) |
| **Pulumi Provisioner** | ECS Fargate | Range infrastructure provisioning |
| **Range Instances** | EC2 t3.medium | Kali (attacker), Ubuntu/Windows (victim), Windows DC |
| **VM-Series NGFW** | EC2 | Optional per-user firewall instances |

---

## Network Security

- **ALB** with WAF, access logs
- **Cognito** for OIDC auth (restricted to `@paloaltonetworks.com`)
- **AWS Network Firewall** for Range egress filtering
- **Security Groups**: Portal SSH to Range instances

---

## Django App Stats

| Metric | Value |
|--------|-------|
| **Apps** | 6 (`mission_control`, `engine`, `cms`, `management`, `documentation`, `risk_register`) |
| **Concrete Models** | 9 (`Range`, `UserNGFW`, `Credential`, `AgentConfig`, `OperatingSystem`, `RangeInstance`, `UserProfile`, `ActivityLog`, `Risk`, `Comment`, `APIKey`, `AuditLog`) |
| **WebSocket Consumers** | 2 (`SSHConsumer` for terminal, `NGFWProvisioningConsumer` for status) |
| **ASGI Server** | Daphne (Django Channels) |
| **API** | Django REST Framework with session + API key auth |

---

## Key Features

1. **Browser Terminal**: WebSocket SSH to Kali/Victim via xterm.js
2. **Range Lifecycle**: Provision → Ready → Pause → Destroy (Pulumi IaC)
3. **Agent Management**: Upload XDR/XSIAM installers to S3 with presigned URLs
4. **Credential Vault**: Encrypted storage for SCM pins and authcodes
5. **VM-Series NGFW**: Per-user persistent firewall instances with GWLB
6. **Scenarios**: Templated attack scenarios (basic, AD attack lab)

---

## Packer Images (AMIs via SSM Parameter Store)

- `kali.pkr.hcl` - Kali attacker
- `ubuntu.pkr.hcl` - Ubuntu victim  
- `windows.pkr.hcl` - Windows victim/DC

---

## Codebase Stats

*Generated via `cloc`, excluding node_modules, .venv, migrations, docs*

### Tests

| Metric | Django App | Pulumi Provisioner | Total |
|--------|------------|-------------------|-------|
| **Test files** | 55 | 41 | 96 |
| **Test functions** | 1,599 | 874 | 2,473 |
| **Test LOC** | 14,349 | 10,198 | 24,547 |

### Lines of Code

| Component | Code LOC |
|-----------|----------|
| **Django app** (Python) | 5,264 |
| **Django app** (JS/HTML/CSS) | 6,863 |
| **Django tests** | 14,349 |
| **Pulumi provisioner** (code) | 3,467 |
| **Pulumi provisioner** (tests) | 10,198 |
| **Terraform** (HCL) | 7,402 |
| **Packer** | 989 |

**Total**: ~48k LOC (code + tests)

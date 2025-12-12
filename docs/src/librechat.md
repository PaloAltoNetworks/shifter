# LibreChat

## Overview

LibreChat is a third-party open-source chat interface for AI models. Shifter uses it as the primary user interface for AI agent interactions with ranges.

**Purpose**: Provides browser-based chat UI with agent loop execution and MCP tool integration.

**Source**: https://github.com/danny-avila/LibreChat

## Architecture

### Deployment Model

Single shared LibreChat instance serves all users:
- Deployed in Portal VPC on dedicated EC2 instance
- Multi-tenant via user authentication
- Per-range MCP configuration routing

### Components

| Component | Description |
|-----------|-------------|
| LibreChat container | Node.js web application (port 3080) |
| MongoDB container | User data, conversations, sessions |
| EBS data volume | Persistent MongoDB storage |
| Secrets Manager | JWT secrets, encryption keys |

### Network Topology

```
Portal VPC
├── LibreChat subnet (10.0.3.0/24)
│   └── EC2 instance
│       ├── LibreChat container (ghcr.io/danny-avila/librechat:latest)
│       └── MongoDB container (mongo:7)
└── No ingress (SSM access only)
```

No direct internet ingress. Access via:
- SSM Session Manager for admin
- Future: ALB routing for user access

## Local Development

### Setup

```bash
cd librechat
make init  # Creates .env with generated secrets
```

### Configuration

Environment variables in `.env`:
- `JWT_SECRET`, `JWT_REFRESH_SECRET`: Session tokens
- `CREDS_KEY`, `CREDS_IV`: Credential encryption
- `MONGO_URI`: Database connection
- `APP_TITLE`: UI branding
- `ALLOW_REGISTRATION`: User signup control

### Running

```bash
make up     # Start containers
make logs   # View logs
make down   # Stop containers
make clean  # Remove volumes
```

Accessible at http://localhost:3080

## Production Deployment

### Infrastructure (Terraform)

Module: `terraform/modules/librechat/`

Resources:
- Subnet in Portal VPC
- EC2 instance (AL2023, Docker/Compose)
- Security group (egress only)
- IAM role (Secrets Manager read, SSM, CloudWatch)
- EBS volume (persistent MongoDB data)
- Secrets Manager secret (configuration)

User data script:
1. Install Docker/Compose
2. Mount EBS data volume
3. Fetch secrets from Secrets Manager
4. Generate docker-compose.yml and .env
5. Start containers

### Secrets Management

Secrets stored in AWS Secrets Manager:
- `jwt_secret`: 64-char random hex
- `jwt_refresh_secret`: 64-char random hex
- `creds_key`: 64-char random hex
- `creds_iv`: 32-char random hex
- `allow_registration`: boolean
- `app_title`: string

Generated at Terraform apply, immutable.

Secret refresh script: `/opt/librechat/refresh-secrets.sh`

### Updates

EC2 instance pulls latest LibreChat image:
```bash
cd /opt/librechat
docker compose pull
docker compose up -d
```

## MCP Integration

### Configuration Routing

Provisioner Lambda (`configure_librechat`) creates per-range MCP config:
- User account (if not exists)
- MCP server routing to range victim IP
- SSH keys and credentials

### Multi-Tenancy

Single LibreChat instance, isolated via:
- User authentication (email/password)
- MCP config scoped to user's range
- MongoDB collections per user

## Access Control

### Authentication

- Email/password login (LibreChat native)
- No social login
- No password reset (admin managed)
- Unverified email allowed (internal use)

### Session Management

- Session expiry: 15 minutes (900000ms)
- Refresh token: 7 days (604800000ms)

## Monitoring

### Logs

CloudWatch Logs: `/aws/logs/prod-librechat-*`

Container logs: `/opt/librechat/logs/`

User data execution: `/var/log/user-data.log`

### Health

Service status:
```bash
docker compose ps
```

MongoDB connection:
```bash
docker exec librechat-mongodb mongosh --eval "db.adminCommand('ping')"
```

## Data Persistence

MongoDB data: `/opt/librechat/data/mongodb` (EBS-backed)

EBS volume lifecycle: `prevent_destroy = true`

Survives instance replacement, requires manual cleanup if destroying environment.

## Security

- No ingress rules (SSM-only access)
- IMDSv2 enforced
- EBS encryption enabled
- Secrets rotation: manual via Terraform
- JWT secrets: 64-byte entropy
- Credential encryption: AES with random IV

## Future Enhancements

- ALB integration for HTTPS access
- Cognito SSO (replace native auth)
- Auto-scaling (multiple instances)
- ElastiCache for session storage
- Managed MongoDB (DocumentDB)

# AgentChat

OpenWebUI + Bedrock Access Gateway for AI chat with AWS Bedrock models.

## Architecture

```
User → SSM Tunnel → OpenWebUI (port 3000) → BAG (port 8000) → AWS Bedrock
```

| Component | Purpose |
|-----------|---------|
| OpenWebUI | Chat interface (`ghcr.io/open-webui/open-webui:v0.6.41`) |
| Bedrock Access Gateway (BAG) | Translates OpenAI API to Bedrock SDK |

## Access

AgentChat runs on a private EC2 instance. Access via SSM port forwarding:

```bash
# Connect to dev environment
./scripts/agentchat-tunnel.sh

# Connect to prod environment
./scripts/agentchat-tunnel.sh -e prod

# Access OpenWebUI at http://localhost:3000
```

## Deployment

`agentchat.yml` workflow:

- PR → `terraform plan`
- Merge to main/dev → `terraform apply` + SSM deploy
- Manual dispatch → plan/apply/deploy

**Steps:**

1. Terraform provisions EC2, IAM, Security Group, Secrets Manager
2. SSM deploy clones BAG repo, builds image, starts containers

State: `s3://shifter-infra-xxx/{env}/agentchat/terraform.tfstate`

Variables: `TF_VARS_{ENV}_AGENTCHAT` GitHub secret.

## Configuration

Connection is pre-configured via environment variables during deployment. After first login:

1. Create admin account (first user becomes admin)
2. Apply manual settings per [manual-config.md](manual-config.md)

**Connection details (pre-configured):**
- URL: `http://bedrock-gateway:8080/api/v1`
- API Key: Retrieved from Secrets Manager (`shifter-{env}-agentchat-bag-api-key`)

## Data Storage

OpenWebUI uses PostgreSQL (shared with Portal RDS) for persistent storage of:
- User accounts and settings
- Chat history
- Uploaded files

**Database:** `openwebui` database in Portal RDS instance.

**Credentials:** Stored in Secrets Manager (`shifter-{env}-portal-openwebui-db`).

### Initial Setup (One-Time Per Environment)

> **Note:** On first deployment, OpenWebUI will fail to start because the database doesn't exist yet. This is expected. Complete the steps below, then re-run the AgentChat workflow.

After Portal terraform apply creates the secret, manually create the database:

```bash
# Connect to RDS via SSM tunnel
./scripts/db-connect.sh

# In psql (as shifter_admin):
CREATE DATABASE openwebui;
CREATE USER openwebui WITH PASSWORD '<password-from-secrets-manager>';
GRANT ALL PRIVILEGES ON DATABASE openwebui TO openwebui;
\c openwebui
GRANT ALL ON SCHEMA public TO openwebui;
```

Get the password from Secrets Manager:
```bash
aws secretsmanager get-secret-value \
  --secret-id "shifter-{env}-portal-openwebui-db" \
  --query 'SecretString' --output text | jq -r '.password'
```

## Terraform

Module: `modules/agentchat/ec2/`

Environments: `environments/{dev,prod}/agentchat/`

| Resource | Purpose |
|----------|---------|
| EC2 | Docker host (Amazon Linux 2023) |
| IAM Role | Bedrock invoke, SSM, Secrets Manager read |
| Security Group | Egress only (no ingress) |
| Secrets Manager | BAG API key storage |
| Portal RDS | PostgreSQL database for OpenWebUI data |

## Security

| Control | Implementation |
|---------|----------------|
| Network | No ingress ports - access only via SSM tunnel |
| API Key | Stored in AWS Secrets Manager (not hardcoded) |
| Bedrock | IAM policy restricts to Claude and DeepSeek models |
| Logs | Docker log rotation enabled to prevent disk fill |
| Supply Chain | BAG cloned from forked repo (Brad-Edwards/bedrock-access-gateway) |

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

After first login to OpenWebUI:

1. Go to Admin Panel → Settings → Connections
2. Add new OpenAI connection:
   - URL: `http://bedrock-gateway:80/api/v1`
   - API Key: (retrieve from AWS Secrets Manager: `shifter-{env}-agentchat-bag-api-key`)
3. Verify connection
4. Bedrock models will appear in model selector

## Terraform

Module: `modules/agentchat/ec2/`

Environments: `environments/{dev,prod}/agentchat/`

| Resource | Purpose |
|----------|---------|
| EC2 | Docker host (Amazon Linux 2023) |
| IAM Role | Bedrock invoke, SSM, Secrets Manager read |
| Security Group | Egress only (no ingress) |
| Secrets Manager | BAG API key storage |

## Security

| Control | Implementation |
|---------|----------------|
| Network | No ingress ports - access only via SSM tunnel |
| API Key | Stored in AWS Secrets Manager (not hardcoded) |
| Bedrock | IAM policy restricts to Claude Sonnet 4.5 models only |
| Logs | Docker log rotation enabled to prevent disk fill |
| Supply Chain | BAG cloned from forked repo (Brad-Edwards/bedrock-access-gateway) |

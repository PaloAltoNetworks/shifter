# AgentChat

OpenWebUI + Bedrock Access Gateway for AI chat with AWS Bedrock models.

## Architecture

```
User → SSM Tunnel → OpenWebUI (port 3000) → BAG (port 8000) → AWS Bedrock
```

## Components

- **OpenWebUI**: Chat interface (`ghcr.io/open-webui/open-webui:v0.6.41`)
- **Bedrock Access Gateway (BAG)**: Translates OpenAI API to Bedrock SDK

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

Deployment is handled automatically by GitHub Actions workflow:

1. **Terraform** provisions EC2, IAM, Security Group, Secrets Manager
2. **SSM deploy** clones BAG repo, builds image, starts containers

The workflow runs on:
- Push to `main` or `dev` branches
- Pull requests (plan only, deploy on dev PRs)
- Manual dispatch via GitHub Actions UI

## Configuration

After first login to OpenWebUI:

1. Go to Admin Panel → Settings → Connections
2. Add new OpenAI connection:
   - URL: `http://bedrock-gateway:80/api/v1`
   - API Key: (retrieve from AWS Secrets Manager: `{env}-agentchat-bag-api-key`)
3. Verify connection
4. Bedrock models will appear in model selector

## Security Notes

- BAG API key is stored in AWS Secrets Manager (not hardcoded)
- IAM policy restricts Bedrock to Claude Sonnet 4.5 models only
- No ingress ports - access only via SSM tunnel
- Docker log rotation enabled to prevent disk fill

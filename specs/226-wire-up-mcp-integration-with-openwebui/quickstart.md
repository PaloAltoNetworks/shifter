# Quickstart: MCP Integration with OpenWebUI

**Feature**: 226-wire-up-mcp-integration-with-openwebui

## Prerequisites

- Node.js 18+
- AWS CLI configured with dev profile (`PANW_SHIFTER_DEV_PROFILE`)
- Access to Shifter dev environment
- Range provisioned and in `ready` status

## Local Development Setup

### 1. Install Dependencies

```bash
# From repo root
cd mcp/mcp-shifter
npm install
```

### 2. Configure Environment

Create `.env` file in `mcp/mcp-shifter/`:

```bash
# Cognito
COGNITO_USER_POOL_ID=us-west-2_xxxxxx
COGNITO_CLIENT_ID=xxxxxxxxxxxxx
COGNITO_ISSUER=https://cognito-idp.us-west-2.amazonaws.com/us-west-2_xxxxxx

# RDS
RDS_HOSTNAME=shifter-dev.xxxxx.us-west-2.rds.amazonaws.com
RDS_PORT=5432
RDS_DATABASE=shifter
RDS_USERNAME=iam_user

# AWS
AWS_REGION=us-west-2

# Server
PORT=3001
CONFIG_PATH=./config.json
```

Create `config.json` in `mcp/mcp-shifter/` (**required, no defaults**):

```json
{
  "sessions": {
    "maxPerUser": 7,
    "maxGlobal": 500,
    "logInfoThreshold": 300,
    "logWarnThreshold": 400
  },
  "connections": {
    "idleTimeoutMs": 300000
  }
}
```

**Note**: Server will fail to start if any config value is missing.

### 3. Build and Run

```bash
npm run build
npm start
```

Server runs on `http://localhost:3001/mcp`

### 4. Test with curl

```bash
# Get JWT token (via Cognito hosted UI or CLI)
TOKEN="eyJ..."

# List available tools
curl -X POST http://localhost:3001/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## OpenWebUI Configuration

1. Open OpenWebUI Settings > External Tools
2. Click "Add Server"
3. Select "MCP (Streamable HTTP)"
4. Enter URL: `https://shifter-dev.example.com/mcp`
5. Authentication: Bearer token (Cognito JWT)

## Project Structure

```
mcp/mcp-shifter/
├── src/
│   ├── index.ts         # Express server entrypoint
│   ├── transport.ts     # StreamableHTTPServerTransport setup
│   ├── auth.ts          # Cognito JWT validation
│   ├── range-lookup.ts  # RDS query + Secrets Manager
│   └── config.ts        # Dynamic LabConfig builder
├── tests/
│   ├── auth.test.ts
│   ├── range-lookup.test.ts
│   └── integration/
├── package.json
└── tsconfig.json
```

## Key Files to Implement

| File | Purpose |
|------|---------|
| `auth.ts` | JWT validation using `aws-jwt-verify` |
| `range-lookup.ts` | Query RDS for user's range, fetch SSH key from Secrets Manager |
| `config.ts` | Build `LabConfig` from range data |
| `transport.ts` | Session management with `StreamableHTTPServerTransport` |
| `index.ts` | Express routes: POST/GET/DELETE `/mcp` |

## Testing

```bash
# Unit tests
npm test

# With coverage
npm test -- --coverage

# Watch mode
npm run test:watch
```

## Common Issues

### "No active range for user"
- Ensure user has range in `ready` status
- Check user email matches JWT claims

### "Invalid JWT"
- Verify token not expired
- Check `COGNITO_CLIENT_ID` matches token audience

### "Cannot connect to RDS"
- Ensure IAM role has `rds-db:connect` permission
- Verify SSL is enabled in connection

### "SSH connection failed"
- Check VPC peering is active
- Verify security group allows port 22 from AgentChat

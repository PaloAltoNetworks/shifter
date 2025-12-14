# Research: MCP Integration with OpenWebUI

**Feature**: 226-wire-up-mcp-integration-with-openwebui
**Date**: 2025-12-14

## 1. OpenWebUI MCP Integration

### Decision: Use Streamable HTTP Transport (Native OpenWebUI Support)

OpenWebUI v0.6.31+ natively supports MCP via **Streamable HTTP transport**. This is the recommended approach for web applications.

### Rationale
- Native support, no proxy layer needed (unlike stdio/SSE which require MCPO)
- Multi-tenant friendly with per-session management
- Supports OAuth 2.1 authentication
- Official recommendation from OpenWebUI team
- Handles TLS termination and corporate proxy scenarios

### Configuration
1. Admin opens Settings > External Tools > Add Server
2. Selects "MCP (Streamable HTTP)"
3. Provides server URL (e.g., `https://domain.com/mcp`)
4. OpenWebUI sends POST requests to endpoint

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| MCPO Proxy (stdio/SSE) | Adds unnecessary intermediary layer |
| SSE Transport | Deprecated, connection management challenges |

---

## 2. MCP SDK HTTP Transport

### Decision: Use `StreamableHTTPServerTransport` with Express.js

**Import:**
```typescript
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
```

### API Pattern
```typescript
const transport = new StreamableHTTPServerTransport({
  sessionIdGenerator: () => crypto.randomUUID(),
  onsessioninitialized: (sessionId) => transports.set(sessionId, transport)
});

// Handle requests
await transport.handleRequest(req, res, req.body);
```

### Session Management
- Server maintains `Map<sessionId, StreamableHTTPServerTransport>`
- Client sends `mcp-session-id` header after initialization
- Server routes to correct transport based on session ID

### HTTP Endpoints Required
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/mcp` | Client requests (JSON-RPC) |
| GET | `/mcp` | Server notifications (SSE stream) |
| DELETE | `/mcp` | Session termination |

### Rationale
- Designed for remote/web servers
- Handles concurrent sessions with stateful management
- Compatible with containerized deployment
- SDK v1.24.3 (already in `aptl-mcp-common`) provides implementation

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| StdioServerTransport | Requires shell spawning, not suitable for web deployment |
| Custom HTTP | Unnecessary—SDK provides battle-tested implementation |

---

## 3. Cognito JWT Validation

### Decision: Use `aws-jwt-verify` (AWS Official Library)

**Setup:**
```typescript
import { CognitoJwtVerifier } from 'aws-jwt-verify';

const verifier = CognitoJwtVerifier.create({
  userPoolId: process.env.COGNITO_USER_POOL_ID,
  tokenUse: 'access',
  clientId: process.env.COGNITO_CLIENT_ID,
});

const claims = await verifier.verify(token);
```

### Rationale
- Official AWS library, zero runtime dependencies
- Pure TypeScript, Node.js 18+ support
- Automatic JWKS caching with key rotation
- Validates structure, signature, and claims

### Claims to Verify
- `iss` (issuer): Must match user pool
- `aud` or `client_id`: Must match app client ID
- `exp` (expiration): Verified automatically
- `token_use`: Must be 'access' or 'id'

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| jose | Requires additional verification logic |
| Manual validation | Complex, error-prone |

---

## 4. RDS IAM Authentication

### Decision: Use `@aws-sdk/rds-signer` with `pg` Client

**Setup:**
```typescript
import { Signer } from '@aws-sdk/rds-signer';
import { Pool } from 'pg';

const signer = new Signer({
  region: process.env.AWS_REGION,
  hostname: process.env.RDS_HOSTNAME,
  port: 5432,
  username: 'iam_user'
});

const pool = new Pool({
  host: process.env.RDS_HOSTNAME,
  port: 5432,
  user: 'iam_user',
  database: 'shifter',
  password: await signer.getAuthToken(),
  ssl: { rejectUnauthorized: true }
});
```

### Requirements
- IAM tokens valid for 15 minutes
- SSL must be enabled (RDS rejects non-SSL with IAM auth)
- Database user needs `rds_iam` role grant
- EC2 IAM role needs `rds-db:connect` permission

### Rationale
- Consistent with Shifter architecture (Lambdas use IAM auth)
- No password management
- Automatic rotation via IAM role
- Audit trail via CloudTrail

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| Password auth | Requires secret management, rotation |
| Env var credentials | Anti-pattern, security risk |

---

## 5. Integration Architecture

```
OpenWebUI (Chat UI)
    │
    │ HTTPS POST /mcp
    │ Headers: {"mcp-session-id": "uuid...", "Authorization": "Bearer <JWT>"}
    │
    ▼
┌─────────────────────────────────────────┐
│   mcp-shifter (Express.js)              │
│   ─────────────────────────────────────│
│  ├─ JWT Validation (aws-jwt-verify)    │
│  ├─ Session Management (per-user)      │
│  ├─ Range Lookup (RDS IAM auth)        │
│  ├─ SSH Key Fetch (Secrets Manager)    │
│  └─ Tool Handlers (aptl-mcp-common)    │
└─────────────────────────────────────────┘
    │
    ├─ RDS (IAM Auth) → Range lookup by user email
    │
    ├─ Secrets Manager → SSH private key
    │
    └─ SSH (port 22) → User's Kali instance
```

---

## Dependencies to Add

| Package | Version | Purpose |
|---------|---------|---------|
| express | ^4.18 | HTTP server |
| aws-jwt-verify | ^4.0 | Cognito JWT validation |
| @aws-sdk/rds-signer | ^3.x | RDS IAM token generation |
| @aws-sdk/client-secrets-manager | ^3.x | SSH key retrieval |
| pg | ^8.x | PostgreSQL client |

---

## Key Findings Summary

| Topic | Decision | Key Insight |
|-------|----------|-------------|
| OpenWebUI Transport | Streamable HTTP | Native support, no proxy needed |
| MCP SDK | StreamableHTTPServerTransport | Session management built-in |
| JWT Validation | aws-jwt-verify | Official AWS, zero deps |
| RDS Auth | IAM (@aws-sdk/rds-signer) | Matches existing Shifter pattern |

All NEEDS CLARIFICATION items have been resolved. Ready for Phase 1 design.

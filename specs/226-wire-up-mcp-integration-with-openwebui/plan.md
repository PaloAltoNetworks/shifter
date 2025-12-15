# Implementation Plan: MCP Integration with OpenWebUI

**Branch**: `226-wire-up-mcp-integration-with-openwebui` | **Date**: 2025-12-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/226-wire-up-mcp-integration-with-openwebui/spec.md`

## Summary

Integrate OpenWebUI with the existing MCP infrastructure to enable AI-driven control of user-specific Kali instances. The core MCP functionality (`aptl-mcp-common`) is production-ready with SSH connection management, persistent sessions, and tool handlers. This feature adds:
1. HTTP transport layer (replacing stdio) for OpenWebUI compatibility
2. Dynamic per-user range resolution (JWT → email → database → SSH credentials)
3. Cognito SSO integration for OpenWebUI
4. Infrastructure routing (ALB rules, VPC connectivity)

## Technical Context

**Language/Version**: TypeScript 5.3+ (MCP layer), Python 3.12 (Django portal)
**Primary Dependencies**:
- `@modelcontextprotocol/sdk` ^1.24.3 (existing)
- `aptl-mcp-common` 0.4.4 (existing, unchanged)
- `ssh2` ^1.16.0 (existing)
- OpenWebUI v0.6.41 (deployed)
- AWS SDK v3 (Secrets Manager, RDS IAM auth)
**Storage**: PostgreSQL via RDS (existing Range model)
**Testing**: Vitest (MCP), pytest (Django)
**Target Platform**: Linux (Amazon Linux 2023 on AgentChat EC2)
**Project Type**: Multi-component (MCP server TypeScript + Terraform infra)
**Performance Goals**: MCP tool invocation < 5 seconds, streaming for long commands
**Constraints**: Per-user isolation (no cross-user access), JWT validation on every request
**Scale/Scope**: Single AgentChat instance, up to 254 concurrent ranges

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution file contains placeholder template. Applying Shifter project principles from CLAUDE.md:

| Principle | Status | Notes |
|-----------|--------|-------|
| No features beyond request | PASS | Scope tightly bounded to MCP+OpenWebUI integration |
| Use existing components | PASS | `aptl-mcp-common` unchanged, adding thin HTTP wrapper |
| Single source of truth (RDS) | PASS | Range lookup from existing PostgreSQL |
| Same identity (Cognito) | PASS | SSO via shared Cognito user pool |

**Gate Status**: PASSED

## Project Structure

### Documentation (this feature)

```text
specs/226-wire-up-mcp-integration-with-openwebui/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
mcp/
├── aptl-mcp-common/         # UNCHANGED - existing SSH/session library
│   ├── src/
│   │   ├── ssh.ts           # SSHConnectionManager, PersistentSession
│   │   ├── server.ts        # createMCPServer (stdio transport)
│   │   ├── config.ts        # LabConfig type
│   │   └── tools/           # Tool definitions and handlers
│   └── tests/
├── mcp-red/                 # UNCHANGED - reference implementation
└── mcp-shifter/             # NEW - Shifter-specific HTTP wrapper
    ├── src/
    │   ├── index.ts              # Express app entrypoint
    │   ├── config.ts             # Config loader (sessions, connections)
    │   ├── config-schema.ts      # Zod schema for config validation
    │   ├── auth.ts               # Cognito JWT validation
    │   ├── db.ts                 # RDS connection with IAM auth
    │   ├── range-lookup.ts       # Query range by user email
    │   ├── secrets.ts            # Secrets Manager client
    │   ├── lab-config-builder.ts # Build LabConfig from range data
    │   ├── session-manager.ts    # Map<sessionId, {labConfig, transport, user}>
    │   ├── transport.ts          # StreamableHTTPServerTransport setup
    │   ├── connection-cleanup.ts # Idle connection timer
    │   ├── logger.ts             # Structured logging
    │   ├── types.ts              # UserContext, etc.
    │   ├── routes/
    │   │   ├── health.ts         # GET /health for ALB
    │   │   └── mcp.ts            # POST/GET/DELETE /mcp
    │   └── middleware/
    │       └── auth-middleware.ts # JWT extraction middleware
    └── tests/

terraform/modules/
├── portal/                  # ADD: Cognito app client for OpenWebUI
│   └── cognito.tf
├── agentchat/               # ADD: ALB rules, VPC peering, IAM
│   ├── alb.tf               # /chat/* routing
│   ├── vpc-peering.tf       # Portal VPC ↔ Range VPC
│   └── iam.tf               # Secrets Manager + RDS access
└── range/
    └── provisioner/         # ADD: SSH key storage in Secrets Manager
        └── lambda/
```

**Structure Decision**: New `mcp-shifter` package wraps existing `aptl-mcp-common`. No changes to core library. Terraform additions for infrastructure routing.

## Complexity Tracking

No constitution violations requiring justification.

## Key Technical Decisions

### Transport Layer
- Use MCP SDK's `StreamableHTTPServerTransport` for HTTP-based communication
- Use `aptl-mcp-common` building blocks directly (`SSHConnectionManager`, `generateToolHandlers`) rather than `createMCPServer` wrapper
- `createMCPServer` captures LabConfig at creation time; we need per-session config injection
- Maintain streaming for long-running SSH commands

### Architecture: Why Not createMCPServer

The existing `createMCPServer` in aptl-mcp-common:
1. Takes LabConfig at creation time and captures it in a closure
2. Every tool call gets the same config
3. Uses stdio transport (one process per user)

For multi-user HTTP, we need:
1. One shared `SSHConnectionManager` (connection pooling by `user@host:port`)
2. Per-session LabConfig (different users have different Kali IPs)
3. HTTP transport with session management

**Solution**: Use the primitives directly:
```typescript
// Shared across all sessions
const sshManager = new SSHConnectionManager();
const handlers = generateToolHandlers(serverConfig);

// Per-session: build LabConfig once, cache in session
sessions.set(sessionId, { labConfig, transport, userEmail });

// Per-request: look up cached session, pass to handler
const session = sessions.get(sessionId);
const context: ToolContext = { sshManager, labConfig: session.labConfig };
await handlers[toolName](args, context);
```

### Session-Based Caching

LabConfig is built **once per MCP session**, not per-request:

```
Session Creation (first request, no session ID):
    │
    ▼
Validate JWT (Cognito JWKS) ─────────────────────────────┐
    │                                                     │
    ▼                                                     │
Extract user email from claims                            │
    │                                                     │
    ▼                                                     │
Query RDS: SELECT * FROM mission_control_range            │  DB + Secrets
           WHERE user_id = (SELECT id FROM auth_user      │  hit ONCE
                            WHERE email = ?)              │
           AND status = 'ready'                           │
    │                                                     │
    ▼                                                     │
Fetch SSH key from Secrets Manager                        │
    │                                                     │
    ▼                                                     │
Build LabConfig in memory ───────────────────────────────┘
    │
    ▼
Cache in session: sessions.set(sessionId, { labConfig, userEmail, transport })
    │
    ▼
Return session ID to client

Subsequent Requests (same session):
    │
    ▼
Validate JWT (fast - cached JWKS)
    │
    ▼
Look up session by ID → get cached LabConfig
    │
    ▼
Pass to tool handler via ToolContext

    No DB hit. No Secrets Manager hit.
```

### Memory Footprint

Per-session data is minimal (~4 KB):
- SSH private key: ~400 bytes (Ed25519) to ~3 KB (RSA 4096)
- Connection metadata: ~200 bytes
- Session state: ~100 bytes

At max capacity: `500 sessions × 4 KB = 2 MB`

SSH connections are the larger item: `254 ranges × 75 KB = ~19 MB`

Total memory overhead at max capacity: ~25 MB (negligible on t3.small with 2 GB RAM)

### Database Changes
- ADD `kali_ssh_key_secret_arn` field to Range model (stores Secrets Manager ARN)
- Provisioning Lambda stores SSH key and updates range record

### VPC Connectivity
- VPC peering between Portal VPC and Range VPC
- Security group rules: AgentChat → Kali instances on port 22
- RDS already accessible from Portal VPC (where AgentChat runs)

### Resource Management

**Config file required** - no hardcoded defaults. Server fails to start if missing.

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

| Config Key | Description | Recommended Value |
|------------|-------------|-------------------|
| `sessions.maxPerUser` | Max concurrent sessions per user | 7 |
| `sessions.maxGlobal` | Max total sessions across all users | 500 |
| `sessions.logInfoThreshold` | Log INFO when sessions exceed this | 300 |
| `sessions.logWarnThreshold` | Log WARN when sessions exceed this | 400 |
| `connections.idleTimeoutMs` | Close connections with zero sessions after this | 300000 (5 min) |

**Error Message for Limit Reached**:
```json
{
  "error": "session_limit_reached",
  "message": "Maximum sessions (7) reached for this user. Use kali_list_sessions to see active sessions and kali_close_session to close unused ones.",
  "sessions_active": 7,
  "sessions_max": 7
}
```

**Related**: Session metrics tracking in issue #242

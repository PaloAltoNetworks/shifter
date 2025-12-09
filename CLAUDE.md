# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Shifter** is a self-service cyber range platform. Users access a browser-based chat interface (LibreChat + MCPs) to configure victims and run AI-driven attacks against XDR/XSIAM-protected targets.

### Target Users

PANW SecOps Domain Consultants who need to:
- Run demos in XDR or XSIAM for customers
- Test attack scenarios against XDR-protected victims
- Cannot install tools locally on their work laptops
- Need turnkey, self-service access

---

## Shifter Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         RDS (PostgreSQL)                                │
│            Range table: user_id, status, victim_ip, chat_url            │
└─────────────────────────────────────────────────────────────────────────┘
         │                                    │
         │ writes                             │ reads/writes
         ▼                                    ▼
┌─────────────────────┐            ┌─────────────────────────────┐
│       Portal        │            │    Provisioning Service     │
│     (Django)        │            │   (Step Functions / ECS)    │
│                     │            │                             │
│ • Auth (Cognito)    │───SQS────▶│ • Consumes from queue       │
│ • Agent upload      │            │ • Terraform apply (VPC/EC2) │
│ • Launch range UI   │            │ • Deploy LibreChat instance │
│ • Show range status │            │ • Generate MCP config       │
└─────────────────────┘            └─────────────────────────────┘
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Per-User Range                                                         │
│                                                                          │
│  ┌─────────────────┐     ┌─────────────────┐                           │
│  │   LibreChat     │────▶│   Victim VM     │                           │
│  │   + MCPs        │     │   (EC2)         │                           │
│  │                 │     │                 │                           │
│  │ • Agent loop    │     │ • XDR agent     │──▶ User's XSIAM Tenant   │
│  │ • Chat history  │     │ • AI-configured │                           │
│  │ • Tool use      │     │   vulns         │                           │
│  └─────────────────┘     └─────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### How It Works

1. **User logs into Portal** (Cognito, paloaltonetworks.com email)
2. **Uploads XDR/XSIAM agent installer** (stored in S3)
3. **Clicks "Launch Range"** → Portal writes `Range(status='pending')` to DB, pushes to SQS
4. **Provisioning service consumes from SQS:**
   - Terraform: VPC + victim EC2 + agent install
   - Generates MCP config JSON with victim IP
   - Deploys LibreChat with MCP servers
   - Writes `status='ready'` + `chat_url` back to DB
5. **Portal shows "Open Range"** → user clicks, lands in LibreChat
6. **Two-context workflow:**
   - Chat 1: "Set up a command injection vuln" → MCP configures victim
   - Chat 2: "Hack the target" → MCP runs attack autonomously
   - XDR/XSIAM detects, user demos to customer

### Why This Architecture

| Component | Choice | Reason |
|-----------|--------|--------|
| Chat UI | LibreChat | MCP support, agent loops, Cognito OIDC, open source |
| Decoupling | SQS + RDS | SQS triggers provisioning, RDS stores state |
| Infra Provisioning | Terraform via service | Users don't touch IaC |
| Auth | Cognito SSO | Same identity across Portal and LibreChat |
| Victim VMs | Real EC2 | XDR agent requires real OS |
| Tool Execution | MCP (stdio) | Config-driven, no Lambda wrapper needed |

---

## Components

### 1. Django Portal

**Purpose**: Auth, agent management, range launch/status UI

**Responsibilities**:
- Cognito OIDC authentication
- Agent config CRUD (upload installer to S3)
- Write `Range(status='pending')` to DB on launch
- Display range status, link to LibreChat when ready

Portal does NOT provision infrastructure. It writes requests to DB.

### 2. Provisioning Service

**Purpose**: Provision range infra, deploy LibreChat

**Trigger**: SQS FIFO queue (Portal pushes `{ range_id }` after DB write)

**Actions**:
1. Terraform apply: VPC, EC2 victim, security groups
2. Install user's XDR agent on victim (from S3)
3. Generate MCP config JSON with victim IP
4. Deploy LibreChat instance with MCP servers
5. Update Range row: `status='ready'`, `chat_url`, `victim_ip`

**Implementation options**: Step Functions, ECS task, or Lambda.

### 3. LibreChat

**Purpose**: Browser-based chat UI with agent loop and MCP tool use

**Features used**:
- Cognito OIDC (same as Portal, SSO)
- MCP server integration (stdio transport)
- Multi-turn conversations
- Chat history

**Deployment**: Per-range instance or shared instance with per-user MCP config.

### 4. MCP Servers

**Purpose**: Give AI tools to configure victims and run attacks

**Config-driven** via JSON (see `mcp/mcp-red/docker-lab-config.json`):
```json
{
  "containers": {
    "victim": {
      "container_ip": "${victim_ip}",
      "ssh_key": "/secrets/range-key.pem",
      "ssh_user": "ubuntu",
      "ssh_port": 22
    }
  }
}
```

Provisioning service generates this per-range. Same MCP binary, different config.

**Two-Context Pattern**:
- Chat 1: "Set up a vulnerable web server" → MCP configures victim
- Chat 2: "Hack the target" → MCP attacks (no memory of setup)

---

## Mission Control (Post-Login Portal)

The authenticated area of the Django portal. See full documentation:

- [docs/mission-control.md](docs/mission-control.md) - Pages, layout, user flows
- [docs/design-system.md](docs/design-system.md) - Colors, typography, effects
- [docs/user-stories.md](docs/user-stories.md) - User stories US-1 through US-10

**Key Routes:**

| Route | Page |
|-------|------|
| `/mission-control/` | Dashboard (launch/manage ranges) |
| `/mission-control/agents/` | Agent management |
| `/mission-control/history/` | Range history |
| `/mission-control/settings/` | Account settings |

**Architecture Note:** Portal handles auth and status display. LibreChat handles the actual AI chat interaction. User clicks "Open Range" → redirects to LibreChat URL.

---

## File Structure

```
shifter/
├── CLAUDE.md                    # This file
├── LICENSE
├── README.md
├── CHANGELOG.md
├── mcp/
│   ├── aptl-mcp-common/         # Core MCP library (SSH, tools, server)
│   │   ├── src/
│   │   ├── tests/
│   │   └── package.json
│   └── mcp-red/                 # Reference MCP server + config schema
│       ├── src/index.ts
│       ├── docker-lab-config.json  # Config template
│       └── package.json
├── portal/                      # Django app
│   ├── manage.py
│   ├── config/
│   ├── mission_control/
│   └── templates/
├── terraform/
│   ├── environments/            # prod, dev
│   ├── modules/
│   │   ├── portal/              # VPC, RDS, ALB, EC2, Cognito, S3
│   │   └── range/               # Per-user victim infra
│   └── global/                  # IAM, OIDC
└── .github/
    └── workflows/               # CI/CD pipelines
```

---

## Development Commands

### MCP Common Library

```bash
cd mcp/aptl-mcp-common
npm install
npm run build
npm test -- --coverage
```

### MCP Server (mcp-red example)

```bash
cd mcp/mcp-red
npm install
npm run build
npx @modelcontextprotocol/inspector build/index.js
```

---

## Implementation Phases

### Phase 1: Core Platform (Target: Dec 18)
- [x] Django portal (auth, agent upload, Mission Control UI)
- [x] Portal infrastructure (VPC, RDS, ALB, Cognito)
- [ ] Provisioning service (watch DB, Terraform, deploy LibreChat)
- [ ] LibreChat deployment with MCP integration
- [ ] Range VPC + victim EC2 provisioning

### Phase 2: Polish
- [ ] Auto-destroy ranges after N hours
- [ ] Range status webhooks / polling
- [ ] Error handling and retry logic

### Phase 3: Enhanced Features
- [ ] Windows victim option
- [ ] Multiple victim scenarios
- [ ] XSIAM API MCP (verify detections)

---

### Future: NGFW Integration

When adding PANW NGFW, insert firewall subnet tier:
- Public: ALB, NAT Gateway
- Firewall: NGFW interfaces (new)
- Private: EC2, RDS

Route: ALB → NGFW → EC2

---

## Git Workflow

### Branch Strategy

- `main` - Stable releases
- `dev` - Integration (not currently in use)
- `feature/*` - New features (not currently in use)

### Commit Protocol

**NEVER make commits without explicit user permission:**
1. ALWAYS ask before creating commits
2. Show user what will be committed first
3. Let user review changes before committing
4. Only commit when user explicitly requests it
5. NEVER include Claude attribution or co-authored-by tags

---

## What NOT To Do

Per project rules:
- Do NOT add features not explicitly requested
- Do NOT create documentation for unbuilt features
- Do NOT assume requirements - ask for clarification
- Do NOT add "helpful" extras beyond the request
- Keep responses focused and concise
- Write for technical audience (no marketing language)

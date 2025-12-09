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
│ • Auth (Cognito)    │            │ • Polls for status=pending  │
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
3. **Clicks "Launch Range"** → Portal writes `Range(status='pending')` to DB
4. **Provisioning service picks up request:**
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
| Decoupling | RDS as contract | Portal and provisioning share data model, not APIs |
| Infra Provisioning | Terraform via service | Users don't touch IaC |
| Auth | Cognito SSO | Same identity across Portal and LibreChat |
| Victim VMs | Real EC2 | XDR agent requires real OS |
| Tool Execution | MCP (stdio) | Config-driven, no Lambda wrapper needed |

---

## Components

### 1. Django Portal

**Purpose**: Authentication, agent management, range launch

**Features**:
- Email-restricted signup (paloaltonetworks.com)
- Agent config CRUD (upload installer to S3)
- Launch/destroy range
- Session tracking

**Models**:
```python
class AgentConfig(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)  # "Acme XSIAM"
    s3_uri = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

class Range(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    agent = models.ForeignKey(AgentConfig, on_delete=models.SET_NULL, null=True)
    victim_ip = models.GenericIPAddressField(null=True)
    kasm_session_id = models.CharField(max_length=100, null=True)
    status = models.CharField(max_length=20)  # provisioning, ready, destroying
    created_at = models.DateTimeField(auto_now_add=True)
```

### 2. Kasm Workspaces

**Purpose**: Containerized Kali desktop with Cursor + MCPs

**Custom Image Contents**:
- Kali Linux base (`kasmweb/core-kali-rolling`)
- Cursor IDE (AppImage)
- Node.js 22.x
- MCP servers (built from this repo)
- Startup script for config injection

**Config Injection**: Victim IP passed as env var at container launch, startup script generates MCP config.

### 3. Terraform Backend

**Purpose**: Provision victim infrastructure per-DC

**Resources Created**:
- VPC + subnet
- Security group (SSH from Kasm)
- EC2 victim instance
- User-data installs DC's agent from S3

**Orchestration**: Django → Step Functions → Terraform apply → Return victim IP → Kasm API

### 4. MCP Servers

**Purpose**: Give AI hands to configure victims and run attacks

**Available Tools**:
- `victim_run_command` - Execute command on victim
- `victim_interactive_session` - Persistent SSH session
- Session management (list, close, get output)

**Two-Context Pattern**:
- Chat 1: Configure vulnerability on victim (defender context)
- Chat 2: Attack victim from Kali (attacker context, no memory of setup)

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

**Architecture Note:** DC accesses a control workspace (Kasm + Cursor + MCPs), not Kali directly. MCPs connect to Kali and victim.

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
│   └── mcp-red/                 # Reference MCP server
│       ├── src/index.ts
│       └── package.json
├── portal/                      # Django app (TODO)
│   ├── manage.py
│   ├── portal/
│   └── ranges/
├── terraform/                   # Victim infra (TODO)
│   ├── victim/
│   └── modules/
├── kasm/                        # Kasm image (TODO)
│   ├── Dockerfile
│   └── startup.sh
└── .github/
    └── workflows/
        └── sonar.yml
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

### Phase 1: Core Platform (Current Sprint - 14 days)
- [ ] Kasm custom image with Cursor + MCPs
- [ ] Django portal (auth, agent upload, launch)
- [ ] Terraform victim provisioning
- [ ] Wire together: portal → terraform → kasm → MCP config

### Phase 2: Polish
- [ ] Session timeout/cleanup
- [ ] Cost controls (auto-destroy after N hours)
- [ ] Warm pool for faster victim spin-up

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Shifter** is a self-service cyber range platform for PANW SecOps Domain Consultants. DCs access a browser-based control workspace (Cursor IDE + MCPs), which connects to Kali (attack box) and dynamically provisioned victim infrastructure. AI + MCP enables on-the-fly vulnerability deployment and attack simulation against XDR/XSIAM-protected targets.

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
DC's Work Laptop (browser only)
         │
         │ HTTPS
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Shifter Platform                                                        │
│                                                                          │
│  ┌─────────────┐     ┌─────────────────┐     ┌────────────────────────┐ │
│  │   Django    │     │      Kasm       │     │   Terraform Backend    │ │
│  │   Portal    │────▶│   Workspaces    │     │   (Step Functions)     │ │
│  │             │     │                 │     │                        │ │
│  │ • Auth      │     │ • Kali Desktop  │     │ • Provisions VPC       │ │
│  │ • Agent     │     │ • Cursor + MCPs │     │ • Spins up Victim VM   │ │
│  │   Upload    │     │ • Browser-based │     │ • Injects MCP config   │ │
│  └─────────────┘     └────────┬────────┘     └────────────────────────┘ │
│                               │                                          │
└───────────────────────────────┼──────────────────────────────────────────┘
                                │ SSH/MCP
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Per-DC Victim VPC (Terraform-provisioned)                              │
│                                                                          │
│  ┌───────────────────┐                                                  │
│  │   Victim VM       │                                                  │
│  │   (EC2)           │◀──── DC's XDR Agent (uploaded via portal)        │
│  │                   │                                                  │
│  │   • Blank canvas  │                                                  │
│  │   • AI configures │                                                  │
│  │     vulns on-fly  │                                                  │
│  └─────────┬─────────┘                                                  │
│            │                                                             │
│            ▼                                                             │
│     DC's XSIAM Tenant (alerts, detections)                              │
└─────────────────────────────────────────────────────────────────────────┘
```

### How It Works

1. **DC logs into portal** (paloaltonetworks.com email required)
2. **Uploads their XDR/XSIAM agent installer** (stored in S3)
3. **Clicks "Launch Range"** - selects which agent to use
4. **Backend provisions:**
   - Victim VPC + EC2 instance
   - Installs DC's agent on victim
   - Spins up Kasm container with Cursor + MCPs
   - Injects victim IP into MCP config
5. **DC gets browser link** to control workspace
6. **AI-driven scenarios:**
   - "Set up a PHP command injection vuln" → MCP configures victim
   - New chat: "Exploit the web server" → MCP attacks from Kali
   - XDR/XSIAM detects, DC shows customer

### Why This Architecture

| Component | Choice | Reason |
|-----------|--------|--------|
| Desktop Delivery | Kasm (containers) | Seconds to spin up, scales horizontally, browser-only access |
| Infra Provisioning | Terraform via backend | DCs don't touch IaC, platform orchestrates |
| Auth | Django + paloaltonetworks.com | Restrict to internal users |
| Victim VMs | Real EC2 | XDR agent requires real OS, not container |
| Scenario Setup | AI + MCP | Dynamic, not canned demos |

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

The authenticated area of the Django portal. Design matches the landing page aesthetic (cyberpunk/hacker theme).

### Design System

- **Colors**: neon pink (#FF1B6B), cyan (#00FFFF), purple (#7F00FF), deep blue (#0A0A1A)
- **Fonts**: Share Tech Mono (body), Orbitron (headings)
- **Effects**: glitch text, scanlines, noise texture, glow pulses

### Routes

| Route | Page | User Stories |
|-------|------|--------------|
| `/mission-control/` | Dashboard | US-2, US-3, US-4, US-5 |
| `/mission-control/agents/` | Agents | US-1, US-7 |
| `/mission-control/history/` | History | US-6 |
| `/mission-control/settings/` | Settings | US-8, US-9, US-10 |

### Layout Structure

```
┌─────────────────────────────────────────────────────────┐
│ SHIFTER // MISSION CONTROL           [user] [settings]  │  ← Header
├─────────────────────────────────────────────────────────┤
│ ┌───────┐                                               │
│ │ NAV   │  Main Content Area                            │
│ │       │                                               │
│ │ Home  │  (Dashboard / Agents / History / etc)         │
│ │ Agents│                                               │
│ │ History                                               │
│ │       │                                               │
│ └───────┘                                               │
└─────────────────────────────────────────────────────────┘
```

### Dashboard States

**No Active Range:**
```
┌─────────────────────────────────────────────────────────┐
│  RANGE STATUS                                           │
│  ┌─────────────────────────────────────────────────────┐│
│  │  ● No Active Range                                  ││
│  │                                                     ││
│  │  [Select Agent ▼]  [ LAUNCH RANGE ]                 ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

**Active Range:**
```
┌─────────────────────────────────────────────────────────┐
│  RANGE STATUS                                           │
│  ┌─────────────────────────────────────────────────────┐│
│  │  ● Range Active                                     ││
│  │  Agent: Acme Corp XSIAM                             ││
│  │  Victim: 10.0.1.42                                  ││
│  │  Started: 2h 34m ago                                ││
│  │                                                     ││
│  │  [ OPEN WORKSPACE ]  [ PAUSE ]  [ DESTROY ]         ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

**Paused Range:**
```
┌─────────────────────────────────────────────────────────┐
│  RANGE STATUS                                           │
│  ┌─────────────────────────────────────────────────────┐│
│  │  ● Range Paused                                     ││
│  │  Agent: Acme Corp XSIAM                             ││
│  │  Paused: 1d 3h ago                                  ││
│  │                                                     ││
│  │  [ RESUME ]  [ DESTROY ]                            ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Range Architecture Clarification

DC accesses a **control workspace** (Kasm container with Cursor + MCPs), not Kali directly:
- Control box: Cursor IDE with MCP servers configured
- MCPs connect to: Kali (attack box) + Victim (target)
- DC interacts with AI in Cursor; AI uses MCPs to execute commands

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

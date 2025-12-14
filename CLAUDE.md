# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AWS access:
DEV profile env var: PANW_SHIFTER_DEV_PROFILE
PROD profile env var: PANW_SHIFTER_PROD_PROFILE

## Project Overview

**Shifter** is a self-service cyber range platform. Users access a browser-based chat interface with MCPs to configure victims and run AI-driven attacks against XDR/XSIAM-protected targets.

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
│            Range table: user_id, status, kali_ip, victim_ip             │
└─────────────────────────────────────────────────────────────────────────┘
         │                                    │
         │ writes                             │ reads/writes
         ▼                                    ▼
┌─────────────────────┐            ┌─────────────────────────────┐
│       Portal        │            │    Provisioning Service     │
│     (Django)        │            │   (Step Functions + Lambda) │
│                     │            │                             │
│ • Auth (Cognito)    │──start───▶│ • create_subnet Lambda      │
│ • Agent upload      │ execution  │ • create_kali Lambda        │
│ • Launch range UI   │            │ • create_victim Lambda      │
│ • Show range status │            │ • Updates RDS directly      │
└─────────────────────┘            └─────────────────────────────┘
         │                                    │
         │                                    │ AWS APIs
         ▼                                    ▼
┌─────────────────────┐            ┌─────────────────────────────┐
│  Chat UI            │            │  Range VPC (10.1.0.0/16)    │
│  (shared instance)  │            │                             │
│                     │            │  Per-user subnet:           │
│ • Browser-based     │───SSH────▶│  • Kali EC2 (attack tools)  │
│ • MCP (hexstrike)   │   /MCP     │  • Victim EC2 (XDR agent)   │
│ • Agent loops       │            │                             │
└─────────────────────┘            └─────────────────────────────┘
                                              │
                                              ▼
                                   User's XSIAM Tenant (telemetry)
```

### How It Works

1. **User logs into Portal** (Cognito, paloaltonetworks.com email)
2. **Uploads XDR/XSIAM agent installer** (stored in S3)
3. **Clicks "Launch Range"** → Portal writes `Range(status='provisioning')` to DB, starts Step Functions
4. **Step Functions orchestrates Lambda functions:**
   - `create_subnet`: Creates /24 subnet in Range VPC
   - `create_kali`: Launches Kali EC2 from pre-baked AMI
   - `create_victim`: Launches Victim EC2, installs XDR agent from S3
   - Each Lambda updates RDS directly with resource IDs
5. **Portal shows "Ready"** → user clicks "Open Range", goes to Chat UI
6. **User interacts with AI in Chat:**
   - Uses hexstrike-ai MCP to control Kali instance
   - Runs attacks against Victim, XDR/XSIAM detects

### Why This Architecture

| Component | Choice | Reason |
|-----------|--------|--------|
| Chat UI | TBD | MCP support, agent loops, open source |
| Orchestration | Step Functions + Lambda | Reliable, retry logic, error handling |
| State | RDS only | Single source of truth, no message queues |
| Auth | Cognito | Same identity across Portal and Chat |
| Attack Tools | Kali EC2 | Full Linux with hexstrike-ai pre-installed |
| Victim VMs | Real EC2 | XDR agent requires real OS |

---

## Components

### 1. Django Portal

**Purpose**: Auth, agent management, range launch/status UI

**Responsibilities**:
- Cognito OIDC authentication
- Agent config CRUD (upload installer to S3)
- Write `Range(status='pending')` to DB on launch
- Display range status, link to agentic chat

Portal does NOT provision infrastructure. It writes requests to DB.

### 2. Provisioning Service

**Purpose**: Provision range infra (subnet, Kali, Victim EC2)

**Trigger**: Portal starts Step Functions execution with `{ range_id }`

**Lambda Functions**:
- `create_subnet`: Creates /24 subnet in Range VPC
- `create_kali`: Launches Kali EC2 from pre-baked AMI
- `create_victim`: Launches Victim EC2, installs XDR agent
- `mark_ready`: Updates Range status to 'ready'
- `cleanup`: Destroys resources on error

**Key Design**: Lambda functions run in Portal VPC, access RDS directly via IAM Database Auth, create Range resources via AWS APIs (no VPC peering needed).

### 3. Chat UI

**Purpose**: Browser-based chat UI with agent loop and MCP tool use

**Features needed**:
- MCP server integration (hexstrike-ai for Kali control)
- Multi-turn conversations with agent loops
- Chat history
- AWS Bedrock for Claude models

**Status**: Chat UI component is being evaluated. See GitHub issue #209.

### 4. MCP Servers

**Purpose**: Give AI tools to control Kali and run attacks

**Current**: Uses `hexstrike-ai` MCP for AI-driven pentesting, pre-installed on Kali AMI.

**Two-Context Pattern**:
- Chat 1: "Set up a vulnerable web server" → AI configures victim via Kali
- Chat 2: "Hack the target" → AI attacks (no memory of setup)

---

## Mission Control (Post-Login Portal)

The authenticated area of the Django portal. See full documentation:

- [docs/src/portal/index.md](docs/src/portal/index.md) - Pages, layout, user flows
- [docs/src/portal/design-system.md](docs/src/portal/design-system.md) - Colors, typography, effects
- [docs/src/portal/user-stories.md](docs/src/portal/user-stories.md) - User stories US-1 through US-10

**Key Routes:**

| Route | Page |
|-------|------|
| `/mission-control/` | Dashboard (launch/manage ranges) |
| `/mission-control/agents/` | Agent management |
| `/mission-control/history/` | Range history |
| `/mission-control/settings/` | Account settings |

**Architecture Note:** Portal handles auth and status display. Chat UI handles the actual AI chat interaction. User clicks "Open Range" → redirects to Chat URL.

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
- [ ] Provisioning service (watch DB, Terraform)
- [ ] Chat UI deployment with MCP integration
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

- `main` - Production releases, deploys to prod AWS environment
- `dev` - Integration branch, deploys to dev AWS environment
- `feature/*` - Feature branches for development work

**Branch Flow:** `feature/* → dev → main`

All changes flow through pull requests. GitHub Actions workflows handle deployment:
- PR to `dev` → deploys to dev environment on merge
- PR to `main` → deploys to prod environment on merge

### AWS Profiles

When working locally with AWS CLI or Terraform:
- `PANW_SHIFTER_DEV_PROFILE` - AWS profile for dev environment
- `PANW_SHIFTER_PROD_PROFILE` - AWS profile for prod environment

### Commit Protocol

**Git operations are user-only:**
1. NEVER make commits - the user will do it and sign them
2. NEVER create PRs - the user handles all PR creation
3. NEVER merge branches - the user controls all merges
4. NEVER deploy directly to prod - always go through `feature → dev → main` flow

---

## What NOT To Do

Per project rules:
- Do NOT add features not explicitly requested
- Do NOT create documentation for unbuilt features
- Do NOT assume requirements - ask for clarification
- Do NOT add "helpful" extras beyond the request
- Keep responses focused and concise
- Write for technical audience (no marketing language)

## Active Technologies
- Python 3.12 (per existing `pyproject.toml`) + Django 6.0, Django REST Framework (to add), existing mozilla-django-oidc (001-risk-register)
- PostgreSQL (existing RDS instance) (001-risk-register)

## Recent Changes
- 001-risk-register: Added Python 3.12 (per existing `pyproject.toml`) + Django 6.0, Django REST Framework (to add), existing mozilla-django-oidc

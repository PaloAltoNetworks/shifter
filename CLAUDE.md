# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AWS access:
DEV profile env var: PANW_SHIFTER_DEV_PROFILE
PROD profile env var: PANW_SHIFTER_PROD_PROFILE

## Project Overview

**Shifter** is a self-service cyber range platform. Users provision isolated attack environments with Kali and victim instances to run penetration tests and demos against XDR/XSIAM-protected targets.

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
│            Range table: user_id, status, instance details               │
└─────────────────────────────────────────────────────────────────────────┘
                           │
                           │ reads/writes
                           ▼
              ┌─────────────────────┐
              │       Portal        │
              │     (Django)        │
              │                     │
              │ • Auth (Cognito)    │
              │ • Agent upload      │
              │ • Launch range UI   │
              │ • Show range status │
              │ • Terminal access   │
              └─────────────────────┘
                         │
                         │ SSH via WebSocket
                         ▼
              ┌─────────────────────────────┐
              │  Range VPC (10.1.0.0/16)    │
              │                             │
              │  Per-user subnet:           │
              │  • Kali EC2 (attack tools)  │
              │  • Victim EC2 (XDR agent)   │
              │                             │
              └─────────────────────────────┘
                           │
                           ▼
                User's XSIAM Tenant (telemetry)
```

### How It Works

1. **User logs into Portal** (Cognito, paloaltonetworks.com email)
2. **Uploads XDR/XSIAM agent installer** (stored in S3)
3. **Clicks "Launch Range"** → Portal triggers provisioning
4. **Portal shows "Ready"** → user accesses range via browser-based terminal
5. **User runs attacks from Kali** → XDR/XSIAM detects

---

## Components

### 1. Django Portal

**Purpose**: Auth, agent management, range launch/status UI

**Responsibilities**:
- Cognito OIDC authentication
- Agent config CRUD (upload installer to S3)
- Trigger range provisioning on launch
- Display range status
- Browser-based terminal for SSH access

### 2. Terminal UI

**Purpose**: Browser-based terminal for SSH access to range instances

**Features**:
- WebSocket-based SSH via Django Channels
- Secure key retrieval from Secrets Manager
- Integrated into Portal (no separate app)

**Status**: Planned. See GitHub issue #261.

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

**Architecture Note:** Portal handles auth, status display, and terminal access. User clicks "Open Range" → opens browser-based terminal to Kali.

---

## File Structure

```
shifter/
├── CLAUDE.md                    # This file
├── LICENSE
├── README.md
├── CHANGELOG.md
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

## Implementation Phases

### Phase 1: Core Platform
- [x] Django portal (auth, agent upload, Mission Control UI)
- [x] Portal infrastructure (VPC, RDS, ALB, Cognito)
- [x] Range provisioning service
- [ ] Browser-based terminal for SSH access

### Phase 2: Polish
- [ ] Auto-destroy ranges after N hours
- [ ] Range status webhooks / polling

### Phase 3: Enhanced Features
- [ ] Windows victim option
- [ ] Multiple victim scenarios
- [ ] XSIAM API integration (verify detections)

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
- Python 3.12 + Django 5.x, mozilla-django-oidc
- PostgreSQL (RDS instance)
- Terraform for infrastructure

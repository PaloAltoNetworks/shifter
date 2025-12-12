# Mission Control

The authenticated area of the Shifter portal where DCs manage their ranges and agents.

## Overview

After authenticating via Cognito, users land in Mission Control - their command center for launching and managing cyber ranges. The interface maintains the same cyberpunk aesthetic as the landing page.

## Navigation Structure

```
/mission-control/           → Dashboard (default)
/mission-control/agents/    → Agent Management
/mission-control/history/   → Range History
/mission-control/settings/  → Account Settings
```

## Layout

```
┌─────────────────────────────────────────────────────────┐
│ SHIFTER // MISSION CONTROL           [user] [settings]  │
├─────────────────────────────────────────────────────────┤
│ ┌───────┐                                               │
│ │ NAV   │  Main Content Area                            │
│ │       │                                               │
│ │ Home  │                                               │
│ │ Agents│                                               │
│ │ History                                               │
│ │       │                                               │
│ └───────┘                                               │
└─────────────────────────────────────────────────────────┘
```

- **Header**: Logo, page title, user menu
- **Sidebar**: Navigation links (collapsible on mobile)
- **Content**: Page-specific content

## Pages

### Dashboard (`/mission-control/`)

Primary interface for range operations. Shows current range status and launch controls.

**States:**

1. **No Active Range** - Shows agent selector and launch button
2. **Provisioning** - Shows progress indicator during infrastructure spin-up
3. **Ready** - Shows range details with chat link, pause, and destroy options
4. **Paused** - Shows resume and destroy options

**User Stories:** US-2 (Launch), US-3 (Destroy), US-4 (Pause), US-5 (Resume)

### Agents (`/mission-control/agents/`)

Manage uploaded XDR/XSIAM agent installers.

**Features:**

- List all uploaded agents with metadata
- Upload new agent installer
- Rename existing agents
- Delete agents (with confirmation)
- View which ranges used each agent

**User Stories:** US-1 (First-Time Setup), US-7 (Manage Agents)

### History (`/mission-control/history/`)

View past range sessions.

**Columns:**

- Date created
- Agent used
- Status (destroyed, active, paused)
- Duration
- Actions (re-launch with same agent)

**User Stories:** US-6 (View History)

### Settings (`/mission-control/settings/`)

Account management.

**Sections:**

- **Account**: Email display (read-only, from Cognito)
- **Security**: Change password link (redirects to Cognito)
- **Danger Zone**: Delete account (with confirmation flow)

**User Stories:** US-8 (Logout), US-9 (Change Password), US-10 (Delete Account)

## Authentication Flow

1. User visits any `/mission-control/*` route
2. Django checks for valid session
3. If no session, redirect to Cognito hosted UI
4. After Cognito auth, redirect back to requested page
5. Django creates/updates local user record from JWT claims

Logout clears Django session and optionally redirects to Cognito logout.

## Range Lifecycle

```
┌──────────┐     ┌──────────────┐     ┌───────┐
│ No Range │────▶│ Provisioning │────▶│ Ready │
└──────────┘     └──────────────┘     └───────┘
                                          │
                      ┌───────────────────┼───────────────────┐
                      │                   │                   │
                      ▼                   ▼                   ▼
                 ┌────────┐          ┌───────┐          ┌───────────┐
                 │ Paused │◀────────▶│ Ready │─────────▶│ Destroyed │
                 └────────┘          └───────┘          └───────────┘
                      │                                       ▲
                      └───────────────────────────────────────┘
```

- **Provisioning**: Step Functions creating subnet, EC2, configuring LibreChat
- **Ready**: Range ready, chat interface accessible
- **Paused**: EC2 stopped (cost savings)
- **Destroyed**: All resources terminated

## Chat Interface

When a range is ready, the "Open Chat" button links to LibreChat with:

- **MCP access** to victim VM for command execution
- **AI agent** that can configure vulnerabilities or perform attacks
- **Isolation** - MCP hardcoded to victim IP, cannot escape subnet

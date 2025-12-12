# Mission Control

Portal UI for range and agent management. Authenticated users only (Cognito OIDC).

## Routes

```
/mission-control/           → Dashboard
/mission-control/agents/    → Agent management
/mission-control/history/   → Range history
/mission-control/settings/  → Account settings
/mission-control/help/      → Documentation
```

## UI Layout

```
┌───────────────────────────────────────┐
│ Header: Logo | Page | User           │
├───────┬───────────────────────────────┤
│ Nav   │ Content                       │
│       │                               │
└───────┴───────────────────────────────┘
```

Sidebar nav collapses on mobile. Base template: `templates/mission_control/base.html`.

## Dashboard

**Route**: `/mission-control/`

Range launch and status management.

**States**:
- No active range: agent selector + launch button
- Provisioning: spinner, status polling
- Ready: chat URL, destroy button
- Paused: resume + destroy buttons
- Failed: error message, destroy button

**API calls**:
- `GET /api/range/status/`: Poll current range
- `POST /api/range/launch/`: Create new range with `agent_id`
- `POST /api/range/destroy/`: Trigger teardown

## Agents

**Route**: `/mission-control/agents/`

Agent installer management (XDR/XSIAM packages).

**Operations**:
- Upload: Presigned S3 URL flow, client-side SHA256
- List: User's agents with size, OS, creation date
- Delete: Soft-delete (sets `deleted_at`)

**Upload flow**:
1. `POST /api/upload/initiate/`: Get presigned URL + token
2. Client: `PUT` to S3 directly
3. `POST /api/upload/complete/`: Verify + create AgentConfig record

**Limits**:
- Max file: 2GB
- User quota: 5GB
- Allowed: `.msi`, `.deb`, `.rpm`, `.sh`

## History

**Route**: `/mission-control/history/`

List of past ranges (all statuses). Read-only view.

**Columns**: Created, Agent, Status, Duration, Actions

## Settings

**Route**: `/mission-control/settings/`

Account info:
- Email (read-only from Cognito)
- Password change (redirects to Cognito)
- Account deletion (sets `UserProfile.deleted_at`)

## Authentication

**Flow**:
1. Unauthenticated request to `/mission-control/*`
2. Redirect to Cognito hosted UI (`/oauth2/authorize`)
3. User login + MFA
4. Callback to `/oidc/callback/` with auth code
5. Django exchanges code for JWT (userInfo endpoint)
6. User record upserted, session created
7. Redirect to original URL

**Logout**: Clears Django session, optionally redirects to Cognito `/logout` endpoint.

**Library**: `mozilla-django-oidc`

## Range Lifecycle

```
Pending → Provisioning → Ready → Destroying → Destroyed
                           ↓
                        Paused → Resuming → Ready
                           ↓
                        Failed
```

**Statuses** (in `Range.Status` enum):
- `PENDING`: Initial state before Step Functions trigger
- `PROVISIONING`: Lambda creating VPC + EC2 + LibreChat
- `READY`: Chat URL available, victim accessible
- `PAUSED`: Suspended (not implemented)
- `RESUMING`: Resuming from pause (not implemented)
- `DESTROYING`: Teardown in progress
- `DESTROYED`: Terminal state
- `FAILED`: Provisioning/teardown error

**Provisioning**:
1. `POST /api/range/launch/` → Create Range record, allocate subnet index
2. Invoke Step Functions state machine (ARN in `PROVISION_STATE_MACHINE_ARN`)
3. Lambda reads Range from RDS, provisions infra, updates `status`, `chat_url`, `victim_ip`

**Teardown**:
1. `POST /api/range/destroy/` → Set `status=DESTROYING`
2. Invoke teardown Step Functions (ARN in `TEARDOWN_STATE_MACHINE_ARN`)
3. Lambda destroys resources, sets `status=DESTROYED`

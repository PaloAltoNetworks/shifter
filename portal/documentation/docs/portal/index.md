# Portal

Django web application. Auth, agent management, range lifecycle, terminal access.

## Apps

| App | Purpose |
|-----|---------|
| `mission_control` | Main app - dashboard, agents, terminal, range API |
| `risk_register` | Security risk tracking (admin-only) |

## Routes

### Pages (`mission_control`)

| Route | View | Purpose |
|-------|------|---------|
| `/mission-control/` | `dashboard` | Launch/manage ranges |
| `/mission-control/agents/` | `agents` | List uploaded agents |
| `/mission-control/terminal/` | `terminal` | SSH access to range |
| `/mission-control/ngfw/` | `ngfw_configs` | Strata (NGFW) config management |
| `/mission-control/settings/` | `settings` | Account settings |
| `/mission-control/help/` | `help_page` | Help docs |

### API (`mission_control`)

| Route | Method | Purpose |
|-------|--------|---------|
| `/mission-control/api/range/status/` | GET | Current range status |
| `/mission-control/api/range/launch/` | POST | Launch new range (accepts `agent_id`, `scenario`, `ngfw_enabled`, `ngfw_config_id`) |
| `/mission-control/api/range/cancel/` | POST | Cancel provisioning range |
| `/mission-control/api/range/destroy/` | POST | Destroy range |
| `/mission-control/api/agents/` | GET | List agents for launch dropdown |
| `/mission-control/api/upload/initiate/` | POST | Get presigned S3 URL |
| `/mission-control/api/upload/complete/` | POST | Finalize upload |
| `/mission-control/api/upload/cancel/` | POST | Cancel upload |
| `/mission-control/api/ngfw-configs/` | GET | List NGFW configs for dropdown |
| `/mission-control/api/ngfw-configs/create/` | POST | Create new NGFW config |
| `/mission-control/api/ngfw-configs/<id>/delete/` | DELETE | Delete NGFW config |

## Authentication

Cognito OIDC via `mozilla-django-oidc`.

- Email as username
- MFA required (TOTP)
- Domain restricted to `@paloaltonetworks.com`

## Scenarios

Dashboard provides scenario dropdown for range configuration:

| Scenario | Instances | Use Case |
|----------|-----------|----------|
| Basic Range | Kali + Victim | Standard attack scenarios |
| AD Attack Lab | Kali + DC + domain-joined Victim | AD attacks, lateral movement |

Scenario selection maps to `instance_config` JSON stored in Range model.

## Terminal

Browser-based SSH via WebSocket (Django Channels + xterm.js).

| File | Purpose |
|------|---------|
| `consumers.py` | WebSocket consumer for SSH |
| `services/ssh.py` | Async SSH connection |
| `services/secrets.py` | Fetch SSH keys from Secrets Manager |
| `routing.py` | WebSocket URL routing |

WebSocket URL: `ws/terminal/<range_id>/<instance>/` where instance is `kali` or `victim`.

## Models

See [Architecture](../architecture.md) for model details.

## Services

| Service | Purpose |
|---------|---------|
| `services/provisioner.py` | Trigger ECS tasks |
| `services/ssh.py` | SSH connection management |
| `services/secrets.py` | Secrets Manager access |

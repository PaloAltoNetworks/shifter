# Portal Development

Django application for user authentication, agent management, and range lifecycle control.

## Local Setup

```bash
cd portal
cp .env.example .env
make init  # First time: starts services + creates superuser
make up    # Subsequent runs
```

Access: `http://localhost:8000`

## Commands

| Command | Purpose |
|---------|---------|
| `make up/down` | Start/stop services |
| `make build` | Rebuild container |
| `make logs` | View logs |
| `make shell` | Django shell |
| `make dbshell` | PostgreSQL shell |
| `make migrate` | Apply migrations |
| `make test` | Run pytest |
| `make clean` | Delete volumes |

## Architecture

### Local (docker-compose)
```
web (Django) → db (PostgreSQL 16)
Port 8000    → Port 5432
```

Web container: hot-reload mounts, auto-migrates on start, gunicorn with 2 workers.

### Production
```
ALB → EC2 (Django container) → RDS PostgreSQL
                             → S3 (agent uploads)
                             → Step Functions (provisioning)
                             → Cognito (auth)
```

**Secrets**: Fetched from AWS Secrets Manager at container startup via IMDSv2.
- DB credentials: `shifter-prod-portal-db-credentials`
- Django secret: `shifter-prod-portal-app`

**IAM**: EC2 instance role provides:
- `secretsmanager:GetSecretValue` on portal secrets
- `s3:*Object` on agent storage bucket
- `states:StartExecution` on Step Functions state machines

## Django App Structure

**mission_control** app:
- `models.py`: Range, AgentConfig, OperatingSystem, UserProfile, ActivityLog
- `views.py`: Dashboard, agents, API endpoints
- `services/`: S3 uploads, provisioner integration, validation
- `urls.py`: URL routing

**config** app:
- `settings.py`: Environment config, OIDC, AWS clients
- `urls.py`: Root routing
- `middleware.py`: Health check bypass for ALB
- `oidc.py`: Cognito integration

## Key Endpoints

| Path | Purpose |
|------|---------|
| `/mission-control/` | Dashboard |
| `/mission-control/agents/` | Agent management |
| `/mission-control/api/range/launch/` | Launch range (POST) |
| `/mission-control/api/range/status/` | Range status (GET) |
| `/mission-control/api/upload/initiate/` | Request presigned S3 URL |
| `/admin/` | Django admin |
| `/health/` | ALB health check |

## Authentication

**Local dev**: `/dev-login/` bypass (DEBUG=true only)

**Production**: Cognito OIDC flow
1. Unauthenticated request → redirect to Cognito hosted UI
2. User authenticates (email + MFA)
3. Cognito callback with authorization code
4. Django exchanges code for JWT
5. JWT validated, session created, user record upserted

Configuration: `mozilla-django-oidc` library, endpoints in `settings.py`.

## Dependencies

Add: `uv add <package>` → `make build`

Lock file: `uv.lock` (committed)

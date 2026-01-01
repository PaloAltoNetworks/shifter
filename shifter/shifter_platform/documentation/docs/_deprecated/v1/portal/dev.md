# Portal Development

Local development setup for the Django portal.

## Prerequisites

- Docker and Docker Compose
- Make

## Quick Start

**First time:**
```bash
cd portal
cp .env.example .env
make init
```

This creates your local environment file, starts the services, and prompts you to create an admin user.

**Every time after:**
```bash
cd portal
make up
```

Access the portal at [http://localhost:8000](http://localhost:8000).

## Available Commands

| Command | Description |
|---------|-------------|
| `make init` | First-time setup (starts services + creates superuser) |
| `make up` | Start services |
| `make down` | Stop services |
| `make build` | Rebuild and start |
| `make logs` | Tail web container logs |
| `make shell` | Django shell |
| `make dbshell` | PostgreSQL shell |
| `make migrate` | Run migrations |
| `make makemigrations` | Create new migrations |
| `make createsuperuser` | Create admin user |
| `make test` | Run tests |
| `make clean` | Stop and delete volumes |
| `make ps` | Show running containers |
| `make restart` | Restart web service |

## Environment Variables

The `.env` file configures the local development environment. Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `DJANGO_SECRET_KEY` | Django secret key | (set in .env.example) |
| `DJANGO_DEBUG` | Enable debug mode | `true` |
| `DJANGO_ALLOWED_HOSTS` | Allowed hosts | `localhost,127.0.0.1` |
| `DB_NAME` | Database name | `shifter` |
| `DB_USER` | Database user | `postgres` |
| `DB_PASSWORD` | Database password | (set in .env.example) |
| `DB_PORT` | Database port | `5432` |

Note: `DB_HOST` is set automatically by docker-compose (`db` for the web container).

## Endpoints

| Path | Description |
|------|-------------|
| `/admin/` | Django admin |
| `/health/` | Health check |

## Architecture

```
docker-compose.yml
├── db (postgres:16-alpine)
│   └── port 5432
└── web (portal image)
    └── port 8000
```

The web container:

- Mounts `./` to `/app` for hot reload
- Runs migrations on startup
- Starts gunicorn with 2 workers

## Adding Dependencies

```bash
cd portal
uv add <package>
make build
```

## Production Secrets

Production uses a different secrets flow than local development:

| Environment | Secrets Source |
|-------------|----------------|
| Local dev | `.env` file (local Postgres, no AWS) |
| Production | AWS Secrets Manager (fetched at container startup) |

### How Production Works

1. GitHub Actions deploys the container to EC2 via SSM
2. Container uses EC2 instance role credentials via IMDSv2 (hop limit=2)
3. `entrypoint.sh` detects `DB_SECRET_ARN` and `APP_SECRET_ARN` env vars
4. Fetches secrets from AWS Secrets Manager using boto3 (instance role creds)
5. Exports DB credentials and Django secret key before starting gunicorn

### Secrets Manager Structure

**DB Secret** (`shifter-prod-portal-db-credentials`):
```json
{
  "host": "...",
  "port": "5432",
  "dbname": "...",
  "username": "...",
  "password": "..."
}
```

**App Secret** (`shifter-prod-portal-app`):
```json
{
  "django_secret_key": "..."
}
```

### IAM

The container inherits EC2 instance role permissions:
- `secretsmanager:GetSecretValue` on `shifter-prod-portal-*` secrets
- `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on user storage bucket
- No static IAM user credentials needed

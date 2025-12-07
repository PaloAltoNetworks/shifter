# Portal Development

Local development setup for the Django portal.

## Prerequisites

- Docker and Docker Compose
- Make

## Quick Start

**First time:**
```bash
cd portal
make init
```

This starts the services and prompts you to create an admin user.

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

Copy `.env.example` to `.env` to customize:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `DJANGO_SECRET_KEY` | Django secret key | dev key |
| `DJANGO_DEBUG` | Enable debug mode | `true` |
| `DJANGO_ALLOWED_HOSTS` | Allowed hosts | `localhost,127.0.0.1` |
| `DB_HOST` | Database host | `db` |
| `DB_PORT` | Database port | `5432` |
| `DB_NAME` | Database name | `shifter` |
| `DB_USER` | Database user | `postgres` |
| `DB_PASSWORD` | Database password | `postgres` |

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

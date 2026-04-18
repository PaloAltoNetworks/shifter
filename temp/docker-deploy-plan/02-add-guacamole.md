# Phase 2: Add Guacamole Stack to Docker Compose

## Current State

- `shifter/engine/guacd/Dockerfile` - guacd with RDP file transfer support
- `shifter/engine/guacamole/Dockerfile` - guacamole client with schema init entrypoint
- Neither is in docker-compose.yml
- Django settings already read `GUACAMOLE_JSON_AUTH_SECRET`, `GUACAMOLE_BASE_URL`, `GUACAMOLE_API_BASE_URL`

## Changes

### 1. Add guacd service to docker-compose.yml

```yaml
guacd:
  build:
    context: ../engine/guacd
  restart: unless-stopped
```

No ports exposed - only guacamole-client talks to guacd.

### 2. Add guacamole-client service to docker-compose.yml

```yaml
guacamole:
  build:
    context: ../engine/guacamole
  environment:
    GUACD_HOSTNAME: guacd
    GUACD_PORT: 4822
    POSTGRESQL_HOSTNAME: db
    POSTGRESQL_PORT: 5432
    POSTGRESQL_DATABASE: ${GUACAMOLE_DB_NAME:-guacamole}
    POSTGRESQL_USER: ${GUACAMOLE_DB_USER:-guacamole_admin}
    POSTGRESQL_PASSWORD: ${GUACAMOLE_DB_PASSWORD}
    JSON_ENABLED: "true"
    JSON_SECRET_KEY: ${GUACAMOLE_JSON_AUTH_SECRET}
  depends_on:
    db:
      condition: service_healthy
    guacd:
      condition: service_started
  restart: unless-stopped
```

No ports exposed directly - nginx (Phase 4) will proxy `/guacamole` to this container.

### 3. Add Guacamole env vars to web service

```yaml
web:
  environment:
    GUACAMOLE_JSON_AUTH_SECRET: ${GUACAMOLE_JSON_AUTH_SECRET}
    GUACAMOLE_BASE_URL: /guacamole
    GUACAMOLE_API_BASE_URL: http://guacamole:8080/guacamole
```

`GUACAMOLE_BASE_URL` is what the browser sees (via nginx). `GUACAMOLE_API_BASE_URL` is how Django talks to Guacamole server-side for JSON auth token generation.

### 4. Update .env.example

```env
# Guacamole JSON auth (128-bit hex key)
# Generate with: python -c "import secrets; print(secrets.token_hex(16))"
GUACAMOLE_JSON_AUTH_SECRET=
```

## Build Context

Both Dockerfiles use `context` relative to the compose file location. The compose file is at `shifter/shifter_platform/docker-compose.yml`, so:
- guacd: `../engine/guacd`
- guacamole: `../engine/guacamole`

## Verification

- `docker compose up guacd guacamole` starts without errors
- Guacamole schema initialized in the shared Postgres
- `curl http://localhost:8080/guacamole/` returns Guacamole login page (temporarily expose port for testing)
- Django can generate JSON auth tokens and redirect to Guacamole

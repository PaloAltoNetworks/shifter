# Phase 1: Consolidate Guacamole onto Main Postgres

## Current State

- Prod has two RDS instances: one for Django, one for Guacamole
- Guacamole's entrypoint (`shifter/engine/guacamole/entrypoint.sh`) already handles idempotent schema init via `initdb.sh --postgresql | psql`
- Guacamole needs its own database and user within Postgres (its schema uses `guacamole_` prefixed tables)

## Changes

### 1. Add Guacamole DB init to Postgres container

Create an init script that runs on first Postgres startup to create the Guacamole database and user.

**File:** `shifter/shifter_platform/scripts/postgres-init/01-guacamole-db.sql`

```sql
-- Create Guacamole database and user (idempotent)
CREATE USER guacamole_admin WITH PASSWORD :'GUACAMOLE_DB_PASSWORD';
CREATE DATABASE guacamole OWNER guacamole_admin;
GRANT ALL PRIVILEGES ON DATABASE guacamole TO guacamole_admin;
```

Mount this into the Postgres container's `/docker-entrypoint-initdb.d/` directory.

### 2. Update docker-compose.yml

Add env vars for Guacamole DB credentials to the `db` service and mount the init script:

```yaml
db:
  image: postgres:16-alpine
  environment:
    POSTGRES_DB: ${DB_NAME}
    POSTGRES_USER: ${DB_USER}
    POSTGRES_PASSWORD: ${DB_PASSWORD}
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./scripts/postgres-init:/docker-entrypoint-initdb.d
```

### 3. Add env vars to .env.example

```env
GUACAMOLE_DB_NAME=guacamole
GUACAMOLE_DB_USER=guacamole_admin
GUACAMOLE_DB_PASSWORD=guac-local-password
```

## Notes

- Postgres `docker-entrypoint-initdb.d` scripts only run on first init (empty data volume). Existing volumes won't re-run. This is fine for our use case.
- The Guacamole entrypoint already handles schema creation, so the init script just needs to create the database and user.
- Django and Guacamole use separate databases within the same Postgres instance. No schema conflicts.

## Verification

- `docker compose up db` starts cleanly
- `psql -l` shows both `shifter` and `guacamole` databases
- Guacamole container can connect and init its schema

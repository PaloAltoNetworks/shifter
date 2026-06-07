#!/bin/bash
set -euo pipefail

# ------------------------------------------------------------------------------
# Fetch secrets from the active cloud secret manager (prod only)
# ------------------------------------------------------------------------------
# The fetch helper lives in entrypoint-lib.sh so tests in
# `tests/test_entrypoint_lib.sh` can exercise it without running the
# whole entrypoint. Sourcing it must succeed (`set -e` aborts the
# container otherwise) before any caller uses fetch_runtime_secret.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./entrypoint-lib.sh
source "$SCRIPT_DIR/entrypoint-lib.sh"

DB_SECRET_ID="${DB_SECRET_ID:-${DB_SECRET_ARN:-}}"
APP_SECRET_ID="${APP_SECRET_ID:-${APP_SECRET_ARN:-}}"
OIDC_SECRET_ID="${OIDC_SECRET_ID:-${OIDC_SECRET_ARN:-${COGNITO_SECRET_ARN:-}}}"
GUACAMOLE_SECRET_ID="${GUACAMOLE_SECRET_ID:-${GUACAMOLE_SECRET_ARN:-}}"
DC_DOMAIN_PASSWORD_SECRET_ID="${DC_DOMAIN_PASSWORD_SECRET_ID:-${DC_DOMAIN_PASSWORD_SECRET_ARN:-}}"

# NOTE: every secret-hydration line below uses the
#   VAR=...
#   export VAR
# pattern instead of `export VAR=...` so a non-zero exit inside the
# command substitution propagates through `set -e` and aborts the
# entrypoint. `export VAR=$(failing_cmd)` always returns 0 because
# `export` itself succeeds, which is what produced the silent
# DC_DOMAIN_PASSWORD=empty regression on the dev portal CMK (issue #52).
# The same hazard applies to the JSON-parsing python subshells: a
# missing field or malformed payload now fails the container start
# rather than exporting an empty required secret.

if [[ -n "${DB_SECRET_ID:-}" ]] && [[ -n "${APP_SECRET_ID:-}" ]]; then
    echo "Fetching runtime secrets from ${CLOUD_PROVIDER:-aws} secret manager..."

    # Fetch DB secret
    DB_SECRET=$(fetch_runtime_secret "$DB_SECRET_ID")

    # Export DB credentials. DB_HOST / DB_PORT can be overridden via env var;
    # the `${X:-...}` default still runs the command substitution when X is
    # empty, and its exit code now propagates because the assignment isn't
    # wrapped in `export`.
    DB_HOST=${DB_HOST:-$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['host'])")}
    export DB_HOST
    DB_PORT=${DB_PORT:-$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['port'])")}
    export DB_PORT
    DB_NAME=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['dbname'])")
    export DB_NAME
    DB_USER=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['username'])")
    export DB_USER
    DB_PASSWORD=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['password'])")
    export DB_PASSWORD

    # Fetch App secret
    APP_SECRET=$(fetch_runtime_secret "$APP_SECRET_ID")

    # Export Django secret key
    DJANGO_SECRET_KEY=$(echo "$APP_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['django_secret_key'])")
    export DJANGO_SECRET_KEY

    # Export field encryption key with proper base64 padding (Fernet requires it)
    FIELD_ENCRYPTION_KEY=$(echo "$APP_SECRET" | python -c "
import sys, json
key = json.load(sys.stdin)['field_encryption_key']
# Add padding if missing (base64 requires length % 4 == 0)
padding = (4 - len(key) % 4) % 4
print(key + '=' * padding)
")
    export FIELD_ENCRYPTION_KEY

    # Fetch OIDC secret if provided
    if [[ -n "${OIDC_SECRET_ID:-}" ]]; then
        OIDC_SECRET=$(fetch_runtime_secret "$OIDC_SECRET_ID")

        # Export OIDC credentials
        OIDC_RP_CLIENT_ID=$(echo "$OIDC_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['client_id'])")
        export OIDC_RP_CLIENT_ID
        OIDC_RP_CLIENT_SECRET=$(echo "$OIDC_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['client_secret'])")
        export OIDC_RP_CLIENT_SECRET
        OIDC_ISSUER_URL=$(echo "$OIDC_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['issuer_url'])")
        export OIDC_ISSUER_URL
        OIDC_AUTH_DOMAIN=$(echo "$OIDC_SECRET" | python -c "import sys, json; print(json.load(sys.stdin).get('domain', ''))")
        export OIDC_AUTH_DOMAIN
    fi

    # Fetch Guacamole JSON auth secret if provided (for RDP integration)
    if [[ -n "${GUACAMOLE_SECRET_ID:-}" ]]; then
        GUACAMOLE_JSON_AUTH_SECRET=$(fetch_runtime_secret "$GUACAMOLE_SECRET_ID")
        export GUACAMOLE_JSON_AUTH_SECRET
    fi

    echo "Secrets loaded successfully"
fi

# Fetch the prebaked DC Administrator password if provided. Guarded
# independently of the DB/app outer block so deployments that supply
# DC_DOMAIN_PASSWORD_SECRET_ARN without DB_SECRET_ID / APP_SECRET_ID
# (direct env-var configurations, non-portal entrypoint commands)
# still hydrate the value. The Windows-DC RDP credential lookup in
# engine.services depends on this env var being exported.
if [[ -n "${DC_DOMAIN_PASSWORD_SECRET_ID:-}" ]]; then
    DC_DOMAIN_PASSWORD=$(fetch_runtime_secret "$DC_DOMAIN_PASSWORD_SECRET_ID")
    export DC_DOMAIN_PASSWORD
fi

# Hydrate the Redis AUTH token and Memorystore server CA from Secret
# Manager when the GCP runtime advertises it (ADR-008-R6, #963).
# REDIS_SECRET_ID is rendered into the pod env by
# scripts/gcp/render_runtime_env.py; the token itself never travels via
# the runtime ConfigMap or generated env file. The payload is JSON (same
# shape as the DB bundle) and flows through stdin into `python -c` so
# the secret value is not exposed in process argv. The CA PEM is needed
# by Django Channels to verify the Memorystore server certificate when
# negotiating SERVER_AUTHENTICATION TLS — without it, the channels_redis
# connection would fail certificate verification.
if [[ -n "${REDIS_SECRET_ID:-}" ]]; then
    REDIS_SECRET=$(fetch_runtime_secret "$REDIS_SECRET_ID")
    REDIS_PASSWORD=$(echo "$REDIS_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['password'])")
    export REDIS_PASSWORD
    REDIS_CA_PEM=$(echo "$REDIS_SECRET" | python -c "import sys, json; print(json.load(sys.stdin).get('server_ca_cert', ''))")
    export REDIS_CA_PEM
    unset REDIS_SECRET
fi

# ------------------------------------------------------------------------------
# Wait for database
# ------------------------------------------------------------------------------

echo "Waiting for database..."
while ! python -c "
import os
import psycopg
try:
    psycopg.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=os.environ.get('DB_PORT', '5432'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASSWORD', 'postgres'),
        dbname=os.environ.get('DB_NAME', 'shifter'),
        connect_timeout=5
    )
    print('Database is ready')
except Exception as e:
    print(f'Database not ready: {e}')
    exit(1)
" 2>/dev/null; do
    echo "Database not ready, waiting..."
    sleep 2
done

# ------------------------------------------------------------------------------
# Django setup
# ------------------------------------------------------------------------------

# Run migrations (skip if SKIP_MIGRATIONS is set)
if [[ -z "${SKIP_MIGRATIONS:-}" ]]; then
    echo "Running migrations..."
    python manage.py migrate --noinput
else
    echo "Skipping migrations (SKIP_MIGRATIONS is set)"
fi

# Collect static files
echo "Compiling message catalogs..."
python manage.py compilemessages

echo "Collecting static files..."
python manage.py collectstatic --noinput

# Run command passed as arguments, or default to gunicorn + uvicorn workers.
#
# The production portal web process runs Gunicorn managing a pool of Uvicorn
# ASGI workers (issue #174). An unhandled exception in any WebSocket consumer
# only crashes one worker (which Gunicorn restarts) instead of taking down the
# whole single-process Daphne server. The worker-count, bind address, and
# timeouts are env-owned so AWS instance sizes and GCP pod limits can tune the
# pool without rebuilding the image. Defaults are conservative: 4 workers and
# a 90s timeout (Gunicorn's 30s default would kill long-lived WebSocket and
# SSH terminal connections that are the portal's main workload). The worker
# class string is `uvicorn_worker.UvicornWorker` (the supported standalone
# `uvicorn-worker` package) — `uvicorn.workers.UvicornWorker` is deprecated
# upstream. `tests/test_asgi_worker_smoke.py` pins the import contract in CI.
if [[ $# -gt 0 ]]; then
    echo "Running: $@"
    exec "$@"
else
    echo "Starting gunicorn (uvicorn workers)..."
    exec gunicorn config.asgi:application \
        --worker-class uvicorn_worker.UvicornWorker \
        --bind "${PORTAL_WEB_BIND:-0.0.0.0:8000}" \
        --workers "${PORTAL_WEB_WORKERS:-4}" \
        --timeout "${PORTAL_WEB_TIMEOUT:-90}" \
        --graceful-timeout "${PORTAL_WEB_GRACEFUL_TIMEOUT:-30}" \
        --access-logfile - \
        --error-logfile - \
        --log-level info
fi

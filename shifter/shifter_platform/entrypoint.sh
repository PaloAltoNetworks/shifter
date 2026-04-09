#!/bin/bash
set -euo pipefail

# ------------------------------------------------------------------------------
# Fetch secrets from the active cloud secret manager (prod only)
# ------------------------------------------------------------------------------

fetch_runtime_secret() {
    python - "$1" <<'PY'
import os
import sys

provider = os.environ.get("CLOUD_PROVIDER", "aws")
secret_id = sys.argv[1]

if provider == "gcp":
    from google.cloud import secretmanager

    name = secret_id
    if "/versions/" not in name:
        if name.startswith("projects/"):
            name = f"{name}/versions/latest"
        else:
            project_id = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
            if not project_id:
                raise RuntimeError("GCP_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required for Secret Manager access")
            name = f"projects/{project_id}/secrets/{name}/versions/latest"

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": name})
    print(response.payload.data.decode("utf-8"))
else:
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("CLOUD_REGION") or "us-east-2"
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_id)
    print(response["SecretString"])
PY
}

DB_SECRET_ID="${DB_SECRET_ID:-${DB_SECRET_ARN:-}}"
APP_SECRET_ID="${APP_SECRET_ID:-${APP_SECRET_ARN:-}}"
OIDC_SECRET_ID="${OIDC_SECRET_ID:-${OIDC_SECRET_ARN:-${COGNITO_SECRET_ARN:-}}}"
GUACAMOLE_SECRET_ID="${GUACAMOLE_SECRET_ID:-${GUACAMOLE_SECRET_ARN:-}}"

if [[ -n "${DB_SECRET_ID:-}" ]] && [[ -n "${APP_SECRET_ID:-}" ]]; then
    echo "Fetching runtime secrets from ${CLOUD_PROVIDER:-aws} secret manager..."

    # Fetch DB secret
    DB_SECRET=$(fetch_runtime_secret "$DB_SECRET_ID")

    # Export DB credentials
    # DB_HOST can be overridden via env var
    export DB_HOST=${DB_HOST:-$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['host'])")}
    export DB_PORT=${DB_PORT:-$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['port'])")}
    export DB_NAME=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['dbname'])")
    export DB_USER=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['username'])")
    export DB_PASSWORD=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['password'])")

    # Fetch App secret
    APP_SECRET=$(fetch_runtime_secret "$APP_SECRET_ID")

    # Export Django secret key
    export DJANGO_SECRET_KEY=$(echo "$APP_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['django_secret_key'])")

    # Export field encryption key with proper base64 padding (Fernet requires it)
    export FIELD_ENCRYPTION_KEY=$(echo "$APP_SECRET" | python -c "
import sys, json
key = json.load(sys.stdin)['field_encryption_key']
# Add padding if missing (base64 requires length % 4 == 0)
padding = (4 - len(key) % 4) % 4
print(key + '=' * padding)
")

    # Fetch OIDC secret if provided
    if [[ -n "${OIDC_SECRET_ID:-}" ]]; then
        OIDC_SECRET=$(fetch_runtime_secret "$OIDC_SECRET_ID")

        # Export OIDC credentials
        export OIDC_RP_CLIENT_ID=$(echo "$OIDC_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['client_id'])")
        export OIDC_RP_CLIENT_SECRET=$(echo "$OIDC_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['client_secret'])")
        export OIDC_ISSUER_URL=$(echo "$OIDC_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['issuer_url'])")
        export OIDC_AUTH_DOMAIN=$(echo "$OIDC_SECRET" | python -c "import sys, json; print(json.load(sys.stdin).get('domain', ''))")
    fi

    # Fetch Guacamole JSON auth secret if provided (for RDP integration)
    if [[ -n "${GUACAMOLE_SECRET_ID:-}" ]]; then
        export GUACAMOLE_JSON_AUTH_SECRET=$(fetch_runtime_secret "$GUACAMOLE_SECRET_ID")
    fi

    echo "Secrets loaded successfully"
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
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Run command passed as arguments, or default to daphne
if [[ $# -gt 0 ]]; then
    echo "Running: $@"
    exec "$@"
else
    echo "Starting daphne..."
    exec daphne config.asgi:application \
        --bind 0.0.0.0 \
        --port 8000 \
        --access-log - \
        --verbosity 1
fi

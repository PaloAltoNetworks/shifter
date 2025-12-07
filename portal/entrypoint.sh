#!/bin/bash
set -euo pipefail

# ------------------------------------------------------------------------------
# Fetch secrets from AWS Secrets Manager (prod only)
# ------------------------------------------------------------------------------

if [ -n "${DB_SECRET_ARN:-}" ] && [ -n "${APP_SECRET_ARN:-}" ]; then
    echo "Fetching secrets from AWS Secrets Manager..."

    # Fetch DB secret
    DB_SECRET=$(python -c "
import boto3
import json
import os

client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-2'))
response = client.get_secret_value(SecretId=os.environ['DB_SECRET_ARN'])
print(response['SecretString'])
")

    # Export DB credentials
    export DB_HOST=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['host'])")
    export DB_PORT=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['port'])")
    export DB_NAME=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['dbname'])")
    export DB_USER=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['username'])")
    export DB_PASSWORD=$(echo "$DB_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['password'])")

    # Fetch App secret
    APP_SECRET=$(python -c "
import boto3
import json
import os

client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-2'))
response = client.get_secret_value(SecretId=os.environ['APP_SECRET_ARN'])
print(response['SecretString'])
")

    # Export Django secret key
    export DJANGO_SECRET_KEY=$(echo "$APP_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['django_secret_key'])")

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

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start gunicorn
echo "Starting gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-30}" \
    --access-logfile - \
    --error-logfile - \
    --capture-output

#!/bin/bash
set -euo pipefail

# Wait for database
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

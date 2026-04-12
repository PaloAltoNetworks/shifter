#!/bin/bash
set -euo pipefail

# ------------------------------------------------------------------------------
# Guacamole Entrypoint Wrapper
# ------------------------------------------------------------------------------
# Initializes the PostgreSQL database schema if needed, then starts Guacamole.
# This runs on every container start but is idempotent - it checks if the
# schema exists before attempting initialization.

echo "Guacamole entrypoint starting..."

# ------------------------------------------------------------------------------
# Database Schema Initialization (idempotent)
# ------------------------------------------------------------------------------

# Check if we have PostgreSQL connection info
if [[ -n "${POSTGRESQL_HOSTNAME:-}" ]] && [[ -n "${POSTGRESQL_DATABASE:-}" ]]; then
    echo "Checking if Guacamole database schema exists..."

    # Build connection string
    export PGHOST="${POSTGRESQL_HOSTNAME}"
    export PGPORT="${POSTGRESQL_PORT:-5432}"
    export PGDATABASE="${POSTGRESQL_DATABASE}"
    export PGUSER="${POSTGRESQL_USER:-guacamole_admin}"
    export PGPASSWORD="${POSTGRESQL_PASSWORD:-}"

    # Check if schema exists by querying guacamole_user table
    if psql -c "SELECT 1 FROM guacamole_user LIMIT 1" >/dev/null 2>&1; then
        echo "Database schema already exists, skipping initialization"
    else
        echo "Database schema not found, initializing..."

        # Generate and apply schema
        /opt/guacamole/bin/initdb.sh --postgresql | psql

        if [[ $? -eq 0 ]]; then
            echo "Database schema initialized successfully"
        else
            echo "ERROR: Failed to initialize database schema"
            exit 1
        fi
    fi

    # Clean up
    unset PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD
else
    echo "PostgreSQL connection info not provided, skipping schema check"
fi

# ------------------------------------------------------------------------------
# Start Guacamole
# ------------------------------------------------------------------------------

echo "Starting Guacamole..."

# Only create a custom Guacamole home. The base image already ships the default
# home path, and recreating it fails under readOnlyRootFilesystem.
if [[ -n "${GUACAMOLE_HOME:-}" ]] && [[ "${GUACAMOLE_HOME}" != "/home/guacamole/.guacamole" ]]; then
    mkdir -p "${GUACAMOLE_HOME}"
fi

# Execute the original CMD from base image (passed as arguments when ENTRYPOINT is set)
exec "$@"

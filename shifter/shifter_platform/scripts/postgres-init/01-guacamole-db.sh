#!/bin/bash
set -e

GUAC_USER="${GUACAMOLE_DB_USER:-guacamole_admin}"
GUAC_PASS="${GUACAMOLE_DB_PASSWORD:-guacamole}"
GUAC_DB="${GUACAMOLE_DB_NAME:-guacamole}"

# Create user and database
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER ${GUAC_USER} WITH PASSWORD '${GUAC_PASS}';
    CREATE DATABASE ${GUAC_DB} OWNER ${GUAC_USER};
    GRANT ALL PRIVILEGES ON DATABASE ${GUAC_DB} TO ${GUAC_USER};
EOSQL

# PostgreSQL 15+ restricts CREATE on public schema to the database owner.
# Guacamole's initdb.sh creates tables in the public schema, so the
# guacamole_admin user needs explicit CREATE + USAGE grants on it.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$GUAC_DB" <<-EOSQL
    GRANT ALL ON SCHEMA public TO ${GUAC_USER};
EOSQL

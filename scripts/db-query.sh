#!/bin/bash
# Quick database query tool using psql
#
# Unlike db-connect.sh which requires psycopg, this uses psql directly
# and handles password escaping via a temporary .pgpass file.
#
# Prerequisites:
#   - AWS CLI configured
#   - psql installed
#   - Port forwarding running (start with: ./scripts/db-connect.sh -e <env>)
#
# Usage:
#   ./scripts/db-query.sh -e prod "SELECT COUNT(*) FROM auth_user"
#   ./scripts/db-query.sh -e dev "SELECT * FROM ranges_range LIMIT 5"
#   ./scripts/db-query.sh -e prod   # Interactive psql session

set -e

# Defaults
ENV="prod"
REGION="us-east-2"
LOCAL_PORT="15432"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENV="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-e|--env <dev|prod>] [SQL query]"
            echo ""
            echo "Examples:"
            echo "  $0 -e prod \"SELECT COUNT(*) FROM auth_user\""
            echo "  $0 -e dev   # Interactive session"
            exit 0
            ;;
        *)
            QUERY="$1"
            shift
            ;;
    esac
done

# Validate environment
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo "Error: Environment must be 'dev' or 'prod'"
    exit 1
fi

# Set profile based on environment
if [[ "$ENV" == "dev" ]]; then
    PROFILE="${PANW_SHIFTER_DEV_PROFILE:-}"
else
    PROFILE="${PANW_SHIFTER_PROD_PROFILE:-}"
fi

if [[ -z "$PROFILE" ]]; then
    echo "Error: AWS profile not set. Export PANW_SHIFTER_${ENV^^}_PROFILE"
    exit 1
fi

SECRET_ID="shifter-${ENV}-portal-db-credentials"

# Get credentials from Secrets Manager
echo "Fetching credentials from Secrets Manager..." >&2
CREDS=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_ID" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'SecretString' \
    --output text)

DB_USER=$(echo "$CREDS" | jq -r '.username')
DB_PASS=$(echo "$CREDS" | jq -r '.password')
DB_NAME=$(echo "$CREDS" | jq -r '.dbname')

# Create temporary pgpass file (handles special chars in password)
PGPASS_TMP=$(mktemp)
trap 'rm -f $PGPASS_TMP' EXIT

# Escape colons and backslashes in password for pgpass format
ESCAPED_PASS=$(echo "$DB_PASS" | sed 's/\\/\\\\/g; s/:/\\:/g')
echo "localhost:${LOCAL_PORT}:${DB_NAME}:${DB_USER}:${ESCAPED_PASS}" > "$PGPASS_TMP"
chmod 600 "$PGPASS_TMP"

export PGPASSFILE="$PGPASS_TMP"

# Run query or interactive session
if [[ -n "${QUERY:-}" ]]; then
    psql "host=localhost port=${LOCAL_PORT} dbname=${DB_NAME} user=${DB_USER} sslmode=require" -c "$QUERY"
else
    echo "Connecting to $ENV database..." >&2
    psql "host=localhost port=${LOCAL_PORT} dbname=${DB_NAME} user=${DB_USER} sslmode=require"
fi

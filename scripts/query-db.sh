#!/bin/bash
# Query the database
PROFILE="${PANW_SHIFTER_DEV_PROFILE}"
REGION="us-east-2"
SECRET_ID="shifter-dev-portal-db-credentials"

SECRET=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_ID" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'SecretString' \
    --output text)

DB_USER=$(echo "$SECRET" | jq -r '.username')
DB_PASS=$(echo "$SECRET" | jq -r '.password')

PGPASSWORD="$DB_PASS" psql -h localhost -p 15432 -U "$DB_USER" -d shifter -c "$1"

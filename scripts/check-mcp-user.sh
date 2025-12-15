#!/bin/bash
# Check mcp_user status in RDS

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

echo "Checking roles..."
PGPASSWORD="$DB_PASS" psql -h localhost -p 15432 -U "$DB_USER" -d shifter -c \
    "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname IN ('mcp_user', 'rds_iam', 'provisioner_lambda')"

echo ""
echo "Checking rds_iam membership..."
PGPASSWORD="$DB_PASS" psql -h localhost -p 15432 -U "$DB_USER" -d shifter -c \
    "SELECT r.rolname as role, m.rolname as member
     FROM pg_roles r
     JOIN pg_auth_members am ON r.oid = am.roleid
     JOIN pg_roles m ON am.member = m.oid
     WHERE r.rolname = 'rds_iam'"

echo ""
echo "Checking migrations..."
PGPASSWORD="$DB_PASS" psql -h localhost -p 15432 -U "$DB_USER" -d shifter -c \
    "SELECT name, applied FROM django_migrations WHERE app = 'mission_control' ORDER BY id DESC LIMIT 5"

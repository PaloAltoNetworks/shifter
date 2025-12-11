#!/bin/bash
# Connect to RDS PostgreSQL via SSM port forwarding
#
# Prerequisites:
#   - AWS CLI configured with dev-workstation-user profile
#   - AWS Session Manager plugin installed
#   - psycopg[binary] or psql installed locally
#
# Usage:
#   ./scripts/db-connect.sh          # Start port forwarding
#   ./scripts/db-connect.sh --query  # Run a query directly

set -e

PROFILE="dev-workstation-user"
REGION="us-east-2"
LOCAL_PORT="15432"
SECRET_ID="shifter-prod-portal-db-credentials"
EC2_TAG_NAME="prod-portal-ec2"

# Get EC2 instance ID
get_instance_id() {
    aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=${EC2_TAG_NAME}" "Name=instance-state-name,Values=running" \
        --query 'Reservations[0].Instances[0].InstanceId' \
        --output text \
        --region "$REGION" \
        --profile "$PROFILE"
}

# Get RDS endpoint
get_rds_endpoint() {
    aws rds describe-db-instances \
        --region "$REGION" \
        --profile "$PROFILE" \
        --query 'DBInstances[?contains(DBInstanceIdentifier, `portal`)].Endpoint.Address' \
        --output text
}

# Get DB credentials from Secrets Manager
get_credentials() {
    aws secretsmanager get-secret-value \
        --secret-id "$SECRET_ID" \
        --region "$REGION" \
        --profile "$PROFILE" \
        --query 'SecretString' \
        --output text
}

# Start port forwarding
start_port_forward() {
    local instance_id rds_host
    instance_id=$(get_instance_id)
    rds_host=$(get_rds_endpoint)

    echo "Instance ID: $instance_id"
    echo "RDS Host: $rds_host"
    echo "Starting port forwarding on localhost:${LOCAL_PORT}..."
    echo ""
    echo "In another terminal, run queries with:"
    echo "  ./scripts/db-connect.sh --query \"SELECT version()\""
    echo ""

    aws ssm start-session \
        --target "$instance_id" \
        --document-name AWS-StartPortForwardingSessionToRemoteHost \
        --parameters "{\"host\":[\"${rds_host}\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"${LOCAL_PORT}\"]}" \
        --region "$REGION" \
        --profile "$PROFILE"
}

# Run a query directly (requires port forwarding running in another terminal)
run_query() {
    local query="$1"
    python3 << EOF
import subprocess
import json
import psycopg

result = subprocess.run([
    'aws', 'secretsmanager', 'get-secret-value',
    '--secret-id', '${SECRET_ID}',
    '--region', '${REGION}',
    '--profile', '${PROFILE}',
    '--query', 'SecretString',
    '--output', 'text'
], capture_output=True, text=True)

secret = json.loads(result.stdout)

conn = psycopg.connect(
    host='localhost',
    port=${LOCAL_PORT},
    user=secret['username'],
    password=secret['password'],
    dbname=secret['dbname'],
    sslmode='require',
    autocommit=True
)

cur = conn.cursor()
cur.execute("""${query}""")
try:
    for row in cur.fetchall():
        print(row)
except psycopg.ProgrammingError:
    pass  # No results to fetch (INSERT/UPDATE/DELETE)
EOF
}

case "${1:-}" in
    --query)
        shift
        run_query "$*"
        ;;
    *)
        start_port_forward
        ;;
esac

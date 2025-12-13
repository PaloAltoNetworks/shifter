#!/bin/bash
# Connect to RDS PostgreSQL via SSM port forwarding
#
# Prerequisites:
#   - AWS CLI configured with dev-workstation-user profile
#   - AWS Session Manager plugin installed
#   - psycopg[binary] or psql installed locally
#
# Usage:
#   ./scripts/db-connect.sh                     # Start port forwarding (prod)
#   ./scripts/db-connect.sh -e dev              # Start port forwarding (dev)
#   ./scripts/db-connect.sh --query "SELECT 1"  # Run a query directly

set -e

# Defaults
ENV="dev"
REGION="us-east-2"
LOCAL_PORT="15432"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENV="$2"
            shift 2
            ;;
        --query)
            shift
            QUERY_MODE=1
            QUERY="$*"
            break
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [-e|--env <dev|prod>] [--query \"SQL\"]"
            exit 1
            ;;
    esac
done

# Validate environment
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo "Error: Environment must be 'dev' or 'prod'"
    exit 1
fi

# Set environment-specific values
SECRET_ID="shifter-${ENV}-portal-db-credentials"
EC2_TAG_NAME="${ENV}-portal-ec2"

# Profile depends on environment
if [[ "$ENV" == "dev" ]]; then
    PROFILE="panw-shifter-dev-workstation"
else
    PROFILE="dev-workstation-user"
fi

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
        --query "DBInstances[?contains(DBInstanceIdentifier, \`${ENV}-portal\`)].Endpoint.Address" \
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

    if [ "$instance_id" == "None" ] || [ -z "$instance_id" ]; then
        echo "Error: Could not find running ${ENV} portal EC2 instance"
        exit 1
    fi

    echo "Environment: $ENV"
    echo "Instance ID: $instance_id"
    echo "RDS Host: $rds_host"
    echo "Starting port forwarding on localhost:${LOCAL_PORT}..."
    echo ""
    echo "In another terminal, run queries with:"
    echo "  ./scripts/db-connect.sh -e $ENV --query \"SELECT version()\""
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

if [ "${QUERY_MODE:-}" == "1" ]; then
    run_query "$QUERY"
else
    start_port_forward
fi

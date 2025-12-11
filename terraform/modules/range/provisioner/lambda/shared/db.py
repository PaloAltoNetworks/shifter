"""
RDS IAM Authentication helper for provisioner Lambda functions.

Uses generate_db_auth_token() to connect without stored passwords.
"""

import os
import ssl
from pathlib import Path

import boto3
import psycopg

# Path to RDS CA bundle - bundled in Lambda layer
# AWS global bundle covers all regions: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html
RDS_CA_BUNDLE_PATH = Path(__file__).parent / "certs" / "global-bundle.pem"


def get_db_connection():
    """
    Create a database connection using IAM Database Authentication.

    Environment variables required:
    - DB_HOST: RDS endpoint
    - DB_PORT: RDS port (default 5432)
    - DB_NAME: Database name
    - DB_USER: PostgreSQL user (provisioner_lambda)
    - AWS_REGION: AWS region for token generation

    Returns:
        psycopg.Connection: Database connection
    """
    host = os.environ["DB_HOST"]
    port = int(os.environ.get("DB_PORT", "5432"))
    dbname = os.environ["DB_NAME"]
    user = os.environ.get("DB_USER", "provisioner_lambda")
    region = os.environ.get("AWS_REGION", "us-east-2")

    # Generate IAM auth token (valid for 15 minutes)
    rds_client = boto3.client("rds", region_name=region)
    token = rds_client.generate_db_auth_token(
        DBHostname=host,
        Port=port,
        DBUsername=user,
        Region=region,
    )

    # RDS requires SSL for IAM auth
    # Load AWS RDS CA bundle for proper certificate verification
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = True
    ssl_context.verify_mode = ssl.CERT_REQUIRED

    # Load RDS CA bundle if available, fall back to system CAs
    if RDS_CA_BUNDLE_PATH.exists():
        ssl_context.load_verify_locations(cafile=str(RDS_CA_BUNDLE_PATH))

    conn = psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=token,
        sslmode="verify-full",  # Full verification with CA bundle
        sslrootcert=str(RDS_CA_BUNDLE_PATH) if RDS_CA_BUNDLE_PATH.exists() else None,
        connect_timeout=10,
    )

    return conn


def get_range(conn, range_id: str) -> dict | None:
    """
    Fetch a Range record from the database.

    Args:
        conn: Database connection
        range_id: UUID of the range

    Returns:
        dict with range fields, or None if not found
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id, user_id, agent_config_id, status,
                subnet_id, subnet_cidr, subnet_index,
                victim_ip, victim_instance_id,
                chat_url, error_message,
                created_at, ready_at, destroyed_at,
                step_function_execution_arn
            FROM mission_control_range
            WHERE id = %s
            """,
            (range_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "user_id": row[1],
            "agent_config_id": row[2],
            "status": row[3],
            "subnet_id": row[4],
            "subnet_cidr": row[5],
            "subnet_index": row[6],
            "victim_ip": row[7],
            "victim_instance_id": row[8],
            "chat_url": row[9],
            "error_message": row[10],
            "created_at": row[11],
            "ready_at": row[12],
            "destroyed_at": row[13],
            "step_function_execution_arn": row[14],
        }


def get_agent_config(conn, agent_config_id: int) -> dict | None:
    """
    Fetch an AgentConfig record from the database.

    Args:
        conn: Database connection
        agent_config_id: ID of the agent config

    Returns:
        dict with agent config fields, or None if not found
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, s3_key, os_type_id
            FROM mission_control_agentconfig
            WHERE id = %s
            """,
            (agent_config_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "s3_key": row[2],
            "os_type_id": row[3],
        }


# Allowed fields for update_range() - prevents SQL injection via field names
ALLOWED_UPDATE_FIELDS = frozenset({
    "status",
    "subnet_id",
    "subnet_cidr",
    "victim_ip",
    "victim_instance_id",
    "chat_url",
    "error_message",
    "ready_at",
    "destroyed_at",
})


def validate_range_id(value) -> bool:
    """
    Validate that a value is a valid range_id (positive integer).

    The Range model uses BigAutoField (integer primary key), not UUID.
    """
    try:
        int_value = int(value)
        return int_value > 0
    except (TypeError, ValueError):
        return False


def update_range(conn, range_id: str, **fields) -> None:
    """
    Update specific fields on a Range record.

    Only allowed fields can be updated (enforced by whitelist and DB permissions):
    - status, subnet_id, subnet_cidr, victim_ip, victim_instance_id,
    - chat_url, error_message, ready_at, destroyed_at

    Args:
        conn: Database connection
        range_id: UUID of the range
        **fields: Field names and values to update

    Raises:
        ValueError: If range_id is not a valid UUID or field name is not allowed
    """
    if not fields:
        return

    # Validate range_id is a positive integer
    if not validate_range_id(range_id):
        raise ValueError(f"Invalid range_id format: {range_id}")

    # Validate field names against whitelist (prevents SQL injection)
    invalid_fields = set(fields.keys()) - ALLOWED_UPDATE_FIELDS
    if invalid_fields:
        raise ValueError(f"Invalid field names: {invalid_fields}")

    # Build SET clause - field names are now validated against whitelist
    set_parts = []
    values = []
    for field, value in fields.items():
        set_parts.append(f"{field} = %s")
        values.append(value)

    values.append(range_id)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE mission_control_range
            SET {', '.join(set_parts)}
            WHERE id = %s
            """,
            values,
        )
    conn.commit()

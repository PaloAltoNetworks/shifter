"""Container entrypoint for Shifter Engine.

This module is the main entry point when running the Shifter Engine container.
It handles:
- Database connection via RDS IAM authentication
- Range status updates in the Django database
- Pulumi stack creation, provisioning, and destruction
"""

import json
import logging
import os
import shutil
import subprocess  # nosec B404 - subprocess used for Pulumi CLI calls with hardcoded commands

import boto3
import psycopg

from events import (
    STATUS_AWAITING_ASSOCIATION,
    STATUS_DESTROYED,
    STATUS_DESTROYING,
    STATUS_FAILED,
    STATUS_PROVISIONING,
    STATUS_READY,
    publish_destroyed,
    publish_failed,
    publish_ngfw_event,
    publish_ready,
    publish_status_update,
)
from executors.aws_executor import AWSExecutor
from executors.ssh_executor import SSHExecutor
from orchestrators.ops_orchestrator import OpsOrchestrator
from orchestrators.setup_orchestrator import SetupOrchestrator

logger = logging.getLogger(__name__)

# Default timeout for waiting for NGFW SSH to become available (seconds)
# PAN-OS boot time is typically 15-25 minutes, but can take longer on first boot
NGFW_SSH_WAIT_TIMEOUT_DEFAULT = 3600  # 60 minutes


def get_vpc_gateway_ip(cidr: str) -> str:
    """Compute VPC gateway IP from CIDR (first IP + 1).

    AWS reserves the first IP (.0) for the network address and uses
    the second IP (.1) as the VPC gateway/router.

    Example: 10.1.4.0/22 -> 10.1.4.1

    Args:
        cidr: CIDR block string (e.g., "10.1.4.0/22")

    Returns:
        Gateway IP address string (e.g., "10.1.4.1")
    """
    import ipaddress

    network = ipaddress.ip_network(cidr, strict=False)
    return str(network.network_address + 1)


def _get_pulumi_path() -> str:
    """Get the full path to the pulumi executable."""
    path = shutil.which("pulumi")
    if not path:
        raise RuntimeError("pulumi executable not found in PATH")
    logger.debug("_get_pulumi_path: found pulumi at %s", path)
    return path


def _get_working_dir() -> str:
    """Get the working directory for Pulumi commands.

    In ECS container: /app
    In local dev: the provisioner directory (where this script lives)
    """
    # If DB_PASSWORD is set, we're running locally
    if os.environ.get("DB_PASSWORD"):
        return os.path.dirname(os.path.abspath(__file__))
    return "/app"


def get_db_connection() -> psycopg.Connection:
    """Get database connection.

    Supports two authentication modes:
    - If DB_PASSWORD is set: Uses standard password authentication (local dev)
    - Otherwise: Uses RDS IAM authentication (ECS/production)

    Returns:
        psycopg.Connection: Active database connection.

    Raises:
        Exception: If connection fails.
    """
    db_host = os.environ.get("DB_HOST")
    db_port = int(os.environ.get("DB_PORT", 5432))
    db_user = os.environ.get("DB_USER")
    db_name = os.environ.get("DB_NAME")
    db_password = os.environ.get("DB_PASSWORD")

    # Local dev mode: use password auth
    if db_password:
        if not all([db_host, db_user, db_name]):
            missing = [
                k
                for k, v in [
                    ("DB_HOST", db_host),
                    ("DB_USER", db_user),
                    ("DB_NAME", db_name),
                ]
                if not v
            ]
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

        logger.debug("get_db_connection: password auth to %s:%s/%s", db_host, db_port, db_name)
        return psycopg.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
        )

    # Production mode: use RDS IAM auth
    aws_region = os.environ.get("AWS_REGION")
    if not all([db_host, db_user, db_name, aws_region]):
        missing = [
            k
            for k, v in [
                ("DB_HOST", db_host),
                ("DB_USER", db_user),
                ("DB_NAME", db_name),
                ("AWS_REGION", aws_region),
            ]
            if not v
        ]
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    logger.debug("get_db_connection: RDS IAM auth to %s:%s/%s", db_host, db_port, db_name)
    client = boto3.client("rds")
    token = client.generate_db_auth_token(
        DBHostname=db_host,
        Port=db_port,
        DBUsername=db_user,
        Region=aws_region,
    )
    return psycopg.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=token,
        sslmode="require",
    )


def update_range_status(range_id: int, status: str, **kwargs: str | int | None) -> None:
    """Update range status in database.

    Args:
        range_id: The ID of the range to update.
        status: New status value (e.g., 'provisioning', 'ready', 'failed').
        **kwargs: Additional fields to update (e.g., subnet_id, error_message).
    """
    logger.debug("update_range_status: range_id=%s status=%s kwargs=%s", range_id, status, list(kwargs.keys()))
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            updates = ["status = %s", "updated_at = NOW()"]
            values: list = [status]

            for key, value in kwargs.items():
                if value is not None:
                    # Handle special SQL expressions
                    if value == "NOW()":
                        updates.append(f"{key} = NOW()")
                    else:
                        updates.append(f"{key} = %s")
                        values.append(value)

            values.append(range_id)
            # Security: Column names in 'updates' are from hardcoded kwargs keys in calling code,
            # not user input. Values are parameterized via %s placeholders.
            sql = f"UPDATE mission_control_range SET {', '.join(updates)} WHERE id = %s"  # nosec B608  # noqa: S608
            cur.execute(sql, values)
        conn.commit()


def _validate_pulumi_output_schema(output_data: dict) -> None:
    """Validate Pulumi stack outputs have expected structure.

    Args:
        output_data: Parsed JSON from `pulumi stack output --json`.

    Raises:
        ValueError: If required keys are missing or have wrong types.
    """
    if "subnets" not in output_data:
        raise ValueError("Pulumi outputs missing 'subnets' key")
    if not isinstance(output_data["subnets"], dict):
        raise ValueError("Pulumi 'subnets' must be a dict")

    if "instances" not in output_data:
        raise ValueError("Pulumi outputs missing 'instances' key")
    if not isinstance(output_data["instances"], list):
        raise ValueError("Pulumi 'instances' must be a list")


def _validate_provisioned_outputs(
    subnets: dict[str, dict],
    instances: list[dict],
    expected_subnet_names: set[str] | None = None,
) -> None:
    """Validate Pulumi outputs have required fields before DB write.

    Args:
        subnets: Dict of subnet_name -> subnet details.
        instances: List of instance dicts.
        expected_subnet_names: Optional set of expected subnet names from spec.

    Raises:
        ValueError: If required fields are missing or empty.
    """
    # Validate subnet data
    for subnet_name, subnet_data in subnets.items():
        subnet_uuid = subnet_data.get("uuid")
        if not subnet_uuid:
            raise ValueError(f"Subnet '{subnet_name}' missing required 'uuid'")

        subnet_id = subnet_data.get("subnet_id")
        if not subnet_id:
            raise ValueError(f"Subnet '{subnet_name}' missing 'subnet_id'")

        subnet_cidr = subnet_data.get("subnet_cidr")
        if not subnet_cidr:
            raise ValueError(f"Subnet '{subnet_name}' missing 'subnet_cidr'")

    # Validate instance data
    for i, inst in enumerate(instances):
        instance_uuid = inst.get("uuid")
        if not instance_uuid:
            raise ValueError(f"Instance[{i}] (role={inst.get('role')}) missing 'uuid'")

        instance_id = inst.get("instance_id")
        if not instance_id:
            raise ValueError(f"Instance[{i}] missing 'instance_id'")

    # Validate expected subnets were created
    if expected_subnet_names:
        actual_subnets = set(subnets.keys())
        missing = expected_subnet_names - actual_subnets
        if missing:
            raise ValueError(f"Expected subnets not created: {missing}")

        extra = actual_subnets - expected_subnet_names
        if extra:
            logger.warning("Unexpected subnets in output: %s", extra)


def write_provisioned_state(
    range_id: int,
    subnets: dict[str, dict],
    instances: list[dict],
    ngfw_instance_id: int | None = None,
) -> None:
    """Write provisioned infrastructure state directly to database.

    This follows the NGFW pattern: provisioner writes state directly to DB,
    events are notification-only.

    Args:
        range_id: The range ID being provisioned.
        subnets: Dict of subnet_name -> subnet details with uuid and AWS resource IDs.
        instances: List of instance dicts with uuid, instance_id, private_ip, etc.
        ngfw_instance_id: ID of the NGFW Instance this range is attached to (if any).
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Update engine_subnet.state for each subnet
            for subnet_name, subnet_data in subnets.items():
                subnet_uuid = subnet_data.get("uuid")
                if not subnet_uuid:
                    logger.warning("Subnet %s missing UUID, skipping DB write", subnet_name)
                    continue

                state = {
                    "aws_subnet_id": subnet_data.get("subnet_id"),
                    "aws_cidr": subnet_data.get("subnet_cidr"),
                    "aws_security_group_id": subnet_data.get("security_group_id"),
                    "aws_route_table_id": subnet_data.get("route_table_id"),
                }

                cur.execute(
                    """
                    UPDATE engine_subnet
                    SET state = %s, status = 'ready'
                    WHERE uuid = %s AND range_id = %s
                    """,
                    (json.dumps(state), subnet_uuid, range_id),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"No engine_subnet record found for uuid={subnet_uuid}, range_id={range_id}")
                logger.debug("Updated engine_subnet state: uuid=%s", subnet_uuid)

            # Update engine_instance records with provisioned state
            provisioned_instances = []
            for inst in instances:
                instance_uuid = inst.get("uuid")
                if not instance_uuid:
                    logger.warning(
                        "Instance (role=%s) missing UUID, skipping DB write",
                        inst.get("role", "unknown"),
                    )
                    continue

                # Build state dict with AWS resource details
                instance_state = {
                    "aws_instance_id": inst.get("instance_id"),
                    "private_ip": inst.get("private_ip"),
                    "ssh_key_secret_arn": inst.get("ssh_key_secret_arn"),
                    "subnet_name": inst.get("subnet_name"),
                }

                cur.execute(
                    """
                    UPDATE engine_instance
                    SET status = 'ready', state = %s
                    WHERE uuid = %s
                    """,
                    (json.dumps(instance_state), instance_uuid),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"No engine_instance record found for uuid={instance_uuid}")
                logger.debug("Updated engine_instance state: uuid=%s", instance_uuid)

                # Also build legacy provisioned_instances for Range.provisioned_instances
                provisioned_instances.append(
                    {
                        "uuid": instance_uuid,
                        "role": inst.get("role"),
                        "os_type": inst.get("os"),
                        "subnet_name": inst.get("subnet_name"),
                        "instance_id": inst.get("instance_id"),
                        "private_ip": inst.get("private_ip"),
                        "ssh_key_secret_arn": inst.get("ssh_key_secret_arn"),
                    }
                )

            # Update Range.provisioned_instances and ngfw_instance_id
            cur.execute(
                """
                UPDATE mission_control_range
                SET provisioned_instances = %s, ngfw_instance_id = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(provisioned_instances), ngfw_instance_id, range_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"No mission_control_range record found for id={range_id}")
            logger.debug(
                "Updated Range.provisioned_instances: range_id=%s count=%d",
                range_id,
                len(provisioned_instances),
            )

        conn.commit()
    logger.info(
        "Wrote provisioned state to DB: range_id=%s subnets=%d instances=%d",
        range_id,
        len(subnets),
        len(instances),
    )


def mark_range_instances_destroyed(range_id: int) -> tuple[int, int]:
    """Mark all engine_instance and engine_subnet records for a range as destroyed.

    Uses single UPDATE statements with subqueries to avoid race conditions between
    SELECT and UPDATE operations.

    Called after Pulumi destroy succeeds to update Instance and Subnet status.

    Args:
        range_id: The range ID that was destroyed.

    Returns:
        Tuple of (instance_count, subnet_count) marked as destroyed.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Single UPDATE with subquery - no race window between SELECT and UPDATE
            cur.execute(
                """
                UPDATE engine_instance
                SET status = 'destroyed', destroyed_at = NOW()
                WHERE uuid IN (
                    SELECT DISTINCT i.uuid
                    FROM engine_instance i
                    JOIN engine_request r ON i.request_id = r.id
                    JOIN mission_control_range rng ON rng.request_id = r.id
                    WHERE rng.id = %s
                )
                """,
                (range_id,),
            )
            instance_count = cur.rowcount
            logger.debug(
                "Marked %d engine_instance records as destroyed for range_id=%s",
                instance_count,
                range_id,
            )

            # Update engine_subnet records
            cur.execute(
                """
                UPDATE engine_subnet
                SET status = 'destroyed', destroyed_at = NOW()
                WHERE range_id = %s
                """,
                (range_id,),
            )
            subnet_count = cur.rowcount
            logger.debug(
                "Marked %d engine_subnet records as destroyed for range_id=%s",
                subnet_count,
                range_id,
            )

        conn.commit()
    logger.info(
        "Marked engine records as destroyed: range_id=%s instances=%d subnets=%d",
        range_id,
        instance_count,
        subnet_count,
    )
    return instance_count, subnet_count


def get_user_ngfw_data(user_id: int) -> dict | None:
    """Get NGFW data for a user (if they have one provisioned).

    Queries for a ready/active NGFW Instance belonging to this user.

    Args:
        user_id: Django User ID.

    Returns:
        Dictionary with ec2_instance_id, management_ip, ssh_key_secret_arn,
        and ngfw_request_id. Returns None if user has no NGFW.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                i.state,
                i.status
            FROM engine_instance i
            JOIN engine_request r ON i.request_id = r.id
            WHERE r.user_id = %s
              AND i.role = 'ngfw'
              AND i.status IN ('ready', 'active', 'stopped')
            ORDER BY i.created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        request_id = str(row[0])
        state = row[1] if row[1] else {}
        status = row[2]

        return {
            "ngfw_request_id": request_id,
            "ec2_instance_id": state.get("ec2_instance_id"),
            "management_ip": state.get("management_ip"),
            "ssh_key_secret_arn": state.get("ssh_key_secret_arn"),
            "status": status,
        }


def configure_ngfw_subnets(user_id: int, subnets: list[dict], range_id: int) -> None:
    """Configure user's NGFW with subnet routes, addresses and security rules.

    Starts the NGFW if stopped, waits for SSH, then runs the configure plan.

    Args:
        user_id: Django User ID who owns the NGFW.
        subnets: List of subnet dicts with 'name', 'cidr', 'connected_to'.
        range_id: Range ID for unique naming of routes/addresses/rules.

    Raises:
        ValueError: If user has no NGFW provisioned or NGFW_SUBNET_CIDR not set.
        RuntimeError: If NGFW configuration fails.
    """
    from plans.ngfw_configure_subnets import NGFWConfigureSubnetsPlan

    # Get VPC gateway IP from NGFW subnet CIDR
    ngfw_subnet_cidr = os.environ.get("NGFW_SUBNET_CIDR")
    if not ngfw_subnet_cidr:
        raise ValueError("NGFW_SUBNET_CIDR environment variable is required for subnet configuration")
    vpc_gateway_ip = get_vpc_gateway_ip(ngfw_subnet_cidr)
    logger.debug("configure_ngfw_subnets: vpc_gateway_ip=%s (from %s)", vpc_gateway_ip, ngfw_subnet_cidr)

    # Get user's NGFW
    ngfw_data = get_user_ngfw_data(user_id)
    if not ngfw_data:
        logger.warning("User %s has no NGFW, skipping subnet configuration", user_id)
        return

    ngfw_request_id = ngfw_data["ngfw_request_id"]
    management_ip = ngfw_data["management_ip"]
    ssh_key_secret_arn = ngfw_data["ssh_key_secret_arn"]
    status = ngfw_data["status"]

    if not management_ip or not ssh_key_secret_arn:
        logger.warning("NGFW missing management_ip or ssh_key, skipping config")
        return

    # Start NGFW if stopped
    if status == "stopped":
        logger.info("Starting stopped NGFW for subnet configuration...")
        run_ngfw_operation("start", ngfw_request_id)

    # Get SSH private key from Secrets Manager
    secrets_client = boto3.client("secretsmanager")
    secret_response = secrets_client.get_secret_value(SecretId=ssh_key_secret_arn)
    private_key = secret_response["SecretString"]

    # Create SSH executor and wait for NGFW to be ready
    ssh_executor = SSHExecutor(private_key=private_key)
    logger.info("Waiting for SSH on NGFW at %s...", management_ip)
    ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=300)

    # Build and execute the configure plan
    plan = NGFWConfigureSubnetsPlan()
    steps = plan.get_steps(subnets, range_id, vpc_gateway_ip)

    # Execute steps manually since they're dynamically generated
    for step in steps:
        logger.info("Executing NGFW config step: %s", step.name)
        result = ssh_executor.run_command(
            instance_id=management_ip,
            script=step.script,
            stdin_input=step.stdin_input,
            timeout_seconds=step.timeout_seconds,
        )
        if not result.success:
            raise RuntimeError(f"NGFW config step '{step.name}' failed: {result.stderr}")
        logger.info("NGFW config step '%s' completed", step.name)

    logger.info("NGFW subnet configuration complete for range %s", range_id)


def remove_ngfw_subnets(user_id: int, subnets: list[dict], range_id: int) -> None:
    """Remove subnet addresses and security rules from user's NGFW.

    Starts the NGFW if stopped, waits for SSH, then runs the remove plan.

    Args:
        user_id: Django User ID who owns the NGFW.
        subnets: List of subnet dicts with 'name' and 'connected_to'.
        range_id: Range ID for naming of addresses/rules to remove.

    Raises:
        RuntimeError: If NGFW configuration removal fails.
    """
    from plans.ngfw_configure_subnets import NGFWRemoveSubnetsPlan

    # Get user's NGFW
    ngfw_data = get_user_ngfw_data(user_id)
    if not ngfw_data:
        logger.warning("User %s has no NGFW, skipping subnet removal", user_id)
        return

    ngfw_request_id = ngfw_data["ngfw_request_id"]
    management_ip = ngfw_data["management_ip"]
    ssh_key_secret_arn = ngfw_data["ssh_key_secret_arn"]
    status = ngfw_data["status"]

    if not management_ip or not ssh_key_secret_arn:
        logger.warning("NGFW missing management_ip or ssh_key, skipping removal")
        return

    # NGFW should NEVER be stopped while ranges are active - this indicates a bug
    if status == "stopped":
        logger.error(
            "NGFW is stopped during range destroy - this should never happen! "
            "range_id=%s user_id=%s ngfw_request_id=%s. Skipping NGFW cleanup.",
            range_id,
            user_id,
            ngfw_request_id,
        )
        return

    # Get SSH private key from Secrets Manager
    secrets_client = boto3.client("secretsmanager")
    secret_response = secrets_client.get_secret_value(SecretId=ssh_key_secret_arn)
    private_key = secret_response["SecretString"]

    # Create SSH executor and wait for NGFW to be ready
    ssh_executor = SSHExecutor(private_key=private_key)
    logger.info("Waiting for SSH on NGFW at %s...", management_ip)
    ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=300)

    # Build and execute the remove plan
    plan = NGFWRemoveSubnetsPlan()
    steps = plan.get_steps(subnets, range_id)

    # Execute steps manually since they're dynamically generated
    for step in steps:
        logger.info("Executing NGFW remove step: %s", step.name)
        result = ssh_executor.run_command(
            instance_id=management_ip,
            script=step.script,
            stdin_input=step.stdin_input,
            timeout_seconds=step.timeout_seconds,
        )
        if not result.success:
            raise RuntimeError(f"NGFW remove step '{step.name}' failed: {result.stderr}")
        logger.info("NGFW remove step '%s' completed", step.name)

    logger.info("NGFW subnet removal complete for range %s", range_id)


def user_has_active_ranges(user_id: int, exclude_range_id: int) -> bool:
    """Check if user has any active ranges besides the one being destroyed.

    Args:
        user_id: Django User ID.
        exclude_range_id: Range ID to exclude from the check.

    Returns:
        True if user has other active ranges, False otherwise.
    """
    logger.debug("user_has_active_ranges: user_id=%s exclude_range_id=%s", user_id, exclude_range_id)
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM mission_control_range
            WHERE user_id = %s
              AND id != %s
              AND status IN ('ready', 'provisioning')
            """,
            (user_id, exclude_range_id),
        )
        row = cur.fetchone()
        count = row[0] if row else 0
        logger.debug("user_has_active_ranges: found %d active ranges", count)
        return count > 0


def get_ngfw_data_by_request_id(request_id: str) -> dict:
    """Read NGFW request and instance data from Engine database.

    Queries engine_request joined with engine_instance and engine_app
    to get all correlation IDs and instance data needed for provisioning.

    Args:
        request_id: UUID string of the Request.

    Returns:
        Dictionary with:
            - request_id: UUID string of the Request
            - instance_id: UUID string of the Instance
            - app_id: UUID string of the App (NGFW)
            - spec: JSON dict from Instance.spec
            - app_spec: JSON dict from App.spec (contains hydrated credentials)
            - state: JSON dict from Instance.state (Pulumi outputs, etc.)
            - status: Current Instance status

    Raises:
        ValueError: If Request or NGFW Instance not found.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                i.uuid AS instance_id,
                a.uuid AS app_id,
                i.spec,
                a.spec AS app_spec,
                i.state,
                i.status
            FROM engine_request r
            JOIN engine_instance i ON i.request_id = r.id
            LEFT JOIN engine_app a ON a.instance_id = i.id
            WHERE r.request_id = %s
              AND i.role = 'ngfw'
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"NGFW request not found: {request_id}")
        return {
            "request_id": str(row[0]),
            "instance_id": str(row[1]),
            "app_id": str(row[2]) if row[2] else None,
            "spec": row[3] if row[3] else {},
            "app_spec": row[4] if row[4] else {},
            "state": row[5] if row[5] else {},
            "status": row[6],
        }


def get_range_data_by_request_id(request_id: str) -> dict:
    """Read Range request data from Engine database.

    Queries engine_request joined with mission_control_range to get
    all correlation IDs and data needed for provisioning.

    Args:
        request_id: UUID string of the Request.

    Returns:
        Dictionary with:
            - request_id: UUID string of the Request
            - range_id: Integer ID of the Range
            - user_id: Django User ID
            - spec: JSON dict (range_config)
            - subnet_index: Allocated subnet index
            - status: Current Range status
            - ngfw_instance_id: ID of the NGFW Instance if ngfw is enabled and available

    Raises:
        ValueError: If Request or Range not found.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                rng.id AS range_id,
                rng.user_id,
                rng.range_config,
                rng.subnet_index,
                rng.status
            FROM engine_request r
            JOIN mission_control_range rng ON rng.request_id = r.id
            WHERE r.request_id = %s
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Range request not found: {request_id}")

        range_config = row[3] if row[3] else {}
        user_id = row[2]
        ngfw_instance_id = None

        # Look up NGFW instance ID if ngfw is enabled
        if range_config.get("ngfw", False):
            cur.execute(
                """
                SELECT ei.id
                FROM engine_instance ei
                JOIN engine_request er ON ei.request_id = er.id
                WHERE er.user_id = %s
                  AND ei.role = 'ngfw'
                  AND ei.status = 'active'
                  AND ei.state->>'service_name' IS NOT NULL
                ORDER BY ei.created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            ngfw_row = cur.fetchone()
            if ngfw_row:
                ngfw_instance_id = ngfw_row[0]

        return {
            "request_id": str(row[0]),
            "range_id": row[1],
            "user_id": user_id,
            "spec": range_config,
            "subnet_index": row[4],
            "status": row[5],
            "ngfw_instance_id": ngfw_instance_id,
        }


def parse_serial_number(system_info_output: str) -> str | None:
    """Extract serial number from PAN-OS 'show system info' output.

    PAN-OS format includes a line like:
        serial: 007200001267

    Args:
        system_info_output: stdout from 'show system info' command.

    Returns:
        Serial number string if found and valid, None otherwise.
        Returns None for placeholder values like "unknown" or empty strings.
    """
    import re

    # Match "serial:" followed by the serial number value
    match = re.search(r"serial:\s*(\S+)", system_info_output, re.IGNORECASE)
    if not match:
        logger.warning("Serial number not found in system info output")
        return None

    serial = match.group(1).strip()

    # Reject placeholder/invalid values
    if not serial or serial.lower() in ("unknown", "none", "n/a", ""):
        logger.warning("Serial number is placeholder value: %s", serial)
        return None

    logger.info("Extracted NGFW serial number: %s", serial)
    return serial


def poll_for_serial_number(
    ssh_executor: "SSHExecutor",
    host: str,
    timeout_seconds: int = 600,
    poll_interval: int = 30,
) -> str:
    """Poll NGFW for serial number until it appears or timeout.

    License registration with Palo Alto CSP can take 10-20 minutes after boot.
    This function polls 'show system info' until a valid serial number appears.

    Args:
        ssh_executor: SSHExecutor instance for running commands.
        host: NGFW management IP address.
        timeout_seconds: Maximum time to wait for serial (default 10 min).
        poll_interval: Seconds between poll attempts (default 30s).

    Returns:
        Serial number string.

    Raises:
        RuntimeError: If serial not found within timeout.
    """
    import time

    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise RuntimeError(
                f"NGFW serial number not found after {timeout_seconds}s - license registration may have failed"
            )

        logger.info(
            "Polling for NGFW serial number... (%.0fs / %ds)",
            elapsed,
            timeout_seconds,
        )

        try:
            result = ssh_executor.run_command(
                instance_id=host,
                script="show system info",
                timeout_seconds=60,
            )
            serial = parse_serial_number(result.stdout)
            if serial:
                logger.info(
                    "NGFW serial number found after %.0fs: %s",
                    elapsed,
                    serial,
                )
                return serial

            logger.info("Serial not yet available, retrying in %ds...", poll_interval)

        except Exception as e:
            logger.warning("Error polling for serial (will retry): %s", e)

        time.sleep(poll_interval)


def parse_device_certificate_status(system_info_output: str) -> str | None:
    """Extract device certificate status from PAN-OS 'show system info' output.

    PAN-OS format includes a line like:
        device-certificate-status: Valid

    Args:
        system_info_output: stdout from 'show system info' command.

    Returns:
        Certificate status string if found (e.g., "Valid"), None otherwise.
    """
    import re

    match = re.search(r"device-certificate-status:\s*(\S+)", system_info_output, re.IGNORECASE)
    if not match:
        return None

    return match.group(1).strip()


def poll_for_serial_and_cert(
    ssh_executor: "SSHExecutor",
    host: str,
    timeout_seconds: int = 1800,
    poll_interval: int = 30,
) -> str:
    """Poll NGFW until both serial number AND device certificate are present.

    License registration and certificate provisioning can take 10-30 minutes
    after boot. This function polls until both are valid, tracking each
    independently since they may appear at different times.

    Args:
        ssh_executor: SSHExecutor instance for running commands.
        host: NGFW management IP address.
        timeout_seconds: Maximum time to wait (default 30 min).
        poll_interval: Seconds between poll attempts (default 30s).

    Returns:
        Serial number string when both serial and cert are valid.

    Raises:
        RuntimeError: If either check fails within timeout, with details
            on which check(s) failed.
    """
    import time

    start_time = time.time()
    serial_value = None
    cert_status = None

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            missing = []
            if not serial_value:
                missing.append("serial number")
            if cert_status != "Valid":
                missing.append(f"device certificate (status: {cert_status or 'not found'})")
            raise RuntimeError(f"NGFW verification failed after {timeout_seconds}s - missing: {', '.join(missing)}")

        logger.info(
            "Polling for NGFW serial and certificate... (%.0fs / %ds)",
            elapsed,
            timeout_seconds,
        )

        try:
            result = ssh_executor.run_command(
                instance_id=host,
                script="show system info",
                timeout_seconds=60,
            )

            # Debug: log raw output to diagnose parsing issues
            logger.debug("Raw SSH output (first 500 chars): %r", result.stdout[:500])

            # Parse both values from output
            serial_value = parse_serial_number(result.stdout)
            cert_status = parse_device_certificate_status(result.stdout)

            # Log current state
            serial_ok = bool(serial_value)
            cert_ok = cert_status == "Valid"

            if serial_ok and cert_ok:
                logger.info(
                    "NGFW verification complete after %.0fs: serial=%s, cert=%s",
                    elapsed,
                    serial_value,
                    cert_status,
                )
                assert serial_value is not None  # Guaranteed by serial_ok check
                return serial_value

            # Log what's still missing
            status_parts = []
            if serial_ok:
                status_parts.append(f"serial={serial_value}")
            else:
                status_parts.append("serial=waiting")
            if cert_ok:
                status_parts.append(f"cert={cert_status}")
            else:
                status_parts.append(f"cert={cert_status or 'waiting'}")

            logger.info(
                "NGFW not ready (%s), retrying in %ds...",
                ", ".join(status_parts),
                poll_interval,
            )

        except Exception as e:
            logger.warning("Error polling NGFW (will retry): %s", e)

        time.sleep(poll_interval)


def update_instance_state(request_id: str, status: str, **state_updates) -> None:
    """Update NGFW Instance and App status/state in Engine database.

    Updates both the engine_instance and engine_app records for the NGFW
    associated with the given request_id. This is the single source of truth
    for state - events are lightweight notifications only.

    Args:
        request_id: UUID string of the Request.
        status: New status value (e.g., 'provisioning', 'ready', 'failed', 'destroyed').
        **state_updates: Key-value pairs to merge into Instance.state JSON.
            Common keys: ec2_instance_id, management_ip, dataplane_ip,
            service_name, data_eni_id, pulumi_stack, error_message.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get instance id, app id, and current state
            cur.execute(
                """
                SELECT i.id, i.state, a.id
                FROM engine_request r
                JOIN engine_instance i ON i.request_id = r.id
                LEFT JOIN engine_app a ON a.instance_id = i.id
                WHERE r.request_id = %s
                  AND i.role = 'ngfw'
                """,
                (request_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"NGFW instance not found for request: {request_id}")

            instance_id = row[0]
            current_state = row[1] if row[1] else {}
            app_id = row[2]

            # Merge state updates into current state
            if state_updates:
                current_state.update(state_updates)

            # Update Instance with new status and merged state
            if status == STATUS_DESTROYED:
                cur.execute(
                    """
                    UPDATE engine_instance
                    SET status = %s, state = %s, updated_at = NOW(), destroyed_at = NOW()
                    WHERE id = %s
                    """,
                    (status, json.dumps(current_state), instance_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE engine_instance
                    SET status = %s, state = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, json.dumps(current_state), instance_id),
                )

            # Update App status (if app exists)
            if app_id:
                if status == STATUS_DESTROYED:
                    cur.execute(
                        """
                        UPDATE engine_app
                        SET status = %s, updated_at = NOW(), destroyed_at = NOW()
                        WHERE id = %s
                        """,
                        (status, app_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE engine_app
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (status, app_id),
                    )

        conn.commit()


def run_pulumi(operation: str, request_id: str) -> None:
    """Run Pulumi operation.

    Args:
        operation: Either 'up' (provision) or 'destroy' (teardown).
        request_id: UUID string of the Request.

    Raises:
        Exception: If the Pulumi operation fails.
    """
    logger.info("run_pulumi: starting operation=%s request_id=%s", operation, request_id)

    # Fetch data from DB (matches NGFW pattern)
    range_data = get_range_data_by_request_id(request_id)
    range_id = range_data["range_id"]
    user_id = range_data["user_id"]

    stack_name = f"range-{range_id}"
    env = os.environ.copy()
    # Security: Empty passphrase is intentional - we use AWS KMS via PULUMI_SECRETS_PROVIDER.
    env["PULUMI_CONFIG_PASSPHRASE"] = ""  # nosec B105

    try:
        # Select or create stack with proper secrets provider
        _select_or_create_stack(stack_name, env)

        # Set stack configuration from environment
        _set_stack_config(env, range_id)

        if operation == "up":
            _run_provision(request_id, range_id, user_id, stack_name, env)
        elif operation == "destroy":
            _run_destroy(request_id, range_id, user_id, stack_name, env)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    except Exception as e:
        error_msg = str(e)[:1000]
        logger.error(f"Operation failed: {error_msg}")

        if operation == "up":
            # Auto-cleanup on failure to avoid orphaned resources
            logger.info("Provision failed - attempting auto-cleanup...")
            subprocess.run(
                ["pulumi", "destroy", "--yes", "--non-interactive"],  # noqa: S607
                cwd=_get_working_dir(),
                env=env,
                capture_output=True,
            )

        # Publish failed event
        publish_failed(request_id=request_id, range_id=range_id, user_id=user_id, error_message=error_msg)
        raise


def _select_or_create_stack(stack_name: str, env: dict) -> None:
    """Select an existing stack or create a new one with the KMS secrets provider.

    `pulumi stack select --create` does not honor PULUMI_SECRETS_PROVIDER for new
    stacks. We must use `pulumi stack init --secrets-provider` to ensure new stacks
    use KMS encryption instead of the default passphrase provider.

    Args:
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.

    Raises:
        Exception: If stack selection/creation fails.
    """
    logger.info(f"Selecting stack: {stack_name}")

    # Try to select existing stack
    result = subprocess.run(  # noqa: S603
        ["pulumi", "stack", "select", stack_name],  # noqa: S607
        cwd=_get_working_dir(),
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        logger.info(f"Selected existing stack: {stack_name}")
        return

    # Stack doesn't exist - create with explicit secrets provider
    # PULUMI_SECRETS_PROVIDER env var is NOT honored by `stack init` without --secrets-provider
    # The env var is set by the ECS task definition to use our dedicated KMS CMK
    secrets_provider = os.environ.get("PULUMI_SECRETS_PROVIDER")
    if not secrets_provider:
        raise ValueError("PULUMI_SECRETS_PROVIDER environment variable is required")
    logger.info(f"Creating new stack with secrets provider: {secrets_provider}")

    result = subprocess.run(  # noqa: S603
        [
            _get_pulumi_path(),
            "stack",
            "init",
            stack_name,
            "--secrets-provider",
            secrets_provider,
        ],
        cwd=_get_working_dir(),
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Stack creation failed: {result.stderr}")

    logger.info(f"Created new stack: {stack_name}")


def _set_stack_config(env: dict, range_id: int) -> None:
    """Set Pulumi stack configuration from environment variables.

    All config values are explicitly set or removed to prevent stale values
    from persisting across runs (e.g., old AMI IDs from previous deployments).

    Args:
        env: Environment dictionary for subprocess.
        range_id: The range ID to configure.
    """
    config_values = {
        "rangeId": str(range_id),
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "rangeVpcId": os.environ.get("RANGE_VPC_ID", ""),
        "rangeVpcCidr": os.environ.get("RANGE_VPC_CIDR", ""),
        "rangeRouteTableId": os.environ.get("RANGE_ROUTE_TABLE_ID", ""),
        "availabilityZone": os.environ.get("RANGE_AVAILABILITY_ZONE", ""),
        "rangeInstanceProfileName": os.environ.get("RANGE_INSTANCE_PROFILE_NAME", ""),
        "kaliAmiId": os.environ.get("KALI_AMI_ID", ""),
        "victimAmiId": os.environ.get("VICTIM_AMI_ID", ""),
        "windowsAmiId": os.environ.get("WINDOWS_AMI_ID", ""),
        "dcAmiId": os.environ.get("DC_AMI_ID", ""),
        "agentS3Bucket": os.environ.get("AGENT_S3_BUCKET", ""),
        "s3EndpointId": os.environ.get("S3_ENDPOINT_ID", ""),
        "firewallEndpointId": os.environ.get("FIREWALL_ENDPOINT_ID", ""),
        "portalVpcCidr": os.environ.get("PORTAL_VPC_CIDR", ""),
        "portalVpcPeeringId": os.environ.get("PORTAL_VPC_PEERING_ID", ""),
    }

    for key, value in config_values.items():
        if value:
            subprocess.run(  # noqa: S603
                ["pulumi", "config", "set", key, value],  # noqa: S607
                cwd=_get_working_dir(),
                env=env,
                capture_output=True,
            )
        else:
            # Remove empty config values to prevent stale values from persisting
            subprocess.run(  # noqa: S603
                ["pulumi", "config", "rm", key],  # noqa: S607
                cwd=_get_working_dir(),
                env=env,
                capture_output=True,
                # Ignore errors - key may not exist
            )


def _run_provision(request_id: str, range_id: int, user_id: int, stack_name: str, env: dict) -> None:
    """Run Pulumi up to provision the range.

    The sequence is:
    1. Run Pulumi up
    2. Validate outputs (fail early if incomplete)
    3. Configure NGFW (fail before marking ready)
    4. Write to DB (mark as ready)
    5. Publish ready event

    This ensures the range is NOT marked ready if NGFW configuration fails.

    Args:
        request_id: UUID string of the Request.
        range_id: The range ID being provisioned.
        user_id: The Django user ID who owns this range.
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    # Publish status change event
    publish_status_update(request_id=request_id, range_id=range_id, user_id=user_id, new_status="provisioning")
    logger.info("Running pulumi up...")

    result = subprocess.run(
        ["pulumi", "up", "--yes", "--non-interactive", "--skip-preview"],  # noqa: S607
        cwd=_get_working_dir(),
        env=env,
        capture_output=True,
        text=True,
    )

    logger.info(f"Pulumi stdout:\n{result.stdout}")
    if result.stderr:
        logger.warning(f"Pulumi stderr:\n{result.stderr}")

    if result.returncode != 0:
        raise RuntimeError(f"Pulumi up failed: {result.stderr}")

    # Get outputs
    logger.info("Retrieving stack outputs...")
    outputs = subprocess.run(
        ["pulumi", "stack", "output", "--json"],  # noqa: S607
        cwd=_get_working_dir(),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output_data = json.loads(outputs.stdout)
    logger.info(f"Stack outputs: {json.dumps(output_data, indent=2)}")

    # Validate output schema
    _validate_pulumi_output_schema(output_data)

    subnets_output = output_data.get("subnets", {})
    instances_output = output_data.get("instances", [])

    # Get range spec for validation and NGFW config
    range_data = get_range_data_by_request_id(request_id)
    range_spec = range_data.get("spec", {})
    spec_subnets = range_spec.get("subnets", [])
    expected_subnet_names = {s.get("name") for s in spec_subnets}

    # Validate outputs have all required fields
    _validate_provisioned_outputs(
        subnets=subnets_output,
        instances=instances_output,
        expected_subnet_names=expected_subnet_names,
    )

    # Configure NGFW BEFORE marking range as ready
    # If NGFW config fails, the range should NOT be marked ready
    subnets_for_ngfw = []
    for subnet_spec in spec_subnets:
        subnet_name = subnet_spec.get("name")
        subnet_output = subnets_output.get(subnet_name, {})
        cidr = subnet_output.get("subnet_cidr", "")
        if not cidr:
            raise ValueError(f"Subnet '{subnet_name}' has no CIDR - cannot configure NGFW")
        subnets_for_ngfw.append(
            {
                "name": subnet_name,
                "cidr": cidr,
                "connected_to": subnet_spec.get("connected_to", []),
            }
        )

    if subnets_for_ngfw:
        configure_ngfw_subnets(user_id, subnets_for_ngfw, range_id)

    # Write provisioned state to DB - only after NGFW is configured
    write_provisioned_state(
        range_id=range_id,
        subnets=subnets_output,
        instances=instances_output,
        ngfw_instance_id=range_data.get("ngfw_instance_id"),
    )

    # Publish notification-only ready event
    publish_ready(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
    )


def _run_destroy(request_id: str, range_id: int, user_id: int, stack_name: str, env: dict) -> None:
    """Run Pulumi destroy to tear down the range.

    This function is designed to be idempotent: if Pulumi destroy succeeds,
    the database records are marked as destroyed even if subsequent steps fail.

    Pre-destroy validation ensures we don't attempt to destroy ranges that are
    already in a terminal state or don't exist.

    Args:
        request_id: UUID string of the Request.
        range_id: The range ID being destroyed.
        user_id: The Django user ID who owns this range.
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    # Pre-destroy validation: verify range exists and is in a destroyable state
    try:
        range_data = get_range_data_by_request_id(request_id)
    except ValueError as e:
        logger.warning("Range not found for request %s, skipping destroy: %s", request_id, e)
        return

    current_status = range_data.get("status")
    if current_status in ("destroyed", "failed"):
        logger.info(
            "Range %d already in terminal state '%s', skipping destroy",
            range_id,
            current_status,
        )
        return

    # Get subnet specs from range_config for NGFW removal
    range_spec = range_data.get("spec", {})
    spec_subnets = range_spec.get("subnets", [])

    if spec_subnets:
        try:
            remove_ngfw_subnets(user_id, spec_subnets, range_id)
        except Exception as e:
            # Log but continue with destroy - don't leave AWS resources orphaned
            logger.warning("NGFW subnet removal failed (continuing with destroy): %s", e)

    logger.info("Running pulumi destroy...")

    pulumi_succeeded = False
    try:
        result = subprocess.run(  # noqa: S603
            [
                _get_pulumi_path(),
                "destroy",
                "--yes",
                "--non-interactive",
                "--skip-preview",
            ],
            cwd=_get_working_dir(),
            env=env,
            capture_output=True,
            text=True,
        )

        logger.info(f"Pulumi stdout:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"Pulumi stderr:\n{result.stderr}")

        if result.returncode != 0:
            raise RuntimeError(f"Pulumi destroy failed: {result.stderr}")

        pulumi_succeeded = True

        # Remove stack
        logger.info(f"Removing stack: {stack_name}")
        subprocess.run(  # noqa: S603
            ["pulumi", "stack", "rm", stack_name, "--yes"],  # noqa: S607
            cwd=_get_working_dir(),
            env=env,
            check=True,
            capture_output=True,
        )

    finally:
        # Always mark DB records as destroyed if Pulumi succeeded
        # This ensures DB state is updated even if stack removal fails
        if pulumi_succeeded:
            try:
                mark_range_instances_destroyed(range_id)
            except Exception as e:
                logger.error("Failed to mark range %d as destroyed in DB: %s", range_id, e)
                # Don't raise - AWS resources are gone, DB inconsistency is better than stuck

        # Always attempt NGFW auto-stop (soft fail)
        try:
            if not user_has_active_ranges(user_id, range_id):
                ngfw_data = get_user_ngfw_data(user_id)
                if ngfw_data and ngfw_data["status"] == "active":
                    logger.info("No other active ranges for user %s, stopping NGFW", user_id)
                    run_ngfw_operation("stop", ngfw_data["ngfw_request_id"])
        except Exception as e:
            logger.warning("Failed to stop NGFW (non-fatal): %s", e)

    # Publish destroyed event only on full success
    publish_destroyed(request_id=request_id, range_id=range_id, user_id=user_id)


def run_ngfw_operation(operation: str, request_id: str, **kwargs: str) -> None:
    """Run NGFW runtime operation (start/stop/complete-setup).

    Retrieves EC2 instance ID from the Instance.state (populated during Pulumi
    provisioning), executes the operation plan, and publishes events for status
    updates.

    Args:
        operation: Operation name (start, stop, complete-setup).
        request_id: UUID string of the Request.
        **kwargs: Operation-specific parameters (overrides for context).

    Raises:
        ValueError: If unknown operation or EC2 instance ID not found.
        Exception: If operation fails.
    """
    logger.info("run_ngfw_operation: starting operation=%s request_id=%s", operation, request_id)
    if kwargs:
        logger.debug("run_ngfw_operation: kwargs=%s", list(kwargs.keys()))

    # Handle complete-setup as special case (requires AWS + SSH hybrid execution)
    if operation == "complete-setup":
        _run_complete_setup(request_id)
        return

    from events import publish_ngfw_event

    # Status transitions for each operation
    status_map = {
        "start": ("starting", "active"),
        "stop": ("stopping", "stopped"),
    }

    if operation not in status_map:
        raise ValueError(f"Unknown operation: {operation}")

    # Get NGFW data from database including state with EC2 instance ID
    ngfw_data = get_ngfw_data_by_request_id(request_id)
    instance_uuid = ngfw_data["instance_id"]  # Our UUID, not AWS instance ID
    app_id = ngfw_data["app_id"]
    state = ngfw_data.get("state", {})

    # EC2 instance ID is stored in state after Pulumi provisioning
    ec2_instance_id = state.get("ec2_instance_id")
    if not ec2_instance_id:
        raise ValueError(f"EC2 instance ID not found in state for request: {request_id}")

    in_progress_status, success_status = status_map[operation]

    # Update DB and publish event for in-progress status
    update_instance_state(request_id, in_progress_status)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_uuid,
        app_id=app_id,
        status=in_progress_status,
    )

    try:
        # Create executor and orchestrator
        executor = AWSExecutor()
        orchestrator = OpsOrchestrator(executor)

        # Load the appropriate plan
        plan_map = {
            "start": "plans.ngfw_start.NGFWStartPlan",
            "stop": "plans.ngfw_stop.NGFWStopPlan",
        }

        plan_path = plan_map[operation]
        module_path, class_name = plan_path.rsplit(".", 1)

        import importlib

        module = importlib.import_module(module_path)
        plan_class = getattr(module, class_name)
        plan = plan_class()

        # Build context dict with EC2 instance ID and any additional kwargs
        # NOTE ON NAMING: Plans use "instance_id" key for the AWS EC2 Instance ID
        # (e.g., "i-099ee928142d5f092"), NOT the Django Instance UUID.
        # This is a legacy naming convention that should eventually be renamed.
        context = {
            "instance_id": ec2_instance_id,  # AWS EC2 Instance ID (e.g., "i-...")
            **kwargs,
        }

        # Execute the plan - orchestrate(target_id, plan, context)
        result = orchestrator.orchestrate(ec2_instance_id, plan, context)

        if not result.success:
            # Log step errors for debugging
            for step_result in result.step_results:
                if not step_result.success:
                    logger.error(
                        "NGFW %s step %s failed: %s",
                        operation,
                        step_result.step_name,
                        step_result.stderr,
                    )
            raise RuntimeError(f"Operation {operation} failed")

        # Update DB and publish event for success status
        update_instance_state(request_id, success_status)
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_uuid,
            app_id=app_id,
            status=success_status,
        )

    except Exception as e:
        error_msg = str(e)[:1000]
        update_instance_state(request_id, STATUS_FAILED, error_message=error_msg)
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_uuid,
            app_id=app_id,
            status=STATUS_FAILED,
        )
        raise


def _run_complete_setup(request_id: str) -> None:
    """Complete NGFW setup after user associates device in SCM/XDR.

    This hybrid operation combines AWS (start instance) and SSH (license fetch,
    certificate verification) to finalize NGFW configuration after the user
    has manually associated the device in Strata Cloud Manager and XDR.

    Flow:
    1. Start NGFW if stopped, wait if in transitional state (AWS)
    2. Wait for SSH connectivity
    3. Fetch license (SSH) - retrieves Logging Service license from CDL
    4. Poll for valid device certificate (SSH)
    5. Mark NGFW as ready and auto-stop

    Args:
        request_id: UUID string of the Request.

    Raises:
        RuntimeError: If any step fails.
    """

    logger.info("_run_complete_setup: starting request_id=%s", request_id)

    # Get NGFW data from database
    ngfw_data = get_ngfw_data_by_request_id(request_id)
    instance_uuid: str = ngfw_data["instance_id"]
    app_id: str | None = ngfw_data["app_id"]
    state: dict = ngfw_data.get("state", {})
    current_status: str = ngfw_data.get("status", "")

    ec2_instance_id: str | None = state.get("ec2_instance_id")
    management_ip: str | None = state.get("management_ip")
    ssh_key_secret_arn: str | None = state.get("ssh_key_secret_arn")

    if not ec2_instance_id:
        raise RuntimeError(f"EC2 instance ID not found in state for request: {request_id}")
    if not management_ip:
        raise RuntimeError(f"Management IP not found in state for request: {request_id}")
    if not ssh_key_secret_arn:
        raise RuntimeError(f"SSH key secret ARN not found in state for request: {request_id}")

    # Warn if already in configuring state (possible retry of failed attempt)
    if current_status == "configuring":
        logger.warning(
            "_run_complete_setup: NGFW already in 'configuring' status, "
            "possibly retrying after previous failure: request_id=%s",
            request_id,
        )

    # Update status to configuring
    update_instance_state(request_id, "configuring")
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_uuid,
        app_id=app_id,
        status="configuring",
    )

    try:
        # 1. Start NGFW if stopped, wait if in transitional state
        aws_executor = AWSExecutor()
        result = aws_executor.describe_instance(ec2_instance_id)
        if not result.success:
            raise RuntimeError(f"Failed to describe instance: {result.stderr}")
        instance_data = json.loads(result.stdout)
        ec2_state: str = (
            instance_data.get("Reservations", [{}])[0].get("Instances", [{}])[0].get("State", {}).get("Name", "unknown")
        )
        logger.info("_run_complete_setup: EC2 instance state=%s", ec2_state)

        if ec2_state == "stopped":
            logger.info("_run_complete_setup: Starting stopped NGFW instance")
            aws_executor.start_instance(ec2_instance_id)
            aws_executor.wait_for_running(ec2_instance_id)
        elif ec2_state in ("pending", "stopping", "shutting-down"):
            # Instance is in a transitional state - wait for it to stabilize
            logger.info(
                "_run_complete_setup: Instance in transitional state '%s', waiting for stable state",
                ec2_state,
            )
            if ec2_state == "pending":
                aws_executor.wait_for_running(ec2_instance_id)
            elif ec2_state == "stopping":
                aws_executor.wait_for_stopped(ec2_instance_id)
                # Now start it
                logger.info("_run_complete_setup: Starting NGFW after it finished stopping")
                aws_executor.start_instance(ec2_instance_id)
                aws_executor.wait_for_running(ec2_instance_id)
            else:  # shutting-down
                raise RuntimeError(f"NGFW instance is shutting down (terminating): {ec2_instance_id}")
        elif ec2_state == "running":
            logger.info("_run_complete_setup: NGFW instance already running")
        elif ec2_state == "terminated":
            raise RuntimeError(f"NGFW instance has been terminated: {ec2_instance_id}")
        else:
            raise RuntimeError(f"NGFW instance in unexpected state: {ec2_state}")

        # 2. Wait for SSH connectivity
        logger.info("_run_complete_setup: Waiting for SSH on %s", management_ip)
        secrets_client = boto3.client("secretsmanager")
        secret_response = secrets_client.get_secret_value(SecretId=ssh_key_secret_arn)
        private_key: str = secret_response["SecretString"]

        ssh_executor = SSHExecutor(private_key=private_key)
        ssh_timeout = int(os.environ.get("NGFW_SSH_WAIT_TIMEOUT", NGFW_SSH_WAIT_TIMEOUT_DEFAULT))
        ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=ssh_timeout)

        # 3. Fetch license (retrieves Logging Service license after SCM association)
        logger.info("_run_complete_setup: Fetching license")
        license_result = ssh_executor.run_command(
            instance_id=management_ip,
            script="request license fetch",
            timeout_seconds=120,
        )
        if not license_result.success:
            logger.warning("License fetch returned non-success: %s", license_result.stderr)
            # Don't fail - license fetch may report errors even when successful

        logger.info(
            "License fetch output: %s",
            license_result.stdout[:500] if license_result.stdout else "(empty)",
        )

        # 4. Poll for valid device certificate
        # CSP certificate sync typically takes 10-30 minutes after license fetch.
        # Rather than sleeping a fixed time, poll with appropriate timeout.
        logger.info("_run_complete_setup: Polling for valid device certificate")
        poll_timeout = int(os.environ.get("NGFW_CERT_POLL_TIMEOUT", 2400))  # 40 min default
        serial_number = poll_for_serial_and_cert(
            ssh_executor=ssh_executor,
            host=management_ip,
            timeout_seconds=poll_timeout,
            poll_interval=30,
        )

        # 5. Update state and mark ready (only pass serial_number, not entire state)
        update_instance_state(request_id, STATUS_READY, serial_number=serial_number)
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_uuid,
            app_id=app_id,
            status=STATUS_READY,
            serial_number=serial_number,
        )

        logger.info("_run_complete_setup: NGFW marked as ready, serial=%s", serial_number)

        # 6. Auto-stop NGFW to save costs (soft failure - setup already succeeded)
        logger.info("_run_complete_setup: Auto-stopping NGFW")
        try:
            run_ngfw_operation("stop", request_id)
            logger.info("_run_complete_setup: Auto-stop completed successfully")
        except Exception:
            logger.exception(
                "_run_complete_setup: Auto-stop failed (non-fatal) - NGFW remains running: request_id=%s",
                request_id,
            )
            # Don't re-raise - setup succeeded, stop failure is non-fatal

        logger.info("_run_complete_setup: Complete setup finished successfully")

    except Exception:
        logger.exception("_run_complete_setup failed: request_id=%s", request_id)
        error_msg = "Complete setup failed - check logs for details"
        update_instance_state(request_id, STATUS_FAILED, error_message=error_msg)
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_uuid,
            app_id=app_id,
            status=STATUS_FAILED,
        )
        raise


def run_ngfw_pulumi(operation: str, request_id: str) -> None:
    """Run NGFW Pulumi operation (provision or deprovision).

    Args:
        operation: Either 'up' (provision) or 'destroy' (deprovision).
        request_id: UUID string of the Request.

    Raises:
        ValueError: If unknown operation or Request not found.
        Exception: If the Pulumi operation fails.
    """
    logger.info("run_ngfw_pulumi: starting operation=%s request_id=%s", operation, request_id)

    # Get NGFW data from database (needed for correlation IDs and credentials)
    ngfw_data = get_ngfw_data_by_request_id(request_id)
    # NOTE: "instance_id" here is the Django Instance UUID (e.g., "5eb96281-a4a8-...")
    # NOT the AWS EC2 Instance ID. Variable named for event publishing compatibility.
    instance_id = ngfw_data["instance_id"]
    app_id = ngfw_data["app_id"]
    app_spec = ngfw_data.get("app_spec", {})

    # Use request_id for stack naming (deterministic from UUID)
    stack_name = f"ngfw-{request_id}"
    env = os.environ.copy()
    # Security: Empty passphrase is intentional - we use AWS KMS via PULUMI_SECRETS_PROVIDER.
    env["PULUMI_CONFIG_PASSPHRASE"] = ""  # nosec B105

    try:
        # Select or create stack with proper secrets provider
        _select_or_create_stack(stack_name, env)

        # Set NGFW stack configuration from environment and app_spec credentials
        _set_ngfw_stack_config(env, request_id, instance_id, app_spec)

        if operation == "up":
            _run_ngfw_provision(request_id, instance_id, app_id, stack_name, env)
        elif operation == "destroy":
            _run_ngfw_deprovision(request_id, instance_id, app_id, stack_name, env)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    except Exception as e:
        error_msg = str(e)[:1000]
        logger.error(f"NGFW operation failed: {error_msg}")

        if operation == "up":
            # Auto-cleanup on failure to avoid orphaned resources
            logger.info("NGFW provision failed - attempting auto-cleanup...")
            subprocess.run(
                ["pulumi", "destroy", "--yes", "--non-interactive"],  # noqa: S607
                cwd=_get_working_dir(),
                env=env,
                capture_output=True,
            )

        # Update local DB and emit failure event
        update_instance_state(request_id, STATUS_FAILED, error_message=error_msg)
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_id,
            app_id=app_id,
            status=STATUS_FAILED,
        )
        raise


def _set_ngfw_stack_config(env: dict, request_id: str, instance_uuid: str, app_spec: dict) -> None:
    """Set Pulumi stack configuration for NGFW from environment and app_spec.

    Infrastructure config (VPC, subnet, AMI, etc.) comes from environment variables.
    Credential config (PIN, authcode, folder) comes from app_spec (hydrated by CMS).

    Args:
        env: Environment dictionary for subprocess.
        request_id: UUID string of the Request.
        instance_uuid: UUID string of the Instance (for tagging/correlation).
        app_spec: Hydrated NGFWAppSpec dict containing credentials.
    """
    # Infrastructure config from environment (same for all NGFWs)
    config_values = {
        "requestId": request_id,
        "instanceUuid": instance_uuid,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "ngfwVpcId": os.environ.get("NGFW_VPC_ID", ""),
        "ngfwSubnetId": os.environ.get("NGFW_SUBNET_ID", ""),
        "ngfwMgmtSecurityGroupId": os.environ.get("NGFW_MGMT_SECURITY_GROUP_ID", ""),
        "ngfwDataSecurityGroupId": os.environ.get("NGFW_DATA_SECURITY_GROUP_ID", ""),
        "ngfwAmiId": os.environ.get("NGFW_AMI_ID", ""),
        "bootstrapBucket": os.environ.get("NGFW_BOOTSTRAP_BUCKET", ""),
        "ngfwInstanceType": os.environ.get("NGFW_INSTANCE_TYPE", "m5.xlarge"),
        "ngfwInstanceProfileName": os.environ.get("NGFW_INSTANCE_PROFILE_NAME", ""),
        # Credential config from app_spec (per-NGFW, hydrated by CMS)
        "scmPinId": app_spec.get("scm_pin_id", ""),
        "scmPinValue": app_spec.get("scm_pin_value", ""),
        "scmFolderName": app_spec.get("scm_folder_name", ""),
        "authcode": app_spec.get("authcode", ""),
        "userId": str(app_spec.get("user_id", "")),
    }

    for key, value in config_values.items():
        if value:
            subprocess.run(  # noqa: S603
                ["pulumi", "config", "set", key, value],  # noqa: S607
                cwd=_get_working_dir(),
                env=env,
                capture_output=True,
            )
        else:
            subprocess.run(  # noqa: S603
                ["pulumi", "config", "rm", key],  # noqa: S607
                cwd=_get_working_dir(),
                env=env,
                capture_output=True,
            )


def _run_ngfw_provision(request_id: str, instance_id: str, app_id: str, stack_name: str, env: dict) -> None:
    """Run Pulumi up to provision the NGFW, then run post-Pulumi configuration.

    Args:
        request_id: UUID string of the Request.
        instance_id: Django Instance UUID (e.g., "5eb96281-a4a8-..."), NOT AWS EC2 ID.
        app_id: UUID string of the App (NGFW).
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    # Update local DB and emit provisioning status event
    update_instance_state(request_id, STATUS_PROVISIONING)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_PROVISIONING,
    )
    logger.info("Running pulumi up for NGFW...")

    result = subprocess.run(
        ["pulumi", "up", "--yes", "--non-interactive", "--skip-preview"],  # noqa: S607
        cwd=_get_working_dir(),
        env=env,
        capture_output=True,
        text=True,
    )

    logger.info(f"Pulumi stdout:\n{result.stdout}")
    if result.stderr:
        logger.warning(f"Pulumi stderr:\n{result.stderr}")

    if result.returncode != 0:
        raise RuntimeError(f"NGFW Pulumi up failed: {result.stderr}")

    # Get outputs
    logger.info("Retrieving NGFW stack outputs...")
    outputs = subprocess.run(
        ["pulumi", "stack", "output", "--json"],  # noqa: S607
        cwd=_get_working_dir(),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output_data = json.loads(outputs.stdout)
    logger.info(f"NGFW Stack outputs: {json.dumps(output_data, indent=2)}")

    # Run post-Pulumi configuration (wait for SSH, configure cloud logging, etc.)
    # Skip in local dev mode (DB_PASSWORD set) - post-Pulumi config requires real AWS resources
    if os.environ.get("DB_PASSWORD"):
        logger.info("LOCAL DEV MODE: Skipping post-Pulumi NGFW configuration")
        # Update state with mock outputs and mark as ready
        update_instance_state(
            request_id,
            STATUS_READY,
            **output_data,
        )
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_id,
            app_id=app_id,
            status=STATUS_READY,
        )
        # Auto-stop: In local dev, just update status (no real EC2 to stop)
        logger.info("LOCAL DEV MODE: Setting NGFW status to stopped: request_id=%s", request_id)
        update_instance_state(request_id, "stopped")
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_id,
            app_id=app_id,
            status="stopped",
        )
        return

    logger.info("Running post-Pulumi NGFW configuration...")

    # Get SSH private key from Secrets Manager
    management_ip = output_data.get("management_ip")
    ssh_key_secret_arn = output_data.get("ssh_key_secret_arn")
    if not ssh_key_secret_arn:
        raise RuntimeError("NGFW stack missing ssh_key_secret_arn output")
    if not management_ip:
        raise RuntimeError("NGFW stack missing management_ip output")

    secrets_client = boto3.client("secretsmanager")
    secret_response = secrets_client.get_secret_value(SecretId=ssh_key_secret_arn)
    private_key = secret_response["SecretString"]

    # Create SSH executor and wait for NGFW to be ready (15-25 min boot time)
    ssh_executor = SSHExecutor(private_key=private_key)
    ssh_timeout = int(os.environ.get("NGFW_SSH_WAIT_TIMEOUT", NGFW_SSH_WAIT_TIMEOUT_DEFAULT))
    logger.info(f"Waiting for SSH on NGFW at {management_ip}...")
    ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=ssh_timeout)

    # Create orchestrator with SSH executor
    orchestrator = SetupOrchestrator(ssh_executor)

    # Create context dict with the stack outputs for template rendering
    context = {
        "ec2_instance_id": output_data.get("ec2_instance_id"),
        "management_ip": management_ip,
        "dataplane_ip": output_data.get("dataplane_ip"),
        "data_eni_id": output_data.get("data_eni_id"),
        "sls_region": os.environ.get("AWS_REGION", "us-east-2"),
    }

    # Import and run the NGFW provision plan
    from plans.ngfw_provision import NGFWProvisionPlan

    provision_plan = NGFWProvisionPlan()
    # NOTE: SetupOrchestrator.orchestrate() uses "instance_id" as the SSH target.
    # For SSH-based plans, this is the management IP address, not a UUID or EC2 ID.
    provision_result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=provision_plan,
        context=context,
    )

    if not provision_result.success:
        raise RuntimeError("NGFW post-Pulumi configuration failed")

    # Poll for serial number only - user must associate in SCM before cert is available
    # Serial becomes available quickly after SSH is ready (embedded in VM)
    logger.info("Polling for NGFW serial number...")
    serial_number = poll_for_serial_number(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=600,  # 10 min - serial should appear quickly
        poll_interval=30,
    )

    # Build state dict with all outputs including data_eni_id for range routing
    state = {
        "ec2_instance_id": output_data.get("ec2_instance_id"),
        "management_ip": output_data.get("management_ip"),
        "dataplane_ip": output_data.get("dataplane_ip"),
        "data_eni_id": output_data.get("data_eni_id"),
        "ssh_key_secret_arn": ssh_key_secret_arn,
        "pulumi_stack": stack_name,
        "serial_number": serial_number,
    }

    # Update local DB with provisioned resources - awaiting user association
    # User must: 1) Associate device in SCM, 2) Connect to XDR/XSIAM
    update_instance_state(request_id, STATUS_AWAITING_ASSOCIATION, **state)

    # Emit awaiting_association event for UI to show user action prompt
    # Serial number included so users can copy it for SCM device association
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_AWAITING_ASSOCIATION,
        serial_number=serial_number,
    )

    # Auto-stop NGFW to save costs while user completes association
    # NGFW will be started when user triggers "complete-setup" operation
    logger.info("Auto-stopping NGFW after provisioning (awaiting association): request_id=%s", request_id)
    try:
        run_ngfw_operation("stop", request_id)
        logger.info("Auto-stop completed successfully: request_id=%s", request_id)
    except Exception:
        logger.exception("Auto-stop FAILED: request_id=%s - NGFW remains running (cost impact)", request_id)


def _run_ngfw_deprovision(request_id: str, instance_id: str, app_id: str, stack_name: str, env: dict) -> None:
    """Run license deactivation then Pulumi destroy for NGFW.

    Args:
        request_id: UUID string of the Request.
        instance_id: Django Instance UUID (e.g., "5eb96281-a4a8-..."), NOT AWS EC2 ID.
        app_id: UUID string of the App (NGFW).
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    # Update local DB and emit destroying status event
    update_instance_state(request_id, STATUS_DESTROYING)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_DESTROYING,
    )

    # Get current instance state for management_ip and ssh_key needed by license deactivation
    ngfw_data = get_ngfw_data_by_request_id(request_id)
    current_state = ngfw_data.get("state", {})
    management_ip = current_state.get("management_ip")
    ssh_key_secret_arn = current_state.get("ssh_key_secret_arn")

    # Run pre-destroy license deactivation (requires SSH to NGFW)
    if management_ip and ssh_key_secret_arn:
        logger.info("Running NGFW license deactivation...")
        try:
            # Get SSH private key from Secrets Manager
            secrets_client = boto3.client("secretsmanager")
            secret_response = secrets_client.get_secret_value(SecretId=ssh_key_secret_arn)
            private_key = secret_response["SecretString"]

            # Create SSH executor
            ssh_executor = SSHExecutor(private_key=private_key)
            orchestrator = SetupOrchestrator(ssh_executor)

            # Import and run the NGFW deprovision plan (license deactivation)
            from plans.ngfw_deprovision import NGFWDeprovisionPlan

            deprovision_plan = NGFWDeprovisionPlan()

            # Create context dict with management_ip from stored state
            context = {"management_ip": management_ip}

            # NOTE: SetupOrchestrator uses "instance_id" as the SSH target (IP address here).
            deprovision_result = orchestrator.orchestrate(
                instance_id=management_ip,
                plan=deprovision_plan,
                context=context,
            )
            if not deprovision_result.success:
                logger.warning("License deactivation failed, proceeding with destroy anyway")
        except Exception as e:
            logger.warning(f"License deactivation error: {e}, proceeding with destroy")
    else:
        logger.warning("Missing management_ip or ssh_key_secret_arn in state, skipping license deactivation")

    # Run Pulumi destroy
    logger.info("Running pulumi destroy for NGFW...")

    result = subprocess.run(  # noqa: S603
        [
            _get_pulumi_path(),
            "destroy",
            "--yes",
            "--non-interactive",
            "--skip-preview",
        ],
        cwd=_get_working_dir(),
        env=env,
        capture_output=True,
        text=True,
    )

    logger.info(f"Pulumi stdout:\n{result.stdout}")
    if result.stderr:
        logger.warning(f"Pulumi stderr:\n{result.stderr}")

    if result.returncode != 0:
        raise RuntimeError(f"NGFW Pulumi destroy failed: {result.stderr}")

    # Remove stack
    logger.info(f"Removing NGFW stack: {stack_name}")
    subprocess.run(  # noqa: S603
        ["pulumi", "stack", "rm", stack_name, "--yes"],  # noqa: S607
        cwd=_get_working_dir(),
        env=env,
        check=True,
        capture_output=True,
    )

    # Update local DB and emit destroyed event
    update_instance_state(request_id, STATUS_DESTROYED)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_DESTROYED,
    )


if __name__ == "__main__":
    from logging_config import configure_logging

    configure_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Shifter Engine for provisioning cyber ranges and NGFW operations")
    subparsers = parser.add_subparsers(dest="resource", required=True, help="Resource type")

    # Range operations - use request_id (UUID) like NGFW pattern
    range_parser = subparsers.add_parser("range", help="Range lifecycle operations")
    range_parser.add_argument(
        "operation",
        choices=["provision", "destroy"],
        help="Operation to perform: provision (create) or destroy (teardown)",
    )
    range_parser.add_argument(
        "--request-id",
        type=str,
        required=True,
        dest="request_id",
        help="UUID of the Request for this Range",
    )

    # NGFW operations
    ngfw_parser = subparsers.add_parser("ngfw", help="NGFW runtime operations")
    ngfw_parser.add_argument(
        "operation",
        choices=[
            "provision",
            "deprovision",
            "start",
            "stop",
            "complete-setup",
        ],
        help="NGFW operation to perform",
    )
    ngfw_parser.add_argument(
        "--request-id",
        type=str,
        required=True,
        dest="request_id",
        help="UUID of the Request for this NGFW",
    )
    ngfw_parser.add_argument(
        "--ec2-instance-id",
        type=str,
        help="EC2 instance ID (for start/stop)",
    )

    args = parser.parse_args()

    # Handle resource-based dispatch
    if args.resource == "ngfw":
        logger.info(f"Starting NGFW {args.operation} for request_id={args.request_id}")
        logger.info(f"Environment: {os.environ.get('ENVIRONMENT', 'unknown')}")

        # Pulumi operations vs runtime operations
        if args.operation in ("provision", "deprovision"):
            # Map to Pulumi operations
            pulumi_op = "up" if args.operation == "provision" else "destroy"
            run_ngfw_pulumi(pulumi_op, args.request_id)
        else:
            # Runtime operations (start, stop, complete-setup)
            kwargs = {}
            if args.ec2_instance_id:
                kwargs["ec2_instance_id"] = args.ec2_instance_id

            run_ngfw_operation(args.operation, args.request_id, **kwargs)

        logger.info(f"Completed NGFW {args.operation} for request_id={args.request_id}")

    elif args.resource == "range":
        # Handle range operations
        request_id = args.request_id

        # Map Django command names to Pulumi operations
        operation_map = {"provision": "up", "destroy": "destroy"}
        pulumi_op = operation_map[args.operation]

        logger.info(f"Starting {pulumi_op} for request_id={request_id}")
        logger.info(f"Environment: {os.environ.get('ENVIRONMENT', 'unknown')}")

        run_pulumi(pulumi_op, request_id)

        logger.info(f"Completed {pulumi_op} for request_id={request_id}")

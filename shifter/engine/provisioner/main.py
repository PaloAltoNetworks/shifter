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


def _get_pulumi_path() -> str:
    """Get the full path to the pulumi executable."""
    path = shutil.which("pulumi")
    if not path:
        raise RuntimeError("pulumi executable not found in PATH")
    return path


def get_db_connection() -> psycopg.Connection:
    """Get database connection using RDS IAM auth.

    Returns:
        psycopg.Connection: Active database connection with SSL.

    Raises:
        Exception: If connection fails.
    """
    client = boto3.client("rds")
    token = client.generate_db_auth_token(
        DBHostname=os.environ["DB_HOST"],
        Port=int(os.environ.get("DB_PORT", 5432)),
        DBUsername=os.environ["DB_USER"],
        Region=os.environ["AWS_REGION"],
    )
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=token,
        sslmode="require",
    )


def update_range_status(range_id: int, status: str, **kwargs) -> None:
    """Update range status in database.

    Args:
        range_id: The ID of the range to update.
        status: New status value (e.g., 'provisioning', 'ready', 'failed').
        **kwargs: Additional fields to update (e.g., subnet_id, error_message).
    """
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
            service_name, gwlb_arn, target_group_arn, pulumi_stack, error_message.
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


def run_pulumi(operation: str, range_id: int, user_id: int) -> None:
    """Run Pulumi operation.

    Args:
        operation: Either 'up' (provision) or 'destroy' (teardown).
        range_id: The ID of the range to operate on.
        user_id: The Django user ID who owns this range.

    Raises:
        Exception: If the Pulumi operation fails.
    """
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
            _run_provision(range_id, user_id, stack_name, env)
        elif operation == "destroy":
            _run_destroy(range_id, user_id, stack_name, env)
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
                cwd="/app",
                env=env,
                capture_output=True,
            )

        # Publish failed event
        publish_failed(range_id=range_id, user_id=user_id, error_message=error_msg)
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
        cwd="/app",
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
        cwd="/app",
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
        "kaliSecurityGroupId": os.environ.get("KALI_SECURITY_GROUP_ID", ""),
        "victimSecurityGroupId": os.environ.get("VICTIM_SECURITY_GROUP_ID", ""),
        "dcSecurityGroupId": os.environ.get("DC_SECURITY_GROUP_ID", ""),
        "rangeInstanceProfileName": os.environ.get("RANGE_INSTANCE_PROFILE_NAME", ""),
        "kaliAmiId": os.environ.get("KALI_AMI_ID", ""),
        "victimAmiId": os.environ.get("VICTIM_AMI_ID", ""),
        "windowsAmiId": os.environ.get("WINDOWS_AMI_ID", ""),
        "dcAmiId": os.environ.get("DC_AMI_ID", ""),
        "agentS3Bucket": os.environ.get("AGENT_S3_BUCKET", ""),
    }

    for key, value in config_values.items():
        if value:
            subprocess.run(  # noqa: S603
                ["pulumi", "config", "set", key, value],  # noqa: S607
                cwd="/app",
                env=env,
                capture_output=True,
            )
        else:
            # Remove empty config values to prevent stale values from persisting
            subprocess.run(  # noqa: S603
                ["pulumi", "config", "rm", key],  # noqa: S607
                cwd="/app",
                env=env,
                capture_output=True,
                # Ignore errors - key may not exist
            )


def _run_provision(range_id: int, user_id: int, stack_name: str, env: dict) -> None:
    """Run Pulumi up to provision the range.

    Args:
        range_id: The range ID being provisioned.
        user_id: The Django user ID who owns this range.
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    # Publish status change event
    publish_status_update(range_id=range_id, user_id=user_id, new_status="provisioning")
    logger.info("Running pulumi up...")

    result = subprocess.run(
        ["pulumi", "up", "--yes", "--non-interactive", "--skip-preview"],  # noqa: S607
        cwd="/app",
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
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output_data = json.loads(outputs.stdout)
    logger.info(f"Stack outputs: {json.dumps(output_data, indent=2)}")

    # Publish ready event with instance details
    publish_ready(
        range_id=range_id,
        user_id=user_id,
        instances=output_data.get("instances", []),
        subnet_id=output_data.get("subnet_id"),
        subnet_cidr=output_data.get("subnet_cidr"),
        pulumi_stack=stack_name,
    )


def _run_destroy(range_id: int, user_id: int, stack_name: str, env: dict) -> None:
    """Run Pulumi destroy to tear down the range.

    Args:
        range_id: The range ID being destroyed.
        user_id: The Django user ID who owns this range.
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    # Engine already set status to DESTROYING before launching ECS task
    logger.info("Running pulumi destroy...")

    result = subprocess.run(  # noqa: S603
        [
            _get_pulumi_path(),
            "destroy",
            "--yes",
            "--non-interactive",
            "--skip-preview",
        ],
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
    )

    logger.info(f"Pulumi stdout:\n{result.stdout}")
    if result.stderr:
        logger.warning(f"Pulumi stderr:\n{result.stderr}")

    if result.returncode != 0:
        raise RuntimeError(f"Pulumi destroy failed: {result.stderr}")

    # Remove stack
    logger.info(f"Removing stack: {stack_name}")
    subprocess.run(  # noqa: S603
        ["pulumi", "stack", "rm", stack_name, "--yes"],  # noqa: S607
        cwd="/app",
        env=env,
        check=True,
        capture_output=True,
    )

    # Publish destroyed event
    publish_destroyed(range_id=range_id, user_id=user_id)


def run_ngfw_operation(operation: str, request_id: str, **kwargs) -> None:
    """Run NGFW runtime operation (start/stop/route management).

    Retrieves EC2 instance ID from the Instance.state (populated during Pulumi
    provisioning), executes the operation plan, and publishes events for status
    updates.

    Args:
        operation: Operation name (start, stop, add-route, remove-route).
        request_id: UUID string of the Request.
        **kwargs: Operation-specific parameters (overrides for context).

    Raises:
        ValueError: If unknown operation or EC2 instance ID not found.
        Exception: If operation fails.
    """
    from events import publish_ngfw_event

    # Status transitions for each operation
    status_map = {
        "start": ("starting", "active"),
        "stop": ("stopping", "stopped"),
        "add-route": ("configuring", "active"),
        "remove-route": ("configuring", "active"),
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
            "add-route": "plans.gwlb_add_route.GWLBAddRoutePlan",
            "remove-route": "plans.gwlb_remove_route.GWLBRemoveRoutePlan",
        }

        plan_path = plan_map[operation]
        module_path, class_name = plan_path.rsplit(".", 1)

        import importlib

        module = importlib.import_module(module_path)
        plan_class = getattr(module, class_name)
        plan = plan_class()

        # Build context dict with EC2 instance ID and any additional kwargs
        # Note: Plans use "instance_id" for the EC2 instance ID parameter
        context = {
            "instance_id": ec2_instance_id,
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


def run_ngfw_pulumi(operation: str, request_id: str) -> None:
    """Run NGFW Pulumi operation (provision or deprovision).

    Args:
        operation: Either 'up' (provision) or 'destroy' (deprovision).
        request_id: UUID string of the Request.

    Raises:
        ValueError: If unknown operation or Request not found.
        Exception: If the Pulumi operation fails.
    """
    # Get NGFW data from database (needed for correlation IDs and credentials)
    ngfw_data = get_ngfw_data_by_request_id(request_id)
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
        _set_ngfw_stack_config(env, request_id, app_spec)

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
                cwd="/app",
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


def _set_ngfw_stack_config(env: dict, request_id: str, app_spec: dict) -> None:
    """Set Pulumi stack configuration for NGFW from environment and app_spec.

    Infrastructure config (VPC, subnet, AMI, etc.) comes from environment variables.
    Credential config (PIN, authcode, folder) comes from app_spec (hydrated by CMS).

    Args:
        env: Environment dictionary for subprocess.
        request_id: UUID string of the Request.
        app_spec: Hydrated NGFWAppSpec dict containing credentials.
    """
    # Infrastructure config from environment (same for all NGFWs)
    config_values = {
        "requestId": request_id,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "ngfwVpcId": os.environ.get("NGFW_VPC_ID", ""),
        "ngfwSubnetId": os.environ.get("NGFW_SUBNET_ID", ""),
        "ngfwSecurityGroupId": os.environ.get("NGFW_SECURITY_GROUP_ID", ""),
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
                cwd="/app",
                env=env,
                capture_output=True,
            )
        else:
            subprocess.run(  # noqa: S603
                ["pulumi", "config", "rm", key],  # noqa: S607
                cwd="/app",
                env=env,
                capture_output=True,
            )


def _run_ngfw_provision(request_id: str, instance_id: str, app_id: str, stack_name: str, env: dict) -> None:
    """Run Pulumi up to provision the NGFW, then run post-Pulumi configuration.

    Args:
        request_id: UUID string of the Request.
        instance_id: UUID string of the Instance.
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
        cwd="/app",
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
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output_data = json.loads(outputs.stdout)
    logger.info(f"NGFW Stack outputs: {json.dumps(output_data, indent=2)}")

    # Run post-Pulumi configuration (wait for SSH, configure cloud logging, etc.)
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
    logger.info(f"Waiting for SSH on NGFW at {management_ip}...")
    ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=1800)

    # Create orchestrator with SSH executor
    orchestrator = SetupOrchestrator(ssh_executor)

    # Create context object with the stack outputs
    class NGFWContext:
        pass

    context = NGFWContext()
    context.ec2_instance_id = output_data.get("instance_id")
    context.management_ip = management_ip
    context.dataplane_ip = output_data.get("dataplane_ip")
    context.service_name = output_data.get("service_name")
    context.gwlb_arn = output_data.get("gwlb_arn")
    context.target_group_arn = output_data.get("target_group_arn")
    context.sls_region = os.environ.get("AWS_REGION", "us-east-2")

    # Import and run the NGFW provision plan
    from plans.ngfw_provision import NGFWProvisionPlan

    provision_plan = NGFWProvisionPlan()
    provision_result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=provision_plan,
        context=context,
    )

    if not provision_result.success:
        raise RuntimeError("NGFW post-Pulumi configuration failed")

    # Extract serial number from verify_device_cert step output
    serial_number = None
    for step_result in provision_result.step_results:
        if step_result.step_name == "verify_device_cert":
            serial_number = parse_serial_number(step_result.stdout)
            break

    if not serial_number:
        raise RuntimeError("NGFW serial number not found - CSP registration may have failed")

    # Run GWLB setup (register target, wait for healthy)
    # This uses AWSExecutor directly since GWLBSetupPlan expects AWS API calls
    logger.info("Running GWLB target registration...")
    from plans.gwlb_setup import GWLBSetupPlan

    aws_executor = AWSExecutor()
    gwlb_plan = GWLBSetupPlan()

    # Build context for GWLB setup - needs target_group_arn and instance_id (EC2)
    ec2_instance_id = output_data.get("instance_id")
    target_group_arn = output_data.get("target_group_arn")

    if not target_group_arn:
        raise RuntimeError("NGFW stack missing target_group_arn output")
    if not ec2_instance_id:
        raise RuntimeError("NGFW stack missing instance_id output")

    # Execute GWLB setup steps directly via AWSExecutor
    gwlb_context = {
        "target_group_arn": target_group_arn,
        "target_id": ec2_instance_id,
    }

    for step in gwlb_plan.steps:
        step_params = {k: gwlb_context[k] for k in step.params}
        logger.info(f"Executing GWLB step: {step.name}")
        method = getattr(aws_executor, step.action)
        step_result = method(**step_params)
        if not step_result.success:
            raise RuntimeError(f"GWLB setup step '{step.name}' failed: {step_result.stderr}")
        logger.info(f"GWLB step '{step.name}' completed successfully")

    # Build state dict with all outputs
    state = {
        "ec2_instance_id": output_data.get("instance_id"),
        "management_ip": output_data.get("management_ip"),
        "dataplane_ip": output_data.get("dataplane_ip"),
        "service_name": output_data.get("service_name"),
        "gwlb_arn": output_data.get("gwlb_arn"),
        "target_group_arn": output_data.get("target_group_arn"),
        "ssh_key_secret_arn": ssh_key_secret_arn,
        "pulumi_stack": stack_name,
        "serial_number": serial_number,
    }

    # Update local DB with provisioned resources
    update_instance_state(request_id, STATUS_READY, **state)

    # Emit ready event notification for CMS/Engine handlers
    # Note: Full state is already in DB - this is just a notification
    # Serial number included so consumers can verify CSP registration
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_READY,
        serial_number=serial_number,
    )

    # Auto-stop NGFW after provisioning to save costs
    # NGFW will be started on-demand when ranges link to it
    logger.info("Auto-stopping NGFW after provisioning: request_id=%s", request_id)
    run_ngfw_operation("stop", request_id)


def _run_ngfw_deprovision(request_id: str, instance_id: str, app_id: str, stack_name: str, env: dict) -> None:
    """Run license deactivation then Pulumi destroy for NGFW.

    Args:
        request_id: UUID string of the Request.
        instance_id: UUID string of the Instance.
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

            # Create context with management_ip from stored state
            class NGFWContext:
                pass

            context = NGFWContext()
            context.management_ip = management_ip

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
        cwd="/app",
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
        cwd="/app",
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

    RANGE_ID_HELP = "Database ID of the range to operate on"

    parser = argparse.ArgumentParser(description="Shifter Engine for provisioning cyber ranges and NGFW operations")
    subparsers = parser.add_subparsers(dest="resource", required=True, help="Resource type")

    # Range operations - backward compatible with: provision --range-id 42
    # Also supports: range provision --range-id 42
    range_parser = subparsers.add_parser("range", help="Range lifecycle operations")
    range_parser.add_argument(
        "operation",
        choices=["provision", "destroy"],
        help="Operation to perform: provision (create) or destroy (teardown)",
    )
    range_parser.add_argument(
        "--range-id",
        type=int,
        required=True,
        help=RANGE_ID_HELP,
    )
    range_parser.add_argument(
        "--user-id",
        type=int,
        required=True,
        help="Django User ID of the range owner",
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
            "add-route",
            "remove-route",
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
    ngfw_parser.add_argument(
        "--subnet-id",
        type=str,
        help="Subnet ID (for add-route)",
    )
    ngfw_parser.add_argument(
        "--service-name",
        type=str,
        help="VPC Endpoint Service name (for add-route)",
    )
    ngfw_parser.add_argument(
        "--vpc-id",
        type=str,
        help="VPC ID (for add-route)",
    )
    ngfw_parser.add_argument(
        "--route-table-id",
        type=str,
        help="Route table ID (for add-route)",
    )
    ngfw_parser.add_argument(
        "--endpoint-id",
        type=str,
        help="VPC Endpoint ID (for remove-route)",
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
            # Runtime operations (start, stop, add-route, remove-route)
            kwargs = {}
            if args.ec2_instance_id:
                kwargs["ec2_instance_id"] = args.ec2_instance_id
            if args.subnet_id:
                kwargs["subnet_id"] = args.subnet_id
            if args.service_name:
                kwargs["service_name"] = args.service_name
            if args.vpc_id:
                kwargs["vpc_id"] = args.vpc_id
            if args.route_table_id:
                kwargs["route_table_id"] = args.route_table_id
            if args.endpoint_id:
                kwargs["endpoint_id"] = args.endpoint_id

            run_ngfw_operation(args.operation, args.request_id, **kwargs)

        logger.info(f"Completed NGFW {args.operation} for request_id={args.request_id}")

    elif args.resource == "range":
        # Handle range operations
        range_id = args.range_id
        user_id = args.user_id

        # Map Django command names to Pulumi operations
        operation_map = {"provision": "up", "destroy": "destroy"}
        pulumi_op = operation_map[args.operation]

        logger.info(f"Starting {pulumi_op} for range {range_id} (user {user_id})")
        logger.info(f"Environment: {os.environ.get('ENVIRONMENT', 'unknown')}")

        run_pulumi(pulumi_op, range_id, user_id)

        logger.info(f"Completed {pulumi_op} for range {range_id}")

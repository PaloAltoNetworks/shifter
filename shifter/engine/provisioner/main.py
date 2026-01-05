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
import subprocess  # nosec B404 - subprocess used for Pulumi CLI calls with hardcoded commands

import boto3
import psycopg

from events import publish_destroyed, publish_failed, publish_ready, publish_status_update
from executors.aws_executor import AWSExecutor
from orchestrators.ops_orchestrator import OpsOrchestrator
from orchestrators.setup_orchestrator import SetupOrchestrator

logger = logging.getLogger(__name__)


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


def update_ngfw_status(user_ngfw_id: int, status: str, **kwargs) -> None:
    """Update UserNGFW status in database.

    Args:
        user_ngfw_id: The ID of the UserNGFW record to update.
        status: New status value (e.g., 'starting', 'active', 'stopped', 'failed').
        **kwargs: Additional fields to update (e.g., last_started_at, error_message).
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

            values.append(user_ngfw_id)
            # Security: Column names in 'updates' are from hardcoded kwargs keys in calling code,
            # not user input. Values are parameterized via %s placeholders.
            sql = f"UPDATE mission_control_userngfw SET {', '.join(updates)} WHERE id = %s"  # nosec B608  # noqa: S608
            cur.execute(sql, values)
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
        ["pulumi", "stack", "init", stack_name, "--secrets-provider", secrets_provider],  # noqa: S607
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

    result = subprocess.run(
        ["pulumi", "destroy", "--yes", "--non-interactive", "--skip-preview"],  # noqa: S607
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


def run_ngfw_operation(operation: str, user_ngfw_id: int, **kwargs) -> None:
    """Run NGFW runtime operation.

    Args:
        operation: Operation name (start, stop, add-route, remove-route).
        user_ngfw_id: The ID of the UserNGFW record.
        **kwargs: Operation-specific parameters (instance_id, subnet_id, etc.).

    Raises:
        ValueError: If unknown operation.
        Exception: If operation fails.
    """
    # Status transitions for each operation
    status_map = {
        "start": ("starting", "active"),
        "stop": ("stopping", "stopped"),
        "add-route": ("configuring", "active"),
        "remove-route": ("configuring", "active"),
    }

    if operation not in status_map:
        raise ValueError(f"Unknown operation: {operation}")

    in_progress_status, success_status = status_map[operation]
    update_ngfw_status(user_ngfw_id, in_progress_status)

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

        # Create context object with kwargs as attributes
        class Context:
            pass

        context = Context()
        for key, value in kwargs.items():
            setattr(context, key, value)

        # Execute the plan
        result = orchestrator.orchestrate(plan, context)

        if not result.success:
            raise RuntimeError(f"Operation {operation} failed")

        # Update success status with timestamp if applicable
        extra_kwargs = {}
        if operation == "start":
            extra_kwargs["last_started_at"] = "NOW()"
        elif operation == "stop":
            extra_kwargs["last_stopped_at"] = "NOW()"

        update_ngfw_status(user_ngfw_id, success_status, **extra_kwargs)

    except Exception as e:
        error_msg = str(e)[:1000]
        update_ngfw_status(user_ngfw_id, "failed", error_message=error_msg)
        raise


def run_ngfw_pulumi(operation: str, user_ngfw_id: int) -> None:
    """Run NGFW Pulumi operation (provision or deprovision).

    Args:
        operation: Either 'up' (provision) or 'destroy' (deprovision).
        user_ngfw_id: The ID of the UserNGFW record.

    Raises:
        ValueError: If unknown operation.
        Exception: If the Pulumi operation fails.
    """
    stack_name = f"ngfw-{user_ngfw_id}"
    env = os.environ.copy()
    # Security: Empty passphrase is intentional - we use AWS KMS via PULUMI_SECRETS_PROVIDER.
    env["PULUMI_CONFIG_PASSPHRASE"] = ""  # nosec B105

    try:
        # Select or create stack with proper secrets provider
        _select_or_create_stack(stack_name, env)

        # Set NGFW stack configuration from environment
        _set_ngfw_stack_config(env, user_ngfw_id)

        if operation == "up":
            _run_ngfw_provision(user_ngfw_id, stack_name, env)
        elif operation == "destroy":
            _run_ngfw_deprovision(user_ngfw_id, stack_name, env)
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

        update_ngfw_status(user_ngfw_id, "failed", error_message=error_msg)
        raise


def _set_ngfw_stack_config(env: dict, user_ngfw_id: int) -> None:
    """Set Pulumi stack configuration for NGFW from environment variables.

    Args:
        env: Environment dictionary for subprocess.
        user_ngfw_id: The UserNGFW ID to configure.
    """
    config_values = {
        "userNgfwId": str(user_ngfw_id),
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "ngfwVpcId": os.environ.get("NGFW_VPC_ID", ""),
        "ngfwSubnetId": os.environ.get("NGFW_SUBNET_ID", ""),
        "ngfwSecurityGroupId": os.environ.get("NGFW_SECURITY_GROUP_ID", ""),
        "ngfwAmiId": os.environ.get("NGFW_AMI_ID", ""),
        "bootstrapBucket": os.environ.get("NGFW_BOOTSTRAP_BUCKET", ""),
        "ngfwInstanceType": os.environ.get("NGFW_INSTANCE_TYPE", "m5.xlarge"),
        "ngfwInstanceProfileName": os.environ.get("NGFW_INSTANCE_PROFILE_NAME", ""),
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


def _run_ngfw_provision(user_ngfw_id: int, stack_name: str, env: dict) -> None:
    """Run Pulumi up to provision the NGFW, then run post-Pulumi configuration.

    Args:
        user_ngfw_id: The UserNGFW ID being provisioned.
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    update_ngfw_status(user_ngfw_id, "provisioning")
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

    # Run post-Pulumi configuration (wait for SSH, configure XDR, etc.)
    logger.info("Running post-Pulumi NGFW configuration...")
    executor = AWSExecutor()
    orchestrator = SetupOrchestrator(executor)

    # Create a context object with the stack outputs
    class NGFWContext:
        pass

    context = NGFWContext()
    context.instance_id = output_data.get("instance_id")
    context.management_ip = output_data.get("management_ip")
    context.dataplane_ip = output_data.get("dataplane_ip")
    context.service_name = output_data.get("service_name")
    context.gwlb_arn = output_data.get("gwlb_arn")
    context.target_group_arn = output_data.get("target_group_arn")

    # Import and run the NGFW provision plan
    from plans.ngfw_provision import NGFWProvisionPlan

    provision_plan = NGFWProvisionPlan()
    provision_result = orchestrator.orchestrate(provision_plan, context)

    if not provision_result.success:
        raise RuntimeError("NGFW post-Pulumi configuration failed")

    # Update NGFW with provisioned resources
    update_ngfw_status(
        user_ngfw_id,
        "ready",
        instance_id=output_data.get("instance_id"),
        management_ip=output_data.get("management_ip"),
        dataplane_ip=output_data.get("dataplane_ip"),
        service_name=output_data.get("service_name"),
        gwlb_arn=output_data.get("gwlb_arn"),
        pulumi_stack=stack_name,
        ready_at="NOW()",
    )


def _run_ngfw_deprovision(user_ngfw_id: int, stack_name: str, env: dict) -> None:
    """Run license deactivation then Pulumi destroy for NGFW.

    Args:
        user_ngfw_id: The UserNGFW ID being deprovisioned.
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    update_ngfw_status(user_ngfw_id, "deprovisioning")

    # Run pre-destroy license deactivation
    logger.info("Running NGFW license deactivation...")
    executor = AWSExecutor()
    orchestrator = SetupOrchestrator(executor)

    # Import and run the NGFW deprovision plan (license deactivation)
    from plans.ngfw_deprovision import NGFWDeprovisionPlan

    deprovision_plan = NGFWDeprovisionPlan()

    # Create minimal context - the plan will look up the NGFW by ID
    class NGFWContext:
        pass

    context = NGFWContext()
    context.user_ngfw_id = user_ngfw_id

    deprovision_result = orchestrator.orchestrate(deprovision_plan, context)
    if not deprovision_result.success:
        logger.warning("License deactivation failed, proceeding with destroy anyway")

    # Run Pulumi destroy
    logger.info("Running pulumi destroy for NGFW...")

    result = subprocess.run(
        ["pulumi", "destroy", "--yes", "--non-interactive", "--skip-preview"],  # noqa: S607
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

    update_ngfw_status(user_ngfw_id, "deprovisioned", deprovisioned_at="NOW()")


if __name__ == "__main__":
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
        choices=["provision", "deprovision", "start", "stop", "add-route", "remove-route"],
        help="NGFW operation to perform",
    )
    ngfw_parser.add_argument(
        "--user-ngfw-id",
        type=int,
        required=True,
        help="Database ID of the UserNGFW record",
    )
    ngfw_parser.add_argument(
        "--instance-id",
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
        logger.info(f"Starting NGFW {args.operation} for user_ngfw_id {args.user_ngfw_id}")
        logger.info(f"Environment: {os.environ.get('ENVIRONMENT', 'unknown')}")

        # Pulumi operations vs runtime operations
        if args.operation in ("provision", "deprovision"):
            # Map to Pulumi operations
            pulumi_op = "up" if args.operation == "provision" else "destroy"
            run_ngfw_pulumi(pulumi_op, args.user_ngfw_id)
        else:
            # Runtime operations (start, stop, add-route, remove-route)
            kwargs = {}
            if args.instance_id:
                kwargs["instance_id"] = args.instance_id
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

            run_ngfw_operation(args.operation, args.user_ngfw_id, **kwargs)

        logger.info(f"Completed NGFW {args.operation} for user_ngfw_id {args.user_ngfw_id}")

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

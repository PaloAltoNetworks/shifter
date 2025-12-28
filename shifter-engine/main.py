"""Container entrypoint for Shifter Engine.

This module is the main entry point when running the Shifter Engine container.
It handles:
- Database connection via RDS IAM authentication
- Range status updates in the Django database
- Pulumi stack creation, provisioning, and destruction
"""

import json
import os
import subprocess
import sys

import boto3
import psycopg


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
            sql = f"UPDATE mission_control_range SET {', '.join(updates)} WHERE id = %s"
            cur.execute(sql, values)
        conn.commit()


def run_pulumi(operation: str, range_id: int) -> None:
    """Run Pulumi operation.

    Args:
        operation: Either 'up' (provision) or 'destroy' (teardown).
        range_id: The ID of the range to operate on.

    Raises:
        Exception: If the Pulumi operation fails.
    """
    stack_name = f"range-{range_id}"
    env = os.environ.copy()
    env["PULUMI_CONFIG_PASSPHRASE"] = ""  # We use AWS KMS for secrets

    try:
        # Select or create stack with proper secrets provider
        _select_or_create_stack(stack_name, env)

        # Set stack configuration from environment
        _set_stack_config(env, range_id)

        if operation == "up":
            _run_provision(range_id, stack_name, env)
        elif operation == "destroy":
            _run_destroy(range_id, stack_name, env)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    except Exception as e:
        error_msg = str(e)[:1000]
        print(f"Operation failed: {error_msg}", file=sys.stderr)

        if operation == "up":
            # Auto-cleanup on failure to avoid orphaned resources
            print("Provision failed - attempting auto-cleanup...")
            subprocess.run(
                ["pulumi", "destroy", "--yes", "--non-interactive"],
                cwd="/app",
                env=env,
                capture_output=True,
            )

        update_range_status(range_id, "failed", error_message=error_msg)
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
    print(f"Selecting stack: {stack_name}")

    # Try to select existing stack
    result = subprocess.run(
        ["pulumi", "stack", "select", stack_name],
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"Selected existing stack: {stack_name}")
        return

    # Stack doesn't exist - create with explicit secrets provider
    # PULUMI_SECRETS_PROVIDER env var is NOT honored by `stack init` without --secrets-provider
    # The env var is set by the ECS task definition to use our dedicated KMS CMK
    secrets_provider = os.environ.get("PULUMI_SECRETS_PROVIDER")
    if not secrets_provider:
        raise ValueError("PULUMI_SECRETS_PROVIDER environment variable is required")
    print(f"Creating new stack with secrets provider: {secrets_provider}")

    result = subprocess.run(
        ["pulumi", "stack", "init", stack_name, "--secrets-provider", secrets_provider],
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise Exception(f"Stack creation failed: {result.stderr}")  # noqa: TRY002

    print(f"Created new stack: {stack_name}")


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
            subprocess.run(
                ["pulumi", "config", "set", key, value],
                cwd="/app",
                env=env,
                capture_output=True,
            )
        else:
            # Remove empty config values to prevent stale values from persisting
            subprocess.run(
                ["pulumi", "config", "rm", key],
                cwd="/app",
                env=env,
                capture_output=True,
                # Ignore errors - key may not exist
            )


def _run_provision(range_id: int, stack_name: str, env: dict) -> None:
    """Run Pulumi up to provision the range.

    Args:
        range_id: The range ID being provisioned.
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    update_range_status(range_id, "provisioning")
    print("Running pulumi up...")

    result = subprocess.run(
        ["pulumi", "up", "--yes", "--non-interactive", "--skip-preview"],
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
    )

    print(f"Pulumi stdout:\n{result.stdout}")
    if result.stderr:
        print(f"Pulumi stderr:\n{result.stderr}")

    if result.returncode != 0:
        raise Exception(f"Pulumi up failed: {result.stderr}")  # noqa: TRY002

    # Get outputs
    print("Retrieving stack outputs...")
    outputs = subprocess.run(
        ["pulumi", "stack", "output", "--json"],
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output_data = json.loads(outputs.stdout)
    print(f"Stack outputs: {json.dumps(output_data, indent=2)}")

    # Update range with provisioned resources
    update_range_status(
        range_id,
        "ready",
        subnet_id=output_data.get("subnet_id"),
        subnet_cidr=output_data.get("subnet_cidr"),
        provisioned_instances=json.dumps(output_data.get("instances", [])),
        pulumi_stack=stack_name,
        ready_at="NOW()",
    )


def _run_destroy(range_id: int, stack_name: str, env: dict) -> None:
    """Run Pulumi destroy to tear down the range.

    Args:
        range_id: The range ID being destroyed.
        stack_name: The Pulumi stack name.
        env: Environment dictionary for subprocess.
    """
    update_range_status(range_id, "destroying")
    print("Running pulumi destroy...")

    result = subprocess.run(
        ["pulumi", "destroy", "--yes", "--non-interactive", "--skip-preview"],
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
    )

    print(f"Pulumi stdout:\n{result.stdout}")
    if result.stderr:
        print(f"Pulumi stderr:\n{result.stderr}")

    if result.returncode != 0:
        raise Exception(f"Pulumi destroy failed: {result.stderr}")  # noqa: TRY002

    # Remove stack
    print(f"Removing stack: {stack_name}")
    subprocess.run(
        ["pulumi", "stack", "rm", stack_name, "--yes"],
        cwd="/app",
        env=env,
        check=True,
        capture_output=True,
    )

    update_range_status(range_id, "destroyed", destroyed_at="NOW()")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Shifter Engine for provisioning cyber ranges"
    )
    parser.add_argument(
        "operation",
        choices=["provision", "destroy"],
        help="Operation to perform: provision (create) or destroy (teardown)",
    )
    parser.add_argument(
        "--range-id",
        type=int,
        required=True,
        help="Database ID of the range to operate on",
    )

    args = parser.parse_args()

    # Map Django command names to Pulumi operations
    operation_map = {"provision": "up", "destroy": "destroy"}
    operation = operation_map[args.operation]
    range_id = args.range_id

    print(f"Starting {operation} for range {range_id}")
    print(f"Environment: {os.environ.get('ENVIRONMENT', 'unknown')}")

    run_pulumi(operation, range_id)

    print(f"Completed {operation} for range {range_id}")

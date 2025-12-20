"""Container entrypoint for Pulumi provisioner.

This module is the main entry point when running the Pulumi provisioner container.
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
        # Select or create stack
        print(f"Selecting/creating stack: {stack_name}")
        result = subprocess.run(
            ["pulumi", "stack", "select", stack_name, "--create"],
            cwd="/app",
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Stack selection failed - check if it's just a "not found" error
            if "no stack named" not in result.stderr.lower():
                raise Exception(f"Stack selection failed: {result.stderr}")  # noqa: TRY002

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

        if os.environ.get("ENVIRONMENT") == "prod" and operation == "up":
            # Auto-cleanup in prod on failure
            print("Production environment - attempting auto-cleanup...")
            subprocess.run(
                ["pulumi", "destroy", "--yes", "--non-interactive"],
                cwd="/app",
                env=env,
                capture_output=True,
            )

        update_range_status(range_id, "failed", error_message=error_msg)
        raise


def _set_stack_config(env: dict, range_id: int) -> None:
    """Set Pulumi stack configuration from environment variables.

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
        "kaliSecurityGroupId": os.environ.get("KALI_SECURITY_GROUP_ID", ""),
        "victimSecurityGroupId": os.environ.get("VICTIM_SECURITY_GROUP_ID", ""),
        "rangeInstanceProfileName": os.environ.get("RANGE_INSTANCE_PROFILE_NAME", ""),
        "kaliAmiId": os.environ.get("KALI_AMI_ID", ""),
        "victimAmiId": os.environ.get("VICTIM_AMI_ID", ""),
        "windowsAmiId": os.environ.get("WINDOWS_AMI_ID", ""),
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
    if len(sys.argv) < 2:
        print("Usage: python main.py <up|destroy>")
        sys.exit(1)

    operation = sys.argv[1]
    range_id = int(os.environ["RANGE_ID"])

    print(f"Starting {operation} for range {range_id}")
    print(f"Environment: {os.environ.get('ENVIRONMENT', 'unknown')}")

    run_pulumi(operation, range_id)

    print(f"Completed {operation} for range {range_id}")

"""NGFW Terraform operations for provisioning and deprovisioning.

This module provides the Terraform equivalent of the Pulumi NGFW operations.
It makes the same DB calls and emits the same SNS events as the Pulumi path.
"""

import json
import logging
import os
from typing import Any

import boto3

import ansible_runner
import aws_runner
import terraform_runner
from events import (
    STATUS_AWAITING_ASSOCIATION,
    STATUS_DESTROYED,
    STATUS_DESTROYING,
    STATUS_FAILED,
    STATUS_PROVISIONING,
    STATUS_READY,
    publish_ngfw_event,
)
from executors.ssh_executor import SSHExecutor

logger = logging.getLogger(__name__)


def run_ngfw_terraform(operation: str, request_id: str) -> None:
    """Run NGFW Terraform operation (provision or deprovision).

    This is the Terraform equivalent of run_ngfw_pulumi. It makes the same
    DB calls and emits the same SNS events, but uses Terraform instead of Pulumi.

    Args:
        operation: Either 'up' (provision) or 'destroy' (deprovision).
        request_id: UUID string of the Request.

    Raises:
        ValueError: If unknown operation or Request not found.
        Exception: If the Terraform operation fails.
    """
    # Import here to avoid circular imports
    from main import (
        get_ngfw_data_by_request_id,
        update_instance_state,
    )

    logger.info(
        "run_ngfw_terraform: starting operation=%s request_id=%s",
        operation,
        request_id,
    )

    # Get NGFW data from database (same as Pulumi path)
    ngfw_data = get_ngfw_data_by_request_id(request_id)

    # Validate required fields
    instance_id = ngfw_data.get("instance_id")
    if not instance_id:
        raise ValueError(f"Missing instance_id in NGFW data for request {request_id}")

    app_id = ngfw_data.get("app_id")
    if not app_id:
        raise ValueError(f"Missing app_id in NGFW data for request {request_id}")

    app_spec: dict[str, Any] = ngfw_data.get("app_spec", {})

    try:
        if operation == "up":
            sls_region = app_spec.get("sls_region", "americas")
            _run_provision(request_id, instance_id, app_id, app_spec, sls_region)
        elif operation == "destroy":
            _run_deprovision(request_id, instance_id, app_id)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    except Exception as e:
        error_msg = str(e)[:1000]
        logger.error("NGFW Terraform operation failed: %s", error_msg)

        if operation == "up":
            # Auto-cleanup on failure
            logger.info("NGFW provision failed - attempting auto-cleanup...")
            try:
                terraform_runner.destroy_ngfw(request_id, terraform_runner.NGFW_MODULE_PATH)
                terraform_runner.cleanup_ngfw_state(request_id)
            except Exception as cleanup_error:
                logger.warning("Auto-cleanup failed: %s", cleanup_error)

        # Update DB and emit failure event
        update_instance_state(request_id, STATUS_FAILED, error_message=error_msg)
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_id,
            app_id=app_id,
            status=STATUS_FAILED,
        )
        raise


def _run_provision(
    request_id: str,
    instance_id: str,
    app_id: str,
    app_spec: dict[str, Any],
    sls_region: str,
) -> None:
    """Run Terraform apply for NGFW, then run post-Terraform configuration."""
    from main import (
        NGFW_SSH_WAIT_TIMEOUT_DEFAULT,
        poll_for_serial_and_cert,
        update_instance_state,
    )

    # Update local DB and emit provisioning status event
    update_instance_state(request_id, STATUS_PROVISIONING)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_PROVISIONING,
    )

    logger.info("Running terraform apply for NGFW...")

    # Build Terraform variables from environment and app_spec
    user_id = app_spec.get("user_id", 0)
    tf_variables = {
        "name_prefix": f"ngfw-user-{user_id}",
        "user_id": user_id,
        "instance_uuid": instance_id,
        "request_uuid": request_id,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "subnet_id": os.environ.get("NGFW_SUBNET_ID", ""),
        "mgmt_security_group_id": os.environ.get("NGFW_MGMT_SECURITY_GROUP_ID", ""),
        "data_security_group_id": os.environ.get("NGFW_DATA_SECURITY_GROUP_ID", ""),
        "ami_id": os.environ.get("NGFW_AMI_ID", ""),
        "bootstrap_bucket": os.environ.get("NGFW_BOOTSTRAP_BUCKET", ""),
        "instance_type": os.environ.get("NGFW_INSTANCE_TYPE", "m5.xlarge"),
        "instance_profile_name": os.environ.get("NGFW_INSTANCE_PROFILE_NAME") or None,
        "scm_pin_id": app_spec.get("scm_pin_id", ""),
        "scm_pin_value": app_spec.get("scm_pin_value", ""),
        "scm_folder_name": app_spec.get("scm_folder_name", ""),
        "authcode": app_spec.get("authcode", ""),
    }

    # Run Terraform apply and get outputs
    output_data = terraform_runner.apply_ngfw(request_id, tf_variables, terraform_runner.NGFW_MODULE_PATH)
    logger.info("Terraform outputs: %s", json.dumps(output_data, indent=2))

    # Skip post-Terraform config in local dev mode
    if os.environ.get("DB_PASSWORD"):
        logger.info("LOCAL DEV MODE: Skipping post-Terraform NGFW configuration")
        update_instance_state(request_id, STATUS_READY, **output_data)
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_id,
            app_id=app_id,
            status=STATUS_READY,
        )
        logger.info("LOCAL DEV MODE: Setting NGFW status to stopped")
        update_instance_state(request_id, "stopped")
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_id,
            app_id=app_id,
            status="stopped",
        )
        return

    logger.info("Running post-Terraform NGFW configuration...")

    # Get SSH private key from Secrets Manager
    management_ip = output_data.get("management_ip")
    ssh_key_secret_arn = output_data.get("ssh_key_secret_arn")
    if not ssh_key_secret_arn:
        raise RuntimeError("NGFW Terraform missing ssh_key_secret_arn output")
    if not management_ip:
        raise RuntimeError("NGFW Terraform missing management_ip output")

    secrets_client = boto3.client("secretsmanager")
    try:
        secret_response = secrets_client.get_secret_value(SecretId=ssh_key_secret_arn)
        private_key = secret_response["SecretString"]
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve SSH key from Secrets Manager: {e}") from e

    # Wait for SSH availability (NGFW can take 15-25 min to boot)
    ssh_timeout = int(os.environ.get("NGFW_SSH_WAIT_TIMEOUT", NGFW_SSH_WAIT_TIMEOUT_DEFAULT))
    ansible_runner.wait_for_ssh(
        management_ip=management_ip,
        private_key=private_key,
        timeout_seconds=ssh_timeout,
    )

    # Run NGFW provision playbook via Ansible
    ansible_runner.run_ngfw_provision(
        management_ip=management_ip,
        private_key=private_key,
        sls_region=sls_region,
    )

    # Create SSHExecutor for serial polling (still uses SSH directly)
    ssh_executor = SSHExecutor(private_key=private_key)

    # Poll for serial number and certificate
    serial_number = poll_for_serial_and_cert(ssh_executor, management_ip)

    # Build state dict
    state = {
        **output_data,
        "serial_number": serial_number,
    }

    # Update DB with full state
    update_instance_state(request_id, STATUS_PROVISIONING, **state)

    # Auto-stop after provisioning to save costs (uses unified start/stop path)
    from main import run_ngfw_operation

    logger.info("Auto-stopping NGFW after provisioning...")
    run_ngfw_operation("stop", request_id)

    # Update to awaiting_association status
    update_instance_state(request_id, STATUS_AWAITING_ASSOCIATION)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_AWAITING_ASSOCIATION,
        serial_number=serial_number,
    )


def _run_deprovision(
    request_id: str,
    instance_id: str,
    app_id: str,
) -> None:
    """Run license deactivation then Terraform destroy for NGFW."""
    from main import get_ngfw_data_by_request_id, update_instance_state

    # Update local DB and emit destroying status event
    update_instance_state(request_id, STATUS_DESTROYING)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_DESTROYING,
    )

    # Get current instance state for license deactivation
    ngfw_data = get_ngfw_data_by_request_id(request_id)
    current_state = ngfw_data.get("state", {})
    management_ip = current_state.get("management_ip")
    ssh_key_secret_arn = current_state.get("ssh_key_secret_arn")
    ec2_instance_id = current_state.get("ec2_instance_id")

    # Run pre-destroy license deactivation via Ansible
    # NGFW must be running to SSH for license deactivation
    if management_ip and ssh_key_secret_arn and ec2_instance_id:
        logger.info("Running NGFW license deactivation via Ansible...")
        try:
            # Start NGFW if stopped (need SSH access for license deactivation)
            instance_state = aws_runner.get_instance_state(ec2_instance_id)
            if instance_state == "stopped":
                logger.info("Starting stopped NGFW for license deactivation...")
                aws_runner.start_ngfw(ec2_instance_id)

            # Get SSH key from Secrets Manager
            secrets_client = boto3.client("secretsmanager")
            secret_response = secrets_client.get_secret_value(SecretId=ssh_key_secret_arn)
            private_key = secret_response["SecretString"]

            # Wait for SSH to be available
            logger.info("Waiting for SSH availability before license deactivation...")
            ansible_runner.wait_for_ssh(
                management_ip=management_ip,
                private_key=private_key,
                timeout_seconds=300,  # 5 min should be enough for already-booted NGFW
            )

            # Deactivate license
            ansible_runner.run_ngfw_deprovision(
                management_ip=management_ip,
                private_key=private_key,
            )
        except Exception as e:
            logger.warning("License deactivation error: %s, proceeding with destroy", e)
    else:
        logger.warning(
            "Missing state fields for license deactivation (management_ip=%s, ssh_key=%s, ec2=%s), skipping",
            bool(management_ip),
            bool(ssh_key_secret_arn),
            bool(ec2_instance_id),
        )

    # Run Terraform destroy
    logger.info("Running terraform destroy for NGFW...")
    terraform_runner.destroy_ngfw(request_id, terraform_runner.NGFW_MODULE_PATH)

    # Cleanup state file from S3
    logger.info("Cleaning up Terraform state...")
    terraform_runner.cleanup_ngfw_state(request_id)

    # Update local DB and emit destroyed event
    update_instance_state(request_id, STATUS_DESTROYED)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_DESTROYED,
    )

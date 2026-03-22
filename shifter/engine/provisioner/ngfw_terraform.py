"""NGFW Terraform operations for provisioning and deprovisioning.

This module provides the Terraform equivalent of the Pulumi NGFW operations.
It makes the same DB calls and emits the same SNS events as the Pulumi path.
"""

import json
import logging
import os
import time
from typing import Any

import boto3

import terraform_runner
from events import (
    STATUS_DESTROYED,
    STATUS_DESTROYING,
    STATUS_FAILED,
    STATUS_PROVISIONING,
    STATUS_READY,
    publish_ngfw_event,
)
from executors.ngfw_executor import NGFWExecutor
from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.ngfw_provision import NGFWProvisionPlan

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
                tf_vars = _build_tf_variables(request_id, instance_id, app_spec)
                terraform_runner.destroy_ngfw(
                    request_id,
                    terraform_runner.NGFW_MODULE_PATH,
                    variables=tf_vars,
                )
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


def _build_tf_variables(
    request_id: str,
    instance_id: str,
    app_spec: dict[str, Any],
) -> dict[str, Any]:
    """Build Terraform variables from environment and app_spec.

    Used by both provision and deprovision paths so Terraform has
    all declared variables available.
    """
    user_id = app_spec.get("user_id", 0)
    return {
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

    tf_variables = _build_tf_variables(request_id, instance_id, app_spec)

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
        logger.info("LOCAL DEV MODE: Setting NGFW status to paused")
        update_instance_state(request_id, "paused")
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_id,
            app_id=app_id,
            status="paused",
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

    from cloud import get_secrets_store

    try:
        private_key = get_secrets_store().get_secret(ssh_key_secret_arn)
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve SSH key from Secrets Manager: {e}") from e

    # Create NGFWExecutor for all SSH operations (uses piping, not paramiko)
    ssh_executor = NGFWExecutor(private_key=private_key)

    # Wait for SSH availability (NGFW can take 15-25 min to boot)
    ssh_timeout = int(os.environ.get("NGFW_SSH_WAIT_TIMEOUT", NGFW_SSH_WAIT_TIMEOUT_DEFAULT))
    logger.info("Waiting for SSH on NGFW at %s...", management_ip)
    ssh_executor.wait_for_agent(management_ip, timeout_seconds=ssh_timeout)

    # Poll for serial number BEFORE running provision plan - this ensures management
    # plane is ready to accept configuration commands. Serial number appearing
    # indicates the PAN-OS management server is operational.
    from main import poll_for_serial_number

    logger.info("Polling for NGFW serial number (management plane readiness check)...")
    serial_number = poll_for_serial_number(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=600,  # 10 min - serial should appear after mgmt plane is up
        poll_interval=30,
    )
    logger.info("NGFW management plane ready, serial=%s", serial_number)

    # Brief pause after serial poll to let management plane stabilize
    logger.info("Waiting 30s for management plane to stabilize before configuration...")
    time.sleep(30)

    # Re-verify SSH availability with extended timeout to handle potential NGFW reboots
    # PAN-OS may auto-reboot after licensing, causing SSH to become temporarily unavailable
    logger.info("Re-verifying SSH availability (allowing for potential NGFW reboot)...")
    ssh_executor.wait_for_agent(management_ip, timeout_seconds=600)  # 10 min retry period
    logger.info("SSH confirmed available, proceeding with configuration...")

    # Create orchestrator with SSH executor
    orchestrator = SetupOrchestrator(executor=ssh_executor)

    # Create context dict with the Terraform outputs for template rendering
    context = {
        "ec2_instance_id": output_data.get("ec2_instance_id"),
        "management_ip": management_ip,
        "dataplane_ip": output_data.get("dataplane_ip"),
        "data_eni_id": output_data.get("data_eni_id"),
        "sls_region": sls_region,
    }

    # Run the NGFW provision plan
    provision_plan = NGFWProvisionPlan()
    logger.info("Running NGFW provision plan...")
    provision_result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=provision_plan,
        context=context,
    )

    if not provision_result.success:
        raise RuntimeError("NGFW post-Terraform configuration failed")

    # Build state dict with all outputs including data_eni_id for range routing
    state = {
        **output_data,
        "serial_number": serial_number,
    }

    # Save state to DB so run_ngfw_operation can find ec2_instance_id
    update_instance_state(request_id, STATUS_PROVISIONING, **state)

    # Fetch license (retrieves Logging Service license)
    logger.info("Fetching NGFW license: request_id=%s", request_id)
    license_result = ssh_executor.run_command(
        instance_id=management_ip,
        script="request license fetch",
        timeout_seconds=120,
    )
    if not license_result.success:
        logger.warning("License fetch returned non-success: %s", license_result.stderr)
    logger.info(
        "License fetch output: %s",
        license_result.stdout[:500] if license_result.stdout else "(empty)",
    )

    # Poll for valid device certificate
    from main import poll_for_serial_and_cert

    logger.info("Polling for valid device certificate: request_id=%s", request_id)
    poll_timeout = int(os.environ.get("NGFW_CERT_POLL_TIMEOUT", 2400))  # 40 min default
    cert_serial = poll_for_serial_and_cert(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=poll_timeout,
        poll_interval=30,
    )
    # Use cert poll serial if available (more recent), otherwise keep initial serial
    if cert_serial:
        serial_number = cert_serial

    # Mark NGFW as ready
    update_instance_state(request_id, STATUS_READY, serial_number=serial_number)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_READY,
        serial_number=serial_number,
    )
    logger.info("NGFW provisioning complete, serial=%s: request_id=%s", serial_number, request_id)

    # Auto-stop NGFW to save costs (non-fatal)
    from main import run_ngfw_operation

    logger.info("Auto-stopping NGFW: request_id=%s", request_id)
    try:
        run_ngfw_operation("stop", request_id)
        logger.info("Auto-stop completed: request_id=%s", request_id)
    except Exception:
        logger.exception(
            "Auto-stop failed (non-fatal) - NGFW remains running: request_id=%s",
            request_id,
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

    # Run pre-destroy license deactivation via SSH
    # NGFW must be running to SSH for license deactivation
    if management_ip and ssh_key_secret_arn and ec2_instance_id:
        logger.info("Running NGFW license deactivation...")
        try:
            # Start NGFW if stopped (need SSH access for license deactivation)
            ec2_client = boto3.client("ec2")
            response = ec2_client.describe_instances(InstanceIds=[ec2_instance_id])
            instance_state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
            if instance_state == "stopped":
                logger.info("Starting stopped NGFW for license deactivation...")
                ec2_client.start_instances(InstanceIds=[ec2_instance_id])
                # Wait for instance to be running
                waiter = ec2_client.get_waiter("instance_running")
                waiter.wait(InstanceIds=[ec2_instance_id])

            # Get SSH key from Secrets Manager
            from cloud import get_secrets_store

            private_key = get_secrets_store().get_secret(ssh_key_secret_arn)

            # Create NGFWExecutor and wait for SSH (uses piping, not paramiko)
            ssh_executor = NGFWExecutor(private_key=private_key)
            logger.info("Waiting for SSH availability before license deactivation...")
            ssh_executor.wait_for_agent(management_ip, timeout_seconds=300)

            # Deactivate license
            logger.info("Deactivating VM-Series license...")
            ssh_executor.run_command(
                instance_id=management_ip,
                script="",
                stdin_input="request license deactivate VM-Capacity mode auto\n",
                timeout_seconds=120,
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

    # Build variables for destroy (Terraform needs all declared variables)
    app_spec: dict[str, Any] = ngfw_data.get("app_spec", {})
    tf_variables = _build_tf_variables(request_id, instance_id, app_spec)

    # Run Terraform destroy
    logger.info("Running terraform destroy for NGFW...")
    terraform_runner.destroy_ngfw(
        request_id,
        terraform_runner.NGFW_MODULE_PATH,
        variables=tf_variables,
    )

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

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


def _build_provider_state(output_data: dict[str, Any]) -> dict[str, Any]:
    """Build provider-neutral NGFW state fields for the Terraform outputs."""
    cloud_provider = output_data.get("cloud_provider") or os.environ.get("CLOUD_PROVIDER", "aws")
    management_ip = output_data.get("management_ip", "")
    dataplane_ip = output_data.get("dataplane_ip", "")
    data_attachment_id = output_data.get("data_eni_id", "")
    ssh_key_secret_arn = output_data.get("ssh_key_secret_arn", "")
    if cloud_provider == "gcp":
        data_attachment_id = output_data.get("data_attachment_id", "")
        return {
            "cloud_provider": "gcp",
            "route_next_hop_ip": output_data.get("route_next_hop_ip", ""),
            "attachment_mode": output_data.get("attachment_mode", "gdc-vmruntime-palo-alto-vmseries"),
            "data_attachment_id": data_attachment_id,
            "attached_ranges": [],
            "provider_metadata": output_data.get("provider_metadata", {}),
        }

    provider_state = {
        "management_ip": management_ip,
        "dataplane_ip": dataplane_ip,
        "route_next_hop_ip": dataplane_ip,
        "attachment_mode": "aws-route-table-eni" if cloud_provider == "aws" else "",
        "data_attachment_id": data_attachment_id,
        "data_eni_id": data_attachment_id,
        "ssh_key_secret_arn": ssh_key_secret_arn,
    }
    return {
        "cloud_provider": cloud_provider,
        "route_next_hop_ip": dataplane_ip,
        "attachment_mode": provider_state["attachment_mode"],
        "data_attachment_id": data_attachment_id,
        "attached_ranges": [],
        "provider_metadata": {
            cloud_provider: provider_state,
        },
    }


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
            if os.environ.get("CLOUD_PROVIDER", "aws") == "gcp":
                _run_gdc_provision(request_id, instance_id, app_id, app_spec, sls_region)
            else:
                _run_provision(request_id, instance_id, app_id, app_spec, sls_region)
        elif operation == "destroy":
            if os.environ.get("CLOUD_PROVIDER", "aws") == "gcp":
                _run_gdc_deprovision(request_id, instance_id, app_id)
            else:
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
                if os.environ.get("CLOUD_PROVIDER", "aws") == "gcp":
                    from main import get_ngfw_data_by_request_id

                    gdc_state = get_ngfw_data_by_request_id(request_id).get("state", {})
                    if gdc_state:
                        import gdc_vmseries_ngfw

                        gdc_vmseries_ngfw.destroy_ngfw(gdc_state)
                else:
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


def _run_pan_os_post_provision(
    *,
    request_id: str,
    instance_id: str,
    app_id: str,
    output_data: dict[str, Any],
    sls_region: str,
) -> None:
    """Run shared PAN-OS VM-Series post-boot configuration for any provider."""
    from main import (
        NGFW_SSH_WAIT_TIMEOUT_DEFAULT,
        poll_for_serial_number,
        update_instance_state,
    )

    # Skip post-infrastructure config in local dev mode.
    if os.environ.get("DB_PASSWORD"):
        logger.info("LOCAL DEV MODE: Skipping post-infrastructure NGFW configuration")
        update_instance_state(request_id, STATUS_READY, **output_data, **_build_provider_state(output_data))
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

    logger.info("Running post-infrastructure NGFW configuration...")

    management_ip = output_data.get("management_ip")
    ssh_key_secret_arn = output_data.get("ssh_key_secret_arn")
    if not ssh_key_secret_arn:
        raise RuntimeError("NGFW provisioning output missing ssh_key_secret_arn")
    if not management_ip:
        raise RuntimeError("NGFW provisioning output missing management_ip")

    from cloud import get_secrets_store

    try:
        private_key = get_secrets_store().get_secret(ssh_key_secret_arn)
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve SSH key from Secrets Manager: {e}") from e

    ssh_executor = NGFWExecutor(private_key=private_key)

    # Wait for SSH availability (VM-Series can take 15-25 min to boot).
    ssh_timeout = int(os.environ.get("NGFW_SSH_WAIT_TIMEOUT", NGFW_SSH_WAIT_TIMEOUT_DEFAULT))
    logger.info("Waiting for SSH on NGFW at %s...", management_ip)
    ssh_executor.wait_for_agent(management_ip, timeout_seconds=ssh_timeout)

    # Poll for serial number BEFORE running provision plan - this ensures the
    # PAN-OS management plane is operational.
    logger.info("Polling for NGFW serial number (management plane readiness check)...")
    serial_number = poll_for_serial_number(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=600,
        poll_interval=30,
    )
    logger.info("NGFW management plane ready, serial=%s", serial_number)

    logger.info("Waiting 30s for management plane to stabilize before configuration...")
    time.sleep(30)

    # Re-verify SSH availability with extended timeout to handle potential VM-Series reboots.
    logger.info("Re-verifying SSH availability (allowing for potential NGFW reboot)...")
    ssh_executor.wait_for_agent(management_ip, timeout_seconds=600)
    logger.info("SSH confirmed available, proceeding with configuration...")

    orchestrator = SetupOrchestrator(executor=ssh_executor)
    context = {
        "ec2_instance_id": output_data.get("ec2_instance_id"),
        "management_ip": management_ip,
        "dataplane_ip": output_data.get("dataplane_ip"),
        "data_eni_id": output_data.get("data_eni_id"),
        "sls_region": sls_region,
    }

    provision_plan = NGFWProvisionPlan()
    logger.info("Running NGFW provision plan...")
    provision_result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=provision_plan,
        context=context,
    )
    if not provision_result.success:
        raise RuntimeError("NGFW post-infrastructure configuration failed")

    state = {
        **output_data,
        **_build_provider_state(output_data),
        "serial_number": serial_number,
    }
    update_instance_state(request_id, STATUS_PROVISIONING, **state)

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

    from main import poll_for_serial_and_cert, run_ngfw_operation

    logger.info("Polling for valid device certificate: request_id=%s", request_id)
    poll_timeout = int(os.environ.get("NGFW_CERT_POLL_TIMEOUT", 2400))
    cert_serial = poll_for_serial_and_cert(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=poll_timeout,
        poll_interval=30,
    )
    if cert_serial:
        serial_number = cert_serial

    update_instance_state(request_id, STATUS_READY, serial_number=serial_number)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_READY,
        serial_number=serial_number,
    )
    logger.info("NGFW provisioning complete, serial=%s: request_id=%s", serial_number, request_id)

    logger.info("Auto-stopping NGFW: request_id=%s", request_id)
    try:
        run_ngfw_operation("stop", request_id)
        logger.info("Auto-stop completed: request_id=%s", request_id)
    except Exception:
        logger.exception(
            "Auto-stop failed (non-fatal) - NGFW remains running: request_id=%s",
            request_id,
        )


def _run_provision(
    request_id: str,
    instance_id: str,
    app_id: str,
    app_spec: dict[str, Any],
    sls_region: str,
) -> None:
    """Run Terraform apply for NGFW, then run post-Terraform configuration."""
    from main import update_instance_state

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

    _run_pan_os_post_provision(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        output_data=output_data,
        sls_region=sls_region,
    )


def _run_gdc_provision(
    request_id: str,
    instance_id: str,
    app_id: str,
    app_spec: dict[str, Any],
    sls_region: str,
) -> None:
    """Create a Palo Alto VM-Series firewall on GDC VM Runtime, then configure PAN-OS."""
    import gdc_vmseries_ngfw
    from main import update_instance_state

    update_instance_state(request_id, STATUS_PROVISIONING)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_PROVISIONING,
    )

    logger.info("Running GDC VM Runtime provisioning for Palo Alto VM-Series...")
    output_data = gdc_vmseries_ngfw.apply_ngfw(
        request_id=request_id,
        instance_id=instance_id,
        app_spec=app_spec,
    )
    logger.info("GDC VM-Series outputs: %s", json.dumps(output_data, indent=2))

    # Persist the VM Runtime state before waiting on PAN-OS so failure cleanup has enough context.
    update_instance_state(request_id, STATUS_PROVISIONING, **output_data, **_build_provider_state(output_data))

    _run_pan_os_post_provision(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        output_data=output_data,
        sls_region=sls_region,
    )


def _deactivate_vmseries_license(
    *,
    management_ip: str,
    ssh_key_secret_arn: str,
) -> None:
    """Best-effort VM-Series license deactivation over PAN-OS SSH."""
    from cloud import get_secrets_store

    private_key = get_secrets_store().get_secret(ssh_key_secret_arn)
    ssh_executor = NGFWExecutor(private_key=private_key)
    logger.info("Waiting for SSH availability before license deactivation...")
    ssh_executor.wait_for_agent(management_ip, timeout_seconds=300)

    logger.info("Deactivating VM-Series license...")
    ssh_executor.run_command(
        instance_id=management_ip,
        script="",
        stdin_input="request license deactivate VM-Capacity mode auto\n",
        timeout_seconds=120,
    )


def _run_gdc_deprovision(
    request_id: str,
    instance_id: str,
    app_id: str,
) -> None:
    """Deactivate and destroy a Palo Alto VM-Series firewall on GDC VM Runtime."""
    import gdc_vmseries_ngfw
    from main import get_ngfw_data_by_request_id, update_instance_state

    update_instance_state(request_id, STATUS_DESTROYING)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_DESTROYING,
    )

    ngfw_data = get_ngfw_data_by_request_id(request_id)
    current_state = ngfw_data.get("state", {})
    management_ip = current_state.get("management_ip")
    ssh_key_secret_arn = current_state.get("ssh_key_secret_arn")

    if management_ip and ssh_key_secret_arn:
        try:
            gdc_vmseries_ngfw.run_power_operation("start", current_state)
            _deactivate_vmseries_license(
                management_ip=management_ip,
                ssh_key_secret_arn=ssh_key_secret_arn,
            )
        except Exception as e:
            logger.warning("GDC VM-Series license deactivation error: %s, proceeding with destroy", e)
    else:
        logger.warning(
            "Missing GDC VM-Series state fields for license deactivation (management_ip=%s, ssh_key=%s), skipping",
            bool(management_ip),
            bool(ssh_key_secret_arn),
        )

    logger.info("Destroying GDC VM Runtime Palo Alto VM-Series resources...")
    gdc_vmseries_ngfw.destroy_ngfw(current_state)

    update_instance_state(request_id, STATUS_DESTROYED)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_DESTROYED,
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

"""Cleanup and deprovision helpers for NGFW Terraform operations."""

import logging
import os
from typing import Any

import boto3

import terraform_runner
from events import (
    STATUS_DESTROYED,
    STATUS_DESTROYING,
    publish_ngfw_event,
)
from executors.ngfw_executor import NGFWExecutor
from ngfw_terraform_state import _build_tf_variables

logger = logging.getLogger(__name__)


def _cleanup_ngfw_bootstrap_objects(instance_id: str) -> None:
    """Delete sensitive AWS S3 bootstrap objects after NGFW readiness."""
    if os.environ.get("CLOUD_PROVIDER", "aws") != "aws":
        return

    bootstrap_bucket = os.environ.get("NGFW_BOOTSTRAP_BUCKET", "").strip()
    if not bootstrap_bucket:
        raise RuntimeError("NGFW_BOOTSTRAP_BUCKET is required for bootstrap object cleanup")

    from cloud import get_object_storage

    storage = get_object_storage()
    bootstrap_prefix = f"bootstrap/ngfw/{instance_id}"
    failures: list[tuple[str, Exception]] = []
    for key in (
        f"{bootstrap_prefix}/config/init-cfg.txt",
        f"{bootstrap_prefix}/license/authcodes",
    ):
        logger.info("Deleting NGFW bootstrap object: bucket=%s key=%s", bootstrap_bucket, key)
        try:
            storage.delete_object(bucket=bootstrap_bucket, key=key)
        except Exception as e:
            logger.exception(
                "Failed to delete NGFW bootstrap object: bucket=%s key=%s error=%s",
                bootstrap_bucket,
                key,
                e,
            )
            failures.append((key, e))

    if failures:
        failed_keys = [key for key, _ in failures]
        raise RuntimeError(f"Failed to delete NGFW bootstrap object(s): {', '.join(failed_keys)}") from failures[-1][1]


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


def _deactivate_aws_vmseries_license(current_state: dict[str, Any]) -> None:
    """Start the AWS NGFW if needed and deactivate its VM-Series license."""
    management_ip = current_state.get("management_ip")
    ssh_key_secret_arn = current_state.get("ssh_key_secret_arn")
    ec2_instance_id = current_state.get("ec2_instance_id")
    if not (management_ip and ssh_key_secret_arn and ec2_instance_id):
        logger.warning(
            "Missing state fields for license deactivation (management_ip=%s, ssh_key=%s, ec2=%s), skipping",
            bool(management_ip),
            bool(ssh_key_secret_arn),
            bool(ec2_instance_id),
        )
        return

    logger.info("Running NGFW license deactivation...")
    try:
        ec2_client = boto3.client("ec2")
        response = ec2_client.describe_instances(InstanceIds=[ec2_instance_id])
        instance_state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
        if instance_state == "stopped":
            logger.info("Starting stopped NGFW for license deactivation...")
            ec2_client.start_instances(InstanceIds=[ec2_instance_id])
            waiter = ec2_client.get_waiter("instance_running")
            waiter.wait(InstanceIds=[ec2_instance_id])

        _deactivate_vmseries_license(
            management_ip=management_ip,
            ssh_key_secret_arn=ssh_key_secret_arn,
        )
    except Exception as e:
        logger.warning("License deactivation error: %s, proceeding with destroy", e)


def _run_deprovision(
    request_id: str,
    instance_id: str,
    app_id: str,
) -> None:
    """Run license deactivation then Terraform destroy for NGFW."""
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
    _deactivate_aws_vmseries_license(current_state)

    app_spec: dict[str, Any] = ngfw_data.get("app_spec", {})
    tf_variables = _build_tf_variables(request_id, instance_id, app_spec)

    logger.info("Running terraform destroy for NGFW...")
    terraform_runner.destroy_ngfw(
        request_id,
        terraform_runner.NGFW_MODULE_PATH,
        variables=tf_variables,
    )

    logger.info("Cleaning up Terraform state...")
    terraform_runner.cleanup_ngfw_state(request_id)

    update_instance_state(request_id, STATUS_DESTROYED)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_id,
        app_id=app_id,
        status=STATUS_DESTROYED,
    )

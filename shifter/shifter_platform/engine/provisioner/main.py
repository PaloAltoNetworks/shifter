"""Shifter Engine provisioner — Django-integrated entry point.

This module provides the provisioner functions called by Celery tasks
(engine/tasks.py). It handles:
- Range provisioning and destruction via Terraform
- NGFW lifecycle operations (provision, start, stop, complete-setup)
- Instance setup via SSM/SSH orchestration
- Database updates via Django ORM
"""

import ipaddress
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from django.utils import timezone

from engine.provisioner.catalog.instances import (
    _get_dc_instance_type,
    _get_kali_instance_type,
    _get_victim_instance_type,
    _get_windows_instance_type,
)
from engine.provisioner.config import generate_presigned_url
from engine.provisioner.events import (
    STATUS_DESTROYED,
    STATUS_FAILED,
    STATUS_READY,
    publish_destroyed,
    publish_failed,
    publish_ngfw_event,
    publish_ready,
    publish_status_update,
)
from engine.provisioner.executors.aws_executor import AWSExecutor
from engine.provisioner.executors.ssh_executor import SSHExecutor
from engine.provisioner.executors.ssm_executor import SSMExecutor
from engine.provisioner.orchestrators.ops_orchestrator import OpsOrchestrator
from engine.provisioner.orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from engine.provisioner.plans.base import SetupStep
from engine.provisioner.plans.bootstrap import BootstrapPlan
from engine.provisioner.plans.dc_setup import DCSetupPlan
from engine.provisioner.plans.domain_join import DomainJoinPlan
from engine.provisioner.plans.linux_bootstrap import LinuxBootstrapPlan
from engine.provisioner.plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from engine.provisioner.plans.ngfw_configure_subnets import NGFWConfigureSubnetsPlan, NGFWRemoveSubnetsPlan
from engine.provisioner.plans.xdr_agent_install import XDRAgentInstallPlan
from engine.provisioner.terraform import ngfw_runner as ngfw_terraform
from engine.provisioner.terraform import range_runner as range_terraform_runner
from engine.provisioner.utils.text import sanitize_hostname

logger = logging.getLogger(__name__)


def get_agent_presigned_url(inst_config: dict) -> str | None:
    """Generate presigned URL for XDR agent from instance config.

    Args:
        inst_config: Instance config dict from range_spec containing agent data.

    Returns:
        Presigned URL string, or None if agent data missing.
    """
    agent_data = inst_config.get("agent") or {}
    s3_key = agent_data.get("s3_key")
    if not s3_key:
        return None

    bucket = os.environ.get("AGENT_S3_BUCKET", "")
    if not bucket:
        logger.warning("AGENT_S3_BUCKET not set, cannot generate presigned URL")
        return None

    try:
        s3_client = boto3.client("s3")
        url: str = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": s3_key},
            ExpiresIn=3600,
        )
        return url
    except Exception as e:
        logger.error("Failed to generate presigned URL for %s: %s", s3_key, e)
        return None


class DynamicPlan:
    """Simple wrapper for dynamically-built setup plans.

    Wraps a list of steps to satisfy the SetupPlan protocol
    when steps are built at runtime (e.g., from subnet lists).
    """

    def __init__(self, name: str, steps: list[SetupStep]) -> None:
        self.name = name
        self.steps = steps
        self.verify_step: SetupStep | None = None

    def get_context(self, instance: object) -> dict:
        """No template variables needed - steps are pre-built."""
        return {}


# SSM parameter paths for AMI IDs (fetched at runtime for latest values)
_AMI_SSM_PARAMS = {
    "kali": "/shifter/ami/kali",
    "victim": "/shifter/ami/ubuntu",
    "windows": "/shifter/ami/windows",
    "dc": "/shifter/ami/dc",
}

# Cache for SSM AMI lookups (cleared per invocation, avoids repeated API calls)
_ami_cache: dict[str, str] = {}


def get_ami_id(ami_type: str) -> str:
    """Get AMI ID from SSM Parameter Store at runtime.

    This ensures the provisioner always uses the latest AMI IDs without
    requiring a Terraform apply or ECS task definition update.

    Args:
        ami_type: One of 'kali', 'victim', 'windows', 'dc'

    Returns:
        AMI ID string

    Raises:
        ValueError: If ami_type is unknown or SSM parameter not found
    """
    if ami_type in _ami_cache:
        return _ami_cache[ami_type]

    param_path = _AMI_SSM_PARAMS.get(ami_type)
    if not param_path:
        raise ValueError(f"Unknown AMI type: {ami_type}")

    try:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(Name=param_path)
        ami_id = response["Parameter"]["Value"]
        logger.info("Fetched %s AMI from SSM %s: %s", ami_type, param_path, ami_id)
        _ami_cache[ami_type] = ami_id
        return ami_id
    except Exception as e:
        # No fallback - fail fast to surface IAM/config issues immediately
        raise ValueError(f"Failed to get {ami_type} AMI ID from SSM parameter {param_path}: {e}") from e


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


def update_range_status(range_id: int, status: str, **kwargs: str | int | None) -> None:
    """Update range status in database via Django ORM.

    Args:
        range_id: The ID of the range to update.
        status: New status value (e.g., 'provisioning', 'ready', 'failed').
        **kwargs: Additional fields to update (e.g., error_message, paused_at, ready_at).
    """
    from engine.models import Range

    logger.debug("update_range_status: range_id=%s status=%s kwargs=%s", range_id, status, list(kwargs.keys()))

    update_fields = {"status": status, "updated_at": timezone.now()}
    for key, value in kwargs.items():
        if value is not None:
            if value == "NOW()":
                update_fields[key] = timezone.now()
            else:
                update_fields[key] = value

    Range.objects.filter(id=range_id).update(**update_fields)


def write_provisioned_state(
    range_id: int,
    subnets: dict[str, dict],
    instances: list[dict],
    ngfw_instance_id: int | None = None,
) -> None:
    """Write provisioned infrastructure state directly to database via Django ORM.

    Args:
        range_id: The range ID being provisioned.
        subnets: Dict of subnet_name -> subnet details with uuid and AWS resource IDs.
        instances: List of instance dicts with uuid, instance_id, private_ip, etc.
        ngfw_instance_id: ID of the NGFW Instance this range is attached to (if any).
    """
    from engine.models import Instance, Range, Subnet

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

        updated = Subnet.objects.filter(uuid=subnet_uuid, range_id=range_id).update(state=state, status="ready")
        if updated == 0:
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

        instance_state = {
            "aws_instance_id": inst.get("instance_id"),
            "private_ip": inst.get("private_ip"),
            "ssh_key_secret_arn": inst.get("ssh_key_secret_arn"),
            "subnet_name": inst.get("subnet_name"),
        }

        updated = Instance.objects.filter(uuid=instance_uuid).update(status="ready", state=instance_state)
        if updated == 0:
            raise ValueError(f"No engine_instance record found for uuid={instance_uuid}")
        logger.debug("Updated engine_instance state: uuid=%s", instance_uuid)

        provisioned_instances.append(
            {
                "uuid": instance_uuid,
                "name": inst.get("name"),
                "role": inst.get("role"),
                "os_type": inst.get("os"),
                "subnet_name": inst.get("subnet_name"),
                "instance_id": inst.get("instance_id"),
                "private_ip": inst.get("private_ip"),
                "ssh_key_secret_arn": inst.get("ssh_key_secret_arn"),
            }
        )

    # Update Range.provisioned_instances and ngfw_instance_id
    updated = Range.objects.filter(id=range_id).update(
        provisioned_instances=provisioned_instances,
        ngfw_instance_id=ngfw_instance_id,
        updated_at=timezone.now(),
    )
    if updated == 0:
        raise ValueError(f"No mission_control_range record found for id={range_id}")
    logger.debug(
        "Updated Range.provisioned_instances: range_id=%s count=%d",
        range_id,
        len(provisioned_instances),
    )
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
    from engine.models import Instance, Range, Subnet

    now = timezone.now()

    # Get instances via Range -> Request -> Instance relationship
    range_obj = Range.objects.select_related("request").filter(id=range_id).first()
    if range_obj and range_obj.request:
        instance_count = Instance.objects.filter(request=range_obj.request).update(status="destroyed", destroyed_at=now)
    else:
        instance_count = 0

    logger.debug(
        "Marked %d engine_instance records as destroyed for range_id=%s",
        instance_count,
        range_id,
    )

    # Update engine_subnet records
    subnet_count = Subnet.objects.filter(range_id=range_id).update(status="destroyed", destroyed_at=now)
    logger.debug(
        "Marked %d engine_subnet records as destroyed for range_id=%s",
        subnet_count,
        range_id,
    )

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
    Includes 'stopping' status because range provisioner will wait for
    stop to complete, then start the NGFW.

    Args:
        user_id: Django User ID.

    Returns:
        Dictionary with ec2_instance_id, management_ip, ssh_key_secret_arn,
        and ngfw_request_id. Returns None if user has no NGFW.
    """
    from engine.models import Instance

    instance = (
        Instance.objects.filter(
            role="ngfw",
            request__user_id=user_id,
            status__in=["ready", "active", "stopped", "stopping"],
        )
        .select_related("request")
        .order_by("-created_at")
        .first()
    )

    if not instance:
        return None

    assert instance.request is not None  # guaranteed by filter on request__user_id
    state = instance.state or {}
    return {
        "ngfw_request_id": str(instance.request.request_id),
        "ec2_instance_id": state.get("ec2_instance_id"),
        "management_ip": state.get("management_ip"),
        "ssh_key_secret_arn": state.get("ssh_key_secret_arn"),
        "status": instance.status,
    }


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

    # Wait for management plane to be ready
    logger.info("Verifying NGFW management plane is ready...")
    poll_for_serial_number(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=300,  # 5 min - should be quick since NGFW is running
        poll_interval=15,
    )

    # Build dynamic steps and wrap in DynamicPlan for SetupOrchestrator
    # This ensures consistent execution flow with proven retry/commit handling
    steps = NGFWRemoveSubnetsPlan().get_steps(subnets, range_id)
    plan = DynamicPlan(name="ngfw_remove_subnets", steps=steps)

    orchestrator = SetupOrchestrator(ssh_executor)
    logger.info("Running NGFW subnet removal via SetupOrchestrator...")
    result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=plan,
        context={},
    )

    if not result.success:
        raise RuntimeError(f"NGFW subnet removal failed: {result.error or 'unknown error'}")

    logger.info("NGFW subnet removal complete for range %s", range_id)


def user_has_active_ranges(user_id: int, exclude_range_id: int) -> bool:
    """Check if user has any active ranges besides the one being destroyed.

    Args:
        user_id: Django User ID.
        exclude_range_id: Range ID to exclude from the check.

    Returns:
        True if user has other active ranges, False otherwise.
    """
    from engine.models import Range

    logger.debug("user_has_active_ranges: user_id=%s exclude_range_id=%s", user_id, exclude_range_id)
    exists = (
        Range.objects.filter(
            user_id=user_id,
            status__in=["ready", "provisioning"],
        )
        .exclude(id=exclude_range_id)
        .exists()
    )
    logger.debug("user_has_active_ranges: %s", exists)
    return exists


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
    from engine.models import App, Instance

    instance = (
        Instance.objects.filter(
            role="ngfw",
            request__request_id=request_id,
        )
        .select_related("request")
        .first()
    )

    if not instance:
        raise ValueError(f"NGFW request not found: {request_id}")

    assert instance.request is not None  # guaranteed by filter on request__request_id
    app = App.objects.filter(instance=instance).first()

    return {
        "request_id": str(instance.request.request_id),
        "instance_id": str(instance.uuid),
        "app_id": str(app.uuid) if app else None,
        "spec": instance.spec or {},
        "app_spec": app.spec if app else {},
        "state": instance.state or {},
        "status": instance.status,
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
    from engine.models import Instance, Range

    range_obj = Range.objects.filter(request__request_id=request_id).select_related("request").first()

    if not range_obj:
        raise ValueError(f"Range request not found: {request_id}")

    range_config = range_obj.range_config or {}
    user_id = range_obj.user_id
    ngfw_instance_id = None

    # Look up NGFW instance ID if ngfw is enabled
    if range_config.get("ngfw", False):
        ngfw_instance = (
            Instance.objects.filter(
                role="ngfw",
                request__user_id=user_id,
                status="active",
            )
            .order_by("-created_at")
            .first()
        )
        # Check that state has service_name
        if ngfw_instance and ngfw_instance.state and ngfw_instance.state.get("service_name"):
            ngfw_instance_id = ngfw_instance.id

    assert range_obj.request is not None  # guaranteed by filter on request__request_id
    return {
        "request_id": str(range_obj.request.request_id),
        "range_id": range_obj.id,
        "user_id": user_id,
        "spec": range_config,
        "subnet_index": range_obj.subnet_index,
        "status": range_obj.status,
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


def wait_for_autocommit(
    ssh_executor: "SSHExecutor",
    host: str,
    timeout_seconds: int = 600,
    poll_interval: int = 15,
) -> None:
    """Wait for NGFW boot autocommit to complete before configuring.

    After boot, PAN-OS runs an autocommit that must complete before any
    configuration changes can be made. This function polls 'show jobs all'
    until there are no active (ACT) commit jobs.

    Args:
        ssh_executor: SSHExecutor instance for running commands.
        host: NGFW management IP address.
        timeout_seconds: Maximum time to wait (default 10 min).
        poll_interval: Seconds between poll attempts (default 15s).

    Raises:
        RuntimeError: If autocommit doesn't complete within timeout.
    """
    import re
    import time

    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise RuntimeError(
                f"NGFW autocommit did not complete after {timeout_seconds}s - management plane may be stuck"
            )

        logger.info(
            "Checking for active NGFW jobs... (%.0fs / %ds)",
            elapsed,
            timeout_seconds,
        )

        try:
            result = ssh_executor.run_command(
                instance_id=host,
                script="show jobs all",
                timeout_seconds=60,
            )

            # Parse job output for any active (ACT) jobs
            # Output format has Status column with ACT (active) or FIN (finished)
            # We look for "ACT" which indicates a job is still running
            output = result.stdout

            # Check for active jobs - look for ACT in the output
            # The output format is tabular with columns like:
            # Enqueued  ID  Type  Status  Result  Completed
            has_active_jobs = bool(re.search(r"\bACT\b", output))

            if not has_active_jobs:
                logger.info(
                    "No active NGFW jobs found after %.0fs - ready for configuration",
                    elapsed,
                )
                return

            # Log which jobs are active
            active_lines = [line.strip() for line in output.split("\n") if "ACT" in line]
            logger.info(
                "Found %d active job(s), waiting %ds: %s",
                len(active_lines),
                poll_interval,
                active_lines[:3],  # Show first 3 for brevity
            )

        except Exception as e:
            logger.warning("Error checking NGFW jobs (will retry): %s", e)

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
    from engine.models import App, Instance

    instance = Instance.objects.filter(
        role="ngfw",
        request__request_id=request_id,
    ).first()

    if not instance:
        raise ValueError(f"NGFW instance not found for request: {request_id}")

    # Merge state updates into current state
    current_state = instance.state or {}
    if state_updates:
        current_state.update(state_updates)

    # Update Instance with new status and merged state
    now = timezone.now()
    instance.status = status
    instance.state = current_state
    instance.updated_at = now
    if status == STATUS_DESTROYED:
        instance.destroyed_at = now
    instance.save(update_fields=["status", "state", "updated_at", "destroyed_at"])

    # Update App status (if app exists)
    app_update = {"status": status, "updated_at": now}
    if status == STATUS_DESTROYED:
        app_update["destroyed_at"] = now
    App.objects.filter(instance=instance).update(**app_update)


# =============================================================================
# Post-Terraform Setup Functions
# These run AFTER terraform apply creates infrastructure, BEFORE marking range ready
# =============================================================================


def find_stale_routes_by_cidr(
    ssh_executor: SSHExecutor,
    management_ip: str,
    target_cidrs: set[str],
) -> list[str]:
    """Find existing NGFW static routes that match target CIDRs.

    Queries the NGFW running config for static routes and returns names of
    any routes whose destination matches one of the target CIDRs. Used to
    clean up stale routes from destroyed ranges when CIDRs are recycled.

    Args:
        ssh_executor: SSH executor for NGFW connection.
        management_ip: NGFW management IP address.
        target_cidrs: Set of CIDRs to match against.

    Returns:
        List of route names that should be deleted.
    """
    import re

    # Query the running static route config using configure mode
    # 'show config running | match static-route' only returns lines with "static-route"
    # We need the full hierarchical output to parse route names and destinations
    query_cmd = "set cli pager off\nconfigure\nshow network virtual-router default routing-table ip static-route\nexit"
    try:
        result = ssh_executor.run_command(
            instance_id=management_ip,
            script="",
            stdin_input=query_cmd + "\nexit\n",
            timeout_seconds=30,
        )
    except Exception as e:
        logger.warning("Failed to query NGFW routes for cleanup: %s", e)
        return []

    if not result.success or not result.stdout:
        return []

    # Parse output to find route entries with matching destinations
    # Configure mode 'show' returns hierarchical format:
    #   range-146-dc_network {
    #     destination 10.1.2.0/28;
    #     ...
    #   }
    stale_routes = []

    # Match route name and destination in hierarchical config format
    # Pattern matches: range-{id}-{name} { ... destination X.X.X.X/Y; ... }
    # Uses [^}]* to stay within the route block (stops at closing brace)
    route_pattern = re.compile(r"(range-\d+-\w+)\s*\{[^}]*destination\s+([\d./]+);", re.DOTALL)

    for match in route_pattern.finditer(result.stdout):
        route_name = match.group(1)
        cidr = match.group(2)
        if cidr in target_cidrs:
            logger.info(
                "Found stale route %s with CIDR %s - will delete",
                route_name,
                cidr,
            )
            stale_routes.append(route_name)

    return stale_routes


def find_stale_routes_by_db(
    ssh_executor: SSHExecutor,
    management_ip: str,
    current_range_id: int,
) -> list[str]:
    """Find NGFW routes belonging to destroyed/failed ranges via DB lookup.

    Queries all NGFW routes matching the range-{id}-{name} pattern, extracts
    the range IDs, and checks the database to find routes belonging to ranges
    that are destroyed, failed, or no longer exist.

    This is a secondary check to catch routes that weren't cleaned up during
    range destruction, complementing find_stale_routes_by_cidr.

    Args:
        ssh_executor: SSH executor for NGFW connection.
        management_ip: NGFW management IP address.
        current_range_id: Current range ID (to exclude from stale detection).

    Returns:
        List of route names that should be deleted.
    """
    import re

    # Query the running static route config using configure mode
    # 'show config running | match static-route' only returns lines with "static-route"
    # We need the full hierarchical output to parse route names
    query_cmd = "set cli pager off\nconfigure\nshow network virtual-router default routing-table ip static-route\nexit"
    try:
        result = ssh_executor.run_command(
            instance_id=management_ip,
            script="",
            stdin_input=query_cmd + "\nexit\n",
            timeout_seconds=30,
        )
    except Exception as e:
        logger.warning("Failed to query NGFW routes for DB cleanup check: %s", e)
        return []

    if not result.success or not result.stdout:
        return []

    # Extract all range IDs from route names in hierarchical config format
    # Pattern matches: range-{id}-{name} { (route block opening)
    route_pattern = re.compile(r"(range-(\d+)-\w+)\s*\{")
    routes_by_range: dict[int, list[str]] = {}

    for match in route_pattern.finditer(result.stdout):
        route_name = match.group(1)
        range_id = int(match.group(2))
        if range_id != current_range_id:
            if range_id not in routes_by_range:
                routes_by_range[range_id] = []
            routes_by_range[range_id].append(route_name)

    if not routes_by_range:
        return []

    # Query DB for these range IDs to find which are stale
    from engine.models import Range

    range_ids = list(routes_by_range.keys())
    stale_routes = []

    try:
        # Find ranges that are active (not stale)
        # Stale = destroyed, failed, or doesn't exist
        active_range_ids = set(
            Range.objects.filter(
                id__in=range_ids,
            )
            .exclude(status__in=["destroyed", "failed"])
            .values_list("id", flat=True)
        )

        # Routes belonging to ranges NOT in active_range_ids are stale
        for range_id, routes in routes_by_range.items():
            if range_id not in active_range_ids:
                logger.info(
                    "Found %d stale routes for range %d (destroyed/failed/missing)",
                    len(routes),
                    range_id,
                )
                stale_routes.extend(routes)

    except Exception as e:
        logger.warning("Failed to query DB for stale routes: %s", e)
        return []

    return stale_routes


def configure_ngfw_subnets(
    subnets: list[dict],
    range_id: int,
    management_ip: str,
    ssh_key_secret_arn: str,
    ngfw_subnet_cidr: str,
) -> None:
    """Configure NGFW with routes for range subnets.

    This runs AFTER pulumi up (subnets exist) and BEFORE instance setup.
    Configures static routes on the NGFW so traffic can flow between subnets.

    Args:
        subnets: List of dicts with 'name', 'cidr', 'connected_to'.
        range_id: Range ID for unique naming.
        management_ip: NGFW management IP for SSH.
        ssh_key_secret_arn: Secrets Manager ARN for SSH private key.
        ngfw_subnet_cidr: NGFW subnet CIDR for computing gateway IP.
    """
    # Compute VPC gateway IP (first IP + 1 in the subnet)
    network = ipaddress.ip_network(ngfw_subnet_cidr, strict=False)
    vpc_gateway_ip = str(network.network_address + 1)
    logger.info(
        "Configuring NGFW: %d subnets, gateway=%s",
        len(subnets),
        vpc_gateway_ip,
    )

    # Get SSH private key from Secrets Manager
    secrets_client = boto3.client("secretsmanager")
    secret_response = secrets_client.get_secret_value(SecretId=ssh_key_secret_arn)
    private_key = secret_response["SecretString"]

    # Create SSH executor
    ssh_executor = SSHExecutor(private_key=private_key)

    # Wait for SSH to be available
    logger.info("Waiting for SSH on NGFW at %s...", management_ip)
    ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=300)

    # Wait for management plane to be ready (especially important after NGFW start)
    logger.info("Verifying NGFW management plane is ready...")
    poll_for_serial_number(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=300,
        poll_interval=15,
    )

    # Wait for boot autocommit to complete before attempting configuration
    # The NGFW runs an autocommit at boot that must finish before we can commit changes
    logger.info("Waiting for NGFW autocommit to complete...")
    wait_for_autocommit(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=600,  # 10 min max for autocommit
        poll_interval=15,
    )

    # Find stale routes using two methods:
    # 1. CIDR match - routes with same destination as our target subnets
    # 2. DB lookup - routes belonging to destroyed/failed/missing ranges
    target_cidrs = {s["cidr"] for s in subnets if s.get("cidr")}
    stale_by_cidr = find_stale_routes_by_cidr(ssh_executor, management_ip, target_cidrs)
    stale_by_db = find_stale_routes_by_db(ssh_executor, management_ip, range_id)

    # Combine and deduplicate
    stale_routes = list(set(stale_by_cidr + stale_by_db))
    if stale_routes:
        logger.info(
            "Found %d stale routes to clean up: %s (cidr=%d, db=%d)",
            len(stale_routes),
            stale_routes,
            len(stale_by_cidr),
            len(stale_by_db),
        )

    # Build dynamic steps and wrap in DynamicPlan for SetupOrchestrator
    # This ensures consistent execution flow with proven retry/commit handling
    steps = NGFWConfigureSubnetsPlan().get_steps(subnets, range_id, vpc_gateway_ip, stale_routes)
    plan = DynamicPlan(name="ngfw_configure_subnets", steps=steps)

    orchestrator = SetupOrchestrator(ssh_executor)
    logger.info("Running NGFW subnet configuration via SetupOrchestrator...")
    result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=plan,
        context={},  # No template variables - steps are pre-built
    )

    if not result.success:
        raise RuntimeError(f"NGFW subnet configuration failed: {result.error or 'unknown error'}")

    logger.info(
        "NGFW configuration complete for range %s (%d subnets)",
        range_id,
        len(subnets),
    )


def _run_single_instance_setup(
    instance_id: str,
    role: str,
    os_type: str,
    public_key: str,
    agent_presigned_url: str,
    join_domain: bool,
    dc_ip: str | None,
    domain_name: str | None,
    xdr_required: bool = False,
    instance_name: str = "",
    range_id: int = 0,
) -> bool:
    """Run setup for a single non-DC instance.

    Args:
        instance_id: EC2 instance ID.
        role: Instance role ('attacker' or 'victim').
        os_type: OS type ('kali', 'ubuntu', 'windows').
        public_key: SSH public key for terminal access.
        agent_presigned_url: Pre-signed URL for XDR agent download.
        join_domain: Whether to join the domain.
        dc_ip: DC private IP (for domain join).
        domain_name: Domain FQDN (for domain join).
        xdr_required: If True, fail hard when XDR agent URL is missing.
        instance_name: Friendly display name for hostname (e.g., "target-ubuntu").
        range_id: Range ID for hostname generation.

    Returns:
        True on success.

    Raises:
        SetupError: If setup fails or XDR required but URL missing.
    """
    logger.info("Starting setup for %s instance %s...", role, instance_id)

    # Create executor and orchestrator
    executor = SSMExecutor()
    orchestrator = SetupOrchestrator(executor=executor)

    # Select SSM document based on OS type
    document_name = "AWS-RunShellScript" if os_type in ("kali", "ubuntu", "amazon-linux") else "AWS-RunPowerShellScript"

    # Wait for SSM agent to come online
    logger.info("Waiting for SSM agent on %s...", instance_id)
    executor.wait_for_agent(instance_id, timeout_seconds=300)
    logger.info("Instance %s is ready (SSM agent online)", instance_id)

    # Create context object for plan get_context()
    # Use friendly name for hostname (e.g., "Workstation" becomes "shifter-range-123-workstation")
    sanitized_name = sanitize_hostname(instance_name) if instance_name else ""
    if sanitized_name and range_id:
        hostname = f"shifter-range-{range_id}-{sanitized_name}"
    elif sanitized_name:
        hostname = f"shifter-{sanitized_name}"
    else:
        hostname = f"inst-{instance_id[-8:]}"

    class InstanceContext:
        def __init__(self):
            self.hostname = hostname
            self.public_key = public_key
            self.agent_presigned_url = agent_presigned_url
            self.ssh_user = "kali" if os_type == "kali" else "ubuntu"

    ctx = InstanceContext()

    # Select and run plans based on role and OS type
    if role == "attacker":
        # Kali: hostname + SSH setup
        plan = LinuxBootstrapPlan()
        context = plan.get_context(ctx)
        result = orchestrator.orchestrate(instance_id, plan, context, document_name=document_name)
        if not result.success:
            raise SetupError(f"Kali setup failed: {result.error}")
        logger.info("Kali setup complete for %s", instance_id)

    elif role == "victim":
        if os_type in ("kali", "ubuntu", "amazon-linux"):
            # Linux victim: Bootstrap + XDR
            bootstrap_plan = LinuxBootstrapPlan()
            bootstrap_ctx = bootstrap_plan.get_context(ctx)
            result = orchestrator.orchestrate(instance_id, bootstrap_plan, bootstrap_ctx, document_name=document_name)
            if not result.success:
                raise SetupError(f"Linux bootstrap failed: {result.error}")
            logger.info("Linux bootstrap complete for %s", instance_id)

            # Install XDR agent
            if agent_presigned_url:
                xdr_plan = LinuxXDRAgentInstallPlan()
                xdr_ctx = xdr_plan.get_context({"agent_presigned_url": agent_presigned_url})
                result = orchestrator.orchestrate(instance_id, xdr_plan, xdr_ctx, document_name=document_name)
                if not result.success:
                    raise SetupError(f"Linux XDR install failed: {result.error}")
                logger.info("Linux XDR agent installed on %s", instance_id)
            elif xdr_required:
                raise SetupError(f"XDR agent required but no URL provided for {instance_id}")
            else:
                logger.info("No XDR agent URL provided for %s (not required)", instance_id)

        else:
            # Windows victim: Bootstrap + XDR + Domain join
            win_bootstrap_plan = BootstrapPlan()
            win_bootstrap_ctx = win_bootstrap_plan.get_context(ctx)
            result = orchestrator.orchestrate(
                instance_id, win_bootstrap_plan, win_bootstrap_ctx, document_name=document_name
            )
            if not result.success:
                raise SetupError(f"Windows bootstrap failed: {result.error}")
            logger.info("Windows bootstrap complete for %s", instance_id)

            # Install XDR agent
            if agent_presigned_url:
                win_xdr_plan = XDRAgentInstallPlan()
                win_xdr_ctx = win_xdr_plan.get_context({"agent_presigned_url": agent_presigned_url})
                result = orchestrator.orchestrate(instance_id, win_xdr_plan, win_xdr_ctx, document_name=document_name)
                if not result.success:
                    raise SetupError(f"Windows XDR install failed: {result.error}")
                logger.info("Windows XDR agent installed on %s", instance_id)
            elif xdr_required:
                raise SetupError(f"XDR agent required but no URL provided for {instance_id}")
            else:
                logger.info("No XDR agent URL provided for %s (not required)", instance_id)

            # Domain join (only for Windows victims with join_domain=True)
            if join_domain and dc_ip and domain_name:
                domain_password = os.environ.get("DC_DOMAIN_PASSWORD", "")
                if domain_password:
                    logger.info("Joining domain %s for %s...", domain_name, instance_id)
                    domain_join_plan = DomainJoinPlan()
                    dj_context = domain_join_plan.get_context(
                        {
                            "dc_ip": dc_ip,
                            "domain_name": domain_name,
                            "domain_admin_password": domain_password,
                        }
                    )
                    result = orchestrator.orchestrate(
                        instance_id, domain_join_plan, dj_context, document_name=document_name
                    )
                    if not result.success:
                        raise SetupError(f"Domain join failed for {instance_id}")
                    logger.info("Domain join complete for %s", instance_id)
                else:
                    # join_domain=True means domain join is required
                    raise SetupError(f"Domain join required but DC_DOMAIN_PASSWORD not set for {instance_id}")
            elif join_domain:
                # join_domain=True means domain join is required
                raise SetupError(f"Domain join required but dc_ip or domain_name not provided for {instance_id}")

    return True


def _run_dc_setup(
    instance_id: str,
    dc_config: dict,
    agent_presigned_url: str,
    public_key: str = "",
    xdr_required: bool = False,
) -> bool:
    """Run setup for a DC instance.

    Args:
        instance_id: EC2 instance ID.
        dc_config: DC configuration dict with domain_name, netbios_name, etc.
        agent_presigned_url: Pre-signed URL for XDR agent download.
        public_key: SSH public key for terminal access.
        xdr_required: If True, fail hard when XDR agent URL is missing.

    Returns:
        True on success.

    Raises:
        SetupError: If setup fails or XDR required but URL missing.
    """
    logger.info("DC instance %s starting setup...", instance_id)
    domain_name = dc_config.get("domain_name", "")
    netbios_name = dc_config.get("netbios_name", "")
    logger.info("Domain: %s, NetBIOS: %s", domain_name, netbios_name)

    # Create executor and orchestrator
    executor = SSMExecutor()
    orchestrator = SetupOrchestrator(executor=executor)

    # Wait for SSM agent to come online
    logger.info("Waiting for SSM agent on DC %s...", instance_id)
    executor.wait_for_agent(instance_id, timeout_seconds=600)
    logger.info("DC %s SSM agent online", instance_id)

    # Prebaked DC: Skip hostname change - DC already has correct hostname from AMI
    logger.info("Using prebaked DC AMI - skipping hostname change")

    # Configure SSH key for terminal access (before DC verification)
    if public_key:
        logger.info("Configuring SSH key on DC %s...", instance_id)
        ssh_key_script = f'''
$ErrorActionPreference = "Stop"
$publicKey = "{public_key}"

Write-Host "Configuring SSH key for Administrator..."

$sshDir = "C:\\ProgramData\\ssh"
if (!(Test-Path $sshDir)) {{
    New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
}}

$publicKey | Out-File -Encoding ascii "$sshDir\\administrators_authorized_keys"

# Set proper permissions
icacls "$sshDir\\administrators_authorized_keys" /inheritance:r `
    /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null

# Restart sshd to pick up new key
Restart-Service sshd -Force -ErrorAction SilentlyContinue

Write-Host "SSH key configured successfully"
'''
        ssh_result = executor.run_command(
            instance_id=instance_id,
            script=ssh_key_script,
            document_name="AWS-RunPowerShellScript",
            timeout_seconds=60,
        )
        if not ssh_result.success:
            logger.warning("SSH key configuration failed: %s (continuing with setup)", ssh_result.stderr)
        else:
            logger.info("SSH key configured on DC %s", instance_id)
    else:
        logger.warning("No public key provided for DC %s, SSH key auth will not work", instance_id)

    # Verify Domain Controller via DCSetupPlan
    logger.info("Verifying Domain Controller (%s)...", domain_name)
    dc_plan = DCSetupPlan()

    # Create config object for DCSetupPlan context
    class DCPromoteConfig:
        def __init__(self, domain_name: str, netbios_name: str, dsrm_password: str, domain_admin_password: str):
            self.domain_name = domain_name
            self.netbios_name = netbios_name
            self.dsrm_password = dsrm_password
            self.domain_admin_password = domain_admin_password

    # Passwords come from env var, not from spec (same as InstanceComponent)
    domain_admin_password = os.environ.get("DC_DOMAIN_PASSWORD", "")
    dsrm_password = domain_admin_password  # Reuse for DSRM (same as InstanceComponent)

    config_obj = DCPromoteConfig(domain_name, netbios_name, dsrm_password, domain_admin_password)
    dc_context = dc_plan.get_context(config_obj)
    dc_result = orchestrator.orchestrate(instance_id, dc_plan, dc_context)
    if not dc_result.success:
        raise SetupError(f"DC verification failed: {dc_result.error}")
    logger.info("DC verification complete")

    # Install XDR agent on DC
    if agent_presigned_url:
        logger.info("Installing XDR agent on DC %s...", instance_id)
        xdr_plan = XDRAgentInstallPlan()
        xdr_context = xdr_plan.get_context({"agent_presigned_url": agent_presigned_url})
        xdr_result = orchestrator.orchestrate(instance_id, xdr_plan, xdr_context)
        if not xdr_result.success:
            raise SetupError(f"XDR agent install failed on DC: {xdr_result.error}")
        logger.info("XDR agent installed successfully on DC")
    elif xdr_required:
        raise SetupError(f"XDR agent required but no URL provided for DC {instance_id}")
    else:
        logger.info("No XDR agent URL provided for DC (not required)")

    return True


def run_instance_setup(
    instances_output: list[dict],
    range_spec: dict,
    dc_ip: str | None = None,
    domain_name: str | None = None,
    range_id: int = 0,
) -> None:
    """Run setup for all instances after infrastructure is ready.

    Runs DC setup first (blocking), then all other instances in parallel.

    Args:
        instances_output: List of instance dicts from Pulumi outputs.
        range_spec: Range specification with subnet/instance configs.
        dc_ip: DC private IP for domain join (from DC instance output).
        domain_name: Domain FQDN for domain join.
        range_id: Range ID for hostname generation.
    """
    # Build lookup from instance UUID to config
    uuid_to_config: dict[str, dict] = {}
    for subnet in range_spec.get("subnets", []):
        for inst in subnet.get("instances", []):
            uuid_to_config[inst.get("uuid", "")] = inst

    # Separate DCs from other instances
    dc_instances = []
    other_instances = []
    for inst in instances_output:
        if inst.get("role") == "dc":
            dc_instances.append(inst)
        else:
            other_instances.append(inst)

    # Run DC setup FIRST (blocking) - must complete before domain joins
    for dc_inst in dc_instances:
        inst_uuid = dc_inst.get("uuid", "")
        inst_config = uuid_to_config.get(inst_uuid, {})
        dc_config = inst_config.get("dc_config", {})
        agent_url = get_agent_presigned_url(inst_config)
        xdr_required = bool(inst_config.get("agent"))  # XDR required if agent data present
        public_key = dc_inst.get("public_key", "")
        _run_dc_setup(
            dc_inst["instance_id"],
            dc_config,
            agent_url or "",
            public_key=public_key,
            xdr_required=xdr_required,
        )

    # Get DC IP and domain for domain joins (from first DC)
    actual_dc_ip = dc_ip
    actual_domain = domain_name
    if dc_instances and not actual_dc_ip:
        actual_dc_ip = dc_instances[0].get("private_ip")
        # Get domain from DC config
        dc_uuid = dc_instances[0].get("uuid", "")
        dc_config = uuid_to_config.get(dc_uuid, {}).get("dc_config", {})
        actual_domain = dc_config.get("domain_name")

    # Run other instances in parallel
    if other_instances:
        logger.info("Running setup for %d non-DC instances in parallel...", len(other_instances))

        def setup_instance(inst: dict) -> tuple[str, bool, str | None]:
            """Setup a single instance, return (instance_id, success, error)."""
            inst_id = inst["instance_id"]
            inst_uuid = inst.get("uuid", "")
            inst_config = uuid_to_config.get(inst_uuid, {})
            try:
                _run_single_instance_setup(
                    instance_id=inst_id,
                    role=inst.get("role", "victim"),
                    os_type=inst.get("os", "ubuntu"),
                    public_key=inst.get("public_key", ""),
                    agent_presigned_url=get_agent_presigned_url(inst_config) or "",
                    join_domain=inst_config.get("join_domain", False),
                    dc_ip=actual_dc_ip,
                    domain_name=actual_domain,
                    xdr_required=bool(inst_config.get("agent")),  # XDR required if agent data present
                    instance_name=inst.get("name", ""),
                    range_id=range_id,
                )
                return (inst_id, True, None)
            except Exception as e:
                return (inst_id, False, str(e))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(setup_instance, inst): inst for inst in other_instances}
            for future in as_completed(futures):
                inst_id, success, error = future.result()
                if not success:
                    raise SetupError(f"Instance {inst_id} setup failed: {error}")

    logger.info("All instance setup complete")


def run_range_terraform(operation: str, request_id: str) -> None:
    """Run Range Terraform operation (provision or destroy).

    This is the Terraform equivalent of run_pulumi for ranges. It uses
    range_terraform_runner for infrastructure and the existing instance
    setup code for configuration.

    Args:
        operation: Either 'up' (provision) or 'destroy' (teardown).
        request_id: UUID string of the Request.

    Raises:
        Exception: If the Terraform operation fails.
    """
    logger.info("run_range_terraform: starting operation=%s request_id=%s", operation, request_id)

    range_data = get_range_data_by_request_id(request_id)
    range_id = range_data["range_id"]
    user_id = range_data["user_id"]
    range_spec = range_data.get("spec", {})

    # If NGFW is enabled, start it if stopped (must be running for subnet config)
    if range_spec.get("ngfw", False):
        ngfw_data = get_user_ngfw_data(user_id)
        if ngfw_data and ngfw_data.get("management_ip"):
            logger.info("NGFW enabled for range %s", range_id)
            ngfw_status = ngfw_data.get("status")
            if ngfw_status in ("stopped", "stopping"):
                ec2_instance_id = ngfw_data.get("ec2_instance_id")
                if ngfw_status == "stopping" and ec2_instance_id:
                    logger.info("NGFW is stopping, waiting for stop to complete...")
                    aws_executor = AWSExecutor()
                    aws_executor.wait_for_stopped(ec2_instance_id)
                logger.info("Starting stopped NGFW for range provisioning...")
                run_ngfw_operation("start", ngfw_data["ngfw_request_id"])

    try:
        if operation == "up":
            _run_terraform_provision(request_id, range_id, user_id, range_spec)
        elif operation == "destroy":
            _run_terraform_destroy(request_id, range_id, user_id, range_spec)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    except Exception as e:
        error_msg = str(e)[:1000]
        logger.error("Range Terraform operation failed: %s", error_msg)

        if operation == "up":
            logger.info("Provision failed - attempting Terraform cleanup...")
            try:
                range_terraform_runner.destroy_range(request_id, range_terraform_runner.RANGE_MODULE_PATH)
                range_terraform_runner.cleanup_range_state(request_id)
            except Exception as cleanup_error:
                logger.warning("Auto-cleanup failed: %s", cleanup_error)

        publish_failed(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            error_message=error_msg,
        )
        raise


def _validate_provisioned_outputs(
    subnets: dict[str, dict],
    instances: list[dict],
    expected_subnet_names: set[str] | None = None,
) -> None:
    """Validate Terraform outputs have required fields before DB write.

    Args:
        subnets: Dict of subnet_name -> subnet details.
        instances: List of instance dicts.
        expected_subnet_names: Optional set of expected subnet names from spec.

    Raises:
        ValueError: If required fields are missing or empty.
    """
    for subnet_name, subnet_data in subnets.items():
        if not subnet_data.get("uuid"):
            raise ValueError(f"Subnet '{subnet_name}' missing required 'uuid'")
        if not subnet_data.get("subnet_id"):
            raise ValueError(f"Subnet '{subnet_name}' missing 'subnet_id'")
        if not subnet_data.get("subnet_cidr"):
            raise ValueError(f"Subnet '{subnet_name}' missing 'subnet_cidr'")

    for i, inst in enumerate(instances):
        if not inst.get("uuid"):
            raise ValueError(f"Instance[{i}] (role={inst.get('role')}) missing 'uuid'")
        if not inst.get("instance_id"):
            raise ValueError(f"Instance[{i}] missing 'instance_id'")
        if not inst.get("private_ip"):
            raise ValueError(f"Instance[{i}] (role={inst.get('role')}, os={inst.get('os')}) missing 'private_ip'")

    if expected_subnet_names:
        actual_subnets = set(subnets.keys())
        missing = expected_subnet_names - actual_subnets
        if missing:
            raise ValueError(f"Expected subnets not created: {missing}")
        extra = actual_subnets - expected_subnet_names
        if extra:
            logger.warning("Unexpected subnets in output: %s", extra)


def _run_terraform_provision(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict,
) -> None:
    """Run Terraform apply for range, then run instance setup.

    Sequence:
    1. Run Terraform apply (creates subnets and instances)
    2. Validate outputs
    3. Configure NGFW subnets (routes for traffic flow)
    4. Run instance setup (DC first, then others in parallel)
    5. Write to DB
    6. Publish ready event
    """
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status="provisioning",
    )

    logger.info("Running terraform apply for range...")

    # Allocate CIDRs for subnets before Terraform
    spec_subnets = range_spec.get("subnets", [])
    if spec_subnets:
        from engine.provisioner.utils.network import allocate_subnets

        vpc_id = os.environ.get("RANGE_VPC_ID", "")
        vpc_cidr = os.environ.get("RANGE_VPC_CIDR", "10.1.0.0/16")
        # Extract CIDR prefix (e.g., "10.1" from "10.1.0.0/16")
        cidr_prefix = ".".join(vpc_cidr.split("/")[0].split(".")[:2])

        subnet_count = len(spec_subnets)
        logger.info("Allocating %d subnet CIDRs in VPC %s", subnet_count, vpc_id)

        allocated_cidrs = allocate_subnets(vpc_id, cidr_prefix, subnet_count, subnet_size=28)
        logger.info("Allocated CIDRs: %s", allocated_cidrs)

        # Add CIDRs to range_spec subnets
        for i, subnet in enumerate(spec_subnets):
            subnet["cidr"] = allocated_cidrs[i]

    # Build Terraform variables from range spec (now with CIDRs)
    tf_variables = _build_range_terraform_variables(request_id, range_id, user_id, range_spec)

    # Run Terraform apply
    output_data = range_terraform_runner.apply_range(
        request_id,
        tf_variables,
        range_terraform_runner.RANGE_MODULE_PATH,
    )
    logger.info("Terraform outputs: %s", json.dumps(output_data, indent=2))

    subnets_output = output_data.get("subnets", {})
    instances_output = output_data.get("instances", [])

    expected_subnet_names = {s.get("name") for s in spec_subnets}
    _validate_provisioned_outputs(
        subnets=subnets_output,
        instances=instances_output,
        expected_subnet_names=expected_subnet_names,
    )

    # Configure NGFW with routes for range subnets
    ngfw_data = get_user_ngfw_data(user_id)
    ngfw_subnet_cidr = os.environ.get("NGFW_SUBNET_CIDR")
    if ngfw_data and ngfw_data.get("management_ip") and ngfw_subnet_cidr:
        logger.info("Configuring NGFW with subnet routes...")
        subnets_for_ngfw = []
        for spec_subnet in spec_subnets:
            subnet_name = spec_subnet.get("name", "")
            subnet_output = subnets_output.get(subnet_name, {})
            subnets_for_ngfw.append(
                {
                    "name": subnet_name,
                    "cidr": subnet_output.get("subnet_cidr", ""),
                    "connected_to": spec_subnet.get("connected_to", []),
                }
            )
        configure_ngfw_subnets(
            subnets=subnets_for_ngfw,
            range_id=range_id,
            management_ip=ngfw_data["management_ip"],
            ssh_key_secret_arn=ngfw_data["ssh_key_secret_arn"],
            ngfw_subnet_cidr=ngfw_subnet_cidr,
        )

    # Run instance setup (DC first, then others in parallel)
    logger.info("Running instance setup...")
    run_instance_setup(
        instances_output=instances_output,
        range_spec=range_spec,
    )

    # Write provisioned state to DB
    range_data = get_range_data_by_request_id(request_id)
    write_provisioned_state(
        range_id=range_id,
        subnets=subnets_output,
        instances=instances_output,
        ngfw_instance_id=range_data.get("ngfw_instance_id"),
    )

    publish_ready(request_id=request_id, range_id=range_id, user_id=user_id)


def _run_terraform_destroy(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict,
) -> None:
    """Run Terraform destroy for range."""
    # Pre-destroy validation
    try:
        range_data = get_range_data_by_request_id(request_id)
    except ValueError as e:
        logger.warning("Range not found for request %s, skipping destroy: %s", request_id, e)
        return

    current_status = range_data.get("status")
    if current_status in ("destroyed", "failed"):
        logger.info("Range %d already in terminal state '%s', skipping", range_id, current_status)
        return

    # Remove NGFW subnet config
    spec_subnets = range_spec.get("subnets", [])
    if spec_subnets:
        try:
            remove_ngfw_subnets(user_id, spec_subnets, range_id)
        except Exception as e:
            logger.warning("NGFW subnet removal failed (continuing): %s", e)

    logger.info("Running terraform destroy for range...")

    terraform_succeeded = False
    try:
        range_terraform_runner.destroy_range(request_id, range_terraform_runner.RANGE_MODULE_PATH)
        terraform_succeeded = True

        logger.info("Cleaning up Terraform state...")
        range_terraform_runner.cleanup_range_state(request_id)

    finally:
        if terraform_succeeded:
            try:
                mark_range_instances_destroyed(range_id)
            except Exception as e:
                logger.error("Failed to mark range %d as destroyed: %s", range_id, e)

        # Auto-stop NGFW if no other active ranges
        try:
            if not user_has_active_ranges(user_id, range_id):
                ngfw_data = get_user_ngfw_data(user_id)
                if ngfw_data and ngfw_data["status"] == "active":
                    logger.info("No other active ranges, stopping NGFW")
                    run_ngfw_operation("stop", ngfw_data["ngfw_request_id"])
        except Exception as e:
            logger.warning("Failed to stop NGFW (non-fatal): %s", e)

    publish_destroyed(request_id=request_id, range_id=range_id, user_id=user_id)


def _build_range_terraform_variables(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict,
) -> dict:
    """Build Terraform variables dict from range spec and environment.

    Args:
        request_id: Provisioning request UUID for state isolation.
        range_id: Range database ID.
        user_id: Owner's Django user ID.
        range_spec: Range specification from database.

    Returns:
        Dict of Terraform variables matching modules/range/variables.tf.
    """
    spec_subnets = range_spec.get("subnets", [])

    # Build subnets with nested instances (Terraform expected format)
    tf_subnets = []
    for subnet in spec_subnets:
        subnet_instances = []
        for inst in subnet.get("instances", []):
            os_type = inst.get("os_type", "ubuntu")
            role = inst.get("role", "victim")

            # Map to Terraform os_type values
            # DC role always uses Windows (domain controller)
            # Attacker role always uses Kali
            if role == "dc":
                tf_os_type = "windows"
            elif role == "attacker" or os_type == "kali":
                tf_os_type = "kali"
            elif os_type == "windows":
                tf_os_type = "windows"
            else:
                tf_os_type = "ubuntu"

            # Get instance_type from role/os-based defaults (not in spec)
            if role == "attacker":
                instance_type = _get_kali_instance_type()
            elif role == "dc":
                instance_type = _get_dc_instance_type()
            elif tf_os_type == "windows":
                instance_type = _get_windows_instance_type()
            else:
                instance_type = _get_victim_instance_type()

            # Get agent presigned URL from agent.s3_key (spec has nested structure)
            agent_data = inst.get("agent") or {}
            agent_s3_key = agent_data.get("s3_key")
            agent_presigned_url = ""
            if agent_s3_key:
                agent_presigned_url = generate_presigned_url(
                    bucket=os.environ.get("AGENT_S3_BUCKET", ""),
                    key=agent_s3_key,
                )

            subnet_instances.append(
                {
                    "uuid": inst.get("uuid", ""),
                    "role": role,
                    "os_type": tf_os_type,
                    "instance_type": instance_type,
                    "agent_presigned_url": agent_presigned_url,
                    "join_domain": inst.get("join_domain", False),
                }
            )

        tf_subnets.append(
            {
                "name": subnet.get("name", ""),
                "uuid": subnet.get("uuid", ""),
                "cidr": subnet.get("cidr", ""),  # Pre-allocated CIDR
                "connected_to": subnet.get("connected_to", []),
                "instances": subnet_instances,
            }
        )

    return {
        # Core identifiers
        "range_id": range_id,
        "user_id": user_id,
        "request_uuid": request_id,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        # VPC configuration
        "vpc_id": os.environ.get("RANGE_VPC_ID", ""),
        "vpc_cidr": os.environ.get("RANGE_VPC_CIDR", ""),
        "availability_zone": os.environ.get("AVAILABILITY_ZONE", "us-east-2b"),
        # Network integration
        "s3_endpoint_id": os.environ.get("S3_ENDPOINT_ID", ""),
        "firewall_endpoint_id": os.environ.get("FIREWALL_ENDPOINT_ID", ""),
        "portal_vpc_cidr": os.environ.get("PORTAL_VPC_CIDR", ""),
        "portal_vpc_peering_id": os.environ.get("PORTAL_VPC_PEERING_ID", ""),
        "ngfw_data_eni_id": os.environ.get("NGFW_ENI_ID", ""),
        # AMI IDs
        "kali_ami_id": get_ami_id("kali"),
        "victim_ami_id": get_ami_id("victim"),
        "windows_ami_id": get_ami_id("windows"),
        "dc_ami_id": get_ami_id("dc"),
        # IAM
        "instance_profile_name": os.environ.get("RANGE_INSTANCE_PROFILE_NAME", ""),
        # Subnets specification
        "subnets": tf_subnets,
    }


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

    from engine.provisioner.events import publish_ngfw_event

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
            "start": "engine.provisioner.plans.ngfw_start.NGFWStartPlan",
            "stop": "engine.provisioner.plans.ngfw_stop.NGFWStopPlan",
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


# =============================================================================
# Entry-point wrappers (called by engine/tasks.py Celery tasks)
# =============================================================================


def run_range_provision(request_id: str) -> None:
    """Provision a range via Terraform."""
    run_range_terraform("up", request_id)


def run_range_destroy(request_id: str) -> None:
    """Destroy a range via Terraform."""
    run_range_terraform("destroy", request_id)


def run_range_pause(request_id: str) -> None:
    """Pause all instances in a range."""
    from engine.provisioner.operations.range_ops import run_range_pause as _pause

    _pause(request_id)


def run_range_resume(request_id: str) -> None:
    """Resume all instances in a range."""
    from engine.provisioner.operations.range_ops import run_range_resume as _resume

    _resume(request_id)


def run_ngfw_provision(request_id: str) -> None:
    """Provision NGFW via Terraform."""
    ngfw_terraform.run_ngfw_terraform("up", request_id)


def run_ngfw_deprovision(request_id: str) -> None:
    """Deprovision NGFW via Terraform."""
    ngfw_terraform.run_ngfw_terraform("destroy", request_id)


def run_ngfw_start(request_id: str) -> None:
    """Start a stopped NGFW instance."""
    run_ngfw_operation("start", request_id)


def run_ngfw_stop(request_id: str) -> None:
    """Stop a running NGFW instance."""
    run_ngfw_operation("stop", request_id)


def run_ngfw_complete_setup(request_id: str) -> None:
    """Complete NGFW setup after user associates device."""
    _run_complete_setup(request_id)

"""Terraform provision / destroy + Terraform variable builders for Shifter ranges.

Extracted from ``main.py`` (Sonar S104). Owns the run_range_terraform
dispatch path, the per-operation provision and destroy pipelines, the
NGFW recovery path that runs before provisioning, the NGFW-on-range
attachment helpers that run after the Terraform apply, and the
``_build_range_terraform_variables`` family that maps the range spec
into the inputs the Terraform module expects.

Cross-module callees that are patched in tests via ``patch("main.X")``
go through ``main.X(...)`` lazy lookups so the existing test mocks
intercept the same call sites without per-test edits.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from config import resolve_ngfw_attachment_config
from executors.aws_executor import AWSExecutor
from state_helpers import _get_cloud_provider, _validate_provisioned_outputs

logger = logging.getLogger(__name__)


def _describe_ec2_state(aws_executor: AWSExecutor, ec2_instance_id: str) -> str | None:
    """Return the EC2 state name for an instance (``running`` / ``stopped`` / etc.)."""
    result = aws_executor.describe_instance(ec2_instance_id)
    if not result.success:
        return None
    data = json.loads(result.stdout)
    reservations = data.get("Reservations", [])
    if not reservations or not reservations[0].get("Instances"):
        return None
    return reservations[0]["Instances"][0].get("State", {}).get("Name")


def _recover_aws_ngfw_stuck_resuming(ec2_instance_id: str, ngfw_request_id: str) -> None:
    """Recover an AWS NGFW whose status field is stuck in 'resuming'."""
    import main

    aws_executor = AWSExecutor()
    ec2_state = _describe_ec2_state(aws_executor, ec2_instance_id)
    if ec2_state == "stopped":
        logger.info("NGFW stuck in 'resuming' but EC2 is stopped, resuming...")
        main.run_ngfw_operation("start", ngfw_request_id)
    elif ec2_state == "running":
        logger.info("NGFW resuming, EC2 already running")
    elif ec2_state == "pending":
        logger.info("NGFW resuming, waiting for EC2 to be running...")
        aws_executor.wait_for_running(ec2_instance_id)


def _resume_aws_ngfw_for_provisioning(ngfw_data: dict[str, Any]) -> None:
    """Bring an AWS NGFW back into running state before range provisioning."""
    import main

    ngfw_status = ngfw_data.get("status")
    ec2_instance_id = ngfw_data.get("ec2_instance_id")
    ngfw_request_id = ngfw_data["ngfw_request_id"]
    if ngfw_status == "pausing" and ec2_instance_id:
        logger.info("NGFW is pausing, waiting for pause to complete...")
        AWSExecutor().wait_for_stopped(ec2_instance_id)
        return
    if ngfw_status == "resuming" and ec2_instance_id:
        _recover_aws_ngfw_stuck_resuming(ec2_instance_id, ngfw_request_id)
        return
    logger.info("Resuming paused NGFW for range provisioning...")
    main.run_ngfw_operation("start", ngfw_request_id)


def _ensure_ngfw_ready_for_provisioning(range_id: int, user_id: int) -> None:
    """Resume the user's NGFW if paused (AWS) or assert it's already ready (other clouds)."""
    import main

    ngfw_data = main.get_user_ngfw_data(user_id)
    if not ngfw_data or not ngfw_data.get("management_ip"):
        return
    logger.info("NGFW enabled for range %s", range_id)
    ngfw_status = ngfw_data.get("status")
    ngfw_provider = ngfw_data.get("cloud_provider", "aws")
    if ngfw_provider == "aws" and ngfw_status in ("paused", "pausing", "resuming"):
        _resume_aws_ngfw_for_provisioning(ngfw_data)
        return
    if ngfw_provider != "aws" and ngfw_status != "ready":
        raise RuntimeError(
            "GDC-attached NGFW ranges require the NGFW to already be in ready state. "
            f"Current status={ngfw_status!r} for request_id={ngfw_data['ngfw_request_id']}"
        )


def _release_subnet_allocations_best_effort(request_id: str) -> None:
    """Release subnet allocations on provision failure; never raise."""
    try:
        from components.network import release_subnet_allocations

        release_subnet_allocations(request_id)
    except Exception as e:
        logger.warning("Failed to release subnet allocations: %s", e)


def _attempt_terraform_auto_cleanup(request_id: str, range_id: int, user_id: int, range_spec: dict[str, Any]) -> None:
    """Best-effort `terraform destroy` after a failed provision."""
    import main

    logger.error(
        "Provision failed for range_id=%s request_id=%s - attempting Terraform cleanup...",
        range_id,
        request_id,
    )
    try:
        tf_variables = main._build_range_terraform_variables(request_id, range_id, user_id, range_spec)
        main.range_terraform_runner.destroy_range(request_id, variables=tf_variables)
        main.range_terraform_runner.cleanup_range_state(request_id)
        logger.info("Auto-cleanup succeeded for range_id=%s", range_id)
    except Exception as cleanup_error:
        logger.error(
            "Auto-cleanup FAILED for range_id=%s request_id=%s: %s. "
            "Orphaned cloud resources may exist and require manual cleanup.",
            range_id,
            request_id,
            cleanup_error,
        )
    _release_subnet_allocations_best_effort(request_id)


def _dispatch_terraform_operation(
    operation: str, request_id: str, range_id: int, user_id: int, range_spec: dict[str, Any]
) -> None:
    """Run the requested Terraform operation; raise ValueError for unknown ops."""
    import main

    if operation == "up":
        main._run_terraform_provision(request_id, range_id, user_id, range_spec)
        return
    if operation == "destroy":
        main._run_terraform_destroy(request_id, range_id, user_id, range_spec)
        return
    raise ValueError(f"Unknown operation: {operation}")


def run_range_terraform(operation: str, request_id: str) -> None:
    """Run Range Terraform operation (provision or destroy)."""
    import main

    logger.info("run_range_terraform: starting operation=%s request_id=%s", operation, request_id)

    range_data = main.get_range_data_by_request_id(request_id)
    range_id = range_data["range_id"]
    user_id = range_data["user_id"]
    range_spec = range_data.get("spec", {})

    if range_spec.get("ngfw", False):
        _ensure_ngfw_ready_for_provisioning(range_id, user_id)

    try:
        _dispatch_terraform_operation(operation, request_id, range_id, user_id, range_spec)
    except Exception as e:
        error_msg = str(e)[:1000]
        logger.error("Range Terraform operation failed: %s", error_msg)
        if operation == "up":
            _attempt_terraform_auto_cleanup(request_id, range_id, user_id, range_spec)
        main.publish_failed(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            error_message=error_msg,
        )
        raise


def _run_terraform_provision(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
) -> None:
    """Run Terraform apply for range, then run instance setup."""
    import main

    main.publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status="provisioning",
    )

    logger.info("Running terraform apply for range...")

    spec_subnets = _allocate_range_subnet_cidrs(request_id, range_id, range_spec)

    # Build Terraform variables from range spec (now with CIDRs)
    tf_variables = main._build_range_terraform_variables(request_id, range_id, user_id, range_spec)

    # Run Terraform apply
    output_data = main.range_terraform_runner.apply_range(request_id, tf_variables)
    logger.info("Terraform outputs: %s", json.dumps(output_data, indent=2))

    subnets_output = output_data.get("subnets", {})
    instances_output = output_data.get("instances", [])

    expected_subnet_names = {str(subnet_name) for subnet in spec_subnets if (subnet_name := subnet.get("name"))}
    _validate_provisioned_outputs(
        subnets=subnets_output,
        instances=instances_output,
        expected_subnet_names=expected_subnet_names,
    )

    _validate_ngfw_range_attachment(range_spec, user_id)
    _configure_ngfw_for_range(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        range_spec=range_spec,
        spec_subnets=spec_subnets,
        subnets_output=subnets_output,
    )

    # Run instance setup (DC first, then others in parallel)
    logger.info("Running instance setup...")
    main.run_instance_setup(
        instances_output=instances_output,
        range_spec=range_spec,
    )

    # Write provisioned state to DB
    range_data = main.get_range_data_by_request_id(request_id)
    main.write_provisioned_state(
        range_id=range_id,
        subnets=subnets_output,
        instances=instances_output,
        ngfw_instance_id=range_data.get("ngfw_instance_id"),
    )

    main.publish_ready(request_id=request_id, range_id=range_id, user_id=user_id)


def _allocate_range_subnet_cidrs(request_id: str, range_id: int, range_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Allocate subnet CIDRs from the active VPC and persist them onto the range spec."""
    import main

    spec_subnets = range_spec.get("subnets", [])
    if not spec_subnets:
        return spec_subnets

    from components.network import allocate_subnets

    range_network = main.load_range_network_config()
    vpc_id = range_network.network_id
    vpc_cidr = range_network.network_cidr or "10.1.0.0/16"
    cidr_prefix = ".".join(vpc_cidr.split("/")[0].split(".")[:2])
    subnet_count = len(spec_subnets)
    logger.info("Allocating %d subnet CIDRs in VPC %s", subnet_count, vpc_id)
    allocated_cidrs = allocate_subnets(
        vpc_id,
        cidr_prefix,
        subnet_count,
        subnet_size=28,
        range_id=range_id,
        request_id=request_id,
    )
    logger.info("Allocated CIDRs: %s", allocated_cidrs)
    for i, subnet in enumerate(spec_subnets):
        subnet["cidr"] = allocated_cidrs[i]
    main._update_range_config(range_id, range_spec)
    return spec_subnets


def _validate_ngfw_range_attachment(range_spec: dict[str, Any], user_id: int) -> None:
    """Raise if a NGFW-required range is not actually attachable to the user's NGFW."""
    import main

    if not range_spec.get("ngfw", False):
        return
    ngfw_data = main.get_user_ngfw_data(user_id)
    if not ngfw_data or not resolve_ngfw_attachment_config(ngfw_data).is_attachable:
        raise RuntimeError(
            "NGFW routing validation failed: range requires NGFW but the active NGFW "
            "is missing attachable routing state."
        )
    logger.info("NGFW-enabled range validated: attachment_mode=%s", ngfw_data.get("attachment_mode", ""))


def _build_ngfw_subnet_payloads(
    spec_subnets: list[dict[str, Any]],
    subnets_output: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the NGFW subnet-config payloads from per-subnet provisioner outputs."""
    provider = _get_cloud_provider()
    subnets_for_ngfw = []
    for spec_subnet in spec_subnets:
        subnet_name = spec_subnet.get("name", "")
        subnet_output = subnets_output.get(subnet_name, {})
        subnets_for_ngfw.append(
            {
                "name": subnet_name,
                "cidr": subnet_output.get("subnet_cidr", ""),
                "connected_to": spec_subnet.get("connected_to", []),
                "provider_metadata": {
                    "gcp": {
                        "namespace": subnet_output.get("gdc_namespace", ""),
                        "network_name": subnet_output.get("gdc_network_name", ""),
                        "gateway_ip": subnet_output.get("gdc_gateway_ip", ""),
                    }
                }
                if provider == "gcp"
                else {},
            }
        )
    return subnets_for_ngfw


def _configure_ngfw_for_range(
    *,
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
    spec_subnets: list[dict[str, Any]],
    subnets_output: dict[str, dict[str, Any]],
) -> None:
    """Configure routes/rules on the user's NGFW for this range, if a NGFW is attached."""
    import main

    if not range_spec.get("ngfw", False):
        return

    ngfw_data = main.get_user_ngfw_data(user_id)
    route_next_hop_ip = ngfw_data.get("route_next_hop_ip") if ngfw_data else ""
    if not (ngfw_data and ngfw_data.get("management_ip") and route_next_hop_ip):
        return

    logger.info("Configuring NGFW with subnet routes...")
    subnets_for_ngfw = _build_ngfw_subnet_payloads(spec_subnets, subnets_output)
    main.configure_ngfw_subnets(
        subnets=subnets_for_ngfw,
        range_id=range_id,
        management_ip=ngfw_data["management_ip"],
        ssh_key_secret_arn=ngfw_data["ssh_key_secret_arn"],
        route_next_hop_ip=route_next_hop_ip,
        ssm_endpoints_subnet_cidr=os.environ.get("SSM_ENDPOINTS_SUBNET_CIDR", ""),
    )
    main._record_ngfw_range_attachment(
        ngfw_request_id=ngfw_data["ngfw_request_id"],
        ngfw_status=ngfw_data["status"],
        attachment_record=main._build_ngfw_range_attachment_record(
            range_id=range_id,
            request_id=request_id,
            subnets=subnets_for_ngfw,
            ngfw_data=ngfw_data,
        ),
    )


def _remove_ngfw_attachments_for_destroy(user_id: int, range_id: int, range_spec: dict[str, Any]) -> None:
    """Best-effort detach of NGFW subnets / range attachment before terraform destroy.

    Failures are logged and swallowed; terraform destroy runs regardless.
    """
    import main

    spec_subnets = range_spec.get("subnets", [])
    if not spec_subnets:
        return
    try:
        ngfw_data = main.get_user_ngfw_data(user_id) if range_spec.get("ngfw", False) else None
        main.remove_ngfw_subnets(user_id, spec_subnets, range_id)
        if ngfw_data:
            main._remove_ngfw_range_attachment(
                ngfw_request_id=ngfw_data["ngfw_request_id"],
                ngfw_status=ngfw_data["status"],
                range_id=range_id,
            )
    except Exception as e:
        logger.warning("NGFW subnet removal failed (continuing): %s", e)


def _recover_missing_subnet_cidrs(range_id: int, range_spec: dict[str, Any]) -> None:
    """If range_spec lost its subnet CIDRs, repopulate from the allocation table."""
    spec_subnets = range_spec.get("subnets", [])
    if not spec_subnets or spec_subnets[0].get("cidr"):
        return
    logger.warning("range_config missing CIDRs for range %d, recovering from allocation table", range_id)
    from components.network import get_allocated_cidrs

    allocated = get_allocated_cidrs(range_id)
    for i, subnet in enumerate(spec_subnets):
        if i < len(allocated):
            subnet["cidr"] = allocated[i]


def _post_destroy_cleanup(request_id: str, range_id: int) -> None:
    """Mark range destroyed, release subnet allocations. Best-effort."""
    import main

    try:
        main.mark_range_instances_destroyed(range_id)
    except Exception as e:
        logger.error("Failed to mark range %d as destroyed: %s", range_id, e)

    try:
        from components.network import release_subnet_allocations

        release_subnet_allocations(request_id)
    except Exception as e:
        logger.warning("Failed to release subnet allocations: %s", e)


def _maybe_pause_user_ngfw(user_id: int, range_id: int) -> None:
    """If this range was the user's last active range, pause their AWS NGFW."""
    import main

    try:
        if main.user_has_active_ranges(user_id, range_id):
            return
        ngfw_data = main.get_user_ngfw_data(user_id)
        if ngfw_data and ngfw_data["status"] == "ready" and ngfw_data.get("cloud_provider") == "aws":
            logger.info("No other active ranges, pausing NGFW")
            main.run_ngfw_operation("stop", ngfw_data["ngfw_request_id"])
    except Exception as e:
        logger.warning("Failed to pause NGFW (non-fatal): %s", e)


def _ensure_range_is_active(request_id: str, range_id: int) -> bool:
    """Return True if the range exists and is not already destroyed."""
    import main

    try:
        range_data = main.get_range_data_by_request_id(request_id)
    except ValueError as e:
        logger.warning("Range not found for request %s, skipping destroy: %s", request_id, e)
        return False
    if range_data.get("status") == "destroyed":
        logger.info("Range %d already destroyed, skipping", range_id)
        return False
    return True


def _run_terraform_destroy(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
) -> None:
    """Run Terraform destroy for range."""
    import main

    if not _ensure_range_is_active(request_id, range_id):
        return

    _remove_ngfw_attachments_for_destroy(user_id, range_id, range_spec)
    _recover_missing_subnet_cidrs(range_id, range_spec)

    logger.info("Running terraform destroy for range...")
    terraform_succeeded = False
    try:
        tf_variables = main._build_range_terraform_variables(request_id, range_id, user_id, range_spec)
        main.range_terraform_runner.destroy_range(request_id, variables=tf_variables)
        terraform_succeeded = True
        logger.info("Cleaning up Terraform state...")
        main.range_terraform_runner.cleanup_range_state(request_id)
    finally:
        if terraform_succeeded:
            _post_destroy_cleanup(request_id, range_id)
        _maybe_pause_user_ngfw(user_id, range_id)

    main.publish_destroyed(request_id=request_id, range_id=range_id, user_id=user_id)


def _resolve_tf_os_type(role: str, os_type: str) -> str:
    """Map spec role + os_type to the terraform module's os_type enum."""
    if role == "dc" or os_type == "windows":
        resolved = "windows"
    elif role == "attacker" or os_type == "kali":
        resolved = "kali"
    else:
        resolved = "ubuntu"
    return resolved


def _resolve_instance_type(role: str, tf_os_type: str, override: str | None) -> str:
    """Pick the EC2 instance type: per-instance override wins; otherwise role/OS defaults."""
    import main

    if override:
        resolved = override
    elif role == "attacker":
        resolved = main._get_kali_instance_type()
    elif role == "dc":
        resolved = main._get_dc_instance_type()
    elif tf_os_type == "windows":
        resolved = main._get_windows_instance_type()
    else:
        resolved = main._get_victim_instance_type()
    return resolved


def _resolve_agent_presigned_url(inst: dict[str, Any]) -> str:
    """Generate a presigned URL for the instance's XDR agent S3 object, if any."""
    import main

    agent_data = inst.get("agent") or {}
    agent_s3_key = agent_data.get("s3_key")
    if not agent_s3_key:
        return ""
    return main.generate_presigned_url(
        bucket=os.environ.get("AGENT_STORAGE_BUCKET") or os.environ.get("AGENT_S3_BUCKET", ""),
        key=agent_s3_key,
    )


def _resolve_agent_presigned_url_from_inst(inst: dict[str, Any]) -> str:
    """Generate a presigned URL for the instance's XDR agent S3 object, if any."""
    return _resolve_agent_presigned_url(inst)


def _build_tf_instance(inst: dict[str, Any]) -> dict[str, Any]:
    """Map one spec instance into the dict shape the terraform module expects."""
    import main

    os_type = inst.get("os_type", "ubuntu")
    role = inst.get("role", "victim")
    tf_os_type = _resolve_tf_os_type(role, os_type)
    instance_type = _resolve_instance_type(role, tf_os_type, inst.get("instance_type"))
    ami_key = inst.get("ami_key")
    return {
        "uuid": inst.get("uuid", ""),
        "name": inst.get("name", ""),
        "asset_type": inst.get("asset_type", "vm_runtime_vm"),
        "role": role,
        "os_type": tf_os_type,
        "instance_type": instance_type,
        "agent_presigned_url": _resolve_agent_presigned_url(inst),
        "join_domain": inst.get("join_domain", False),
        "ami_id": main.get_ami_id(ami_key) if ami_key else "",
    }


def _build_tf_subnets(spec_subnets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate spec subnets+instances into the terraform module's nested format."""
    return [
        {
            "name": subnet.get("name", ""),
            "uuid": subnet.get("uuid", ""),
            # Pre-allocated CIDR.
            "cidr": subnet.get("cidr", ""),
            "connected_to": subnet.get("connected_to", []),
            "instances": [_build_tf_instance(inst) for inst in subnet.get("instances", [])],
        }
        for subnet in spec_subnets
    ]


def _resolve_ngfw_for_range(user_id: int, range_id: int) -> tuple[str, dict[str, Any] | None]:
    """Resolve the user's NGFW attachment for an NGFW-enabled range.

    Returns ``(data_eni_id, attachment_block)``; the attachment block is the
    GCP-specific NGFW config or ``None`` for AWS. Raises ``ValueError`` if the
    user has no provisioned/attachable NGFW.
    """
    import main

    ngfw_data = main.get_user_ngfw_data(user_id)
    if not ngfw_data:
        raise ValueError(
            f"Range requires NGFW (ngfw: true in spec) but user {user_id} has no provisioned NGFW. "
            "User must provision an NGFW before creating NGFW-enabled ranges."
        )
    attachment = resolve_ngfw_attachment_config(ngfw_data)
    if not attachment.is_attachable:
        raise ValueError(
            f"Range requires NGFW but user {user_id}'s NGFW is missing attachable routing state. "
            f"NGFW request_id: {ngfw_data.get('ngfw_request_id')}"
        )
    attachment_block = {
        "cloud_provider": attachment.cloud_provider,
        "management_ip": attachment.management_ip,
        "ssh_key_secret_ref": attachment.ssh_key_secret_ref,
        "dataplane_ip": attachment.dataplane_ip,
        "route_next_hop_ip": attachment.route_next_hop_ip,
        "data_attachment_id": attachment.data_attachment_id,
        "attachment_mode": attachment.attachment_mode,
        "provider_metadata": attachment.provider_metadata,
    }
    logger.info(
        "Using NGFW attachment_mode=%s for range %s",
        attachment.attachment_mode or "unknown",
        range_id,
    )
    return attachment.data_attachment_id, attachment_block


def _build_aws_extra_tf_variables() -> dict[str, Any]:
    """AWS-only Terraform variables: per-OS AMI IDs + instance profile + Secrets Manager CMK."""
    import main

    return {
        "kali_ami_id": main.get_ami_id("kali"),
        "victim_ami_id": main.get_ami_id("victim"),
        "windows_ami_id": main.get_ami_id("windows"),
        "dc_ami_id": main.get_ami_id("dc"),
        "instance_profile_name": os.environ.get("RANGE_INSTANCE_PROFILE_NAME", ""),
        "secrets_kms_key_arn": os.environ["SECRETS_KMS_KEY_ARN"],
    }


def _build_range_terraform_variables(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict[str, Any],
) -> dict[str, Any]:
    """Build Terraform variables dict from range spec and environment."""
    import main

    tf_subnets = _build_tf_subnets(range_spec.get("subnets", []))

    ngfw_data_eni_id = ""
    ngfw_attachment: dict[str, Any] | None = None
    if range_spec.get("ngfw", False):
        ngfw_data_eni_id, ngfw_attachment = _resolve_ngfw_for_range(user_id, range_id)

    range_network = main.load_range_network_config()
    variables = {
        "range_id": range_id,
        "user_id": user_id,
        "request_uuid": request_id,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "vpc_id": range_network.network_id,
        "vpc_cidr": range_network.network_cidr,
        "availability_zone": main.get_range_availability_zone(),
        "s3_endpoint_id": os.environ.get("S3_ENDPOINT_ID", ""),
        "firewall_endpoint_id": os.environ.get("FIREWALL_ENDPOINT_ID", ""),
        "portal_vpc_cidr": range_network.primary_portal_cidr,
        "portal_vpc_peering_id": os.environ.get("PORTAL_VPC_PEERING_ID", ""),
        "ngfw_data_eni_id": ngfw_data_eni_id,
        "subnets": tf_subnets,
    }

    if _get_cloud_provider() == "gcp":
        if ngfw_attachment:
            variables["ngfw_attachment"] = ngfw_attachment
        return variables

    variables.update(_build_aws_extra_tf_variables())
    return variables

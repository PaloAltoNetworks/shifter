"""NGFW lifecycle helpers used by Terraform-backed range operations."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from config import resolve_ngfw_attachment_config
from executors.aws_executor import AWSExecutor
from ngfw_runtime import configure_ngfw_subnets, remove_ngfw_subnets, user_has_active_ranges
from ngfw_runtime_ops import run_ngfw_operation
from provisioner_db_ngfw import (
    _build_ngfw_range_attachment_record,
    _record_ngfw_range_attachment,
    _remove_ngfw_range_attachment,
    get_user_ngfw_data,
)
from state_helpers import _get_cloud_provider

logger = logging.getLogger(__name__)

_MANAGEMENT_IP_KEY = "management_ip"
_NGFW_REQUEST_ID_KEY = "ngfw_request_id"
_STATUS_KEY = "status"


def _describe_ec2_state(aws_executor: AWSExecutor, ec2_instance_id: str) -> str | None:
    """Return the EC2 state name for an instance."""
    result = aws_executor.describe_instance(ec2_instance_id)
    if not result.success:
        return None
    data = json.loads(result.stdout)
    reservations = data.get("Reservations", [])
    if not reservations or not reservations[0].get("Instances"):
        return None
    return reservations[0]["Instances"][0].get("State", {}).get("Name")


def _recover_aws_ngfw_stuck_resuming(ec2_instance_id: str, ngfw_request_id: str) -> None:
    """Recover an AWS NGFW whose status field is stuck in ``resuming``."""
    aws_executor = AWSExecutor()
    ec2_state = _describe_ec2_state(aws_executor, ec2_instance_id)
    if ec2_state == "stopped":
        logger.info("NGFW stuck in 'resuming' but EC2 is stopped, resuming...")
        run_ngfw_operation("start", ngfw_request_id)
    elif ec2_state == "running":
        logger.info("NGFW resuming, EC2 already running")
    elif ec2_state == "pending":
        logger.info("NGFW resuming, waiting for EC2 to be running...")
        aws_executor.wait_for_running(ec2_instance_id)


def _resume_aws_ngfw_for_provisioning(ngfw_data: dict[str, Any]) -> None:
    """Bring an AWS NGFW back into running state before range provisioning."""
    ngfw_status = ngfw_data.get(_STATUS_KEY)
    ec2_instance_id = ngfw_data.get("ec2_instance_id")
    ngfw_request_id = ngfw_data[_NGFW_REQUEST_ID_KEY]
    if ngfw_status == "pausing" and ec2_instance_id:
        logger.info("NGFW is pausing, waiting for pause to complete...")
        AWSExecutor().wait_for_stopped(ec2_instance_id)
        return
    if ngfw_status == "resuming" and ec2_instance_id:
        _recover_aws_ngfw_stuck_resuming(ec2_instance_id, ngfw_request_id)
        return
    logger.info("Resuming paused NGFW for range provisioning...")
    run_ngfw_operation("start", ngfw_request_id)


def _ensure_ngfw_ready_for_provisioning(range_id: int, user_id: int) -> None:
    """Resume AWS NGFWs or assert that another provider is already ready."""
    ngfw_data = get_user_ngfw_data(user_id)
    if not ngfw_data or not ngfw_data.get(_MANAGEMENT_IP_KEY):
        return
    logger.info("NGFW enabled for range %s", range_id)
    ngfw_status = ngfw_data.get(_STATUS_KEY)
    ngfw_provider = ngfw_data.get("cloud_provider", "aws")
    if ngfw_provider == "aws" and ngfw_status in ("paused", "pausing", "resuming"):
        _resume_aws_ngfw_for_provisioning(ngfw_data)
        return
    if ngfw_provider != "aws" and ngfw_status != "ready":
        raise RuntimeError(
            "GDC-attached NGFW ranges require the NGFW to already be in ready state. "
            f"Current status={ngfw_status!r} for request_id={ngfw_data[_NGFW_REQUEST_ID_KEY]}"
        )


def _validate_ngfw_range_attachment(range_spec: dict[str, Any], user_id: int) -> None:
    """Raise when a required NGFW lacks attachable routing state."""
    if not range_spec.get("ngfw", False):
        return
    ngfw_data = get_user_ngfw_data(user_id)
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
    """Build NGFW subnet payloads from per-subnet provisioner outputs."""
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
    """Configure routes and rules on the user's attached NGFW."""
    if not range_spec.get("ngfw", False):
        return
    ngfw_data = get_user_ngfw_data(user_id)
    route_next_hop_ip = ngfw_data.get("route_next_hop_ip") if ngfw_data else ""
    if not (ngfw_data and ngfw_data.get(_MANAGEMENT_IP_KEY) and route_next_hop_ip):
        return
    logger.info("Configuring NGFW with subnet routes...")
    subnets_for_ngfw = _build_ngfw_subnet_payloads(spec_subnets, subnets_output)
    configure_ngfw_subnets(
        subnets=subnets_for_ngfw,
        range_id=range_id,
        management_ip=ngfw_data[_MANAGEMENT_IP_KEY],
        ssh_key_secret_arn=ngfw_data["ssh_key_secret_arn"],
        route_next_hop_ip=route_next_hop_ip,
        ssm_endpoints_subnet_cidr=os.environ.get("SSM_ENDPOINTS_SUBNET_CIDR", ""),
    )
    _record_ngfw_range_attachment(
        ngfw_request_id=ngfw_data[_NGFW_REQUEST_ID_KEY],
        ngfw_status=ngfw_data[_STATUS_KEY],
        attachment_record=_build_ngfw_range_attachment_record(
            range_id=range_id,
            request_id=request_id,
            subnets=subnets_for_ngfw,
            ngfw_data=ngfw_data,
        ),
    )


def _remove_ngfw_attachments_for_destroy(user_id: int, range_id: int, range_spec: dict[str, Any]) -> None:
    """Best-effort detach NGFW subnets and range attachment before destroy."""
    spec_subnets = range_spec.get("subnets", [])
    if not spec_subnets:
        return
    try:
        ngfw_data = get_user_ngfw_data(user_id) if range_spec.get("ngfw", False) else None
        remove_ngfw_subnets(user_id, spec_subnets, range_id)
        if ngfw_data:
            _remove_ngfw_range_attachment(
                ngfw_request_id=ngfw_data[_NGFW_REQUEST_ID_KEY],
                ngfw_status=ngfw_data[_STATUS_KEY],
                range_id=range_id,
            )
    except Exception as exc:
        logger.warning("NGFW subnet removal failed (continuing): %s", exc)


def _maybe_pause_user_ngfw(user_id: int, range_id: int) -> None:
    """Pause an AWS NGFW when the destroyed range was the user's last."""
    try:
        if user_has_active_ranges(user_id, range_id):
            return
        ngfw_data = get_user_ngfw_data(user_id)
        if ngfw_data and ngfw_data[_STATUS_KEY] == "ready" and ngfw_data.get("cloud_provider") == "aws":
            logger.info("No other active ranges, pausing NGFW")
            run_ngfw_operation("stop", ngfw_data[_NGFW_REQUEST_ID_KEY])
    except Exception as exc:
        logger.warning("Failed to pause NGFW (non-fatal): %s", exc)


__all__ = [
    "_configure_ngfw_for_range",
    "_describe_ec2_state",
    "_ensure_ngfw_ready_for_provisioning",
    "_maybe_pause_user_ngfw",
    "_recover_aws_ngfw_stuck_resuming",
    "_remove_ngfw_attachments_for_destroy",
    "_resume_aws_ngfw_for_provisioning",
    "_validate_ngfw_range_attachment",
]

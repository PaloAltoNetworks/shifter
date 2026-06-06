"""Container entrypoint for Shifter Engine.

This module is the main entry point when running the Shifter Engine container.
It handles:
- Database connection via RDS IAM authentication
- Range status updates in the Django database
- Terraform-based provisioning and destruction
"""

import logging
import os
from typing import Any

# Re-exports listed in ``__all__`` below are the canonical Python idiom
# for "these names are imported here on purpose so callers can access
# them via ``main.X`` and ``patch('main.X')``." Sonar python:S1128 and
# mypy both honor ``__all__`` and skip the unused-import check.
import range_terraform_runner
from catalog.instances import (
    _get_dc_instance_type,
    _get_kali_instance_type,
    _get_victim_instance_type,
    _get_windows_instance_type,
)
from config import (
    generate_presigned_url,
    get_range_availability_zone,
    has_ngfw_attachment_state,
    load_range_network_config,
    resolve_ngfw_attachment_config,
)
from events import (
    STATUS_DESTROYED,
    publish_destroyed,
    publish_failed,
    publish_ngfw_event,
    publish_ready,
    publish_status_update,
)
from executors.aws_executor import AWSExecutor
from executors.factory import build_guest_execution_context
from ngfw_terraform import run_ngfw_terraform
from orchestrators.ops_orchestrator import OpsOrchestrator
from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.base import SetupPlan, SetupStep
from plans.bootstrap import BootstrapPlan
from plans.dc_setup import DCSetupPlan
from state_helpers import (
    _build_instance_provider_metadata,
    _build_instance_state,
    _build_provisioned_instance_payload,
    _build_subnet_provider_metadata,
    _build_subnet_state,
    _get_cloud_provider,
    _should_promote_dc_at_runtime,
    _should_run_dc_bootstrap_plan,
)

__all__ = [
    "STATUS_DESTROYED",
    "AWSExecutor",
    "BootstrapPlan",
    "DCSetupPlan",
    "OpsOrchestrator",
    "SetupOrchestrator",
    "SetupPlan",
    "SetupStep",
    "_build_instance_provider_metadata",
    "_build_instance_state",
    "_build_provisioned_instance_payload",
    "_build_subnet_provider_metadata",
    "_build_subnet_state",
    "_get_cloud_provider",
    "_get_dc_instance_type",
    "_get_kali_instance_type",
    "_get_victim_instance_type",
    "_get_windows_instance_type",
    "_should_promote_dc_at_runtime",
    "_should_run_dc_bootstrap_plan",
    "build_guest_execution_context",
    "generate_presigned_url",
    "get_range_availability_zone",
    "has_ngfw_attachment_state",
    "load_range_network_config",
    "publish_destroyed",
    "publish_failed",
    "publish_ngfw_event",
    "publish_ready",
    "publish_status_update",
    "range_terraform_runner",
    "resolve_ngfw_attachment_config",
    "run_ngfw_terraform",
]

logger = logging.getLogger(__name__)


def get_agent_presigned_url(inst_config: dict[str, Any]) -> str | None:
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

    bucket = os.environ.get("AGENT_STORAGE_BUCKET") or os.environ.get("AGENT_S3_BUCKET", "")
    if not bucket:
        logger.warning("AGENT_STORAGE_BUCKET/AGENT_S3_BUCKET not set, cannot generate presigned URL")
        return None

    presigned_url: str | None = None
    try:
        from cloud import get_object_storage

        storage = get_object_storage()
        presigned_url = storage.generate_presigned_download_url(bucket=bucket, key=s3_key, expires_in=3600)
    except Exception as e:
        logger.error("Failed to generate presigned URL for %s: %s", s3_key, e)
    return presigned_url


class DynamicPlan(SetupPlan):
    """Simple wrapper for dynamically-built setup plans.

    Implements the SetupPlan protocol nominally: ``steps`` and ``verify_step``
    are exposed as read-only ``@property`` accessors (matching the protocol's
    declarations) backed by values bundled at construction time. Inheriting the
    Protocol explicitly makes the contract visible to nominal type checkers.
    """

    def __init__(self, name: str, steps: list[SetupStep]) -> None:
        """Bundle a name and pre-built steps for SetupOrchestrator."""
        self.name = name
        self._steps = steps
        self._verify_step: SetupStep | None = None

    @property
    def steps(self) -> list[SetupStep]:
        """Pre-built steps to execute in order."""
        return self._steps

    @property
    def verify_step(self) -> SetupStep | None:
        """Dynamically-built plans carry no dedicated verification step."""
        return self._verify_step

    def get_context(self, instance: object) -> dict[str, Any]:
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

    Known types ('kali', 'victim', 'windows', 'dc') use legacy SSM paths.
    Custom ami_key values resolve to /shifter/ami/<ami_key>.

    Args:
        ami_type: Known type or custom ami_key (e.g. 'kali', 'windows').

    Returns:
        AMI ID string

    Raises:
        ValueError: If SSM parameter not found.
    """
    if ami_type in _ami_cache:
        return _ami_cache[ami_type]

    # Known types use legacy SSM paths; custom keys construct path directly
    param_path = _AMI_SSM_PARAMS.get(ami_type)
    if not param_path:
        param_path = f"/shifter/ami/{ami_type}"

    try:
        from cloud import get_config_store

        store = get_config_store()
        ami_id = store.get_parameter(param_path)
        logger.info("Fetched %s AMI from SSM %s: %s", ami_type, param_path, ami_id)
        _ami_cache[ami_type] = ami_id
        return ami_id
    except Exception as e:
        # No fallback - fail fast to surface IAM/config issues immediately
        raise ValueError(f"Failed to get {ami_type} AMI ID from SSM parameter {param_path}: {e}") from e


# Default timeout for waiting for NGFW SSH to become available (seconds)
# PAN-OS boot time is typically 15-25 minutes, but can take longer on first boot
# 25 minutes
NGFW_SSH_WAIT_TIMEOUT_DEFAULT = 1500


# Re-exports from sibling modules (S104 file-split, issue #780). These
# imports preserve `patch("main.X")` test mocks for callers that still
# reach in through ``main`` instead of the new sibling module path. They
# must follow the top-level constants above (hence the per-line E402
# suppressions) so ``main`` exposes the same surface as the pre-split module.
from provisioner_db import (  # noqa: E402
    _append_kwarg_assignment,
    _update_range_config,
    get_db_connection,
    get_range_data_by_request_id,
    mark_range_instances_destroyed,
    update_range_status,
    write_provisioned_state,
)
from provisioner_db_ngfw import (  # noqa: E402
    _build_ngfw_range_attachment_record,
    _record_ngfw_range_attachment,
    _remove_ngfw_range_attachment,
    get_ngfw_data_by_request_id,
    get_user_ngfw_data,
)

_DB_REEXPORTS_USED = (
    _append_kwarg_assignment,
    _build_ngfw_range_attachment_record,
    _record_ngfw_range_attachment,
    _remove_ngfw_range_attachment,
    _update_range_config,
    get_db_connection,
    get_ngfw_data_by_request_id,
    get_range_data_by_request_id,
    get_user_ngfw_data,
    mark_range_instances_destroyed,
    update_range_status,
    write_provisioned_state,
)


from dc_setup import (  # noqa: E402
    _configure_dc_ssh_access,
    _DCBootstrapContext,
    _DCPromoteConfig,
    _install_dc_xdr,
    _run_dc_bootstrap_plan,
    _run_dc_setup,
    _verify_dc_setup,
)
from instance_orchestrator import (  # noqa: E402
    _build_uuid_to_config,
    _partition_dc_vs_other,
    _partition_pod_vs_vm,
    _resolve_dc_ip_and_domain,
    _setup_dc_instances_blocking,
    _setup_one_other_instance,
    _setup_other_instances_parallel,
    run_instance_setup,
)
from instance_setup import (  # noqa: E402
    _LINUX_VICTIM_OS_TYPES,
    _dispatch_instance_setup_role,
    _DomainJoinSpec,
    _install_xdr_or_raise,
    _InstanceSetupCtx,
    _InstanceSetupSpec,
    _join_windows_domain,
    _resolve_rdp_password_from_secret_ref,
    _resolve_setup_hostname,
    _run_setup_plan,
    _run_single_instance_setup,
    _set_local_password_or_raise,
    _setup_attacker_role,
    _setup_linux_victim,
    _setup_windows_victim,
)
from ngfw_polling import (  # noqa: E402
    _format_serial_cert_status,
    _raise_serial_cert_timeout,
    parse_device_certificate_status,
    parse_serial_number,
    poll_for_serial_and_cert,
    poll_for_serial_number,
    wait_for_autocommit,
)
from ngfw_runtime import (  # noqa: E402
    configure_ngfw_subnets,
    find_stale_routes_by_cidr,
    find_stale_routes_by_db,
    remove_ngfw_subnets,
    update_instance_state,
    user_has_active_ranges,
)
from ngfw_runtime_ops import (  # noqa: E402
    _load_ngfw_ops_plan,
    _publish_ngfw_runtime_status,
    _run_aws_ngfw_operation,
    _run_gcp_ngfw_operation,
    _validate_ngfw_operation,
    run_ngfw_operation,
)
from polaris_bootstrap import (  # noqa: E402
    _run_polaris_range_bootstrap,
)
from terraform_ops import (  # noqa: E402
    _allocate_range_subnet_cidrs,
    _attempt_terraform_auto_cleanup,
    _build_ngfw_subnet_payloads,
    _configure_ngfw_for_range,
    _describe_ec2_state,
    _dispatch_terraform_operation,
    _ensure_ngfw_ready_for_provisioning,
    _ensure_range_is_active,
    _maybe_pause_user_ngfw,
    _post_destroy_cleanup,
    _recover_aws_ngfw_stuck_resuming,
    _recover_missing_subnet_cidrs,
    _release_subnet_allocations_best_effort,
    _remove_ngfw_attachments_for_destroy,
    _resume_aws_ngfw_for_provisioning,
    _run_terraform_destroy,
    _run_terraform_provision,
    _validate_ngfw_range_attachment,
    run_range_terraform,
)
from terraform_vars import (  # noqa: E402
    _build_aws_extra_tf_variables,
    _build_range_terraform_variables,
    _build_tf_instance,
    _build_tf_subnets,
    _resolve_agent_presigned_url,
    _resolve_agent_presigned_url_from_inst,
    _resolve_instance_type,
    _resolve_ngfw_for_range,
    _resolve_tf_os_type,
)

_SIBLING_REEXPORTS_USED = (
    _allocate_range_subnet_cidrs,
    _attempt_terraform_auto_cleanup,
    _build_aws_extra_tf_variables,
    _build_ngfw_subnet_payloads,
    _build_range_terraform_variables,
    _build_tf_instance,
    _build_tf_subnets,
    _configure_ngfw_for_range,
    _describe_ec2_state,
    _dispatch_terraform_operation,
    _ensure_ngfw_ready_for_provisioning,
    _ensure_range_is_active,
    _maybe_pause_user_ngfw,
    _post_destroy_cleanup,
    _recover_aws_ngfw_stuck_resuming,
    _recover_missing_subnet_cidrs,
    _release_subnet_allocations_best_effort,
    _remove_ngfw_attachments_for_destroy,
    _resolve_agent_presigned_url,
    _resolve_agent_presigned_url_from_inst,
    _resolve_instance_type,
    _resolve_ngfw_for_range,
    _resolve_tf_os_type,
    _resume_aws_ngfw_for_provisioning,
    _run_terraform_destroy,
    _run_terraform_provision,
    _validate_ngfw_range_attachment,
    run_range_terraform,
    _load_ngfw_ops_plan,
    _publish_ngfw_runtime_status,
    _run_aws_ngfw_operation,
    _run_gcp_ngfw_operation,
    _validate_ngfw_operation,
    run_ngfw_operation,
    _format_serial_cert_status,
    _raise_serial_cert_timeout,
    configure_ngfw_subnets,
    find_stale_routes_by_cidr,
    find_stale_routes_by_db,
    parse_device_certificate_status,
    parse_serial_number,
    poll_for_serial_and_cert,
    poll_for_serial_number,
    remove_ngfw_subnets,
    update_instance_state,
    user_has_active_ranges,
    wait_for_autocommit,
    _build_uuid_to_config,
    _DCBootstrapContext,
    _DCPromoteConfig,
    _dispatch_instance_setup_role,
    _DomainJoinSpec,
    _install_dc_xdr,
    _install_xdr_or_raise,
    _InstanceSetupCtx,
    _InstanceSetupSpec,
    _join_windows_domain,
    _LINUX_VICTIM_OS_TYPES,
    _partition_dc_vs_other,
    _partition_pod_vs_vm,
    _resolve_dc_ip_and_domain,
    _resolve_rdp_password_from_secret_ref,
    _resolve_setup_hostname,
    _run_dc_bootstrap_plan,
    _run_dc_setup,
    _run_polaris_range_bootstrap,
    _run_setup_plan,
    _run_single_instance_setup,
    _set_local_password_or_raise,
    _setup_attacker_role,
    _setup_dc_instances_blocking,
    _setup_linux_victim,
    _setup_one_other_instance,
    _setup_other_instances_parallel,
    _setup_windows_victim,
    _verify_dc_setup,
    _configure_dc_ssh_access,
    run_instance_setup,
)


if __name__ == "__main__":
    from logging_config import configure_logging

    configure_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Shifter Engine for provisioning cyber ranges and NGFW operations")
    subparsers = parser.add_subparsers(dest="resource", required=True, help="Resource type")

    range_parser = subparsers.add_parser("range", help="Range lifecycle operations")
    range_parser.add_argument(
        "operation",
        choices=["provision", "destroy", "pause", "resume"],
        help="Operation to perform: provision (create), destroy (teardown), pause, or resume",
    )
    range_parser.add_argument(
        "--request-id",
        type=str,
        required=True,
        dest="request_id",
        help="UUID of the Request for this Range",
    )

    ngfw_parser = subparsers.add_parser("ngfw", help="NGFW runtime operations")
    ngfw_parser.add_argument(
        "operation",
        choices=["provision", "deprovision", "start", "stop"],
        help="NGFW operation to perform",
    )
    ngfw_parser.add_argument(
        "--request-id",
        type=str,
        required=True,
        dest="request_id",
        help="UUID of the Request for this NGFW",
    )
    ngfw_parser.add_argument(
        "--ec2-instance-id",
        type=str,
        help="EC2 instance ID (for start/stop)",
    )

    args = parser.parse_args()

    if args.resource == "ngfw":
        logger.info("Starting NGFW %s for request_id=%s", args.operation, args.request_id)
        logger.info("Environment: %s", os.environ.get("ENVIRONMENT", "unknown"))

        if args.operation in ("provision", "deprovision"):
            tf_op = "up" if args.operation == "provision" else "destroy"
            run_ngfw_terraform(tf_op, args.request_id)
        else:
            kwargs: dict[str, str] = {}
            if args.ec2_instance_id:
                kwargs["ec2_instance_id"] = args.ec2_instance_id
            run_ngfw_operation(args.operation, args.request_id, **kwargs)

        logger.info("Completed NGFW %s for request_id=%s", args.operation, args.request_id)

    elif args.resource == "range":
        request_id = args.request_id
        tf_op = "up" if args.operation == "provision" else "destroy"

        logger.info("Starting range %s for request_id=%s", args.operation, request_id)
        logger.info("Environment: %s", os.environ.get("ENVIRONMENT", "unknown"))

        if args.operation in ("provision", "destroy"):
            run_range_terraform(tf_op, request_id)
        elif args.operation == "pause":
            from range_ops import run_range_pause

            run_range_pause(request_id)
        elif args.operation == "resume":
            from range_ops import run_range_resume

            run_range_resume(request_id)

        logger.info("Completed range %s for request_id=%s", args.operation, request_id)

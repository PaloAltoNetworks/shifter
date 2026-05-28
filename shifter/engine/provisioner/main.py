"""Container entrypoint for Shifter Engine.

This module is the main entry point when running the Shifter Engine container.
It handles:
- Database connection via RDS IAM authentication
- Range status updates in the Django database
- Terraform-based provisioning and destruction
"""

import json
import logging
import os
from typing import Any

import psycopg
from psycopg import sql

# Explicit ``from x import y as y`` re-exports keep mypy strict-mode happy
# (it treats the redundant alias form as an explicit re-export) and keep
# the symbols importable as ``main.X`` so existing ``patch("main.X")``
# test mocks intercept the sibling-module call sites.
import range_terraform_runner as range_terraform_runner
from catalog.instances import (
    _get_dc_instance_type as _get_dc_instance_type,
)
from catalog.instances import (
    _get_kali_instance_type as _get_kali_instance_type,
)
from catalog.instances import (
    _get_victim_instance_type as _get_victim_instance_type,
)
from catalog.instances import (
    _get_windows_instance_type as _get_windows_instance_type,
)
from config import (
    generate_presigned_url as generate_presigned_url,
)
from config import (
    get_range_availability_zone as get_range_availability_zone,
)
from config import (
    has_ngfw_attachment_state as has_ngfw_attachment_state,
)
from config import (
    load_range_network_config as load_range_network_config,
)
from config import (
    resolve_ngfw_attachment_config as resolve_ngfw_attachment_config,
)
from events import (
    STATUS_DESTROYED as STATUS_DESTROYED,
)
from events import (
    publish_destroyed as publish_destroyed,
)
from events import (
    publish_failed as publish_failed,
)
from events import (
    publish_ngfw_event as publish_ngfw_event,
)
from events import (
    publish_ready as publish_ready,
)
from events import (
    publish_status_update as publish_status_update,
)
from executors.aws_executor import AWSExecutor as AWSExecutor
from executors.factory import (
    build_guest_execution_context as build_guest_execution_context,
)
from ngfw_terraform import run_ngfw_terraform
from orchestrators.ops_orchestrator import (
    OpsOrchestrator as OpsOrchestrator,
)
from orchestrators.setup_orchestrator import (
    SetupOrchestrator as SetupOrchestrator,
)
from plans.base import SetupStep
from plans.bootstrap import BootstrapPlan as BootstrapPlan
from plans.dc_setup import DCSetupPlan as DCSetupPlan
from state_helpers import (
    _should_promote_dc_at_runtime as _should_promote_dc_at_runtime,
)
from state_helpers import (
    _should_run_dc_bootstrap_plan as _should_run_dc_bootstrap_plan,
)

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


class DynamicPlan:
    """Simple wrapper for dynamically-built setup plans.

    Wraps a list of steps to satisfy the SetupPlan protocol
    when steps are built at runtime (e.g., from subnet lists).
    """

    def __init__(self, name: str, steps: list[SetupStep]) -> None:
        self.name = name
        self.steps = steps
        self.verify_step: SetupStep | None = None

    @staticmethod
    def get_context(instance: object) -> dict[str, Any]:
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


def get_db_connection() -> psycopg.Connection:
    """Get database connection.

    Supports two authentication modes:
    - If DB_PASSWORD is set: Uses standard password authentication (local dev)
    - Otherwise: Uses RDS IAM authentication (ECS/production)

    Returns:
        psycopg.Connection: Active database connection.

    Raises:
        Exception: If connection fails.
    """
    db_host = os.environ.get("DB_HOST")
    db_port = int(os.environ.get("DB_PORT", 5432))
    db_user = os.environ.get("DB_USER")
    db_name = os.environ.get("DB_NAME")
    db_password = os.environ.get("DB_PASSWORD")

    # Local dev mode: use password auth
    if db_password:
        if not all([db_host, db_user, db_name]):
            missing = [
                k
                for k, v in [
                    ("DB_HOST", db_host),
                    ("DB_USER", db_user),
                    ("DB_NAME", db_name),
                ]
                if not v
            ]
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

        logger.debug("get_db_connection: password auth to %s:%s/%s", db_host, db_port, db_name)
        return psycopg.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
        )

    # Production mode: use provider-native IAM auth
    cloud_region = os.environ.get("CLOUD_REGION") or os.environ.get("AWS_REGION")
    if not all([db_host, db_user, db_name, cloud_region]):
        missing = [
            k
            for k, v in [
                ("DB_HOST", db_host),
                ("DB_USER", db_user),
                ("DB_NAME", db_name),
                ("CLOUD_REGION", cloud_region),
            ]
            if not v
        ]
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    logger.debug("get_db_connection: cloud IAM auth to %s:%s/%s", db_host, db_port, db_name)
    # validated above
    assert db_host is not None
    # validated above
    assert db_user is not None
    from cloud import get_db_auth

    auth = get_db_auth()
    token = auth.generate_auth_token(
        hostname=db_host,
        port=db_port,
        username=db_user,
    )
    return psycopg.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=token,
        sslmode="require",
    )


def _append_kwarg_assignment(assignments: list[Any], values: list[Any], key: str, value: Any) -> None:
    """Append one SET-clause fragment for an UPDATE, handling NOW() specially.

    `value is None` is filtered by the caller; this helper expects a
    real value. Splits the loop body out so `update_range_status` stays
    within the nesting-depth budget.
    """
    if value == "NOW()":
        assignments.append(sql.SQL("{} = NOW()").format(sql.Identifier(key)))
        return
    assignments.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
    values.append(value)


def update_range_status(range_id: int, status: str, **kwargs: str | int | None) -> None:
    """Update range status in database.

    Args:
        range_id: The ID of the range to update.
        status: New status value (e.g., 'provisioning', 'ready', 'failed').
        **kwargs: Additional fields to update (e.g., subnet_id, error_message).
    """
    logger.debug("update_range_status: range_id=%s status=%s kwargs=%s", range_id, status, list(kwargs.keys()))
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            assignments = [
                sql.SQL("{} = %s").format(sql.Identifier("status")),
                sql.SQL("{} = NOW()").format(sql.Identifier("updated_at")),
            ]
            values: list[Any] = [status]

            for key, value in kwargs.items():
                if value is None:
                    continue
                _append_kwarg_assignment(assignments, values, key, value)

            values.append(range_id)
            query = sql.SQL("UPDATE mission_control_range SET {} WHERE id = %s").format(sql.SQL(", ").join(assignments))
            cur.execute(query, values)
        conn.commit()


from state_helpers import (  # noqa: E402
    _build_instance_state,
    _build_provisioned_instance_payload,
    _build_subnet_state,
    _get_cloud_provider,
)


def write_provisioned_state(
    range_id: int,
    subnets: dict[str, dict[str, Any]],
    instances: list[dict[str, Any]],
    ngfw_instance_id: int | None = None,
) -> None:
    """Write provisioned infrastructure state directly to database.

    This follows the NGFW pattern: provisioner writes state directly to DB,
    events are notification-only.

    Args:
        range_id: The range ID being provisioned.
        subnets: Dict of subnet_name -> subnet details with uuid and provider resource IDs.
        instances: List of instance dicts with uuid, instance_id, private_ip, etc.
        ngfw_instance_id: ID of the NGFW Instance this range is attached to (if any).
    """
    provider = _get_cloud_provider()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Update engine_subnet.state for each subnet
            for subnet_name, subnet_data in subnets.items():
                subnet_uuid = subnet_data.get("uuid")
                if not subnet_uuid:
                    logger.warning("Subnet %s missing UUID, skipping DB write", subnet_name)
                    continue

                state = _build_subnet_state(subnet_data, provider=provider)

                cur.execute(
                    """
                    UPDATE engine_subnet
                    SET state = %s, status = 'ready'
                    WHERE uuid = %s AND range_id = %s
                    """,
                    (json.dumps(state), subnet_uuid, range_id),
                )
                if cur.rowcount == 0:
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

                instance_state = _build_instance_state(inst, provider=provider)

                cur.execute(
                    """
                    UPDATE engine_instance
                    SET status = 'ready', state = %s
                    WHERE uuid = %s
                    """,
                    (json.dumps(instance_state), instance_uuid),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"No engine_instance record found for uuid={instance_uuid}")
                logger.debug("Updated engine_instance state: uuid=%s", instance_uuid)

                provisioned_instances.append(_build_provisioned_instance_payload(inst, provider=provider))

            # Update Range.provisioned_instances and ngfw_instance_id
            cur.execute(
                """
                UPDATE mission_control_range
                SET provisioned_instances = %s, ngfw_instance_id = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(provisioned_instances), ngfw_instance_id, range_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"No mission_control_range record found for id={range_id}")
            logger.debug(
                "Updated Range.provisioned_instances: range_id=%s count=%d",
                range_id,
                len(provisioned_instances),
            )

        conn.commit()
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
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Single UPDATE with subquery - no race window between SELECT and UPDATE
            cur.execute(
                """
                UPDATE engine_instance
                SET status = 'destroyed', destroyed_at = NOW()
                WHERE uuid IN (
                    SELECT DISTINCT i.uuid
                    FROM engine_instance i
                    JOIN engine_request r ON i.request_id = r.id
                    JOIN mission_control_range rng ON rng.request_id = r.id
                    WHERE rng.id = %s
                )
                """,
                (range_id,),
            )
            instance_count = cur.rowcount
            logger.debug(
                "Marked %d engine_instance records as destroyed for range_id=%s",
                instance_count,
                range_id,
            )

            # Update engine_subnet records
            cur.execute(
                """
                UPDATE engine_subnet
                SET status = 'destroyed', destroyed_at = NOW()
                WHERE range_id = %s
                """,
                (range_id,),
            )
            subnet_count = cur.rowcount
            logger.debug(
                "Marked %d engine_subnet records as destroyed for range_id=%s",
                subnet_count,
                range_id,
            )

        conn.commit()
    logger.info(
        "Marked engine records as destroyed: range_id=%s instances=%d subnets=%d",
        range_id,
        instance_count,
        subnet_count,
    )
    return instance_count, subnet_count


def get_user_ngfw_data(user_id: int) -> dict[str, Any] | None:
    """Get NGFW data for a user (if they have one provisioned).

    Queries for a ready/paused NGFW Instance belonging to this user and
    resolves provider-neutral access and attachment details from state.

    Args:
        user_id: Django User ID.

    Returns:
        Dictionary with request correlation IDs, provider-neutral management
        access fields, attachment/routing fields, and legacy AWS aliases.
        Returns None if user has no NGFW.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                i.state,
                i.status
            FROM engine_instance i
            JOIN engine_request r ON i.request_id = r.id
            WHERE r.user_id = %s
              AND i.role = 'ngfw'
              AND i.status IN ('ready', 'paused', 'pausing', 'resuming')
            ORDER BY i.created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        request_id = str(row[0])
        state = row[1] if row[1] else {}
        status = row[2]
        attachment = resolve_ngfw_attachment_config(state)

        return {
            "ngfw_request_id": request_id,
            "cloud_provider": attachment.cloud_provider,
            "ec2_instance_id": state.get("ec2_instance_id"),
            "management_ip": attachment.management_ip,
            "ssh_key_secret_arn": attachment.ssh_key_secret_ref,
            "ssh_key_secret_ref": attachment.ssh_key_secret_ref,
            "dataplane_ip": attachment.dataplane_ip,
            "route_next_hop_ip": attachment.route_next_hop_ip,
            "data_eni_id": attachment.data_attachment_id,
            "data_attachment_id": attachment.data_attachment_id,
            "attachment_mode": attachment.attachment_mode,
            "provider_metadata": attachment.provider_metadata,
            "attached_ranges": state.get("attached_ranges", []),
            "status": status,
        }


def _build_ngfw_range_attachment_record(
    *,
    range_id: int,
    request_id: str,
    subnets: list[dict[str, Any]],
    ngfw_data: dict[str, Any],
) -> dict[str, Any]:
    """Build the persisted attachment record for a range bound to an NGFW."""
    return {
        "range_id": range_id,
        "request_id": request_id,
        "cloud_provider": _get_cloud_provider(),
        "attachment_mode": ngfw_data.get("attachment_mode", ""),
        "route_next_hop_ip": ngfw_data.get("route_next_hop_ip", ""),
        "data_attachment_id": ngfw_data.get("data_attachment_id", ""),
        "subnets": [
            {
                "name": subnet.get("name", ""),
                "cidr": subnet.get("cidr", ""),
                "connected_to": list(subnet.get("connected_to", [])),
                "provider_metadata": subnet.get("provider_metadata", {}),
            }
            for subnet in subnets
        ],
    }


def _record_ngfw_range_attachment(
    *,
    ngfw_request_id: str,
    ngfw_status: str,
    attachment_record: dict[str, Any],
) -> None:
    """Merge the current range attachment into the NGFW instance state."""
    ngfw_data = get_ngfw_data_by_request_id(ngfw_request_id)
    current_state = ngfw_data.get("state") or {}
    current_attachments = list(current_state.get("attached_ranges") or [])
    current_attachments = [
        attachment
        for attachment in current_attachments
        if attachment.get("range_id") != attachment_record.get("range_id")
    ]
    current_attachments.append(attachment_record)
    update_instance_state(
        ngfw_request_id,
        ngfw_status,
        attached_ranges=current_attachments,
    )


def _remove_ngfw_range_attachment(
    *,
    ngfw_request_id: str,
    ngfw_status: str,
    range_id: int,
) -> None:
    """Remove a range attachment from the NGFW instance state."""
    ngfw_data = get_ngfw_data_by_request_id(ngfw_request_id)
    current_state = ngfw_data.get("state") or {}
    current_attachments = list(current_state.get("attached_ranges") or [])
    remaining_attachments = [attachment for attachment in current_attachments if attachment.get("range_id") != range_id]
    update_instance_state(
        ngfw_request_id,
        ngfw_status,
        attached_ranges=remaining_attachments,
    )


def get_ngfw_data_by_request_id(request_id: str) -> dict[str, Any]:
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
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                i.uuid AS instance_id,
                a.uuid AS app_id,
                i.spec,
                a.spec AS app_spec,
                i.state,
                i.status
            FROM engine_request r
            JOIN engine_instance i ON i.request_id = r.id
            LEFT JOIN engine_app a ON a.instance_id = i.id
            WHERE r.request_id = %s
              AND i.role = 'ngfw'
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"NGFW request not found: {request_id}")
        return {
            "request_id": str(row[0]),
            "instance_id": str(row[1]),
            "app_id": str(row[2]) if row[2] else None,
            "spec": row[3] if row[3] else {},
            "app_spec": row[4] if row[4] else {},
            "state": row[5] if row[5] else {},
            "status": row[6],
        }


def _update_range_config(range_id: int, range_spec: dict[str, Any]) -> None:
    """Write updated range_config back to mission_control_range.

    Called after subnet CIDR allocation to persist the CIDRs so that
    destroy can read them later without needing to re-query allocations.

    Args:
        range_id: The range database ID.
        range_spec: The updated range spec dict (with CIDRs populated).
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE mission_control_range SET range_config = %s WHERE id = %s",
            (json.dumps(range_spec), range_id),
        )
        conn.commit()
    logger.info("Persisted updated range_config for range %d", range_id)


def get_range_data_by_request_id(request_id: str) -> dict[str, Any]:
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
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                rng.id AS range_id,
                rng.user_id,
                rng.range_config,
                rng.subnet_index,
                rng.status
            FROM engine_request r
            JOIN mission_control_range rng ON rng.request_id = r.id
            WHERE r.request_id = %s
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Range request not found: {request_id}")

        range_config = row[3] if row[3] else {}
        user_id = row[2]
        ngfw_instance_id = None

        # Look up NGFW instance ID if ngfw is enabled
        if range_config.get("ngfw", False):
            cur.execute(
                """
                SELECT ei.id, ei.state
                FROM engine_instance ei
                JOIN engine_request er ON ei.request_id = er.id
                WHERE er.user_id = %s
                  AND ei.role = 'ngfw'
                  AND ei.status IN ('ready', 'paused', 'pausing', 'resuming')
                ORDER BY ei.created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            ngfw_row = cur.fetchone()
            if ngfw_row and has_ngfw_attachment_state(ngfw_row[1]):
                ngfw_instance_id = ngfw_row[0]

        return {
            "request_id": str(row[0]),
            "range_id": row[1],
            "user_id": user_id,
            "spec": range_config,
            "subnet_index": row[4],
            "status": row[5],
            "ngfw_instance_id": ngfw_instance_id,
        }


# Re-exports from sibling modules (S104 file-split, issue #780). These
# imports preserve `patch("main.X")` test mocks for callers that still
# reach in through ``main`` instead of the new sibling module path.
from instance_setup import (  # noqa: E402
    _LINUX_VICTIM_OS_TYPES,
    _build_uuid_to_config,
    _configure_dc_ssh_access,
    _DCBootstrapContext,
    _DCPromoteConfig,
    _dispatch_instance_setup_role,
    _DomainJoinSpec,
    _install_dc_xdr,
    _install_xdr_or_raise,
    _InstanceSetupCtx,
    _InstanceSetupSpec,
    _join_windows_domain,
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
    run_instance_setup,
)
from ngfw_runtime import (  # noqa: E402
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
)
from ngfw_runtime_ops import (  # noqa: E402
    _load_ngfw_ops_plan,
    _publish_ngfw_runtime_status,
    _run_aws_ngfw_operation,
    _run_gcp_ngfw_operation,
    _validate_ngfw_operation,
    run_ngfw_operation,
)
from terraform_ops import (  # noqa: E402
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

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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import psycopg
from psycopg import sql

import range_terraform_runner
from catalog.instances import (
    _get_dc_instance_type,
    _get_kali_instance_type,
    _get_victim_instance_type,
    _get_windows_instance_type,
)
from components.instance import sanitize_hostname
from config import (
    generate_presigned_url,
    get_range_availability_zone,
    has_ngfw_attachment_state,
    load_range_network_config,
    resolve_ngfw_attachment_config,
)
from events import (
    STATUS_DESTROYED,
    STATUS_FAILED,
    publish_destroyed,
    publish_failed,
    publish_ngfw_event,
    publish_ready,
    publish_status_update,
)
from executors.aws_executor import AWSExecutor
from executors.factory import build_guest_execution_context, get_ssh_username
from executors.ngfw_executor import NGFWExecutor
from executors.ssm_executor import SSMExecutor
from ngfw_terraform import run_ngfw_terraform
from orchestrators.ops_orchestrator import OpsOrchestrator
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.base import SetupStep
from plans.bootstrap import BootstrapPlan
from plans.dc_setup import DCSetupPlan
from plans.domain_join import DomainJoinPlan
from plans.linux_bootstrap import LinuxBootstrapPlan
from plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from plans.ngfw_configure_subnets import NGFWConfigureSubnetsPlan, NGFWRemoveSubnetsPlan
from plans.polaris_range_bootstrap import PolarisRangeBootstrapPlan
from plans.set_local_password import SetLocalPasswordPlan
from plans.xdr_agent_install import XDRAgentInstallPlan

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

    bucket = os.environ.get("AGENT_STORAGE_BUCKET") or os.environ.get("AGENT_S3_BUCKET", "")
    if not bucket:
        logger.warning("AGENT_STORAGE_BUCKET/AGENT_S3_BUCKET not set, cannot generate presigned URL")
        return None

    try:
        from cloud import get_object_storage

        storage = get_object_storage()
        url = storage.generate_presigned_download_url(bucket=bucket, key=s3_key, expires_in=3600)
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
NGFW_SSH_WAIT_TIMEOUT_DEFAULT = 1500  # 25 minutes


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
    assert db_host is not None  # validated above
    assert db_user is not None  # validated above
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


def _append_kwarg_assignment(assignments: list, values: list, key: str, value) -> None:
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
            values: list = [status]

            for key, value in kwargs.items():
                if value is None:
                    continue
                _append_kwarg_assignment(assignments, values, key, value)

            values.append(range_id)
            query = sql.SQL("UPDATE mission_control_range SET {} WHERE id = %s").format(sql.SQL(", ").join(assignments))
            cur.execute(query, values)
        conn.commit()


def _assert_subnet_output(subnet_name: str, subnet_data: dict) -> None:
    """Reject a Pulumi subnet record missing any required field."""
    for field in ("uuid", "subnet_id", "subnet_cidr"):
        if not subnet_data.get(field):
            raise ValueError(f"Subnet '{subnet_name}' missing '{field}'")


def _assert_instance_output(index: int, inst: dict) -> None:
    """Reject a Pulumi instance record missing any required field."""
    if not inst.get("uuid"):
        raise ValueError(f"Instance[{index}] (role={inst.get('role')}) missing 'uuid'")
    if not inst.get("instance_id"):
        raise ValueError(f"Instance[{index}] missing 'instance_id'")
    if not inst.get("private_ip"):
        raise ValueError(f"Instance[{index}] (role={inst.get('role')}, os={inst.get('os')}) missing 'private_ip'")


def _validate_provisioned_outputs(
    subnets: dict[str, dict],
    instances: list[dict],
    expected_subnet_names: set[str] | None = None,
) -> None:
    """Validate Pulumi outputs have required fields before DB write.

    Args:
        subnets: Dict of subnet_name -> subnet details.
        instances: List of instance dicts.
        expected_subnet_names: Optional set of expected subnet names from spec.

    Raises:
        ValueError: If required fields are missing or empty.
    """
    for subnet_name, subnet_data in subnets.items():
        _assert_subnet_output(subnet_name, subnet_data)
    for i, inst in enumerate(instances):
        _assert_instance_output(i, inst)

    if expected_subnet_names:
        actual_subnets = set(subnets.keys())
        missing = expected_subnet_names - actual_subnets
        if missing:
            raise ValueError(f"Expected subnets not created: {missing}")
        extra = actual_subnets - expected_subnet_names
        if extra:
            logger.warning("Unexpected subnets in output: %s", extra)


def _get_cloud_provider() -> str:
    """Return the active cloud provider for range state persistence."""
    return os.environ.get("CLOUD_PROVIDER", "aws")


def _get_bool_env(name: str) -> bool | None:
    """Parse a boolean env var if set, otherwise return None."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return None

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean-like value, got: {raw_value!r}")


def _should_promote_dc_at_runtime(provider: str | None = None) -> bool:
    """Decide whether DC promotion should run during setup."""
    override = _get_bool_env("DC_RUNTIME_PROMOTION")
    if override is not None:
        return override
    return (provider or _get_cloud_provider()) == "gcp"


def _should_run_dc_bootstrap_plan(provider: str | None = None) -> bool:
    """Decide whether DC hostname/SSH bootstrap should run via setup plans."""
    override = _get_bool_env("DC_BOOTSTRAP_VIA_SETUP_PLAN")
    if override is not None:
        return override
    return (provider or _get_cloud_provider()) == "gcp"


def _compact_state_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop empty provider metadata fields so persisted state stays readable."""
    return {key: value for key, value in fields.items() if value not in (None, "", [], {}, ())}


def _get_provider_metadata_prefixes(provider: str) -> list[str]:
    """Return the accepted output prefixes for provider metadata extraction."""
    if provider == "gcp":
        return ["gcp_", "gdc_", "vmruntime_"]
    return [f"{provider}_"]


def _extract_provider_metadata(resource: dict[str, Any], provider: str) -> dict[str, Any]:
    """Collect provider-prefixed keys into a nested metadata block."""
    metadata: dict[str, Any] = {}
    for prefix in _get_provider_metadata_prefixes(provider):
        metadata.update({key.removeprefix(prefix): value for key, value in resource.items() if key.startswith(prefix)})
    return _compact_state_fields(metadata)


def _build_subnet_provider_metadata(subnet_data: dict[str, Any], provider: str) -> dict[str, Any]:
    """Build provider-specific subnet metadata for persisted state."""
    if provider == "aws":
        metadata = {
            "subnet_id": subnet_data.get("subnet_id"),
            "cidr": subnet_data.get("subnet_cidr"),
            "security_group_id": subnet_data.get("security_group_id"),
            "route_table_id": subnet_data.get("route_table_id"),
        }
    else:
        metadata = _extract_provider_metadata(subnet_data, provider)

    return {provider: metadata} if metadata else {}


def _build_instance_provider_metadata(instance_data: dict[str, Any], provider: str) -> dict[str, Any]:
    """Build provider-specific instance metadata for persisted state."""
    if provider == "aws":
        metadata = {
            "instance_id": instance_data.get("instance_id"),
        }
    else:
        metadata = _extract_provider_metadata(instance_data, provider)

    return {provider: metadata} if metadata else {}


def _build_subnet_state(subnet_data: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    """Build the persisted engine_subnet.state payload."""
    resolved_provider = provider or _get_cloud_provider()
    state = {
        "cloud_provider": resolved_provider,
        "subnet_id": subnet_data.get("subnet_id"),
        "subnet_cidr": subnet_data.get("subnet_cidr"),
        "security_group_id": subnet_data.get("security_group_id"),
        "route_table_id": subnet_data.get("route_table_id"),
        "provider_metadata": _build_subnet_provider_metadata(subnet_data, resolved_provider),
        # Preserve the current AWS field names for existing AWS callers.
        "aws_subnet_id": subnet_data.get("subnet_id") if resolved_provider == "aws" else None,
        "aws_cidr": subnet_data.get("subnet_cidr") if resolved_provider == "aws" else None,
        "aws_security_group_id": subnet_data.get("security_group_id") if resolved_provider == "aws" else None,
        "aws_route_table_id": subnet_data.get("route_table_id") if resolved_provider == "aws" else None,
    }
    return state


def _build_instance_state(instance_data: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    """Build the persisted engine_instance.state payload for range guests."""
    resolved_provider = provider or _get_cloud_provider()
    state = {
        "asset_type": instance_data.get("asset_type", "vm_runtime_vm"),
        "cloud_provider": resolved_provider,
        "instance_id": instance_data.get("instance_id"),
        "private_ip": instance_data.get("private_ip"),
        "ssh_key_secret_arn": instance_data.get("ssh_key_secret_arn"),
        # Per-instance RDP password secret reference (#762). Carries the
        # provider-native identifier (AWS Secrets Manager ARN or GCP
        # Secret Manager resource path); the password value itself is
        # never persisted in state.
        "rdp_password_secret_arn": instance_data.get("rdp_password_secret_arn"),
        # SSM Parameter Store SecureString name for the same per-
        # instance password (AWS only; GCP carries ``None``). Used by
        # the AWS push path's ``{{ssm-secure:<name>}}`` substitution so
        # the value never lands in SSM Run Command history (#762 codex
        # cycle 3). Mirrors the Secrets Manager copy referenced above;
        # the portal continues to read the value from Secrets Manager
        # via ``shared.cloud`` at access time.
        "rdp_password_ssm_param_name": instance_data.get("rdp_password_ssm_param_name"),
        "ssh_username": instance_data.get("ssh_username"),
        "subnet_name": instance_data.get("subnet_name"),
        "provider_metadata": _build_instance_provider_metadata(instance_data, resolved_provider),
        # Preserve the current AWS field name for existing pause/resume readers.
        "aws_instance_id": instance_data.get("instance_id") if resolved_provider == "aws" else None,
    }
    return state


def _build_provisioned_instance_payload(instance_data: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    """Build the legacy Range.provisioned_instances entry with provider metadata."""
    resolved_provider = provider or _get_cloud_provider()
    return {
        "uuid": instance_data.get("uuid"),
        "name": instance_data.get("name"),
        "asset_type": instance_data.get("asset_type", "vm_runtime_vm"),
        "role": instance_data.get("role"),
        "os_type": instance_data.get("os"),
        "subnet_name": instance_data.get("subnet_name"),
        "instance_id": instance_data.get("instance_id"),
        "private_ip": instance_data.get("private_ip"),
        "ssh_key_secret_arn": instance_data.get("ssh_key_secret_arn"),
        # Per-instance RDP password secret reference (#762).
        "rdp_password_secret_arn": instance_data.get("rdp_password_secret_arn"),
        # AWS-only mirror in SSM Parameter Store SecureString (#762 cycle 3).
        "rdp_password_ssm_param_name": instance_data.get("rdp_password_ssm_param_name"),
        "ssh_username": instance_data.get("ssh_username"),
        "cloud_provider": resolved_provider,
        "provider_metadata": _build_instance_provider_metadata(instance_data, resolved_provider),
    }


def write_provisioned_state(
    range_id: int,
    subnets: dict[str, dict],
    instances: list[dict],
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


def get_user_ngfw_data(user_id: int) -> dict | None:
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


def remove_ngfw_subnets(user_id: int, subnets: list[dict], range_id: int) -> None:
    """Remove subnet addresses and security rules from user's NGFW.

    Resumes the NGFW if paused, waits for SSH, then runs the remove plan.

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

    # NGFW should NEVER be paused while ranges are active - this indicates a bug
    if status == "paused":
        logger.error(
            "NGFW is paused during range destroy - this should never happen! "
            "range_id=%s user_id=%s ngfw_request_id=%s. Skipping NGFW cleanup.",
            range_id,
            user_id,
            ngfw_request_id,
        )
        return

    # Get SSH private key from Secrets Manager
    from cloud import get_secrets_store

    secrets = get_secrets_store()
    private_key = secrets.get_secret(ssh_key_secret_arn)

    # Create NGFW executor and wait for NGFW to be ready
    ssh_executor = NGFWExecutor(private_key=private_key)
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
    has_endpoints = bool(os.environ.get("SSM_ENDPOINTS_SUBNET_CIDR"))
    steps = NGFWRemoveSubnetsPlan().get_steps(subnets, range_id, has_endpoints)
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
    logger.debug("user_has_active_ranges: user_id=%s exclude_range_id=%s", user_id, exclude_range_id)
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM mission_control_range
            WHERE user_id = %s
              AND id != %s
              AND status IN ('ready', 'provisioning')
            """,
            (user_id, exclude_range_id),
        )
        row = cur.fetchone()
        count = row[0] if row else 0
        logger.debug("user_has_active_ranges: found %d active ranges", count)
        return count > 0


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


def _update_range_config(range_id: int, range_spec: dict) -> None:
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
    ssh_executor: NGFWExecutor,
    host: str,
    timeout_seconds: int = 600,
    poll_interval: int = 30,
) -> str:
    """Poll NGFW for serial number until it appears or timeout.

    License registration with Palo Alto CSP can take 10-20 minutes after boot.
    This function polls 'show system info' until a valid serial number appears.

    Args:
        ssh_executor: NGFWExecutor instance for running commands.
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
    ssh_executor: NGFWExecutor,
    host: str,
    timeout_seconds: int = 1800,
    poll_interval: int = 30,
) -> str:
    """Poll NGFW until both serial number AND device certificate are present.

    License registration and certificate provisioning can take 10-30 minutes
    after boot. This function polls until both are valid, tracking each
    independently since they may appear at different times.

    Args:
        ssh_executor: NGFWExecutor instance for running commands.
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
    ssh_executor: NGFWExecutor,
    host: str,
    timeout_seconds: int = 600,
    poll_interval: int = 15,
) -> None:
    """Wait for NGFW boot autocommit to complete before configuring.

    After boot, PAN-OS runs an autocommit that must complete before any
    configuration changes can be made. This function polls 'show jobs all'
    until there are no active (ACT) commit jobs.

    Args:
        ssh_executor: NGFWExecutor instance for running commands.
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
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get instance id, app id, and current state
            cur.execute(
                """
                SELECT i.id, i.state, a.id
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
                raise ValueError(f"NGFW instance not found for request: {request_id}")

            instance_id = row[0]
            current_state = row[1] if row[1] else {}
            app_id = row[2]

            # Merge state updates into current state
            if state_updates:
                current_state.update(state_updates)

            # Update Instance with new status and merged state
            if status == STATUS_DESTROYED:
                cur.execute(
                    """
                    UPDATE engine_instance
                    SET status = %s, state = %s, updated_at = NOW(), destroyed_at = NOW()
                    WHERE id = %s
                    """,
                    (status, json.dumps(current_state), instance_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE engine_instance
                    SET status = %s, state = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, json.dumps(current_state), instance_id),
                )

            # Update App status (if app exists)
            if app_id:
                if status == STATUS_DESTROYED:
                    cur.execute(
                        """
                        UPDATE engine_app
                        SET status = %s, updated_at = NOW(), destroyed_at = NOW()
                        WHERE id = %s
                        """,
                        (status, app_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE engine_app
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (status, app_id),
                    )

        conn.commit()


# =============================================================================
# Post-Pulumi Setup Functions
# These run AFTER pulumi up creates infrastructure, BEFORE marking range ready
# =============================================================================


def find_stale_routes_by_cidr(
    ssh_executor: NGFWExecutor,
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
    ssh_executor: NGFWExecutor,
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
    range_ids = list(routes_by_range.keys())
    stale_routes = []

    try:
        with get_db_connection() as conn, conn.cursor() as cur:
            # Find ranges that are active (not stale)
            # Stale = destroyed, failed, or doesn't exist
            query = sql.SQL("""
                SELECT id FROM mission_control_range
                WHERE id IN ({})
                AND status NOT IN ('destroyed', 'failed')
                """).format(sql.SQL(", ").join(sql.Placeholder() * len(range_ids)))
            cur.execute(query, range_ids)
            active_range_ids = {row[0] for row in cur.fetchall()}

        # Routes belonging to ranges NOT in active_range_ids are stale
        for range_id, routes in routes_by_range.items():
            if range_id not in active_range_ids:
                logger.info(
                    "Found %d stale routes for range %d (destroyed/failed/missing)",
                    len(routes),
                    range_id,
                )
                stale_routes.extend(routes)

    except psycopg.Error as e:
        logger.warning("Failed to query DB for stale routes: %s", e)
        return []

    return stale_routes


def configure_ngfw_subnets(
    subnets: list[dict],
    range_id: int,
    management_ip: str,
    ssh_key_secret_arn: str,
    route_next_hop_ip: str,
    ssm_endpoints_subnet_cidr: str = "",
) -> None:
    """Configure NGFW with routes for range subnets.

    This runs after range infrastructure exists and before instance setup.
    Configures static routes on the NGFW so traffic can flow between subnets.
    When ssm_endpoints_subnet_cidr is provided, also configures routing for
    Bedrock/SSM endpoint traffic through the NGFW.

    Args:
        subnets: List of dicts with 'name', 'cidr', 'connected_to'.
        range_id: Range ID for unique naming.
        management_ip: NGFW management IP for SSH.
        ssh_key_secret_arn: Secrets Manager ARN for SSH private key.
        route_next_hop_ip: Next-hop IP address for range subnet routes.
        ssm_endpoints_subnet_cidr: SSM/Bedrock endpoints subnet CIDR for NGFW routing.
    """
    logger.info(
        "Configuring NGFW: %d subnets, next_hop=%s",
        len(subnets),
        route_next_hop_ip,
    )

    # Get SSH private key from Secrets Manager
    from cloud import get_secrets_store

    secrets = get_secrets_store()
    private_key = secrets.get_secret(ssh_key_secret_arn)

    # Create NGFW executor
    ssh_executor = NGFWExecutor(private_key=private_key)

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
    steps = NGFWConfigureSubnetsPlan().get_steps(
        subnets,
        range_id,
        route_next_hop_ip,
        stale_routes,
        ssm_endpoints_subnet_cidr,
    )
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


_LINUX_VICTIM_OS_TYPES = ("kali", "ubuntu", "amazon-linux")


class _InstanceSetupCtx:
    """Plan-context shim carrying per-instance setup parameters."""

    def __init__(
        self,
        hostname: str,
        public_key: str,
        agent_presigned_url: str,
        ssh_user: str,
    ) -> None:
        self.hostname = hostname
        self.public_key = public_key
        self.agent_presigned_url = agent_presigned_url
        self.ssh_user = ssh_user


def _resolve_setup_hostname(instance_name: str, instance_id: str) -> str:
    """Return the hostname to write into the per-instance setup context."""
    sanitized_name = sanitize_hostname(instance_name) if instance_name else ""
    return sanitized_name or f"inst-{instance_id[-8:]}"


def _run_setup_plan(
    orchestrator: SetupOrchestrator,
    execution: Any,
    plan: Any,
    context: Any,
    document_name: str,
    failure_prefix: str,
) -> None:
    """Execute one plan and raise SetupError on failure."""
    result = orchestrator.orchestrate(execution.target, plan, context, document_name=document_name)
    if not result.success:
        raise SetupError(f"{failure_prefix}: {result.error}")


def _resolve_rdp_password_from_secret_ref(rdp_password_secret_arn: str | None) -> str | None:
    """Fetch the per-instance RDP password value from the active cloud secret store.

    Returns ``None`` when no secret reference is recorded (e.g., DC role,
    or older state without the field). Callers that require the value
    must check for ``None`` and either skip the push or raise.
    """
    if not rdp_password_secret_arn:
        return None
    from cloud import get_secrets_store

    secrets = get_secrets_store()
    return secrets.get_secret(rdp_password_secret_arn)


def _set_local_password_or_raise(
    orchestrator: SetupOrchestrator,
    execution: Any,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    document_name: str,
    instance_id: str,
    platform: str,
    failure_prefix: str,
) -> None:
    """Push the per-instance local guest password via SSM/SSH (#762).

    On AWS the script body uses ``{{ssm-secure:<param-name>}}``
    substitution against the per-instance SSM Parameter Store
    SecureString that mirrors the Secrets Manager value (see
    ``aws_ssm_parameter.guest_password`` in the range Terraform module).
    The SSM service substitutes the placeholder server-side on the way
    to the agent; the resolved value never appears in
    ``GetCommandInvocation`` history or anywhere else SSM retains the
    original ``commands`` parameter.

    On GCP/GDC there is no analogous service-side substitution. The
    password value is fetched from the per-instance GCP Secret Manager
    secret via ``shared.cloud`` and rendered into the SSH-transported
    script body — the SSH transport does not persist the body
    anywhere; it lives only in the target's bash process memory.

    Raises ``SetupError`` when the appropriate per-instance reference
    is missing or the GCP fetch returns empty: a "ready" range whose
    Guacamole credential is unusable is worse than a provisioning
    error.
    """
    cloud_provider = _get_cloud_provider()
    rdp_token: str
    if cloud_provider == "aws":
        ssm_param_name = instance_data.get("rdp_password_ssm_param_name")
        if not ssm_param_name:
            raise SetupError(
                f"{failure_prefix}: instance {instance_id} has no "
                "rdp_password_ssm_param_name; provisioner did not record an SSM "
                "Parameter Store reference for the per-instance password"
            )
        rdp_token = f"{{{{ssm-secure:{ssm_param_name}}}}}"
    else:
        secret_ref = instance_data.get("rdp_password_secret_arn")
        if not secret_ref:
            raise SetupError(
                f"{failure_prefix}: instance {instance_id} has no rdp_password_secret_arn "
                "in its provisioned state; provisioner did not record a per-instance secret reference"
            )
        fetched = _resolve_rdp_password_from_secret_ref(secret_ref)
        if not fetched:
            raise SetupError(f"{failure_prefix}: per-instance RDP password fetch returned empty for {instance_id}")
        rdp_token = fetched
    plan = SetLocalPasswordPlan(platform=platform)
    context = plan.get_context({"rdp_username": ctx.ssh_user, "rdp_password": rdp_token})
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        context,
        document_name,
        failure_prefix=failure_prefix,
    )
    logger.info("Per-instance RDP password set on %s (%s)", instance_id, platform)


def _setup_attacker_role(
    orchestrator: SetupOrchestrator,
    execution: Any,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    document_name: str,
    instance_id: str,
) -> None:
    """Run the Kali bootstrap plan for an attacker-role instance."""
    plan = LinuxBootstrapPlan()
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        plan.get_context(ctx),
        document_name,
        failure_prefix="Kali setup failed",
    )
    _set_local_password_or_raise(
        orchestrator,
        execution,
        ctx,
        instance_data,
        document_name,
        instance_id,
        platform="linux",
        failure_prefix="Kali RDP password push failed",
    )
    logger.info("Kali setup complete for %s", instance_id)


def _install_xdr_or_raise(
    orchestrator: SetupOrchestrator,
    execution: Any,
    plan_cls: Any,
    document_name: str,
    instance_id: str,
    agent_presigned_url: str,
    xdr_required: bool,
    failure_prefix: str,
    success_log: str,
) -> None:
    """Install the XDR agent or raise/log according to ``xdr_required``."""
    if agent_presigned_url:
        plan = plan_cls()
        ctx_obj = plan.get_context({"agent_presigned_url": agent_presigned_url})
        _run_setup_plan(
            orchestrator,
            execution,
            plan,
            ctx_obj,
            document_name,
            failure_prefix=failure_prefix,
        )
        logger.info(success_log, instance_id)
        return
    if xdr_required:
        raise SetupError(f"XDR agent required but no URL provided for {instance_id}")
    logger.info("No XDR agent URL provided for %s (not required)", instance_id)


def _setup_linux_victim(
    orchestrator: SetupOrchestrator,
    execution: Any,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    document_name: str,
    instance_id: str,
    agent_presigned_url: str,
    xdr_required: bool,
) -> None:
    """Run the linux victim path: bootstrap, per-instance RDP password, optional XDR install."""
    plan = LinuxBootstrapPlan()
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        plan.get_context(ctx),
        document_name,
        failure_prefix="Linux bootstrap failed",
    )
    logger.info("Linux bootstrap complete for %s", instance_id)
    _set_local_password_or_raise(
        orchestrator,
        execution,
        ctx,
        instance_data,
        document_name,
        instance_id,
        platform="linux",
        failure_prefix="Linux RDP password push failed",
    )
    _install_xdr_or_raise(
        orchestrator,
        execution,
        LinuxXDRAgentInstallPlan,
        document_name,
        instance_id,
        agent_presigned_url,
        xdr_required,
        failure_prefix="Linux XDR install failed",
        success_log="Linux XDR agent installed on %s",
    )


def _join_windows_domain(
    orchestrator: SetupOrchestrator,
    execution: Any,
    document_name: str,
    instance_id: str,
    join_domain: bool,
    dc_ip: str | None,
    domain_name: str | None,
) -> None:
    """Join the Windows victim to its domain, or raise per the explicit policy."""
    if not join_domain:
        return
    if not (dc_ip and domain_name):
        raise SetupError(f"Domain join required but dc_ip or domain_name not provided for {instance_id}")
    domain_password = os.environ.get("DC_DOMAIN_PASSWORD", "")
    if not domain_password:
        raise SetupError(f"Domain join required but DC_DOMAIN_PASSWORD not set for {instance_id}")
    logger.info("Joining domain %s for %s...", domain_name, instance_id)
    plan = DomainJoinPlan()
    dj_context = plan.get_context(
        {
            "dc_ip": dc_ip,
            "domain_name": domain_name,
            "domain_admin_password": domain_password,
        }
    )
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        dj_context,
        document_name,
        failure_prefix=f"Domain join failed for {instance_id}",
    )
    logger.info("Domain join complete for %s", instance_id)


def _setup_windows_victim(
    orchestrator: SetupOrchestrator,
    execution: Any,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    document_name: str,
    instance_id: str,
    agent_presigned_url: str,
    xdr_required: bool,
    join_domain: bool,
    dc_ip: str | None,
    domain_name: str | None,
) -> None:
    """Run the windows victim path: bootstrap, per-instance Admin password, XDR install, optional domain join."""
    plan = BootstrapPlan()
    _run_setup_plan(
        orchestrator,
        execution,
        plan,
        plan.get_context(ctx),
        document_name,
        failure_prefix="Windows bootstrap failed",
    )
    logger.info("Windows bootstrap complete for %s", instance_id)
    # Override the bootstrap-default Administrator username for the
    # local-Administrator password push.
    pw_ctx = _InstanceSetupCtx(
        hostname=ctx.hostname,
        public_key=ctx.public_key,
        agent_presigned_url=ctx.agent_presigned_url,
        ssh_user="Administrator",
    )
    _set_local_password_or_raise(
        orchestrator,
        execution,
        pw_ctx,
        instance_data,
        document_name,
        instance_id,
        platform="windows",
        failure_prefix="Windows Administrator password push failed",
    )
    _install_xdr_or_raise(
        orchestrator,
        execution,
        XDRAgentInstallPlan,
        document_name,
        instance_id,
        agent_presigned_url,
        xdr_required,
        failure_prefix="Windows XDR install failed",
        success_log="Windows XDR agent installed on %s",
    )
    _join_windows_domain(
        orchestrator,
        execution,
        document_name,
        instance_id,
        join_domain,
        dc_ip,
        domain_name,
    )


def _dispatch_instance_setup_role(
    orchestrator: SetupOrchestrator,
    execution: Any,
    ctx: _InstanceSetupCtx,
    instance_data: dict[str, Any],
    document_name: str,
    instance_id: str,
    role: str,
    os_type: str,
    agent_presigned_url: str,
    xdr_required: bool,
    join_domain: bool,
    dc_ip: str | None,
    domain_name: str | None,
) -> None:
    """Route an instance through the correct role/os setup path."""
    if role == "attacker":
        _setup_attacker_role(orchestrator, execution, ctx, instance_data, document_name, instance_id)
        return
    if role != "victim":
        # Unknown role: leave behavior identical to pre-refactor (no plan runs).
        return
    if os_type in _LINUX_VICTIM_OS_TYPES:
        _setup_linux_victim(
            orchestrator,
            execution,
            ctx,
            instance_data,
            document_name,
            instance_id,
            agent_presigned_url,
            xdr_required,
        )
        return
    _setup_windows_victim(
        orchestrator,
        execution,
        ctx,
        instance_data,
        document_name,
        instance_id,
        agent_presigned_url,
        xdr_required,
        join_domain,
        dc_ip,
        domain_name,
    )


def _run_single_instance_setup(
    instance_data: dict[str, Any],
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
        instance_id: Provider-specific instance identifier (or name).
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

    execution = build_guest_execution_context(instance_data, os_type=os_type, role=role)
    orchestrator = SetupOrchestrator(executor=execution.executor)
    document_name = execution.document_name

    logger.info("Waiting for %s connectivity on %s...", execution.transport_name, execution.target)
    execution.wait_for_ready(timeout_seconds=300)
    logger.info("Target %s is ready via %s", execution.target, execution.transport_name)

    ctx = _InstanceSetupCtx(
        hostname=_resolve_setup_hostname(instance_name, instance_id),
        public_key=public_key,
        agent_presigned_url=agent_presigned_url,
        ssh_user=get_ssh_username(os_type, role),
    )

    try:
        _dispatch_instance_setup_role(
            orchestrator,
            execution,
            ctx,
            instance_data,
            document_name,
            instance_id,
            role,
            os_type,
            agent_presigned_url,
            xdr_required,
            join_domain,
            dc_ip,
            domain_name,
        )
        return True
    finally:
        execution.close()


def _run_polaris_range_bootstrap(
    instance_id: str,
    dc_ip: str,
    public_key: str,
) -> None:
    """Run PolarisRangeBootstrapPlan against a polaris VM instance.

    Called from setup_instance after the generic LinuxBootstrapPlan
    finishes, when the instance's ami_key is "polaris-vm". Rewrites
    /opt/polaris/scenario-dev/polaris/build/docker-compose.override.yml
    on the host with this range's actual DC IP and per-instance kali
    pubkey, then force-recreates the dns + a14-kali containers so their
    entrypoints pick up the new env vars.

    Args:
        instance_id: EC2 instance ID of the polaris VM.
        dc_ip: Private IP of this range's A2 DC. Must be non-empty.
        public_key: Per-instance SSH public key from
            tls_private_key.instance. Must be non-empty.

    Raises:
        SetupError: If the rewrite or container recreation fails, or
            if dc_ip / public_key are empty.
    """
    if not dc_ip:
        raise SetupError(
            f"polaris range bootstrap for {instance_id}: dc_ip is empty "
            "(scenario must include a role=dc instance so the DC's "
            "private IP can be discovered)"
        )
    if not public_key:
        raise SetupError(
            f"polaris range bootstrap for {instance_id}: public_key is empty "
            "(per-instance ssh key from tls_private_key.instance was not propagated)"
        )

    logger.info(
        "Running polaris range bootstrap on %s (dc_ip=%s, key length=%d)",
        instance_id,
        dc_ip,
        len(public_key),
    )

    # Set IMDSv2 PutResponseHopLimit to 2 on the polaris-vm so the
    # a14-kali container (one extra hop from the EC2 host's network
    # namespace through the docker bridge) can reach IMDS at
    # 169.254.169.254 and pick up the EC2 instance role's credentials.
    # Default IMDS hop limit is 1. Without this, claude inside the kali
    # container has no AWS creds at runtime.
    # Idempotent: re-running on an already-2 instance is a no-op.
    try:
        import boto3 as _boto3

        _ec2 = _boto3.client("ec2", region_name=os.environ.get("AWS_REGION", "us-east-2"))
        _ec2.modify_instance_metadata_options(
            InstanceId=instance_id,
            HttpPutResponseHopLimit=2,
            HttpTokens="required",
            HttpEndpoint="enabled",
        )
        logger.info("Set IMDSv2 hop limit=2 on %s for kali container reachability", instance_id)
    except Exception as e:
        # Warn rather than fail provisioning — claude inside kali will surface
        # the loss of creds at runtime if this slip propagates that far.
        logger.warning("failed to set IMDS hop limit on %s: %s", instance_id, e)

    executor = SSMExecutor()
    orchestrator = SetupOrchestrator(executor=executor)
    plan = PolarisRangeBootstrapPlan()

    class _PolarisCtx:
        def __init__(self) -> None:
            self.dc_ip = dc_ip
            self.public_key = public_key

    context = plan.get_context(_PolarisCtx())
    result = orchestrator.orchestrate(
        instance_id,
        plan,
        context,
        document_name="AWS-RunShellScript",
    )
    if not result.success:
        raise SetupError(f"polaris range bootstrap failed on {instance_id}: {result.error}")
    logger.info("polaris range bootstrap complete for %s", instance_id)


def _run_dc_setup(
    instance_data: dict[str, Any],
    instance_id: str,
    dc_config: dict,
    agent_presigned_url: str,
    public_key: str = "",
    xdr_required: bool = False,
) -> bool:
    """Run setup for a DC instance.

    Args:
        instance_id: Provider-specific instance identifier (or name).
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

    provider = _get_cloud_provider()
    execution = build_guest_execution_context(instance_data, os_type="windows", role="dc")
    executor = execution.executor
    orchestrator = SetupOrchestrator(executor=executor)

    # The Packer-built shifter-dc AMI runs through 2-3 sysprep reboot cycles
    # on first boot before SSM agent is reliably online. Empirically observed
    # 13-15 minutes between launch and stable SSM on the polaris-dc bake
    # exemplar (2026-05-06). The previous 600s (10 min) timeout caused the
    # provisioner to give up early and tear the range down. 1800s (30 min)
    # gives plenty of headroom for any sysprep variation, and on a normal
    # already-warm DC AMI the wait returns in seconds anyway.
    logger.info("Waiting for %s connectivity on DC %s...", execution.transport_name, execution.target)
    execution.wait_for_ready(timeout_seconds=1800)
    logger.info("DC %s ready via %s", instance_id, execution.transport_name)

    try:
        _run_dc_bootstrap_plan(
            provider=provider,
            instance_data=instance_data,
            instance_id=instance_id,
            public_key=public_key,
            orchestrator=orchestrator,
            execution=execution,
        )
        _configure_dc_ssh_access(
            executor=executor,
            execution=execution,
            instance_id=instance_id,
            public_key=public_key,
        )
        _verify_dc_setup(
            provider=provider,
            domain_name=domain_name,
            netbios_name=netbios_name,
            orchestrator=orchestrator,
            execution=execution,
        )
        _install_dc_xdr(
            orchestrator=orchestrator,
            execution=execution,
            instance_id=instance_id,
            agent_presigned_url=agent_presigned_url,
            xdr_required=xdr_required,
        )
        return True
    finally:
        execution.close()


def _build_uuid_to_config(range_spec: dict) -> dict[str, dict]:
    """Return a {instance uuid → instance config} lookup from the range spec."""
    return {
        inst.get("uuid", ""): inst for subnet in range_spec.get("subnets", []) for inst in subnet.get("instances", [])
    }


def _partition_pod_vs_vm(instances_output: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split scanned instances into (pod-backed, VM-backed) lists."""
    pods: list[dict] = []
    vms: list[dict] = []
    for inst in instances_output:
        if inst.get("asset_type", "vm_runtime_vm") == "scenario_pod":
            pods.append(inst)
        else:
            vms.append(inst)
    return pods, vms


def _partition_dc_vs_other(vm_instances: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split VM-backed instances into (DC, non-DC) lists."""
    dcs: list[dict] = []
    others: list[dict] = []
    for inst in vm_instances:
        if inst.get("role") == "dc":
            dcs.append(inst)
        else:
            others.append(inst)
    return dcs, others


def _setup_dc_instances_blocking(dc_instances: list[dict], uuid_to_config: dict[str, dict]) -> None:
    """Run DC setup for every DC instance synchronously (domain joins depend on it)."""
    for dc_inst in dc_instances:
        inst_uuid = dc_inst.get("uuid", "")
        inst_config = uuid_to_config.get(inst_uuid, {})
        dc_config = inst_config.get("dc_config", {})
        agent_url = get_agent_presigned_url(inst_config)
        _run_dc_setup(
            instance_data=dc_inst,
            instance_id=dc_inst["instance_id"],
            dc_config=dc_config,
            agent_presigned_url=agent_url or "",
            public_key=dc_inst.get("public_key", ""),
            xdr_required=bool(inst_config.get("agent")),
        )


def _resolve_dc_ip_and_domain(
    dc_instances: list[dict],
    uuid_to_config: dict[str, dict],
    dc_ip: str | None,
    domain_name: str | None,
) -> tuple[str | None, str | None]:
    """Pick the DC IP + domain to use for downstream domain joins."""
    if not dc_instances or dc_ip:
        return dc_ip, domain_name
    first_dc = dc_instances[0]
    dc_uuid = first_dc.get("uuid", "")
    dc_config = uuid_to_config.get(dc_uuid, {}).get("dc_config", {})
    return first_dc.get("private_ip"), dc_config.get("domain_name")


def _setup_one_other_instance(
    inst: dict,
    uuid_to_config: dict[str, dict],
    actual_dc_ip: str | None,
    actual_domain: str | None,
    range_id: int,
) -> tuple[str, bool, str | None]:
    """Run setup for a single non-DC VM. Returns (instance_id, success, error)."""
    inst_id = inst["instance_id"]
    inst_uuid = inst.get("uuid", "")
    inst_config = uuid_to_config.get(inst_uuid, {})
    try:
        _run_single_instance_setup(
            instance_data=inst,
            instance_id=inst_id,
            role=inst.get("role", "victim"),
            os_type=inst.get("os", "ubuntu"),
            public_key=inst.get("public_key", ""),
            agent_presigned_url=get_agent_presigned_url(inst_config) or "",
            join_domain=inst_config.get("join_domain", False),
            dc_ip=actual_dc_ip,
            domain_name=actual_domain,
            xdr_required=bool(inst_config.get("agent")),
            instance_name=inst.get("hostname", "") or inst.get("name", ""),
            range_id=range_id,
        )
        # Per-scenario post-bootstrap: the polaris VM AMI is pre-baked with
        # a docker compose stack hardcoded to range 0's DC IP and the
        # bake-time kali pubkey. After LinuxBootstrapPlan finishes, rewrite
        # the compose override and force-recreate the dns + a14-kali
        # containers with this range's actual DC IP and per-instance pubkey.
        # Gate on ami_key so this only fires for polaris instances.
        if inst_config.get("ami_key") == "polaris-vm":
            _run_polaris_range_bootstrap(
                instance_id=inst_id,
                dc_ip=actual_dc_ip or "",
                public_key=inst.get("public_key", ""),
            )
        return (inst_id, True, None)
    except Exception as e:
        # Catch-all so any single instance's failure becomes a tuple the
        # orchestrator can fail the whole range on, rather than crashing
        # the executor thread.
        return (inst_id, False, str(e))


def _setup_other_instances_parallel(
    other_instances: list[dict],
    uuid_to_config: dict[str, dict],
    actual_dc_ip: str | None,
    actual_domain: str | None,
    range_id: int,
) -> None:
    """Run setup for non-DC VMs in parallel; raise on any failure."""
    if not other_instances:
        return
    logger.info("Running setup for %d non-DC instances in parallel...", len(other_instances))
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(
                _setup_one_other_instance,
                inst,
                uuid_to_config,
                actual_dc_ip,
                actual_domain,
                range_id,
            ): inst
            for inst in other_instances
        }
        for future in as_completed(futures):
            inst_id, success, error = future.result()
            if not success:
                raise SetupError(f"Instance {inst_id} setup failed: {error}")


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
    uuid_to_config = _build_uuid_to_config(range_spec)
    pod_instances, vm_instances = _partition_pod_vs_vm(instances_output)
    if pod_instances:
        logger.info("Skipping VM setup for %d pod-backed scenario assets", len(pod_instances))

    dc_instances, other_instances = _partition_dc_vs_other(vm_instances)

    # DC setup MUST complete before any domain joins fire.
    _setup_dc_instances_blocking(dc_instances, uuid_to_config)

    actual_dc_ip, actual_domain = _resolve_dc_ip_and_domain(dc_instances, uuid_to_config, dc_ip, domain_name)

    _setup_other_instances_parallel(other_instances, uuid_to_config, actual_dc_ip, actual_domain, range_id)
    logger.info("All instance setup complete")


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


def _resume_aws_ngfw_for_provisioning(ngfw_data: dict) -> None:
    """Bring an AWS NGFW back into running state before range provisioning."""
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
    run_ngfw_operation("start", ngfw_request_id)


def _ensure_ngfw_ready_for_provisioning(range_id: int, user_id: int) -> None:
    """Resume the user's NGFW if paused (AWS) or assert it's already ready (other clouds)."""
    ngfw_data = get_user_ngfw_data(user_id)
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


def _attempt_terraform_auto_cleanup(request_id: str, range_id: int, user_id: int, range_spec: dict) -> None:
    """Best-effort `terraform destroy` after a failed provision."""
    logger.error(
        "Provision failed for range_id=%s request_id=%s - attempting Terraform cleanup...",
        range_id,
        request_id,
    )
    try:
        tf_variables = _build_range_terraform_variables(request_id, range_id, user_id, range_spec)
        range_terraform_runner.destroy_range(request_id, variables=tf_variables)
        range_terraform_runner.cleanup_range_state(request_id)
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
    operation: str, request_id: str, range_id: int, user_id: int, range_spec: dict
) -> None:
    """Run the requested Terraform operation; raise ValueError for unknown ops."""
    if operation == "up":
        _run_terraform_provision(request_id, range_id, user_id, range_spec)
        return
    if operation == "destroy":
        _run_terraform_destroy(request_id, range_id, user_id, range_spec)
        return
    raise ValueError(f"Unknown operation: {operation}")


def run_range_terraform(operation: str, request_id: str) -> None:
    """Run Range Terraform operation (provision or destroy).

    Uses range_terraform_runner for infrastructure and the existing instance
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

    if range_spec.get("ngfw", False):
        _ensure_ngfw_ready_for_provisioning(range_id, user_id)

    try:
        _dispatch_terraform_operation(operation, request_id, range_id, user_id, range_spec)
    except Exception as e:
        error_msg = str(e)[:1000]
        logger.error("Range Terraform operation failed: %s", error_msg)
        if operation == "up":
            _attempt_terraform_auto_cleanup(request_id, range_id, user_id, range_spec)
        publish_failed(
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

    spec_subnets = _allocate_range_subnet_cidrs(request_id, range_id, range_spec)

    # Build Terraform variables from range spec (now with CIDRs)
    tf_variables = _build_range_terraform_variables(request_id, range_id, user_id, range_spec)

    # Run Terraform apply
    output_data = range_terraform_runner.apply_range(request_id, tf_variables)
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


def _allocate_range_subnet_cidrs(request_id: str, range_id: int, range_spec: dict) -> list[dict]:
    spec_subnets = range_spec.get("subnets", [])
    if not spec_subnets:
        return spec_subnets

    from components.network import allocate_subnets

    range_network = load_range_network_config()
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
    _update_range_config(range_id, range_spec)
    return spec_subnets


def _validate_ngfw_range_attachment(range_spec: dict, user_id: int) -> None:
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
    range_spec: dict,
    spec_subnets: list[dict[str, Any]],
    subnets_output: dict[str, dict[str, Any]],
) -> None:
    if not range_spec.get("ngfw", False):
        return

    ngfw_data = get_user_ngfw_data(user_id)
    route_next_hop_ip = ngfw_data.get("route_next_hop_ip") if ngfw_data else ""
    if not (ngfw_data and ngfw_data.get("management_ip") and route_next_hop_ip):
        return

    logger.info("Configuring NGFW with subnet routes...")
    subnets_for_ngfw = _build_ngfw_subnet_payloads(spec_subnets, subnets_output)
    configure_ngfw_subnets(
        subnets=subnets_for_ngfw,
        range_id=range_id,
        management_ip=ngfw_data["management_ip"],
        ssh_key_secret_arn=ngfw_data["ssh_key_secret_arn"],
        route_next_hop_ip=route_next_hop_ip,
        ssm_endpoints_subnet_cidr=os.environ.get("SSM_ENDPOINTS_SUBNET_CIDR", ""),
    )
    _record_ngfw_range_attachment(
        ngfw_request_id=ngfw_data["ngfw_request_id"],
        ngfw_status=ngfw_data["status"],
        attachment_record=_build_ngfw_range_attachment_record(
            range_id=range_id,
            request_id=request_id,
            subnets=subnets_for_ngfw,
            ngfw_data=ngfw_data,
        ),
    )


class _DCBootstrapContext:
    def __init__(self, hostname: str, public_key: str):
        self.hostname = hostname
        self.public_key = public_key


class _DCPromoteConfig:
    def __init__(self, domain_name: str, netbios_name: str, dsrm_password: str, domain_admin_password: str):
        self.domain_name = domain_name
        self.netbios_name = netbios_name
        self.dsrm_password = dsrm_password
        self.domain_admin_password = domain_admin_password


def _run_dc_bootstrap_plan(
    *,
    provider: str,
    instance_data: dict[str, Any],
    instance_id: str,
    public_key: str,
    orchestrator: SetupOrchestrator,
    execution: Any,
) -> None:
    if not _should_run_dc_bootstrap_plan(provider):
        return

    logger.info("Running DC bootstrap plan via %s setup path", provider)
    bootstrap_plan = BootstrapPlan()
    bootstrap_source = instance_data.get("hostname", "") or instance_data.get("name", "")
    bootstrap_hostname = sanitize_hostname(bootstrap_source) or f"dc-{instance_id[-8:]}"
    bootstrap_context = bootstrap_plan.get_context(
        _DCBootstrapContext(hostname=bootstrap_hostname, public_key=public_key)
    )
    bootstrap_result = orchestrator.orchestrate(
        execution.target,
        bootstrap_plan,
        bootstrap_context,
        document_name=execution.document_name,
    )
    if not bootstrap_result.success:
        raise SetupError(f"DC bootstrap failed: {bootstrap_result.error}")
    logger.info("DC bootstrap complete for %s", instance_id)


def _configure_dc_ssh_access(
    *,
    executor: Any,
    execution: Any,
    instance_id: str,
    public_key: str,
) -> None:
    if not public_key:
        logger.warning("No public key provided for DC %s, SSH key auth will not work", instance_id)
        return

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
        instance_id=execution.target,
        script=ssh_key_script,
        document_name=execution.document_name,
        timeout_seconds=60,
    )
    if not ssh_result.success:
        logger.warning("SSH key configuration failed: %s (continuing with setup)", ssh_result.stderr)
        return
    logger.info("SSH key configured on DC %s", instance_id)


def _verify_dc_setup(
    *,
    provider: str,
    domain_name: str,
    netbios_name: str,
    orchestrator: SetupOrchestrator,
    execution: Any,
) -> None:
    logger.info("Verifying Domain Controller (%s)...", domain_name)
    runtime_promotion = _should_promote_dc_at_runtime(provider)
    logger.info(
        "Using %s DC verification path for provider=%s",
        "runtime" if runtime_promotion else "prebaked",
        provider,
    )
    dc_plan = DCSetupPlan(runtime_promotion=runtime_promotion)
    domain_admin_password = os.environ.get("DC_DOMAIN_PASSWORD", "")
    config_obj = _DCPromoteConfig(domain_name, netbios_name, domain_admin_password, domain_admin_password)
    dc_context = dc_plan.get_context(config_obj)
    dc_result = orchestrator.orchestrate(
        execution.target,
        dc_plan,
        dc_context,
        document_name=execution.document_name,
    )
    if not dc_result.success:
        raise SetupError(f"DC verification failed: {dc_result.error}")
    logger.info("DC verification complete")


def _install_dc_xdr(
    *,
    orchestrator: SetupOrchestrator,
    execution: Any,
    instance_id: str,
    agent_presigned_url: str,
    xdr_required: bool,
) -> None:
    if agent_presigned_url:
        logger.info("Installing XDR agent on DC %s...", instance_id)
        xdr_plan = XDRAgentInstallPlan()
        xdr_context = xdr_plan.get_context({"agent_presigned_url": agent_presigned_url})
        xdr_result = orchestrator.orchestrate(
            execution.target,
            xdr_plan,
            xdr_context,
            document_name=execution.document_name,
        )
        if not xdr_result.success:
            raise SetupError(f"XDR agent install failed on DC: {xdr_result.error}")
        logger.info("XDR agent installed successfully on DC")
        return

    if xdr_required:
        raise SetupError(f"XDR agent required but no URL provided for DC {instance_id}")
    logger.info("No XDR agent URL provided for DC (not required)")


def _remove_ngfw_attachments_for_destroy(user_id: int, range_id: int, range_spec: dict) -> None:
    """Best-effort detach of NGFW subnets / range attachment before terraform destroy.

    Failures are logged and swallowed; terraform destroy runs regardless.
    """
    spec_subnets = range_spec.get("subnets", [])
    if not spec_subnets:
        return
    try:
        ngfw_data = get_user_ngfw_data(user_id) if range_spec.get("ngfw", False) else None
        remove_ngfw_subnets(user_id, spec_subnets, range_id)
        if ngfw_data:
            _remove_ngfw_range_attachment(
                ngfw_request_id=ngfw_data["ngfw_request_id"],
                ngfw_status=ngfw_data["status"],
                range_id=range_id,
            )
    except Exception as e:
        logger.warning("NGFW subnet removal failed (continuing): %s", e)


def _recover_missing_subnet_cidrs(range_id: int, range_spec: dict) -> None:
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


def _post_destroy_cleanup(request_id: str, range_id: int, user_id: int) -> None:
    """Mark range destroyed, release subnet allocations, optionally pause NGFW.

    Called only if terraform destroy succeeded. All steps are best-effort.
    """
    try:
        mark_range_instances_destroyed(range_id)
    except Exception as e:
        logger.error("Failed to mark range %d as destroyed: %s", range_id, e)

    try:
        from components.network import release_subnet_allocations

        release_subnet_allocations(request_id)
    except Exception as e:
        logger.warning("Failed to release subnet allocations: %s", e)


def _maybe_pause_user_ngfw(user_id: int, range_id: int) -> None:
    """If this range was the user's last active range, pause their AWS NGFW."""
    try:
        if user_has_active_ranges(user_id, range_id):
            return
        ngfw_data = get_user_ngfw_data(user_id)
        if ngfw_data and ngfw_data["status"] == "ready" and ngfw_data.get("cloud_provider") == "aws":
            logger.info("No other active ranges, pausing NGFW")
            run_ngfw_operation("stop", ngfw_data["ngfw_request_id"])
    except Exception as e:
        logger.warning("Failed to pause NGFW (non-fatal): %s", e)


def _run_terraform_destroy(
    request_id: str,
    range_id: int,
    user_id: int,
    range_spec: dict,
) -> None:
    """Run Terraform destroy for range."""
    try:
        range_data = get_range_data_by_request_id(request_id)
    except ValueError as e:
        logger.warning("Range not found for request %s, skipping destroy: %s", request_id, e)
        return

    if range_data.get("status") == "destroyed":
        logger.info("Range %d already destroyed, skipping", range_id)
        return

    _remove_ngfw_attachments_for_destroy(user_id, range_id, range_spec)
    _recover_missing_subnet_cidrs(range_id, range_spec)

    logger.info("Running terraform destroy for range...")
    terraform_succeeded = False
    try:
        tf_variables = _build_range_terraform_variables(request_id, range_id, user_id, range_spec)
        range_terraform_runner.destroy_range(request_id, variables=tf_variables)
        terraform_succeeded = True
        logger.info("Cleaning up Terraform state...")
        range_terraform_runner.cleanup_range_state(request_id)
    finally:
        if terraform_succeeded:
            _post_destroy_cleanup(request_id, range_id, user_id)
        _maybe_pause_user_ngfw(user_id, range_id)

    publish_destroyed(request_id=request_id, range_id=range_id, user_id=user_id)


def _resolve_tf_os_type(role: str, os_type: str) -> str:
    """Map spec role + os_type to the terraform module's os_type enum."""
    if role == "dc":
        return "windows"
    if role == "attacker" or os_type == "kali":
        return "kali"
    if os_type == "windows":
        return "windows"
    return "ubuntu"


def _resolve_instance_type(role: str, tf_os_type: str, override: str | None) -> str:
    """Pick the EC2 instance type: per-instance override wins; otherwise role/OS defaults.

    Per-instance override exists for cases like POLARIS where one specific
    instance (the polaris VM hosting 17 docker containers including a Kali GUI)
    needs a much bigger box than the global KALI_INSTANCE_TYPE default.
    """
    if override:
        return override
    if role == "attacker":
        return _get_kali_instance_type()
    if role == "dc":
        return _get_dc_instance_type()
    if tf_os_type == "windows":
        return _get_windows_instance_type()
    return _get_victim_instance_type()


def _resolve_agent_presigned_url(inst: dict) -> str:
    """Generate a presigned URL for the instance's XDR agent S3 object, if any."""
    agent_data = inst.get("agent") or {}
    agent_s3_key = agent_data.get("s3_key")
    if not agent_s3_key:
        return ""
    return generate_presigned_url(
        bucket=os.environ.get("AGENT_STORAGE_BUCKET") or os.environ.get("AGENT_S3_BUCKET", ""),
        key=agent_s3_key,
    )


def _build_tf_instance(inst: dict) -> dict:
    """Map one spec instance into the dict shape the terraform module expects."""
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
        "ami_id": get_ami_id(ami_key) if ami_key else "",
    }


def _build_tf_subnets(spec_subnets: list[dict]) -> list[dict]:
    """Translate spec subnets+instances into the terraform module's nested format."""
    return [
        {
            "name": subnet.get("name", ""),
            "uuid": subnet.get("uuid", ""),
            "cidr": subnet.get("cidr", ""),  # Pre-allocated CIDR.
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
    ngfw_data = get_user_ngfw_data(user_id)
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


def _build_aws_extra_tf_variables() -> dict:
    """AWS-only Terraform variables: per-OS AMI IDs + instance profile + Secrets Manager CMK.

    `secrets_kms_key_arn` is AWS-only: it encrypts per-instance SSH-key secrets
    stored in AWS Secrets Manager (CKV_AWS_149 / #213). The GCP range path uses
    GDC VM Runtime + GCP Secret Manager and does not consume this variable, so
    it lives in this AWS-only block rather than the provider-neutral payload.
    """
    return {
        "kali_ami_id": get_ami_id("kali"),
        "victim_ami_id": get_ami_id("victim"),
        "windows_ami_id": get_ami_id("windows"),
        "dc_ami_id": get_ami_id("dc"),
        "instance_profile_name": os.environ.get("RANGE_INSTANCE_PROFILE_NAME", ""),
        "secrets_kms_key_arn": os.environ["SECRETS_KMS_KEY_ARN"],
    }


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
    tf_subnets = _build_tf_subnets(range_spec.get("subnets", []))

    ngfw_data_eni_id = ""
    ngfw_attachment: dict[str, Any] | None = None
    if range_spec.get("ngfw", False):
        ngfw_data_eni_id, ngfw_attachment = _resolve_ngfw_for_range(user_id, range_id)

    range_network = load_range_network_config()
    variables = {
        "range_id": range_id,
        "user_id": user_id,
        "request_uuid": request_id,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "vpc_id": range_network.network_id,
        "vpc_cidr": range_network.network_cidr,
        "availability_zone": get_range_availability_zone(),
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


def _validate_ngfw_operation(operation: str) -> tuple[str, str]:
    status_map = {
        "start": ("resuming", "ready"),
        "stop": ("pausing", "paused"),
    }
    if operation not in status_map:
        raise ValueError(f"Unknown operation: {operation}")
    return status_map[operation]


def _publish_ngfw_runtime_status(request_id: str, instance_uuid: str, app_id: str, status: str) -> None:
    update_instance_state(request_id, status)
    publish_ngfw_event(
        request_id=request_id,
        instance_id=instance_uuid,
        app_id=app_id,
        status=status,
    )


def _run_gcp_ngfw_operation(
    operation: str,
    request_id: str,
    instance_uuid: str,
    app_id: str,
    state: dict[str, Any],
) -> None:
    import gdc_vmseries_ngfw

    in_progress_status, success_status = _validate_ngfw_operation(operation)
    _publish_ngfw_runtime_status(request_id, instance_uuid, app_id, in_progress_status)
    try:
        gdc_vmseries_ngfw.run_power_operation(operation, state)
    except Exception as e:
        logger.error("GDC VM-Series NGFW operation failed: %s", e)
        update_instance_state(request_id, STATUS_FAILED, error_message=str(e))
        publish_ngfw_event(
            request_id=request_id,
            instance_id=instance_uuid,
            app_id=app_id,
            status=STATUS_FAILED,
        )
        raise
    _publish_ngfw_runtime_status(request_id, instance_uuid, app_id, success_status)


def _load_ngfw_ops_plan(operation: str):
    import importlib

    plan_map = {
        "start": "plans.ngfw_start.NGFWStartPlan",
        "stop": "plans.ngfw_stop.NGFWStopPlan",
    }
    module_path, class_name = plan_map[operation].rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def _run_aws_ngfw_operation(
    operation: str,
    request_id: str,
    instance_uuid: str,
    app_id: str,
    ec2_instance_id: str,
    **kwargs: str,
) -> None:
    in_progress_status, success_status = _validate_ngfw_operation(operation)
    _publish_ngfw_runtime_status(request_id, instance_uuid, app_id, in_progress_status)

    try:
        executor = AWSExecutor()
        orchestrator = OpsOrchestrator(executor)
        plan = _load_ngfw_ops_plan(operation)
        context = {"instance_id": ec2_instance_id, **kwargs}
        result = orchestrator.orchestrate(ec2_instance_id, plan, context)
        if not result.success:
            for step_result in result.step_results:
                if not step_result.success:
                    logger.error(
                        "NGFW %s step %s failed: %s",
                        operation,
                        step_result.step_name,
                        step_result.stderr,
                    )
            raise RuntimeError(f"Operation {operation} failed")
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

    _publish_ngfw_runtime_status(request_id, instance_uuid, app_id, success_status)


def run_ngfw_operation(operation: str, request_id: str, **kwargs: str) -> None:
    """Run NGFW runtime operation (start/stop).

    Retrieves EC2 instance ID from the Instance.state (populated during
    provisioning), executes the operation plan, and publishes events for status
    updates.

    Args:
        operation: Operation name (start, stop).
        request_id: UUID string of the Request.
        **kwargs: Operation-specific parameters (overrides for context).

    Raises:
        ValueError: If unknown operation or EC2 instance ID not found.
        Exception: If operation fails.
    """
    logger.info("run_ngfw_operation: starting operation=%s request_id=%s", operation, request_id)
    if kwargs:
        logger.debug("run_ngfw_operation: kwargs=%s", list(kwargs.keys()))

    _validate_ngfw_operation(operation)

    # Get NGFW data from database including state with EC2 instance ID
    ngfw_data = get_ngfw_data_by_request_id(request_id)
    instance_uuid = ngfw_data["instance_id"]  # Our UUID, not AWS instance ID
    app_id = ngfw_data["app_id"]
    state = ngfw_data.get("state", {})
    provider = resolve_ngfw_attachment_config(state).cloud_provider

    if provider != "aws":
        if provider != "gcp":
            raise RuntimeError(
                f"NGFW runtime operation {operation!r} is not implemented for cloud_provider={provider!r}"
            )
        _run_gcp_ngfw_operation(operation, request_id, instance_uuid, app_id, state)
        return

    # EC2 instance ID is stored in state after Terraform provisioning
    ec2_instance_id = state.get("ec2_instance_id")
    if not ec2_instance_id:
        raise ValueError(f"EC2 instance ID not found in state for request: {request_id}")
    _run_aws_ngfw_operation(operation, request_id, instance_uuid, app_id, ec2_instance_id, **kwargs)


if __name__ == "__main__":
    from logging_config import configure_logging

    configure_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Shifter Engine for provisioning cyber ranges and NGFW operations")
    subparsers = parser.add_subparsers(dest="resource", required=True, help="Resource type")

    # Range operations - use request_id (UUID) like NGFW pattern
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

    # NGFW operations
    ngfw_parser = subparsers.add_parser("ngfw", help="NGFW runtime operations")
    ngfw_parser.add_argument(
        "operation",
        choices=[
            "provision",
            "deprovision",
            "start",
            "stop",
        ],
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

    # Handle resource-based dispatch
    if args.resource == "ngfw":
        logger.info("Starting NGFW %s for request_id=%s", args.operation, args.request_id)
        logger.info("Environment: %s", os.environ.get("ENVIRONMENT", "unknown"))

        # Infrastructure operations use Terraform, runtime operations use boto3
        if args.operation in ("provision", "deprovision"):
            tf_op = "up" if args.operation == "provision" else "destroy"
            run_ngfw_terraform(tf_op, args.request_id)
        else:
            # Runtime operations (start, stop)
            kwargs = {}
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
            # Use Terraform for ranges
            run_range_terraform(tf_op, request_id)
        elif args.operation == "pause":
            from range_ops import run_range_pause

            run_range_pause(request_id)
        elif args.operation == "resume":
            from range_ops import run_range_resume

            run_range_resume(request_id)

        logger.info("Completed range %s for request_id=%s", args.operation, request_id)

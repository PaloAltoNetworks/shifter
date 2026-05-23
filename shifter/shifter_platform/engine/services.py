"""Engine service interface.

Infrastructure lifecycle for Shifter platform.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

from engine.secrets import SecretsError, get_rdp_password, get_ssh_key
from shared.enums import CANCELLABLE_STATUSES, ResourceStatus
from shared.schemas import InstanceSpec, RangeContext, RangeSpec, RequestSpec

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.ssh import SSHConnection

logger = logging.getLogger(__name__)


class EngineError(Exception):
    """Base exception for engine service errors."""

    pass


def _first_connection_value(*values: object) -> str:
    """Return the first non-empty connection value as a normalized string."""
    for value in values:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
        elif value not in (None, ""):
            return str(value)
    return ""


def _get_instance_provider_metadata(instance: dict[str, Any]) -> dict[str, Any]:
    """Return the provider-specific metadata block for an instance payload."""
    provider_metadata = instance.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    provider = _first_connection_value(instance.get("cloud_provider")).lower()
    if provider:
        metadata = provider_metadata.get(provider)
        if isinstance(metadata, dict):
            return metadata

    for provider_name in ("gcp", "gdc", "aws"):
        metadata = provider_metadata.get(provider_name)
        if isinstance(metadata, dict):
            return metadata

    return {}


def _resolve_instance_host(instance: dict[str, Any]) -> str:
    """Resolve the best internal host/IP for guest connectivity."""
    provider_metadata = _get_instance_provider_metadata(instance)
    return _first_connection_value(
        instance.get("host"),
        instance.get("private_ip"),
        instance.get("privateIp"),
        instance.get("internal_ip"),
        instance.get("internalIp"),
        provider_metadata.get("private_ip"),
        provider_metadata.get("privateIp"),
        provider_metadata.get("network_ip"),
        provider_metadata.get("internal_ip"),
        provider_metadata.get("internalIp"),
        provider_metadata.get("guest_ip"),
        provider_metadata.get("vm_ip"),
        provider_metadata.get("ip"),
    )


def _resolve_instance_ssh_key_secret_ref(instance: dict[str, Any]) -> str:
    """Resolve the active secret reference for the instance SSH key."""
    provider_metadata = _get_instance_provider_metadata(instance)
    return _first_connection_value(
        instance.get("ssh_key_secret_arn"),
        instance.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_key_secret_arn"),
        provider_metadata.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_secret_ref"),
        provider_metadata.get("ssh_secret_id"),
    )


def _resolve_instance_rdp_password_secret_ref(instance: dict[str, Any]) -> str:
    """Resolve the active secret reference for the per-instance RDP password.

    Mirrors ``_resolve_instance_ssh_key_secret_ref`` so the per-instance
    credential reference can live either at the top of the instance
    payload (AWS engine state, parallel to ``ssh_key_secret_arn``) or
    nested under the provider-specific metadata block (GDC VM Runtime
    payloads under ``provider_metadata.gdc``).
    """
    provider_metadata = _get_instance_provider_metadata(instance)
    return _first_connection_value(
        instance.get("rdp_password_secret_arn"),
        instance.get("rdp_password_secret_id"),
        instance.get("rdp_password_secret_ref"),
        provider_metadata.get("rdp_password_secret_arn"),
        provider_metadata.get("rdp_password_secret_id"),
        provider_metadata.get("rdp_password_secret_ref"),
    )


def _resolve_instance_connection_name(instance: dict[str, Any]) -> str:
    """Resolve a stable display name for RDP/SSH Guacamole connections."""
    provider_metadata = _get_instance_provider_metadata(instance)
    resolved_name = _first_connection_value(
        instance.get("name"),
        provider_metadata.get("instance_name"),
        provider_metadata.get("vm_name"),
        provider_metadata.get("name"),
    )
    if resolved_name:
        return resolved_name

    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    role = _first_connection_value(instance.get("role"), "instance").lower()
    display_role = "target" if role == "victim" else role
    return f"{display_role}-{os_type or 'instance'}"


def _resolve_instance_ssh_username(instance: dict[str, Any]) -> str:
    """Resolve the guest SSH username for terminal and Guacamole access."""
    provider_metadata = _get_instance_provider_metadata(instance)
    explicit_username = _first_connection_value(
        instance.get("ssh_username"),
        instance.get("ssh_user"),
        provider_metadata.get("ssh_username"),
        provider_metadata.get("ssh_user"),
        provider_metadata.get("username"),
    )
    if explicit_username:
        return explicit_username

    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    if os_type == "kali":
        return "kali"
    if os_type == "amazon-linux":
        return "ec2-user"
    if os_type == "windows":
        return "Administrator"
    return "ubuntu"


def _resolve_dc_password(instance: dict[str, Any]) -> str | None:
    """Return the DC Administrator password for a Windows DC instance.

    ``DC_DOMAIN_PASSWORD`` is the env-var contract shared with the engine
    provisioner (``shifter/engine/provisioner/main.py`` for AWS,
    ``shifter/engine/provisioner/gdc_vmruntime_assets.py`` for GCP), so
    the portal reads the same env-var. The credential is deployment-scoped:
    the portal's own ``CLOUD_PROVIDER`` env identifies which provider's DC
    password lives in ``DC_DOMAIN_PASSWORD``. Returning that value for an
    instance from a different provider would leak the portal-deployment
    provider's credential to the requesting provider's user — refuse with
    ``None`` instead.

    An empty ``cloud_provider`` (older payloads) is treated as ``"aws"``,
    matching the default elsewhere in the engine state handling.

    Per ADR-004-R7 and the architecture preflight for #762, treating the
    DC domain Administrator credential as the local desktop RDP credential
    is intentional only for the DC host itself; non-DC guests use
    per-instance secret references.
    """
    instance_provider = _first_connection_value(instance.get("cloud_provider")).lower() or "aws"
    portal_provider = os.environ.get("CLOUD_PROVIDER", "aws").lower()
    if instance_provider != portal_provider:
        return None
    return os.environ.get("DC_DOMAIN_PASSWORD")


def _resolve_non_dc_rdp_password(instance: dict[str, Any]) -> str | None:
    """Resolve a non-DC guest RDP password from the per-instance secret store.

    Returns ``None`` when no secret reference is recorded for the
    instance. ``get_rdp_connection_info`` converts ``None`` into an
    explicit ``ValueError`` so the portal fails closed instead of
    minting a Guacamole RDP URL with a missing or empty password.

    Provider fetch failures (deleted secret version, IAM regression,
    transient cloud error) raise ``ValueError`` rather than letting a
    ``SecretsError`` escape: the mission_control RDP view's error
    envelope only converts ``ValueError`` into a non-sensitive 400, so
    re-raising here keeps the user-facing failure shape identical to
    "no reference recorded" instead of bubbling up as an unhandled 500.
    The operational details (secret reference, provider error chain)
    stay in the warning log, never in the response.
    """
    secret_ref = _resolve_instance_rdp_password_secret_ref(instance)
    if not secret_ref:
        return None
    try:
        return get_rdp_password(secret_ref)
    except SecretsError:
        logger.warning(
            "Failed to fetch per-instance RDP password (instance_uuid=%s); treating as credentials-unavailable",
            instance.get("uuid"),
            exc_info=True,
        )
        raise ValueError(
            "RDP credentials are not available for this instance; the credential store "
            "did not return a value for the recorded secret reference"
        ) from None


def _resolve_rdp_credentials(instance: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolve the RDP username/password pair for a provisioned guest.

    Per-instance credentials (per #762): non-DC guests use a per-instance
    secret reference resolved through the active provider secret store.
    No shared literal fallbacks. The DC role keeps the deployment-scoped
    ``DC_DOMAIN_PASSWORD`` lookup (separate concern — domain admin).
    """
    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    role = _first_connection_value(instance.get("role"), "instance").lower()

    if os_type == "windows":
        if role == "dc":
            return ("Administrator", _resolve_dc_password(instance))
        return ("Administrator", _resolve_non_dc_rdp_password(instance))

    if os_type == "kali":
        return ("kali", _resolve_non_dc_rdp_password(instance))
    if os_type == "ubuntu":
        return ("ubuntu", _resolve_non_dc_rdp_password(instance))
    return None, None


def _get_ngfw_provider_metadata(state: dict[str, Any]) -> dict[str, Any]:
    """Return the provider-specific metadata block for an NGFW state payload."""
    provider_metadata = state.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    provider = _first_connection_value(state.get("cloud_provider")).lower()
    if provider:
        metadata = provider_metadata.get(provider)
        if isinstance(metadata, dict):
            return metadata

    for provider_name in ("gcp", "gdc", "aws"):
        metadata = provider_metadata.get(provider_name)
        if isinstance(metadata, dict):
            return metadata

    return {}


def _resolve_ngfw_management_ip(state: dict[str, Any]) -> str:
    """Resolve the best management IP for an NGFW state payload."""
    provider_metadata = _get_ngfw_provider_metadata(state)
    return _first_connection_value(
        state.get("management_ip"),
        provider_metadata.get("management_ip"),
    )


def _resolve_ngfw_ssh_key_secret_ref(state: dict[str, Any]) -> str:
    """Resolve the SSH key secret reference for NGFW terminal access."""
    provider_metadata = _get_ngfw_provider_metadata(state)
    return _first_connection_value(
        state.get("ssh_key_secret_arn"),
        state.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_key_secret_arn"),
        provider_metadata.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_secret_ref"),
        provider_metadata.get("ssh_secret_id"),
    )


def create_range(request_spec: RequestSpec) -> UUID:
    """Provision infrastructure for range.

    Interprets the RequestSpec into Engine models (Request, Instance),
    creates a Range record for backward compat, and triggers ECS provisioning.

    Args:
        request_spec: RequestSpec containing a RangeSpec item.
            The RangeSpec must have scenario_id, user_id, and instances.

    Returns:
        The request_id UUID for correlation with CMS.

    Raises:
        TypeError: If request_spec is not a RequestSpec.
        ValueError: If request_spec doesn't contain a RangeSpec,
            or subnet allocation fails (capacity exhausted).
        User.DoesNotExist: If user_id doesn't map to a Django user.
        EngineError: If no subnets were linked (invalid scenario template).
    """
    from django.contrib.auth import get_user_model

    from engine.ecs import start_range_provisioning
    from engine.interpreter import interpret
    from engine.models import Range

    User = get_user_model()

    # Validate request type
    if not isinstance(request_spec, RequestSpec):
        raise TypeError(f"request_spec must be RequestSpec, got {type(request_spec).__name__}")

    # Extract RangeSpec from items
    range_spec: RangeSpec | None = None
    for item in request_spec.items:
        if isinstance(item, RangeSpec):
            range_spec = item
            break

    if range_spec is None:
        raise ValueError("RequestSpec must contain a RangeSpec item")

    logger.debug(
        "create_range: scenario=%s user_id=%s subnets=%d instances=%d",
        range_spec.scenario_id,
        range_spec.user_id,
        len(range_spec.subnets),
        len(range_spec.all_instances),
    )

    # All DB operations in a single transaction - if anything fails, rollback everything
    with transaction.atomic():
        # Interpret spec into models (creates Request + Instances + Subnets)
        # interpret() has its own transaction.atomic() which becomes a savepoint here
        request = interpret(request_spec)

        logger.info(
            "create_range: interpreted request_id=%s",
            request_spec.request_id,
        )

        # Get Django user for FK (required for auth)
        user = User.objects.get(id=range_spec.user_id)

        # Allocate subnet index
        subnet_index = Range.allocate_subnet_index()

        # Create Range model for backward compat with provisioner
        # Links to Request via FK
        # Parse UUID from RangeSpec (assigned during hydration)
        range_uuid = range_spec.uuid
        if range_uuid:
            import uuid as uuid_module

            range_obj = Range.objects.create(
                uuid=uuid_module.UUID(range_uuid),
                user=user,
                request=request,
                cms_user_id=range_spec.user_id,
                status=Range.Status.PROVISIONING,
                subnet_index=subnet_index,
                range_config=range_spec.model_dump(),
            )
        else:
            # Fallback for old specs without UUID (auto-generated by model)
            range_obj = Range.objects.create(
                user=user,
                request=request,
                cms_user_id=range_spec.user_id,
                status=Range.Status.PROVISIONING,
                subnet_index=subnet_index,
                range_config=range_spec.model_dump(),
            )

        logger.info(
            "create_range: created range_id=%s uuid=%s subnet_index=%s request_id=%s",
            range_obj.id,
            range_obj.uuid,
            subnet_index,
            request_spec.request_id,
        )

        # Link logical subnets to Range (created by interpreter, need Range FK)
        from engine.models import Subnet

        subnet_count = Subnet.objects.filter(request=request).update(range=range_obj)

        # Validate subnets were linked - if 0, the range is in undefined state
        if subnet_count == 0:
            raise EngineError(
                f"No subnets linked to range {range_obj.id} for request {request_spec.request_id}. "
                "This indicates the scenario template is missing subnet definitions."
            )

        logger.info(
            "create_range: linked %d subnets to range_id=%s",
            subnet_count,
            range_obj.id,
        )

    # Transaction committed - safe to trigger external systems
    # Trigger ECS provisioning using request_id (matches NGFW pattern)
    task_arn = start_range_provisioning(request_spec.request_id)

    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])
        logger.info("create_range: started ECS task=%s", task_arn)

    return request_spec.request_id


def destroy_range(request: RangeContext) -> bool:
    """Tear down range infrastructure.

    Sets status to DESTROYING and triggers async ECS teardown.
    Idempotent: returns True if range is already being destroyed.

    Supports both legacy (range_id) and new (request_id) patterns.
    When range_id is None but request_id is provided, delegates to
    destroy_range_by_request().

    Args:
        request: RangeContext with range_id or request_id and metadata.

    Returns:
        True if range exists and destruction initiated (or already in progress).
        False if range not found, already destroyed, or both IDs are None.
    """
    from engine.ecs import start_teardown
    from engine.models import Range

    # Try request_id first (new pattern) when range_id is None
    if request.range_id is None:
        if request.request_id:
            return destroy_range_by_request(request.request_id)
        logger.warning("destroy_range: both range_id and request_id are None")
        return False

    logger.debug("destroy_range: range_id=%s", request.range_id)

    try:
        range_obj = Range.objects.get(id=request.range_id)
    except Range.DoesNotExist:
        logger.warning("destroy_range: range not found range_id=%s", request.range_id)
        return False

    # Already destroyed - nothing to do
    if range_obj.status == ResourceStatus.DESTROYED:
        logger.warning("destroy_range: range already destroyed range_id=%s", request.range_id)
        return False

    # Already destroying - idempotent success
    if range_obj.status == ResourceStatus.DESTROYING:
        logger.info("destroy_range: range already destroying range_id=%s", request.range_id)
        return True

    # Set status and trigger teardown
    range_obj.status = ResourceStatus.DESTROYING.value
    range_obj.save(update_fields=["status"])

    logger.info("destroy_range: set status to DESTROYING range_id=%s", request.range_id)

    task_arn = start_teardown(request.range_id, request.user_id)

    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])
        logger.info("destroy_range: started ECS task=%s", task_arn)

    return True


def cancel_range(range_ctx: RangeContext) -> None:
    """Cancel in-progress provisioning.

    Only works for ranges in PENDING or PROVISIONING status.
    Sets status directly to DESTROYING without triggering teardown.

    Supports both legacy (range_id) and new (request_id) patterns.
    When range_id is None but request_id is provided, delegates to
    cancel_range_by_request().

    Note: This does NOT clean up any AWS resources that may have been
    partially created. A proper implementation would signal the provisioner
    to abort and clean up. See GitHub issue for tracking.

    Args:
        range_ctx: RangeContext with range_id or request_id and metadata.

    Returns:
        None

    Raises:
        TypeError: If range_ctx is None or not a RangeContext.
        ValueError: If both range_id and request_id are None, or range_id is invalid.
    """
    # Input validation
    if range_ctx is None:
        logger.error("cancel_range called with None range_ctx")
        raise TypeError("range_ctx cannot be None")

    if not isinstance(range_ctx, RangeContext):
        logger.error(
            "cancel_range called with invalid type: %s",
            type(range_ctx).__name__,
        )
        raise TypeError(f"range_ctx must be RangeContext, got {type(range_ctx).__name__}")

    # Try request_id first (new pattern) when range_id is None
    if range_ctx.range_id is None:
        if range_ctx.request_id:
            cancel_range_by_request(range_ctx.request_id)
            return
        logger.error("cancel_range called with both range_id and request_id as None")
        raise ValueError("range_ctx must have either range_id or request_id")

    if not isinstance(range_ctx.range_id, int) or range_ctx.range_id < 0:
        logger.error(
            "cancel_range called with invalid range_id: %s",
            range_ctx.range_id,
        )
        raise ValueError("range_ctx.range_id must be a non-negative integer")

    logger.debug(
        "cancel_range: range_id=%s user_id=%s status=%s",
        range_ctx.range_id,
        range_ctx.user_id,
        range_ctx.status,
    )
    from engine.models import Range

    range_id = range_ctx.range_id

    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("cancel_range: range not found range_id=%s", range_id)
        return

    if range_ctx.status not in CANCELLABLE_STATUSES:
        logger.warning(
            "cancel_range: range not cancellable range_id=%s status=%s",
            range_id,
            range_ctx.status,
        )
        return

    range_ctx.status = ResourceStatus.DESTROYING
    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])

    # Provisioner will poll for status and destroy when it sees DESTROYING
    # accept small risk of race condition. TODO: #465

    logger.info("cancel_range: cancelled range_id=%s", range_id)


# =============================================================================
# Request-based Range Functions (new pattern matching NGFW)
# =============================================================================


def destroy_range_by_request(request_id: UUID) -> bool:
    """Tear down range infrastructure by request_id.

    Follows same pattern as destroy_ngfw(). Looks up Range via Request FK
    and triggers ECS teardown.

    Args:
        request_id: UUID of the request containing the Range.

    Returns:
        True if teardown initiated or already in progress.
        False if not found or already destroyed.
    """
    from engine.ecs import start_range_teardown
    from engine.models import Range

    logger.debug("destroy_range_by_request: request_id=%s", request_id)

    range_obj = Range.objects.filter(request__request_id=request_id).first()
    if not range_obj:
        logger.warning("destroy_range_by_request: no range for request_id=%s", request_id)
        return False

    # Already destroyed - nothing to do
    if range_obj.status == ResourceStatus.DESTROYED.value:
        logger.warning(
            "destroy_range_by_request: already destroyed request_id=%s",
            request_id,
        )
        return False

    # Already destroying - idempotent success
    if range_obj.status == ResourceStatus.DESTROYING.value:
        logger.info(
            "destroy_range_by_request: already destroying request_id=%s",
            request_id,
        )
        return True

    # Set status and trigger teardown
    range_obj.status = ResourceStatus.DESTROYING.value
    range_obj.save(update_fields=["status"])

    logger.info(
        "destroy_range_by_request: set DESTROYING request_id=%s range_id=%s",
        request_id,
        range_obj.id,
    )

    task_arn = start_range_teardown(request_id)

    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])
        logger.info("destroy_range_by_request: started ECS task=%s", task_arn)

    return True


def cancel_range_by_request(request_id: UUID) -> bool:
    """Cancel in-progress range provisioning by request_id.

    Only works for ranges in PENDING or PROVISIONING status.

    Args:
        request_id: UUID of the request containing the Range.

    Returns:
        True if cancelled, False if not found or not cancellable.
    """
    from engine.models import Range

    logger.debug("cancel_range_by_request: request_id=%s", request_id)

    range_obj = Range.objects.filter(request__request_id=request_id).first()
    if not range_obj:
        logger.warning("cancel_range_by_request: no range for request_id=%s", request_id)
        return False

    if range_obj.status not in (Range.Status.PENDING, Range.Status.PROVISIONING):
        logger.warning(
            "cancel_range_by_request: not cancellable status=%s request_id=%s",
            range_obj.status,
            request_id,
        )
        return False

    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])

    logger.info(
        "cancel_range_by_request: cancelled request_id=%s range_id=%s",
        request_id,
        range_obj.id,
    )

    return True


def get_instance_ips_by_uuid(range_id: int) -> dict[str, str]:
    """Return a {uuid: internal_ip} map for the range's provisioned instances.

    Looks up the range via ``get_range_status`` and resolves each instance's
    best internal host/IP using the same priority as
    ``_resolve_instance_host``. Instances without a usable ``uuid`` or a
    resolvable host are dropped silently — the caller treats the missing
    entry as "no IP known yet" and degrades gracefully.

    Args:
        range_id: Engine range identifier (matches ``Range.id`` /
            ``RangeInstance.range_id``). Callers without a ``range_id`` (for
            example, a request that has not yet been picked up by the
            provisioner) should not invoke this — return an empty map.

    Returns:
        ``{uuid: ip}`` for instances that have both. Empty dict when the
        range is missing, has no provisioned state, or no instance has both
        a uuid and a resolvable IP.
    """
    status = get_range_status(range_id)
    if not status:
        return {}

    result: dict[str, str] = {}
    for instance in status.get("instances") or []:
        if not isinstance(instance, dict):
            continue
        uuid_value = instance.get("uuid")
        if not isinstance(uuid_value, str) or not uuid_value.strip():
            continue
        ip_value = _resolve_instance_host(instance)
        if not ip_value:
            continue
        result[uuid_value.strip()] = ip_value
    return result


def get_range_status(range_id: int) -> dict[str, Any] | None:
    """Get current state and instance details.

    Args:
        range_id: The ID of the range.

    Returns:
        Dict with range status info, or None if not found.
        Keys: status, error_message, instances, created_at, ready_at
    """
    from engine.models import Range

    logger.debug("get_range_status: range_id=%s", range_id)

    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("get_range_status: range not found range_id=%s", range_id)
        return None

    return {
        "status": range_obj.status,
        "error_message": range_obj.error_message,
        "instances": range_obj.provisioned_instances or [],
        "created_at": (range_obj.created_at.isoformat() if range_obj.created_at else None),
        "ready_at": range_obj.ready_at.isoformat() if range_obj.ready_at else None,
    }


def pause_range(request_id: UUID) -> bool:
    """Pause all instances in a range.

    Stops all EC2 instances belonging to the range. Idempotent - returns
    True if already paused. Uses select_for_update to prevent race conditions
    from concurrent pause/resume calls.

    Args:
        request_id: UUID of the Request containing the Range.

    Returns:
        True if pause initiated or already paused.
        False if range not found, not in pausable state, or ECS call failed.
    """
    from engine.ecs import start_range_operation
    from engine.models import Range
    from shared.cloud.exceptions import CloudTaskError

    logger.debug("pause_range: request_id=%s", request_id)

    with transaction.atomic():
        range_obj = Range.objects.select_for_update().filter(request__request_id=request_id).first()
        if not range_obj:
            logger.warning("pause_range: no range for request_id=%s", request_id)
            return False

        # Idempotent: already paused or pausing
        if range_obj.status in (ResourceStatus.PAUSED.value, ResourceStatus.PAUSING.value):
            logger.info("pause_range: already paused/pausing request_id=%s", request_id)
            return True

        # Can only pause from READY state
        if range_obj.status != ResourceStatus.READY.value:
            logger.warning(
                "pause_range: cannot pause range in status=%s request_id=%s",
                range_obj.status,
                request_id,
            )
            return False

        # Update status to PAUSING
        range_obj.status = ResourceStatus.PAUSING.value
        range_obj.save(update_fields=["status", "updated_at"])

    # Invoke ECS task outside the atomic block (don't hold DB lock during network call)
    try:
        task_arn = start_range_operation(request_id, "pause")
    except CloudTaskError:
        logger.exception("pause_range: ECS CloudTaskError request_id=%s", request_id)
        range_obj.status = ResourceStatus.READY.value
        range_obj.save(update_fields=["status", "updated_at"])
        return False

    if task_arn:
        logger.info("pause_range: started ECS task=%s request_id=%s", task_arn, request_id)
        return True
    else:
        logger.warning("pause_range: ECS returned None, reverting status request_id=%s", request_id)
        range_obj.status = ResourceStatus.READY.value
        range_obj.save(update_fields=["status", "updated_at"])
        return False


def resume_range(request_id: UUID) -> bool:
    """Resume all instances in a range.

    Starts all EC2 instances belonging to the range. Idempotent - returns
    True if already ready. Uses select_for_update to prevent race conditions
    from concurrent pause/resume calls.

    Args:
        request_id: UUID of the Request containing the Range.

    Returns:
        True if resume initiated or already ready.
        False if range not found, not in resumable state, or ECS call failed.
    """
    from engine.ecs import start_range_operation
    from engine.models import Range
    from shared.cloud.exceptions import CloudTaskError

    logger.debug("resume_range: request_id=%s", request_id)

    with transaction.atomic():
        range_obj = Range.objects.select_for_update().filter(request__request_id=request_id).first()
        if not range_obj:
            logger.warning("resume_range: no range for request_id=%s", request_id)
            return False

        # Idempotent: already ready or resuming
        if range_obj.status in (ResourceStatus.READY.value, ResourceStatus.RESUMING.value):
            logger.info("resume_range: already ready/resuming request_id=%s", request_id)
            return True

        # Can only resume from PAUSED state
        if range_obj.status != ResourceStatus.PAUSED.value:
            logger.warning(
                "resume_range: cannot resume range in status=%s request_id=%s",
                range_obj.status,
                request_id,
            )
            return False

        # Update status to RESUMING
        range_obj.status = ResourceStatus.RESUMING.value
        range_obj.save(update_fields=["status", "updated_at"])

    # Invoke ECS task outside the atomic block (don't hold DB lock during network call)
    try:
        task_arn = start_range_operation(request_id, "resume")
    except CloudTaskError:
        logger.exception("resume_range: ECS CloudTaskError request_id=%s", request_id)
        range_obj.status = ResourceStatus.PAUSED.value
        range_obj.save(update_fields=["status", "updated_at"])
        return False

    if task_arn:
        logger.info("resume_range: started ECS task=%s request_id=%s", task_arn, request_id)
        return True
    else:
        logger.warning("resume_range: ECS returned None, reverting status request_id=%s", request_id)
        range_obj.status = ResourceStatus.PAUSED.value
        range_obj.save(update_fields=["status", "updated_at"])
        return False


def _require_rdp_password(instance: dict[str, Any], os_type: str, rdp_password: str | None) -> None:
    """Fail loud when a range guest has no RDP password.

    Minting a Guacamole RDP URL with an empty password would either fail
    silently or produce an unusable session; mission_control's RDP view
    maps ``ValueError`` -> HTTP 400 so the operator sees the specific
    reason rather than a silent broken connection.

    Non-DC guests use a per-instance secret reference (#762) — the
    resolver returns ``None`` when no reference is recorded. The DC
    role keeps the deployment-scoped ``DC_DOMAIN_PASSWORD`` lookup
    (separate concern); a request for a DC on a different provider than
    the portal's own deployment is rejected rather than handed the wrong
    credential.
    """
    if rdp_password:
        return

    role = _first_connection_value(instance.get("role"), "instance").lower()
    if os_type == "windows" and role == "dc":
        provider_label = _first_connection_value(instance.get("cloud_provider")).lower() or "aws"
        portal_provider = os.environ.get("CLOUD_PROVIDER", "aws").lower()
        if provider_label != portal_provider:
            raise ValueError(
                f"DC password unavailable: instance provider {provider_label!r} "
                f"does not match portal deployment provider {portal_provider!r}; "
                f"DC_DOMAIN_PASSWORD is scoped to the portal's own provider"
            )
        raise ValueError(
            "DC_DOMAIN_PASSWORD is not configured; seed the DC domain password secret and restart the portal"
        )

    raise ValueError(
        "RDP credentials are not available for this instance; the provisioner did not "
        "record a per-instance password secret reference"
    )


def _fetch_sftp_ssh_key(instance: dict[str, Any], os_type: str) -> str | None:
    """SSH key used for SFTP file transfers to a Windows instance.

    Windows uses key-based auth; Linux instances use password auth, so this
    returns ``None`` for them. A lookup failure is logged and swallowed —
    SFTP is best-effort and must not block the RDP session.
    """
    if os_type != "windows":
        return None
    ssh_key_ref = _resolve_instance_ssh_key_secret_ref(instance)
    if not ssh_key_ref:
        return None

    try:
        return get_ssh_key(ssh_key_ref)
    except SecretsError as e:
        logger.warning("Failed to get SSH key for SFTP: %s", e)
        return None


def get_rdp_connection_info(user: User, instance_uuid: str) -> dict[str, Any]:
    """Get connection info for RDP access to a range instance.

    Args:
        user: Authenticated user requesting connection
        instance_uuid: UUID of the instance to connect to

    Returns:
        Dict with keys: private_ip, os_type, connection_name

    Raises:
        ValueError: If no active range, range not READY, instance not found,
            instance has no GUI, or a Windows DC has no RDP password
        PermissionError: If user doesn't own the range
    """
    from engine.models import Range

    if user is None:
        raise ValueError("user is required")
    if not instance_uuid:
        raise ValueError("instance_uuid is required")

    logger.debug("get_rdp_connection_info: user=%s instance_uuid=%s", user.id, instance_uuid)

    range_obj = Range.get_active_for_user(user)
    if not range_obj:
        raise ValueError("No active range found")
    if range_obj.status != Range.Status.READY:
        raise ValueError(f"Range is not ready (status: {range_obj.status})")

    instance = range_obj.get_instance_by_uuid(instance_uuid)
    if not instance:
        raise ValueError(f"Instance {instance_uuid} not found in range")

    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    if os_type not in ("kali", "ubuntu", "windows"):
        raise ValueError(f"RDP not available for {os_type} instances (no GUI)")

    host = _resolve_instance_host(instance)
    if not host:
        raise ValueError(f"Instance {instance_uuid} has no IP address")

    connection_name = _resolve_instance_connection_name(instance)
    rdp_username, rdp_password = _resolve_rdp_credentials(instance)
    _require_rdp_password(instance, os_type, rdp_password)

    return {
        "private_ip": host,
        "host": host,
        "os_type": os_type,
        "connection_name": connection_name,
        "rdp_username": rdp_username,
        "rdp_password": rdp_password,
        "ssh_key": _fetch_sftp_ssh_key(instance, os_type),
    }


def get_ssh_connection_info(user: User, instance_uuid: str) -> dict[str, Any]:
    """Get SSH connection details for a range instance.

    Looks up the Range containing the instance by searching provisioned_instances
    JSONB for matching UUID. This supports the new request_id-based provisioning
    pattern where range_id may not be populated in CMS.

    Args:
        user: Authenticated user requesting connection
        instance_uuid: UUID of the instance to connect to

    Returns:
        Dictionary with host, username, private_key, connection_name, and os_type.

    Raises:
        ValueError: If user is None, instance_uuid invalid,
            range not READY, or instance not found
        PermissionError: If user doesn't own the range
    """
    from engine.models import Range
    from engine.secrets import get_ssh_key

    if user is None:
        raise ValueError("user is required")
    if not instance_uuid:
        raise ValueError("instance_uuid is required")

    logger.debug("connect_terminal: user_id=%s instance_uuid=%s", user.id, instance_uuid)

    # Find Range containing this instance by searching provisioned_instances JSONB
    # PostgreSQL JSONB containment query: find where array contains object with uuid
    range_obj = Range.objects.filter(
        provisioned_instances__contains=[{"uuid": instance_uuid}],
        user=user,
    ).first()

    if not range_obj:
        logger.error(
            "Range not found for instance: user_id=%s instance_uuid=%s",
            user.id,
            instance_uuid,
        )
        raise ValueError(f"No range found containing instance {instance_uuid}")

    # Verify range is ready
    if range_obj.status != Range.Status.READY:
        logger.error(
            "Range not ready: range_id=%s status=%s",
            range_obj.id,
            range_obj.status,
        )
        raise ValueError(f"Range is not ready (status: {range_obj.status})")

    # Find instance by UUID
    instance = range_obj.get_instance_by_uuid(instance_uuid)
    if instance is None:
        logger.error(
            "Instance not found: range_id=%s instance_uuid=%s",
            range_obj.id,
            instance_uuid,
        )
        raise ValueError(f"Instance {instance_uuid} not found in range")
    ssh_key_ref = _resolve_instance_ssh_key_secret_ref(instance)
    if not ssh_key_ref:
        logger.error("No SSH key reference for instance: %s", instance_uuid)
        raise ValueError(f"Instance {instance_uuid} has no SSH key configured")

    ssh_key = get_ssh_key(ssh_key_ref)

    host = _resolve_instance_host(instance)
    if not host:
        logger.error("No IP address for instance: %s", instance_uuid)
        raise ValueError(f"Instance {instance_uuid} has no IP address")

    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    username = _resolve_instance_ssh_username(instance)

    return {
        "host": host,
        "port": 22,
        "username": username,
        "private_key": ssh_key,
        "connection_name": _resolve_instance_connection_name(instance),
        "os_type": os_type,
        "private_ip": host,
        "cloud_provider": _first_connection_value(instance.get("cloud_provider")).lower(),
    }


def connect_terminal(user: User, instance_uuid: str) -> SSHConnection:
    """Get SSH connection to instance.

    Looks up the Range containing the instance by searching provisioned_instances
    JSONB for matching UUID. This supports the new request_id-based provisioning
    pattern where range_id may not be populated in CMS.

    Args:
        user: Authenticated user requesting connection
        instance_uuid: UUID of the instance to connect to

    Returns:
        SSHConnection configured for the instance

    Raises:
        ValueError: If user is None, instance_uuid invalid,
            range not READY, or instance not found
        PermissionError: If user doesn't own the range
    """
    from engine.ssh import SSHConnection

    ssh_info = get_ssh_connection_info(user, instance_uuid)

    # Use tmux for persistent sessions on Linux instances
    # Windows doesn't have tmux, so skip session_id for Windows
    session_id = None
    if ssh_info["os_type"] != "windows":
        session_id = instance_uuid

    return SSHConnection(
        host=ssh_info["host"],
        username=ssh_info["username"],
        private_key=ssh_info["private_key"],
        port=ssh_info["port"],
        session_id=session_id,
    )


def connect_ngfw_terminal(user: User, ngfw_uuid: str) -> SSHConnection:
    """Get SSH connection to NGFW management interface.

    Validates user ownership via Instance → Request → User chain.
    Supports NGFWs in 'ready' status.

    Args:
        user: Authenticated user requesting connection
        ngfw_uuid: UUID of the NGFW instance to connect to

    Returns:
        SSHConnection configured for NGFW admin CLI

    Raises:
        ValueError: If user is None, ngfw_uuid invalid, NGFW not found,
            status invalid, or required state fields missing
        PermissionError: If user doesn't own the NGFW
    """
    # Lazy imports to avoid circular dependencies
    from engine.models import Instance
    from engine.secrets import get_ssh_key
    from engine.ssh import SSHConnection

    # Input validation
    if user is None:
        raise ValueError("user is required")
    if not ngfw_uuid:
        raise ValueError("ngfw_uuid is required")

    logger.debug("connect_ngfw_terminal: user_id=%s ngfw_uuid=%s", user.id, ngfw_uuid)

    # Find NGFW Instance by UUID with role=ngfw
    try:
        ngfw_instance = Instance.objects.select_related("request").get(
            uuid=ngfw_uuid,
            role=Instance.Role.NGFW,
        )
    except Instance.DoesNotExist:
        logger.error(
            "NGFW instance not found: user_id=%s ngfw_uuid=%s",
            user.id,
            ngfw_uuid,
        )
        raise ValueError(f"NGFW instance {ngfw_uuid} not found") from None

    # Verify ownership via Request → User
    if ngfw_instance.request is None:
        logger.error(
            "NGFW instance has no associated request: ngfw_uuid=%s",
            ngfw_uuid,
        )
        raise ValueError(f"NGFW instance {ngfw_uuid} has no associated request")

    if ngfw_instance.request.user != user:
        logger.error(
            "Permission denied: user_id=%s does not own ngfw_uuid=%s (owner=%s)",
            user.id,
            ngfw_uuid,
            ngfw_instance.request.user.id,
        )
        raise PermissionError(f"You do not have permission to access NGFW {ngfw_uuid}")

    # Verify status (ready only)
    if ngfw_instance.status != ResourceStatus.READY.value:
        logger.error(
            "NGFW not accessible: ngfw_uuid=%s status=%s (expected ready)",
            ngfw_uuid,
            ngfw_instance.status,
        )
        raise ValueError(f"NGFW is not accessible (status: {ngfw_instance.status}). NGFW must be in ready state.")

    # Extract state fields
    if not ngfw_instance.state:
        logger.error("NGFW has no state: ngfw_uuid=%s", ngfw_uuid)
        raise ValueError(f"NGFW {ngfw_uuid} has no infrastructure state")

    management_ip = _resolve_ngfw_management_ip(ngfw_instance.state)
    if not management_ip:
        logger.error("No management IP in NGFW state: ngfw_uuid=%s", ngfw_uuid)
        raise ValueError(f"NGFW {ngfw_uuid} has no management IP configured")

    ssh_key_ref = _resolve_ngfw_ssh_key_secret_ref(ngfw_instance.state)
    if not ssh_key_ref:
        logger.error("No SSH key ARN in NGFW state: ngfw_uuid=%s", ngfw_uuid)
        raise ValueError(f"NGFW {ngfw_uuid} has no SSH key configured")

    # Get SSH key from secrets
    ssh_key = get_ssh_key(ssh_key_ref)

    # Create SSH connection for PAN-OS CLI
    # - Username: admin (PAN-OS default admin)
    # - Port: 22 (SSH default)
    # - No tmux: PAN-OS doesn't support it
    logger.info(
        "Creating SSH connection for NGFW: user_id=%s ngfw_uuid=%s management_ip=%s",
        user.id,
        ngfw_uuid,
        management_ip,
    )

    return SSHConnection(
        host=management_ip,
        username="admin",
        private_key=ssh_key,
        port=22,
        session_id=None,  # PAN-OS doesn't support tmux
    )


def create_ngfw(request_spec: RequestSpec) -> UUID:
    """Provision NGFW infrastructure.

    Interprets the RequestSpec into Engine models (Request, Instance, App),
    then triggers ECS provisioning.

    Args:
        request_spec: RequestSpec containing an NGFW InstanceSpec item.
            The InstanceSpec must have role="ngfw" and ngfw_app populated
            with hydrated credentials.

    Returns:
        The request_id UUID for correlation with CMS.

    Raises:
        TypeError: If request_spec is not a RequestSpec.
        ValueError: If request_spec or its NGFW item is invalid.
        User.DoesNotExist: If user_id doesn't map to a Django user.
    """
    from engine.ecs import start_ngfw_provisioning
    from engine.interpreter import interpret

    # Validate NGFW-specific requirements before interpreting
    ngfw_spec: InstanceSpec | None = None
    for item in request_spec.items:
        if isinstance(item, InstanceSpec) and item.role == "ngfw":
            ngfw_spec = item
            break

    if ngfw_spec is None:
        raise ValueError("RequestSpec must contain an NGFW InstanceSpec")
    if ngfw_spec.ngfw_app is None:
        raise ValueError("ngfw_app is required for NGFW provisioning")
    if not ngfw_spec.ngfw_app.is_hydrated:
        raise ValueError("ngfw_app must be hydrated with credential values")

    # Interpret spec into models
    request = interpret(request_spec)

    logger.info(
        "create_ngfw: interpreted request_id=%s",
        request_spec.request_id,
    )

    # Get the NGFW instance for provisioning
    ngfw_instance = request.instance_instantiations.filter(role="ngfw").first()

    if ngfw_instance:
        # Trigger ECS provisioning with Request UUID
        task_arn = start_ngfw_provisioning(request.request_id)

        if task_arn:
            logger.info(
                "create_ngfw: started ECS task=%s for request=%s",
                task_arn,
                request.request_id,
            )

    return request.request_id


def destroy_ngfw(request_id: UUID) -> bool:
    """Tear down NGFW infrastructure.

    Looks up the NGFW Instance by request_id and triggers ECS teardown.

    Args:
        request_id: UUID of the request containing the NGFW to destroy.

    Returns:
        True if teardown initiated, False if request/instance not found.

    Raises:
        EngineError: If ranges are still attached to this NGFW.
    """
    from engine.ecs import start_ngfw_teardown
    from engine.models import Instance, Range, Request

    logger.debug("destroy_ngfw: request_id=%s", request_id)

    # Look up the request and its NGFW instance
    try:
        request = Request.objects.get(request_id=request_id)
    except Request.DoesNotExist:
        logger.warning("destroy_ngfw: request not found request_id=%s", request_id)
        return False

    ngfw_instance = Instance.objects.filter(request=request, role="ngfw").first()
    if not ngfw_instance:
        logger.warning("destroy_ngfw: no NGFW instance found for request_id=%s", request_id)
        return False

    # Check for attached ranges - must be deleted before NGFW can be destroyed
    attached_ranges = Range.objects.filter(
        ngfw_instance=ngfw_instance,
        status__in=[
            Range.Status.READY,
            Range.Status.PENDING,
            Range.Status.PROVISIONING,
            Range.Status.PAUSED,
            Range.Status.RESUMING,
        ],
    )
    if attached_ranges.exists():
        count = attached_ranges.count()
        range_ids = list(attached_ranges.values_list("id", flat=True)[:5])
        raise EngineError(
            f"Cannot delete NGFW: {count} range(s) are still attached. Delete these ranges first: {range_ids}"
        )

    task_arn = start_ngfw_teardown(request_id)

    if task_arn:
        logger.info(
            "destroy_ngfw: started ECS task=%s for request=%s",
            task_arn,
            request_id,
        )

    return task_arn is not None


def start_ngfw(request_id: UUID) -> bool:
    """Start a stopped NGFW instance.

    Validates the Instance is in a stoppable state (stopped or failed),
    then triggers ECS to run the start operation.

    Args:
        request_id: UUID of the request containing the NGFW.

    Returns:
        True if start initiated, False if request/instance not found
        or invalid status.
    """
    from engine.ecs import start_ngfw_operation
    from engine.models import Instance, Request

    logger.debug("start_ngfw: request_id=%s", request_id)

    try:
        request = Request.objects.get(request_id=request_id)
    except Request.DoesNotExist:
        logger.warning("start_ngfw: request not found request_id=%s", request_id)
        return False

    ngfw_instance = Instance.objects.filter(request=request, role="ngfw").first()
    if not ngfw_instance:
        logger.warning("start_ngfw: no NGFW instance found for request_id=%s", request_id)
        return False

    # Only allow starting from paused or failed status
    if ngfw_instance.status not in (
        ResourceStatus.PAUSED.value,
        ResourceStatus.FAILED.value,
    ):
        logger.warning(
            "start_ngfw: invalid status=%s for request_id=%s (must be stopped or failed)",
            ngfw_instance.status,
            request_id,
        )
        return False

    task_arn = start_ngfw_operation(request_id, "start")

    if task_arn:
        logger.info(
            "start_ngfw: started ECS task=%s for request=%s",
            task_arn,
            request_id,
        )

    return task_arn is not None


def stop_ngfw(request_id: UUID) -> bool:
    """Stop a running NGFW instance.

    Validates the Instance is in a running state (ready or active),
    then triggers ECS to run the stop operation.

    Args:
        request_id: UUID of the request containing the NGFW.

    Returns:
        True if stop initiated, False if request/instance not found
        or invalid status.
    """
    from engine.ecs import start_ngfw_operation
    from engine.models import Instance, Request

    logger.debug("stop_ngfw: request_id=%s", request_id)

    try:
        request = Request.objects.get(request_id=request_id)
    except Request.DoesNotExist:
        logger.warning("stop_ngfw: request not found request_id=%s", request_id)
        return False

    ngfw_instance = Instance.objects.filter(request=request, role="ngfw").first()
    if not ngfw_instance:
        logger.warning("stop_ngfw: no NGFW instance found for request_id=%s", request_id)
        return False

    # Only allow stopping from ready status
    if ngfw_instance.status != ResourceStatus.READY.value:
        logger.warning(
            "stop_ngfw: invalid status=%s for request_id=%s (must be ready)",
            ngfw_instance.status,
            request_id,
        )
        return False

    task_arn = start_ngfw_operation(request_id, "stop")

    if task_arn:
        logger.info(
            "stop_ngfw: started ECS task=%s for request=%s",
            task_arn,
            request_id,
        )

    return task_arn is not None


# ---------------------------------------------------------------------------
# Query functions (return dicts, not model instances)
# ---------------------------------------------------------------------------


def get_user_ready_range_instances(user_id: int) -> list[dict[str, Any]]:
    """Get provisioned instances for a user's active ready range.

    Args:
        user_id: PK of the user.

    Returns:
        List of instance dicts from the range's provisioned_instances,
        or empty list if no ready range exists.
    """
    from engine.models import Range

    range_obj = Range.objects.filter(user_id=user_id, status="ready").first()
    if not range_obj or not range_obj.provisioned_instances:
        return []
    return list(range_obj.provisioned_instances)


def get_ranges_for_ngfw(user_id: int, ngfw_instance_id: int) -> list[dict[str, Any]]:
    """Get active ranges linked to an NGFW instance.

    Args:
        user_id: PK of the user.
        ngfw_instance_id: ID of the NGFW instance.

    Returns:
        List of dicts with range_id, status, created_at for each linked range.
    """
    from engine.models import Range

    ranges = Range.objects.filter(
        ngfw_instance_id=ngfw_instance_id,
        user_id=user_id,
        destroyed_at__isnull=True,
    ).order_by("-created_at")

    return [
        {
            "range_id": r.pk,
            "request_id": str(r.request_id) if r.request_id else None,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in ranges
    ]

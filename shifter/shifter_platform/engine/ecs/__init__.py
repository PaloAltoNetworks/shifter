"""ECS Fargate / GCP task orchestration for Shifter Engine (package facade).

This package triggers provisioner tasks to provision and teardown range
infrastructure. The Shifter Engine writes directly to the database, so no
callback endpoint is needed.

Local Development:
    Set LOCAL_PROVISIONER=subprocess in settings to run the provisioner locally
    instead of triggering a remote task. This requires:
    - AWS credentials configured
    - PROVISIONER_PATH setting pointing to the provisioner directory

The implementation is split by responsibility across private submodules
(``_env`` GCP Job env projection, ``_config`` task-runner config, ``_local``
local subprocess fallback, ``_status`` task-status projection) and re-exported
here (#685) so callers keep using ``from engine.ecs import X``. The dispatch
pipeline and its logging stay in this facade so it retains the stable
``engine.ecs`` logger namespace.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shared.cloud import PROVISIONER_CONTAINER_NAME, get_task_runner
from shared.enums import ResourceType

from ._config import _get_engine_task_config
from ._env import (
    _AWS_PROVISIONER_ENV_KEYS,
    _GCP_PROVISIONER_ENV_KEYS,
    _get_aws_provisioner_env_overrides,
    _get_gcp_provisioner_env_overrides,
    _get_provisioner_env_overrides,
)
from ._local import _is_local_provisioner_enabled, _run_local_provisioner
from ._status import get_task_status

# SonarCloud S1192: extracted duplicated string literals.
REQUEST_ID_NONE_MSG = "request_id cannot be None"

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


def _validate_start_ecs_task_args(range_id: int, user_id: int, command: str) -> None:
    """Validate _start_ecs_task inputs, raising TypeError/ValueError on bad input."""
    if range_id is None or not isinstance(range_id, int):
        raise TypeError("range_id must be an integer")
    if user_id is None or not isinstance(user_id, int):
        raise TypeError("user_id must be an integer")
    if range_id < 0:
        raise ValueError("range_id must be non-negative")
    if user_id < 0:
        raise ValueError("user_id must be non-negative")
    if command is None or not isinstance(command, str):
        raise TypeError("command must be a string")
    if not command.strip():
        raise ValueError("command must be a non-empty string")


def _enqueue_provisioner_launch(command: list[str]) -> str | None:
    """Persist one durable ``ProvisionerLaunchIntent`` for the launcher worker and
    return its reserved task ref.

    Provider-neutral (ADR-043-R2): AWS and GCP share this single launch-intent
    contract. There is no synchronous provider dispatch here; the active
    ``TaskRunner.run_task`` is reached only by the ``drain_provisioner_launch_outbox``
    worker through :func:`dispatch_provisioner_command`. Returns ``None`` when the
    engine task runner is not configured, so a misconfigured provider does not
    persist an intent the launcher can never execute (a ghost launch). The domain
    operation generation is reserved and fenced inside
    ``engine.launch_intents.enqueue_provisioner_launch`` for both providers.
    """
    if _get_engine_task_config() is None:
        return None
    from engine.launch_intents import enqueue_provisioner_launch, task_ref_for_intent

    intent_id = enqueue_provisioner_launch(command)
    return task_ref_for_intent(intent_id)


def dispatch_provisioner_command(command: list[str], *, task_identity: str | None = None) -> str | None:
    """Launch one validated command directly; callable only by the launcher worker on GCP."""
    from engine.launch_intents import validate_provisioner_command

    validate_provisioner_command(command)
    task_config = _get_engine_task_config()
    if task_config is None:
        return None
    cluster, task_definition, network_config = task_config
    runner = get_task_runner()
    return runner.run_task(
        task_definition=task_definition,
        cluster=cluster,
        command=command,
        container_name=PROVISIONER_CONTAINER_NAME,
        env_overrides=_get_provisioner_env_overrides(),
        network_config=network_config,
        task_identity=task_identity,
    )


def interrupt_provisioner_task(task_ref: str, command: list[str], task_identity: str) -> str | None:
    """Interrupt a dispatched provisioner task; callable only by the launcher worker (#277).

    Resolves the provider task runner and verifies the workload against the trusted
    launch identity (image/command/container/service-account + the deterministic
    Job identity) before stopping it. Returns a ``TaskInterruptDisposition`` value,
    or ``None`` when the engine task runner is not configured.
    """
    from django.conf import settings

    task_config = _get_engine_task_config()
    if task_config is None:
        return None
    cluster, task_definition, _network_config = task_config
    runner = get_task_runner()
    expected_identity = {
        "task_identity": task_identity,
        "image": task_definition,
        "command": command,
        "container_name": PROVISIONER_CONTAINER_NAME,
        "service_account_name": str(getattr(settings, "ENGINE_TASK_SERVICE_ACCOUNT_NAME", "") or ""),
    }
    return runner.interrupt_task(cluster, task_ref, expected_identity)


def _start_ecs_task(range_id: int, user_id: int, command: str) -> str | None:
    """Start an ECS Fargate task for provisioning operations.

    Args:
        range_id: Database ID of the Range
        user_id: Django User ID of the User
        command: Command to run ("provision" or "destroy")

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured. The launcher worker submits the provider task later.

    Raises:
        TypeError: If range_id is not an integer or user_id is not an integer or command is not a string
        ValueError: If range_id is negative or user_id is negative or command is empty,
            or if current domain state does not authorize the operation
    """
    _validate_start_ecs_task_args(range_id, user_id, command)

    command_list = [
        ResourceType.RANGE.value,
        command,
        "--range-id",
        str(range_id),
        "--user-id",
        str(user_id),
    ]
    logger.info("Enqueuing provisioner launch intent range_id=%s command=%s", range_id, command)
    return _enqueue_provisioner_launch(command_list)


def start_provisioning(range_id: int, user_id: int) -> str | None:
    """Start provisioning a range via ECS Fargate.

    Args:
        range_id: Database ID of the Range to provision
        user_id: Django User ID of the User
    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured (falls back to a local subprocess in local dev)

    Raises:
        ValueError: If current domain state does not authorize the operation
    """
    return _start_ecs_task(range_id, user_id, "provision")


def start_teardown(range_id: int, user_id: int) -> str | None:
    """Start teardown of a range via ECS Fargate.

    Args:
        range_id: Database ID of the Range to teardown
        user_id: User ID for event publishing in the provisioner

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured (falls back to a local subprocess in local dev)

    Raises:
        ValueError: If current domain state does not authorize the operation

    .. deprecated::
        Use :func:`start_range_teardown` instead.
    """
    return _start_ecs_task(range_id, user_id, "destroy")


# =============================================================================
# Request-based Range ECS Functions (new pattern matching NGFW)
# =============================================================================


def _dispatch_remote_provisioner_task(command: list[str], request_id: UUID, resource: str) -> str | None:
    """Enqueue a durable launch intent for a request-based remote operation.

    The ``drain_provisioner_launch_outbox`` worker later submits the provider
    task; nothing here calls ``TaskRunner.run_task`` directly (ADR-043-R2).
    """
    logger.info("Enqueuing %s launch intent for request_id=%s", resource, request_id)
    return _enqueue_provisioner_launch(command)


def _start_range_ecs_task(request_id: UUID, command: str, resource: str = "range") -> str | None:
    """Start an ECS Fargate task for Range operations using request_id.

    Matches NGFW pattern - provisioner fetches all data from DB using request_id.

    Args:
        request_id: UUID of the Request to operate on
        command: Command to run ("provision" or "destroy")
        resource: Provisioner subcommand/resource group. RAES lifecycle calls
            pass ``"raes-range"`` so the provisioner realizes a persisted
            serialized RAES plan (ADR-031/ADR-032); the local/ECS dispatch
            mechanics are otherwise identical.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If command is invalid
        ValueError: If current domain state does not authorize the operation
    """
    from uuid import UUID as UUIDType

    if request_id is None:
        raise TypeError(REQUEST_ID_NONE_MSG)
    if not isinstance(request_id, UUIDType):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    valid_commands = ("provision", "destroy", "pause", "resume")
    if command not in valid_commands:
        raise ValueError(f"Invalid command: {command}. Must be one of {valid_commands}.")

    command_list = [resource, command, "--request-id", str(request_id)]
    if _is_local_provisioner_enabled():
        logger.info(
            "Using local provisioner for %s request_id=%s command=%s",
            resource,
            request_id,
            command,
        )
        return _run_local_provisioner(command_list)
    return _dispatch_remote_provisioner_task(command_list, request_id, resource)


def start_range_provisioning(request_id: UUID) -> str | None:
    """Start provisioning a range via ECS Fargate using request_id.

    Args:
        request_id: UUID of the Request to provision.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If current domain state does not authorize the operation
    """
    return _start_range_ecs_task(request_id, "provision")


def start_raes_range_provisioning(request_id: UUID) -> str | None:
    """Start provisioning an RAES-native range via the provisioner ``raes-range``
    command using request_id (ADR-031, feature-flagged parallel path).

    Identical dispatch mechanics to :func:`start_range_provisioning` (local
    subprocess or ECS Fargate); only the provisioner subcommand differs, so the
    provisioner realizes a persisted serialized RAES plan rather than a RangeSpec.

    Returns:
        Task ARN / local handle if dispatched, None if ECS is not configured.
    """
    return _start_range_ecs_task(request_id, "provision", resource="raes-range")


def start_raes_range_teardown(request_id: UUID) -> str | None:
    """Start teardown of an RAES-native range via the provisioner ``raes-range``
    command using request_id (ADR-031, feature-flagged parallel path).

    Identical dispatch mechanics to :func:`start_range_teardown`; only the
    provisioner subcommand differs, so the provisioner reconstructs the range
    resources from the persisted serialized RAES plan and deletes them.

    Returns:
        Task ARN / local handle if dispatched, None if ECS is not configured.
    """
    return _start_range_ecs_task(request_id, "destroy", resource="raes-range")


def start_range_teardown(request_id: UUID) -> str | None:
    """Start teardown of a range via ECS Fargate using request_id.

    Args:
        request_id: UUID of the Request to teardown.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If current domain state does not authorize the operation
    """
    return _start_range_ecs_task(request_id, "destroy")


def start_range_operation(request_id: UUID, operation: str) -> str | None:
    """Start a range runtime operation (pause/resume) via ECS Fargate.

    Args:
        request_id: UUID of the Request containing the Range.
        operation: Operation to perform ('pause' or 'resume').

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If operation is not 'pause' or 'resume'
        ValueError: If current domain state does not authorize the operation
    """
    from uuid import UUID as UUIDType

    if request_id is None:
        raise TypeError(REQUEST_ID_NONE_MSG)
    if not isinstance(request_id, UUIDType):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if operation not in ("pause", "resume"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'pause' or 'resume'.")

    return _start_range_ecs_task(request_id, operation)


def _start_ngfw_ecs_task(request_id: UUID, command: list[str]) -> str | None:
    """Start an ECS Fargate task for NGFW operations.

    Args:
        request_id: UUID of the Request to operate on
        command: Command list to run (e.g., ["ngfw", "provision", "--request-id", "..."])

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured

    Raises:
        TypeError: If request_id is None or command is not a list
        ValueError: If command is empty
        ValueError: If current domain state does not authorize the operation
    """
    from uuid import UUID

    if request_id is None:
        raise TypeError(REQUEST_ID_NONE_MSG)
    if not isinstance(request_id, UUID):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if command is None or not isinstance(command, list):
        raise TypeError("command must be a list")
    if not command:
        raise ValueError("command must be a non-empty list")

    if _is_local_provisioner_enabled():
        logger.info(
            "Using local provisioner for NGFW request_id=%s command=%s",
            request_id,
            command,
        )
        return _run_local_provisioner(command)
    return _dispatch_remote_provisioner_task(command, request_id, "NGFW")


def start_ngfw_provisioning(request_id: UUID) -> str | None:
    """Start provisioning an NGFW via ECS Fargate.

    Args:
        request_id: UUID of the Request to provision.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured (falls back to a local subprocess in local dev)

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If current domain state does not authorize the operation
    """
    command = ["ngfw", "provision", "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)


def start_ngfw_teardown(request_id: UUID) -> str | None:
    """Start teardown/deprovision of an NGFW via ECS Fargate.

    Args:
        request_id: UUID of the Request to deprovision.

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is
        not configured (falls back to a local subprocess in local dev)

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If current domain state does not authorize the operation
    """
    command = ["ngfw", "deprovision", "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)


def start_ngfw_operation(request_id: UUID, operation: str) -> str | None:
    """Start an NGFW runtime operation (start/stop) via ECS Fargate.

    Args:
        request_id: UUID of the Request containing the NGFW instance.
        operation: Operation to perform ('start' or 'stop').

    Returns:
        Reserved launch-intent task ref, or None if the engine task runner is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If operation is not 'start' or 'stop'
        ValueError: If current domain state does not authorize the operation
    """
    from uuid import UUID

    if request_id is None:
        raise TypeError(REQUEST_ID_NONE_MSG)
    if not isinstance(request_id, UUID):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if operation not in ("start", "stop"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'start' or 'stop'.")

    command = ["ngfw", operation, "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)


__all__ = [
    # Internal seams re-exported for tests, kept stable across the #685 split.
    "_AWS_PROVISIONER_ENV_KEYS",
    "_GCP_PROVISIONER_ENV_KEYS",
    "_get_aws_provisioner_env_overrides",
    "_get_engine_task_config",
    "_get_gcp_provisioner_env_overrides",
    "_get_provisioner_env_overrides",
    "_is_local_provisioner_enabled",
    "_run_local_provisioner",
    "_start_ecs_task",
    "_start_ngfw_ecs_task",
    # Public provisioner dispatch entrypoints.
    "dispatch_provisioner_command",
    "get_task_status",
    "start_ngfw_operation",
    "start_ngfw_provisioning",
    "start_ngfw_teardown",
    "start_provisioning",
    "start_raes_range_provisioning",
    "start_raes_range_teardown",
    "start_range_operation",
    "start_range_provisioning",
    "start_range_teardown",
    "start_teardown",
]

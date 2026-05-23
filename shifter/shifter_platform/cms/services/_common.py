"""Shared helpers used by every cms.services submodule.

Houses the per-call validators and the agent-projection shape contract.
Also holds the range_spec instance flattener and the runtime-IP overlay
helper used by the active-range / range-by-request-id projections.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.models import AgentConfig
from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.schemas.range import InstanceContextBase

logger = logging.getLogger(__name__)

# Shared log format for "%(fn)s called with None %(arg)s for user_id=%(uid)s" so
# the validation helpers stay in sync (Sonar python:S1192).
_LOG_FMT_NONE_PARAM = "%s called with None %s for user_id=%s"


def _validate_caller_user(user: object, fn_name: str) -> None:
    """Reject None/wrong-type/unsaved User; raise the canonical TypeError/ValueError.

    Used by every service entrypoint that takes `user: User` so the
    boilerplate user-input gate lives in one place. Keeps callers below the
    per-function complexity ceiling.
    """
    if user is None:
        logger.error("%s called with None user", fn_name)
        raise TypeError(USER_CANNOT_BE_NONE)
    if not hasattr(user, "id"):
        logger.error("%s called with invalid user type: %s", fn_name, type(user).__name__)
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)
    if user.id is None:
        logger.error("%s called with unsaved user (id=None)", fn_name)
        raise ValueError(USER_MUST_BE_SAVED)


def _validate_nonneg_int_id(value: object, name: str, fn_name: str, user_id: object) -> None:
    """Reject None/wrong-type/negative int IDs; raise canonical TypeError/ValueError."""
    if value is None:
        logger.error(_LOG_FMT_NONE_PARAM, fn_name, name, user_id)
        raise TypeError(f"{name} cannot be None")
    if not isinstance(value, int):
        logger.error(
            "%s called with invalid %s type: %s",
            fn_name,
            name,
            type(value).__name__,
        )
        msg = f"{name} must be an int, got {type(value).__name__}"
        raise TypeError(msg)
    if value < 0:
        logger.error(
            "%s called with negative %s=%s for user_id=%s",
            fn_name,
            name,
            value,
            user_id,
        )
        raise ValueError(f"{name} must be non-negative")


def _validate_listing_user(user: User, fn_name: str) -> None:
    """Validate `user` is suitable for a list-style query; raise on failure."""
    if user is None:
        logger.error("%s called with None user", fn_name)
        raise TypeError(USER_CANNOT_BE_NONE)
    if not hasattr(user, "id"):
        logger.error("%s called with invalid user type: %s", fn_name, type(user).__name__)
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)
    if user.id is None:
        logger.error("%s called with unsaved user (id=None)", fn_name)
        raise ValueError(USER_MUST_BE_SAVED)


def _validate_nonempty_str(value: object, name: str, fn_name: str, user_id: object) -> str:
    """Strip and validate a required non-empty string parameter."""
    if value is None:
        logger.error(_LOG_FMT_NONE_PARAM, fn_name, name, user_id)
        raise ValueError(f"{name} cannot be None")
    if not isinstance(value, str):
        logger.error(
            "%s called with non-string %s (type=%s) for user_id=%s",
            fn_name,
            name,
            type(value).__name__,
            user_id,
        )
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    stripped: str = value.strip()
    if not stripped:
        logger.error("%s called with empty %s for user_id=%s", fn_name, name, user_id)
        raise ValueError(f"{name} cannot be empty")
    return stripped


def _validate_positive_int(value: object, name: str, fn_name: str, user_id: object) -> None:
    """Validate a required positive int (> 0); raise canonical TypeError/ValueError."""
    if value is None:
        logger.error(_LOG_FMT_NONE_PARAM, fn_name, name, user_id)
        raise TypeError(f"{name} cannot be None")
    if not isinstance(value, int):
        logger.error(
            "%s called with invalid %s type: %s",
            fn_name,
            name,
            type(value).__name__,
        )
        msg = f"{name} must be an int, got {type(value).__name__}"
        raise TypeError(msg)
    if value <= 0:
        logger.error("%s called with invalid %s=%s for user_id=%s", fn_name, name, value, user_id)
        raise ValueError(f"{name} must be positive")


_AGENT_PROJECTION_SHAPE: tuple[tuple[str, type | tuple[type, ...], bool, str], ...] = (
    ("id", int, False, "agent.id must be int"),
    ("name", str, True, "agent.name must be non-empty str"),
    ("os_name", str, True, "agent.os.name must be non-empty str"),
    ("os_slug", str, True, "agent.os.slug must be non-empty str"),
    ("file_size_mb", (int, float), False, "agent.file_size_mb must be number"),
    ("original_filename", str, True, "agent.original_filename must be non-empty str"),
)


def _assert_agent_projection_shape(projection: dict[str, Any]) -> None:
    """Assert the projection dict satisfies the documented downstream contract.

    Iterates ``_AGENT_PROJECTION_SHAPE`` so the per-field branches don't
    push this function over Sonar's per-function complexity cap.
    """
    for key, expected_type, require_truthy, error_msg in _AGENT_PROJECTION_SHAPE:
        value = projection[key]
        if not isinstance(value, expected_type):
            raise TypeError(error_msg)
        if require_truthy and not value:
            raise TypeError(error_msg)
    if projection["created_at"] is None:
        raise TypeError("agent.created_at must not be None")


def _agent_projection_dict(agent: AgentConfig) -> dict[str, Any]:
    """Build the agent projection dict; verify the model shape on the way out.

    Centralizes the per-agent type-shape contract that `list_agents` enforces
    on its return rows, keeping the caller below the per-function complexity
    ceiling.
    """
    if not (hasattr(agent, "id") and hasattr(agent, "name") and hasattr(agent, "os")):
        raise TypeError("Model returned invalid agent object")
    projection = {
        "id": agent.id,
        "name": agent.name,
        "os_name": agent.os.name,
        "os_slug": agent.os.slug,
        "file_size_mb": agent.file_size_mb,
        "original_filename": agent.original_filename,
        "created_at": agent.created_at,
        "agent_type": agent.agent_type,
        "agent_type_display": agent.get_agent_type_display(),
    }
    _assert_agent_projection_shape(projection)
    return projection


def _flatten_range_spec_instances(range_spec: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the flat list of raw instance dicts from a stored range_spec.

    Accepts two on-disk shapes:
    - Current: instances nested under subnets (`range_spec["subnets"][*]["instances"]`)
    - Legacy: a flat `range_spec["instances"]` list (preserved for backward
      compatibility with existing prod rows)
    """
    if not range_spec:
        return []
    subnet_specs = range_spec.get("subnets")
    if subnet_specs is not None:
        return [spec for subnet in subnet_specs for spec in subnet.get("instances", [])]
    return list(range_spec.get("instances") or [])


def _instance_contexts_from_range_spec[InstanceContextT: "InstanceContextBase"](
    range_spec: dict[str, Any] | None,
    instance_context_cls: type[InstanceContextT],
    ip_by_uuid: dict[str, str] | None = None,
) -> list[InstanceContextT]:
    """Flatten a stored range_spec into a list of `InstanceContext` rows.

    Delegates the on-disk-shape handling to
    ``_flatten_range_spec_instances``. The ``instance_context_cls`` is
    passed in so this helper has no cross-layer model import; the caller
    already imports it from ``shared.schemas``.

    When ``ip_by_uuid`` is supplied, the helper sets ``private_ip`` on each
    row whose ``uuid`` is in the map. The map is sourced from
    ``engine.services.get_instance_ips_by_uuid`` and joined by uuid (NOT by
    role/name) per the architecture preflight for issue #370.
    """
    ips = ip_by_uuid or {}

    def to_context(spec: dict[str, Any]) -> InstanceContextT:
        """Build one ``instance_context_cls`` row, joining the runtime IP map by uuid."""
        spec_uuid = spec.get("uuid")
        return instance_context_cls(
            uuid=spec_uuid,
            name=spec.get("name", ""),
            role=spec["role"],
            os_type=spec["os_type"],
            join_domain=spec.get("join_domain", False),
            private_ip=ips.get(spec_uuid) if isinstance(spec_uuid, str) else None,
        )

    return [to_context(spec) for spec in _flatten_range_spec_instances(range_spec)]


def _resolve_runtime_ips(range_id: int | None) -> dict[str, str]:
    """Best-effort lookup of {uuid: private_ip} for a range's provisioned instances.

    Returns an empty map when ``range_id`` is None (request not yet
    associated with an engine range) or when the engine lookup fails for
    any reason — the projection still renders, just without IPs.

    Calls through the ``cms.services`` package so tests that patch
    ``cms.services.engine_get_instance_ips_by_uuid`` keep working after
    the package split.
    """
    if range_id is None:
        return {}
    try:
        from cms import services as _cs

        return _cs.engine_get_instance_ips_by_uuid(range_id)
    except Exception:
        logger.exception("Failed to resolve runtime IPs for range_id=%s", range_id)
        return {}
